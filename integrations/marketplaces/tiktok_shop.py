"""Adapter do TikTok Shop (Affiliate Open API).

Documentação: https://partner.tiktokshop.com/

Notas de honestidade dos dados, que definem o que este adapter **não** devolve:

* A **Affiliate Open API** exige aprovação como parceiro e assinatura HMAC-SHA256
  com `app_secret`. Sem credenciais aprovadas o adapter levanta
  `TikTokShopNotConfigured` em vez de devolver lista vazia.
* **Comissão por produto** só existe via Affiliate API aprovada. Fica `None` quando
  indisponível — o Opportunity Score reduz a confiança em vez de estimar.
* **A biblioteca de anúncios** (Creative Center) não tem API pública documentada e
  está declarada como não implementada em `integrations/ads_tiktok/client.py`.
"""
from __future__ import annotations

import hashlib
import hmac
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
from integrations.marketplaces.signing import SignatureError
from integrations.marketplaces.token_store import TokenSet, TokenStore

logger = logging.getLogger(__name__)

API_URL = "https://open-api.tiktokglobalshop.com"
PATH_PRODUCTS_SEARCH = "/product/202309/products/search"
PATH_PRODUCT_DETAIL = "/product/202309/products"
PATH_AUTH_TOKEN = "/auth/token/get"


class TikTokShopError(RuntimeError):
    """Falha ao falar com o TikTok Shop."""


class TikTokShopNotConfigured(TikTokShopError):
    """Credenciais ausentes. Erro de configuração, não de rede."""


@dataclass
class TikTokShopConfig:
    app_key: str = ""
    app_secret: str = ""
    access_token: str = ""
    refresh_token: str = ""
    shop_cipher: str = ""
    api_url: str = API_URL
    timeout: float = 20.0


@dataclass
class TikTokShopAdapterOptions:
    max_items: int = 50
    page_size: int = 50
    warnings: list[str] = field(default_factory=list)


def tiktok_shop_sign(
    app_key: str,
    app_secret: str,
    path: str,
    timestamp: int,
    *,
    query: str = "",
    body: str = "",
) -> str:
    """Assinatura da TikTok Shop Open API.

    Base: `app_secret + path + [query] + body + timestamp`, com o `app_secret`
    envolvendo a string — detalhe específico desta API, diferente da Shopee.
    """
    base = f"{app_secret}{path}{query}{body}{timestamp}{app_secret}"
    return hmac.new(app_secret.encode("utf-8"), base.encode("utf-8"), hashlib.sha256).hexdigest()


