"""Adapter da Shopee (Shopee Open Platform / Affiliate API).

Documentação: https://open.shopee.com/

Notas de honestidade dos dados, que definem o que este adapter **não** devolve:

* A API de **afiliado** da Shopee não é pública para qualquer parceiro: exige
  aprovação como Affiliate Partner. Sem essas credenciais, o adapter levantará
  `ShopeeNotConfigured` em vez de devolver lista vazia — uma lista vazia seria
  indistinguível de "o vendedor não tem produtos".
* **Comissão** só vem pela API de afiliado. Quando indisponível, fica `None` e o
  Opportunity Score reduz a confiança em vez de estimar.
* **Vendas** não são expostas. `fetch_sales` devolve vazio e registra o motivo.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import requests

from config.settings import get_settings
from integrations.marketplaces.base import (
    ConnectorBatch,
    ConnectorProduct,
    MarketplaceAdapter,
    SalesRecord,
)
from integrations.marketplaces.signing import (
    SignatureError,
    shopee_public_params,
    shopee_shop_params,
)
from integrations.marketplaces.token_store import TokenSet, TokenStore

logger = logging.getLogger(__name__)

API_URL = "https://partner.shopeemobile.com"
# Endpoints usados. Os caminhos entram na assinatura, então precisam ser exatos.
PATH_SHOP_INFO = "/api/v2/shop/get_shop_info"
PATH_ITEM_LIST = "/api/v2/product/get_item_list"
PATH_ITEM_BASE_INFO = "/api/v2/product/get_item_base_info"
PATH_AUTH_TOKEN = "/api/v2/auth/token/get"


class ShopeeError(RuntimeError):
    """Falha ao falar com a Shopee."""


class ShopeeNotConfigured(ShopeeError):
    """Credenciais ausentes. Erro de configuração, não de rede."""


@dataclass
class ShopeeConfig:
    partner_id: str = ""
    partner_key: str = ""
    access_token: str = ""
    refresh_token: str = ""
    shop_id: str = ""
    api_url: str = API_URL
    timeout: float = 20.0


@dataclass
class ShopeeAdapterOptions:
    max_items: int = 50
    page_size: int = 50
    warnings: list[str] = field(default_factory=list)


class ShopeeAdapter(MarketplaceAdapter):
    name = "shopee"
    # API de parceiro oficial, mas os dados de comissão dependem do programa de
    # afiliado.
    reliability = 0.9

    def __init__(self, cfg: ShopeeConfig | None = None, token_store: TokenStore | None = None):
        self.cfg = cfg or self._load_config()
        self.tokens = token_store or TokenStore()
        self._load_persisted_tokens()

    @staticmethod
    def _load_config() -> ShopeeConfig:
        settings = get_settings()
        return ShopeeConfig(
            partner_id=settings.shopee_partner_id,
            partner_key=settings.shopee_partner_key,
            access_token=settings.shopee_access_token,
            refresh_token=settings.shopee_refresh_token,
            shop_id=settings.shopee_shop_id,
            timeout=settings.connector_timeout_seconds,
        )

    def _load_persisted_tokens(self) -> None:
        stored = self.tokens.load(self.name)
        if stored is None:
            return
        if stored.access_token:
            self.cfg.access_token = stored.access_token
        if stored.refresh_token:
            self.cfg.refresh_token = stored.refresh_token

    def is_configured(self) -> bool:
        return bool(self.cfg.partner_id and self.cfg.partner_key and self.cfg.access_token and self.cfg.shop_id)

    def get_status(self) -> dict[str, Any]:
        return {
            "connector": self.name,
            "configured": self.is_configured(),
            "has_partner_credentials": bool(self.cfg.partner_id and self.cfg.partner_key),
            "has_access_token": bool(self.cfg.access_token),
            "has_shop_id": bool(self.cfg.shop_id),
            "reliability": self.reliability,
            "note": (
                "A API de afiliado da Shopee exige aprovação como Affiliate Partner. "
                "Sem ela, comissão por produto não está disponível."
            ),
        }

    # --- HTTP -----------------------------------------------------------------

    def _post(self, path: str, body: dict[str, Any], *, authenticated: bool = True) -> dict[str, Any]:
        timestamp = int(time.time())
        try:
            if authenticated and self.cfg.access_token:
                params = shopee_shop_params(
                    self.cfg.partner_id,
                    self.cfg.partner_key,
                    path,
                    timestamp,
                    self.cfg.access_token,
                    self.cfg.shop_id,
                )
            else:
                params = shopee_public_params(self.cfg.partner_id, self.cfg.partner_key, path, timestamp)
        except SignatureError as exc:
            raise ShopeeNotConfigured(str(exc)) from exc

        try:
            response = requests.post(
                f"{self.cfg.api_url}{path}", params=params, json=body, timeout=self.cfg.timeout
            )
        except requests.RequestException as exc:
            raise ShopeeError(f"falha de rede em {path}: {exc}") from exc

        if response.status_code != 200:
            raise ShopeeError(f"HTTP {response.status_code} em {path}: {response.text[:300]}")

        data = response.json()
        if data.get("error"):
            raise ShopeeError(f"{path}: {data.get('error')} — {data.get('message')}")
        return data

    # --- Coleta ---------------------------------------------------------------

    def fetch_products(self, *, limit: int | None = None, options: ShopeeAdapterOptions | None = None) -> ConnectorBatch:
        options = options or ShopeeAdapterOptions()
        if limit is not None:
            options.max_items = limit

        if not self.is_configured():
            raise ShopeeNotConfigured(
                "Credenciais da Shopee incompletas. São necessários partner_id, partner_key, "
                "access_token e shop_id (MARKETPLACE_SHOPEE_* no .env)."
            )

        collected_at = datetime.now(UTC)
        warnings = list(options.warnings)
        item_ids = self._list_item_ids(options, warnings)
        products: list[ConnectorProduct] = []

        for chunk_start in range(0, len(item_ids), options.page_size):
            chunk = item_ids[chunk_start : chunk_start + options.page_size]
            try:
                response = self._post(PATH_ITEM_BASE_INFO, {"item_id_list": chunk})
            except ShopeeError as exc:
                warnings.append(f"lote de itens ignorado: {exc}")
                continue
            for item in response.get("response", {}).get("item_list", []):
                products.append(self._normalize_item(item))

        return ConnectorBatch(
            connector=self.name,
            products=products,
            collected_at=collected_at,
            endpoint=f"{self.cfg.api_url}{PATH_ITEM_BASE_INFO}",
            reliability=self.reliability,
            warnings=warnings,
            raw={"shop_id": self.cfg.shop_id, "item_count": len(item_ids)},
        )

    def _list_item_ids(self, options: ShopeeAdapterOptions, warnings: list[str]) -> list[str]:
        item_ids: list[str] = []
        offset = 0
        while len(item_ids) < options.max_items:
            page_size = min(options.page_size, options.max_items - len(item_ids))
            try:
                response = self._post(
                    PATH_ITEM_LIST,
                    {
                        "offset": offset,
                        "page_size": page_size,
                        "item_status": "NORMAL",
                    },
                )
            except ShopeeError as exc:
                warnings.append(f"listagem de itens interrompida: {exc}")
                break

            payload = response.get("response", {})
            page_items = payload.get("item", [])
            if not page_items:
                break
            item_ids.extend(str(entry.get("item_id")) for entry in page_items if entry.get("item_id"))

            has_next = payload.get("has_next_page")
            if not has_next:
                break
            offset += page_size
        return item_ids[: options.max_items]

    def _normalize_item(self, item: dict[str, Any]) -> ConnectorProduct:
        price_info = item.get("price_info") or []
        price = None
        original_price = None
        currency = None
        if price_info:
            first = price_info[0]
            price = first.get("current_price")
            original_price = first.get("original_price")
            currency = first.get("currency")

        if price is None:
            price = item.get("price")

        discount_pct = None
        if price and original_price and float(original_price) > 0:
            discount_pct = round((1 - float(price) / float(original_price)) * 100, 2)

        image = item.get("image") or {}
        images = [image.get("image_url")] if image.get("image_url") else None

        stock_info = item.get("stock_info_v2") or {}
        available = None
        if isinstance(stock_info, dict):
            summary = stock_info.get("summary_info") or {}
            available = summary.get("total_available_stock")

        return ConnectorProduct(
            external_id=str(item.get("item_id")),
            title=str(item.get("item_name") or "").strip(),
            category_id=str(item.get("category_id")) if item.get("category_id") else None,
            brand=item.get("brand", {}).get("original_brand_name") if isinstance(item.get("brand"), dict) else None,
            condition=item.get("condition"),
            currency=currency,
            price=float(price) if price is not None else None,
            original_price=float(original_price) if original_price is not None else None,
            discount_pct=discount_pct,
            # A comissão de afiliado não é exposta por este endpoint.
            affiliate_commission_pct=None,
            available_quantity=int(available) if available is not None else None,
            sold_quantity=None,
            is_available=item.get("item_status") == "NORMAL" if item.get("item_status") else None,
            rating=_to_float((item.get("item_rating") or {}).get("rating_star")),
            review_count=_to_int((item.get("item_rating") or {}).get("rating_count", [None])[0])
            if isinstance((item.get("item_rating") or {}).get("rating_count"), list)
            else None,
            has_promotion=bool(discount_pct) or None,
            product_url=None,
            images=images,
            attributes={"item_status": item.get("item_status")} if item.get("item_status") else None,
        )

    def fetch_sales(self, *, since: datetime | None = None) -> list[SalesRecord]:
        """A API de produto não expõe vendas nem comissão de afiliado."""
        logger.info("fetch_sales da Shopee não implementado: requer a API de afiliado")
        return []

    def search_competitor(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """A Shopee não oferece busca pública de anúncios concorrentes.

        Devolver vazio é a resposta correta: não há endpoint oficial de busca
        aberta, e um scraper entraria no domínio sem confiabilidade declarada.
        """
        logger.info("search_competitor da Shopee não disponível: sem endpoint oficial")
        return []

    def exchange_code_for_token(self, code: str) -> TokenSet:
        """Troca o `code` do OAuth por um access_token de loja."""
        if not (self.cfg.partner_id and self.cfg.partner_key and self.cfg.shop_id):
            raise ShopeeNotConfigured("partner_id, partner_key e shop_id são obrigatórios.")
        path = PATH_AUTH_TOKEN
        timestamp = int(time.time())
        try:
            params = shopee_public_params(self.cfg.partner_id, self.cfg.partner_key, path, timestamp)
        except SignatureError as exc:
            raise ShopeeNotConfigured(str(exc)) from exc

        response = requests.post(
            f"{self.cfg.api_url}{path}",
            params=params,
            json={"code": code, "shop_id": int(self.cfg.shop_id), "partner_id": int(self.cfg.partner_id)},
            timeout=self.cfg.timeout,
        )
        if response.status_code != 200:
            raise ShopeeError(f"HTTP {response.status_code}: {response.text[:300]}")
        data = response.json()
        if data.get("error"):
            raise ShopeeError(f"{data.get('error')} — {data.get('message')}")

        tokens = TokenSet(
            access_token=data.get("access_token", ""),
            refresh_token=data.get("refresh_token", ""),
        )
        self.cfg.access_token = tokens.access_token
        self.cfg.refresh_token = tokens.refresh_token
        self.tokens.save(self.name, tokens)
        return tokens


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "ShopeeAdapter",
    "ShopeeAdapterOptions",
    "ShopeeConfig",
    "ShopeeError",
    "ShopeeNotConfigured",
]
