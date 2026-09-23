"""Adapter da Shopee — Affiliate Open API (GraphQL).

Documentação: https://open-api.affiliate.shopee.com.br/explorer/v2

Isto substitui a versão anterior, que usava a Shopee **Open Platform**
(`partner.shopeemobile.com/api/v2/...`) — a API de VENDEDOR: ela só lista os
anúncios da própria loja autenticada, exige um fluxo OAuth por loja, e nunca
expõe comissão de afiliado (não é essa a API que a Shopee oferece pra isso).
Descoberto ao vivo (testando o equivalente na Mercado Livre) que "conectado"
não significa "descobre produtos de terceiros" quando o adapter usa a API
errada — o mesmo valia aqui.

A **Affiliate Open API** é o produto certo: devolve `commissionRate` e
`offerLink` reais por produto, de qualquer loja, por busca de palavra-chave —
exatamente o que a seção 4 do briefing pede. Autenticação mais simples também:
não há OAuth por loja, só `app_id` + `secret` assinando cada requisição
(`SHA256(app_id + timestamp + payload + secret)` — ver `signing.py`).

Notas de honestidade dos dados:

* **Comissão e link de afiliado** vêm prontos da API (`commissionRate`,
  `offerLink`) — ao contrário de Mercado Livre e Amazon, aqui não ficam `None`.
* **Vendas** não são expostas por esta API (é catálogo/oferta, não conversão
  attribuída); `fetch_sales` continua vazio.
* Confiança moderada no formato exato da assinatura: montada a partir de
  documentação de terceiros (a doc oficial não abre para scraping) — validar
  contra uma chamada real assim que houver `app_id`/`secret` de verdade.
"""
from __future__ import annotations

import json
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
from integrations.marketplaces.signing import SignatureError, shopee_affiliate_auth_header

logger = logging.getLogger(__name__)

API_URL = "https://open-api.affiliate.shopee.com.br/graphql"

PRODUCT_OFFER_QUERY = """
query($keyword: String, $page: Int, $limit: Int) {
  productOfferV2(keyword: $keyword, page: $page, limit: $limit) {
    nodes {
      itemId
      productName
      commissionRate
      priceMin
      priceMax
      offerLink
      productCatIds
      shopId
      shopName
      imageUrl
      ratingStar
      sales
      periodStartTime
      periodEndTime
    }
    pageInfo {
      hasNextPage
      scrollId
    }
  }
}
"""


class ShopeeError(RuntimeError):
    """Falha ao falar com a Shopee."""


class ShopeeNotConfigured(ShopeeError):
    """Credenciais ausentes. Erro de configuração, não de rede."""


@dataclass
class ShopeeConfig:
    app_id: str = ""
    secret: str = ""
    api_url: str = API_URL
    timeout: float = 20.0


@dataclass
class ShopeeAdapterOptions:
    keywords: list[str] = field(default_factory=list)
    max_items: int = 50
    page_size: int = 50
    warnings: list[str] = field(default_factory=list)