class TikTokShopAdapter(MarketplaceAdapter):
    name = "tiktok_shop"
    reliability = 0.9

    def __init__(self, cfg: TikTokShopConfig | None = None, token_store: TokenStore | None = None):
        self.cfg = cfg or self._load_config()
        self.tokens = token_store or TokenStore()
        self._load_persisted_tokens()

    @staticmethod
    def _load_config() -> TikTokShopConfig:
        settings = get_settings()
        return TikTokShopConfig(
            app_key=settings.tiktokshop_app_key,
            app_secret=settings.tiktokshop_app_secret,
            access_token=settings.tiktokshop_access_token,
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
        return bool(self.cfg.app_key and self.cfg.app_secret and self.cfg.access_token)

    def get_status(self) -> dict[str, Any]:
        return {
            "connector": self.name,
            "configured": self.is_configured(),
            "has_app_credentials": bool(self.cfg.app_key and self.cfg.app_secret),
            "has_access_token": bool(self.cfg.access_token),
            "reliability": self.reliability,
            "note": (
                "A Affiliate Open API exige aprovação como parceiro. A biblioteca de "
                "anúncios (Creative Center) não tem API pública documentada."
            ),
        }

    # --- HTTP -----------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        if not (self.cfg.app_key and self.cfg.app_secret):
            raise TikTokShopNotConfigured(
                "Credenciais do TikTok Shop incompletas: app_key e app_secret são obrigatórios."
            )

        import json as _json

        params = dict(params or {})
        timestamp = int(time.time())
        params["app_key"] = self.cfg.app_key
        params["timestamp"] = timestamp
        if authenticated and self.cfg.access_token:
            params["access_token"] = self.cfg.access_token
        if self.cfg.shop_cipher:
            params["shop_cipher"] = self.cfg.shop_cipher

        body_text = _json.dumps(body, separators=(",", ":"), ensure_ascii=False) if body else ""
        query = "".join(f"{key}{params[key]}" for key in sorted(params) if key != "sign")

        try:
            params["sign"] = tiktok_shop_sign(
                self.cfg.app_key, self.cfg.app_secret, path, timestamp, query=query, body=body_text
            )
        except SignatureError as exc:
            raise TikTokShopNotConfigured(str(exc)) from exc

        headers = {"Content-Type": "application/json"}
        try:
            response = requests.request(
                method,
                f"{self.cfg.api_url}{path}",
                params=params,
                data=body_text.encode("utf-8") if body_text else None,
                headers=headers,
                timeout=self.cfg.timeout,
            )
        except requests.RequestException as exc:
            raise TikTokShopError(f"falha de rede em {path}: {exc}") from exc

        if response.status_code != 200:
            raise TikTokShopError(f"HTTP {response.status_code} em {path}: {response.text[:300]}")

        data = response.json()
        if data.get("code") not in (0, None):
            raise TikTokShopError(f"{path}: code {data.get('code')} — {data.get('message')}")
        return data

    # --- Coleta ---------------------------------------------------------------

    def fetch_products(
        self, *, limit: int | None = None, options: TikTokShopAdapterOptions | None = None
    ) -> ConnectorBatch:
        options = options or TikTokShopAdapterOptions()
        if limit is not None:
            options.max_items = limit

        if not self.is_configured():
            raise TikTokShopNotConfigured(
                "Access token do TikTok Shop ausente. Requer aprovação como parceiro "
                "(MARKETPLACE_TIKTOKSHOP_* no .env)."
            )

        collected_at = datetime.now(UTC)
        warnings = list(options.warnings)
        products: list[ConnectorProduct] = []
        page_token = None

        while len(products) < options.max_items:
            body: dict[str, Any] = {"page_size": min(options.page_size, options.max_items - len(products))}
            if page_token:
                body["page_token"] = page_token

            data = self._request("POST", PATH_PRODUCTS_SEARCH, body=body)
            payload = data.get("data") or {}
            items = payload.get("products") or []
            if not items:
                break

            for item in items:
                products.append(self._normalize_item(item))

            page_token = payload.get("next_page_token")
            if not page_token:
                break

        return ConnectorBatch(
            connector=self.name,
            products=products[: options.max_items],
            collected_at=collected_at,
            endpoint=f"{self.cfg.api_url}{PATH_PRODUCTS_SEARCH}",
            reliability=self.reliability,
            warnings=warnings,
            raw={"shop_cipher": self.cfg.shop_cipher or None},
        )

    def _normalize_item(self, item: dict[str, Any]) -> ConnectorProduct:
        skus = item.get("skus") or []
        first_sku = skus[0] if skus else {}

        price = (first_sku.get("price") or {}).get("sale_price") or (first_sku.get("price") or {}).get(
            "original_price"
        )
        original_price = (first_sku.get("price") or {}).get("original_price")
        currency = (first_sku.get("price") or {}).get("currency")

        discount_pct = None
        if price and original_price and float(original_price) > 0:
            discount_pct = round((1 - float(price) / float(original_price)) * 100, 2)

        inventory = first_sku.get("inventory") or []
        available = None
        if inventory:
            available = inventory[0].get("quantity")

        images = item.get("images") or []
        main_image = (item.get("main_images") or [{}])
        image_urls = [img.get("uri") for img in images if img.get("uri")]
        if not image_urls and main_image and main_image[0].get("uri"):
            image_urls = [main_image[0]["uri"]]

        return ConnectorProduct(
            external_id=str(item.get("id")),
            title=str(item.get("title") or "").strip(),
            category_id=str((item.get("category_chains") or [{}])[-1].get("id"))
            if item.get("category_chains")
            else None,
            brand=((item.get("brand") or {}).get("name")),
            currency=currency,
            price=float(price) if price is not None else None,
            original_price=float(original_price) if original_price is not None else None,
            discount_pct=discount_pct,
            # Comissão de afiliado exige a Affiliate API aprovada.
            affiliate_commission_pct=None,
            available_quantity=int(available) if available is not None else None,
            sold_quantity=None,
            is_available=item.get("status") == "ACTIVATE" if item.get("status") else None,
            rating=None,
            review_count=None,
            has_promotion=bool(discount_pct) or None,
            images=image_urls or None,
            attributes={"status": item.get("status")} if item.get("status") else None,
        )

    def fetch_sales(self, *, since: datetime | None = None) -> list[SalesRecord]:
        """Vendas de afiliado exigem a Affiliate API aprovada."""
        logger.info("fetch_sales do TikTok Shop não implementado: requer Affiliate API aprovada")
        return []

    def search_competitor(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Sem busca pública de concorrentes; a biblioteca de anúncios não tem API."""
        logger.info("search_competitor do TikTok Shop não disponível")
        return []

    def exchange_code_for_token(self, code: str) -> TokenSet:
        if not (self.cfg.app_key and self.cfg.app_secret):
            raise TikTokShopNotConfigured("app_key e app_secret são obrigatórios.")
        data = self._request(
            "GET",
            PATH_AUTH_TOKEN,
            params={"code": code, "grant_type": "authorized_code"},
            authenticated=False,
        )
        payload = data.get("data") or {}
        tokens = TokenSet(
            access_token=payload.get("access_token", ""),
            refresh_token=payload.get("refresh_token", ""),
        )
        self.cfg.access_token = tokens.access_token
        self.cfg.refresh_token = tokens.refresh_token
        self.tokens.save(self.name, tokens)
        return tokens


__all__ = [
    "TikTokShopAdapter",
    "TikTokShopAdapterOptions",
    "TikTokShopConfig",
    "TikTokShopError",
    "TikTokShopNotConfigured",
    "tiktok_shop_sign",
]