class ShopeeAdapter(MarketplaceAdapter):
    name = "shopee"
    # API de afiliado oficial, mas exige aprovação de parceiro — não é acesso
    # público automático como a busca de itens.
    reliability = 0.9

    def __init__(self, cfg: ShopeeConfig | None = None):
        self.cfg = cfg or self._load_config()

    @staticmethod
    def _load_config() -> ShopeeConfig:
        settings = get_settings()
        return ShopeeConfig(
            app_id=settings.shopee_app_id,
            secret=settings.shopee_secret,
            timeout=settings.connector_timeout_seconds,
        )

    def is_configured(self) -> bool:
        return bool(self.cfg.app_id and self.cfg.secret)

    def get_status(self) -> dict[str, Any]:
        return {
            "connector": self.name,
            "configured": self.is_configured(),
            "has_credentials": bool(self.cfg.app_id and self.cfg.secret),
            "reliability": self.reliability,
            "note": (
                "Affiliate Open API exige aprovação como parceiro afiliado da Shopee. "
                "Sem ela, o app_id/secret não terão permissão para consultar productOfferV2."
            ),
        }

    # --- GraphQL ----------------------------------------------------------------

    def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if not self.is_configured():
            raise ShopeeNotConfigured(
                "Credenciais da Shopee incompletas. São necessários app_id e secret "
                "(MARKETPLACE_SHOPEE_* no .env, ou salvos em Integrações)."
            )

        body = {"query": query, "variables": variables}
        payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        timestamp = int(time.time())

        try:
            authorization = shopee_affiliate_auth_header(self.cfg.app_id, self.cfg.secret, timestamp, payload)
        except SignatureError as exc:
            raise ShopeeNotConfigured(str(exc)) from exc

        try:
            response = requests.post(
                self.cfg.api_url,
                data=payload.encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": authorization},
                timeout=self.cfg.timeout,
            )
        except requests.RequestException as exc:
            raise ShopeeError(f"falha de rede em {self.cfg.api_url}: {exc}") from exc

        if response.status_code != 200:
            raise ShopeeError(f"HTTP {response.status_code}: {response.text[:400]}")

        data = response.json()
        if data.get("errors"):
            raise ShopeeError(f"GraphQL errors: {data['errors']}")
        return data.get("data") or {}

    # --- Coleta -------------------------------------------------------------------

    def fetch_products(
        self, *, limit: int | None = None, options: ShopeeAdapterOptions | None = None
    ) -> ConnectorBatch:
        """Descoberta pública por palavra-chave via `productOfferV2`.

        Diferente do antigo adapter (catálogo da própria loja), aqui qualquer
        produto de qualquer loja participante do programa de afiliados pode
        aparecer — é a fonte real de comissão e link de afiliado.
        """
        options = options or ShopeeAdapterOptions()
        if limit is not None:
            options.max_items = limit
        if not self.is_configured():
            raise ShopeeNotConfigured(
                "Credenciais da Shopee incompletas. São necessários app_id e secret "
                "(MARKETPLACE_SHOPEE_* no .env, ou salvos em Integrações)."
            )
        if not options.keywords:
            raise ShopeeError(
                "informe ao menos uma palavra-chave em ShopeeAdapterOptions.keywords: a "
                "Affiliate Open API busca por termo, não lista 'meu catálogo'."
            )

        collected_at = datetime.now(UTC)
        warnings = list(options.warnings)
        products: list[ConnectorProduct] = []
        seen: set[str] = set()
        budget_per_keyword = max(1, options.max_items // max(1, len(options.keywords)))

        for keyword in options.keywords:
            if len(products) >= options.max_items:
                break
            page = 1
            collected_for_keyword = 0
            while collected_for_keyword < budget_per_keyword and len(products) < options.max_items:
                page_size = min(
                    options.page_size,
                    budget_per_keyword - collected_for_keyword,
                    options.max_items - len(products),
                )
                try:
                    data = self._graphql(
                        PRODUCT_OFFER_QUERY, {"keyword": keyword, "page": page, "limit": page_size}
                    )
                except ShopeeError as exc:
                    warnings.append(f"busca por '{keyword}' interrompida na página {page}: {exc}")
                    break

                payload = (data.get("productOfferV2") or {})
                nodes = payload.get("nodes") or []
                if not nodes:
                    break
                for node in nodes:
                    item_id = str(node.get("itemId")) if node.get("itemId") is not None else None
                    if item_id and item_id not in seen:
                        seen.add(item_id)
                        products.append(self._normalize_offer(node))
                        collected_for_keyword += 1

                page_info = payload.get("pageInfo") or {}
                if not page_info.get("hasNextPage"):
                    break
                page += 1

        if len(products) >= options.max_items:
            warnings.append(
                f"coleta limitada a {options.max_items} ofertas; pode haver mais resultados "
                "para essas palavras-chave"
            )

        return ConnectorBatch(
            connector=self.name,
            products=products[: options.max_items],
            collected_at=collected_at,
            endpoint=f"{self.cfg.api_url} (productOfferV2, keywords: {', '.join(options.keywords)})",
            reliability=self.reliability,
            warnings=warnings,
            raw={"keywords": options.keywords},
        )

    def _normalize_offer(self, node: dict[str, Any]) -> ConnectorProduct:
        price_min = _to_float(node.get("priceMin"))
        price_max = _to_float(node.get("priceMax"))
        commission_rate = _to_float(node.get("commissionRate"))

        return ConnectorProduct(
            external_id=str(node.get("itemId")),
            title=str(node.get("productName") or "").strip(),
            category_id=str((node.get("productCatIds") or [None])[0]) if node.get("productCatIds") else None,
            seller_external_id=str(node.get("shopId")) if node.get("shopId") is not None else None,
            seller_nickname=node.get("shopName"),
            currency="BRL",
            price=price_min,
            original_price=price_max if price_max and price_max != price_min else None,
            # A comissão real vem daqui — vantagem desta API sobre ML/Amazon.
            affiliate_commission_pct=commission_rate * 100 if commission_rate is not None else None,
            sold_quantity=_to_int(node.get("sales")),
            rating=_to_float(node.get("ratingStar")),
            affiliate_url=node.get("offerLink"),
            images=[node["imageUrl"]] if node.get("imageUrl") else None,
        )

    def fetch_sales(self, *, since: datetime | None = None) -> list[SalesRecord]:
        """A Affiliate Open API expõe catálogo/oferta, não conversão atribuída."""
        logger.info("fetch_sales da Shopee não implementado: API de afiliado não expõe vendas")
        return []

    def search_competitor(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Busca de concorrentes reaproveitando `productOfferV2`."""
        try:
            batch = self.fetch_products(
                limit=limit, options=ShopeeAdapterOptions(keywords=[query], max_items=limit)
            )
        except ShopeeError:
            return []
        return [
            {
                "platform": self.name,
                "query": query,
                "external_id": product.external_id,
                "title": product.title,
                "price": product.price,
                "currency": product.currency,
                "commission_pct": product.affiliate_commission_pct,
                "permalink": product.affiliate_url,
                "seller_external_id": product.seller_external_id,
            }
            for product in batch.products
        ]


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
