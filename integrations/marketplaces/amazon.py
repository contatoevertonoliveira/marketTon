"""Adapter da Amazon (Product Advertising API 5.0).

Documentação: https://webservices.amazon.com/paapi5/documentation/

Notas de honestidade dos dados, que definem o que este adapter **não** devolve:

* A PA-API 5.0 não expõe a **comissão** de associado. As taxas por categoria ficam
  na tabela pública de fees do Amazon Associates, não na API. O campo fica `None` e
  o Opportunity Score reduz a confiança — em vez de estimar um percentual.
* **Vendas** não são expostas ao associado. `fetch_sales` devolve vazio.
* A PA-API exige **1 venda a cada 30 dias** por conta de associado para permanecer
  ativa; sem isso ela devolve `TooManyRequests`. Esse é um modo de falha real e
  está tratado com mensagem explícita, não silenciado.
"""
from __future__ import annotations

import json
import logging
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
    aws_authorization_header,
    aws_canonical_request,
)

logger = logging.getLogger(__name__)

API_PATH = "/paapi5/searchitems"
DEFAULT_HOST = "webservices.amazon.com.br"
RESOURCES = [
    "ItemInfo.Title",
    "ItemInfo.ByLineInfo",
    "ItemInfo.ExternalIds",
    "ItemInfo.Features",
    "ItemInfo.ProductInfo",
    "Offers.Listings.Price",
    "Offers.Listings.Availability.Message",
    "Offers.Listings.SavingBasis",
    "Offers.Summaries.LowestPrice",
    "Images.Primary.Large",
    "BrowseNodeInfo.BrowseNodes",
]


class AmazonError(RuntimeError):
    """Falha ao falar com a Amazon."""


class AmazonNotConfigured(AmazonError):
    """Credenciais ausentes. Erro de configuração, não de rede."""


class AmazonThrottled(AmazonError):
    """Rate limit ou conta inativa.

    A PA-API devolve `TooManyRequests` também quando a conta de associado não
    registrou venda nos últimos 30 dias — motivo frequente e pouco óbvio.
    """


@dataclass
class AmazonConfig:
    access_key: str = ""
    secret_key: str = ""
    partner_tag: str = ""
    region: str = "us-east-1"
    host: str = DEFAULT_HOST
    marketplace: str = "www.amazon.com.br"
    timeout: float = 20.0


@dataclass
class AmazonAdapterOptions:
    """Opções de coleta da PA-API.

    `keyword` é obrigatório e não tem default: a PA-API não expõe "meu catálogo",
    apenas busca por termo. Um default silencioso faria a coleta devolver produtos
    arbitrários sem que ninguém percebesse.
    """

    keyword: str = ""
    max_items: int = 10  # a PA-API limita a 10 itens por página
    search_index: str = "All"
    item_page: int = 1
    warnings: list[str] = field(default_factory=list)


class AmazonAdapter(MarketplaceAdapter):
    name = "amazon"
    reliability = 1.0  # API oficial

    def __init__(self, cfg: AmazonConfig | None = None):
        self.cfg = cfg or self._load_config()

    @staticmethod
    def _load_config() -> AmazonConfig:
        settings = get_settings()
        return AmazonConfig(
            access_key=settings.amazon_access_key,
            secret_key=settings.amazon_secret_key,
            partner_tag=settings.amazon_partner_tag,
            region=settings.amazon_region,
            host=settings.amazon_host,
            marketplace=settings.amazon_marketplace,
            timeout=settings.connector_timeout_seconds,
        )

    def is_configured(self) -> bool:
        return bool(self.cfg.access_key and self.cfg.secret_key and self.cfg.partner_tag)

    def get_status(self) -> dict[str, Any]:
        return {
            "connector": self.name,
            "configured": self.is_configured(),
            "region": self.cfg.region,
            "host": self.cfg.host,
            "marketplace": self.cfg.marketplace,
            "reliability": self.reliability,
            "note": (
                "A PA-API 5.0 exige ao menos uma venda a cada 30 dias por conta de "
                "associado; sem isso ela responde TooManyRequests. Comissão por "
                "categoria não é exposta pela API."
            ),
        }

    # --- HTTP -----------------------------------------------------------------

    def _call(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.is_configured():
            raise AmazonNotConfigured(
                "Credenciais da Amazon incompletas. São necessários access_key, secret_key e "
                "partner_tag (MARKETPLACE_AMAZON_* no .env)."
            )

        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        target = f"com.amazon.paapi5.v1.ProductAdvertisingAPIv1.{operation}"
        path = f"/paapi5/{operation.lower()}"

        try:
            canonical, headers = aws_canonical_request(
                host=self.cfg.host, path=path, payload=body, target=target
            )
            signed_headers = ";".join(sorted(headers))
            authorization = aws_authorization_header(
                access_key=self.cfg.access_key,
                secret_key=self.cfg.secret_key,
                region=self.cfg.region,
                host=self.cfg.host,
                canonical_request=canonical,
                signed_headers=signed_headers,
            )
        except SignatureError as exc:
            raise AmazonNotConfigured(str(exc)) from exc

        request_headers = {
            "content-encoding": headers["content-encoding"],
            "content-type": headers["content-type"],
            "host": headers["host"],
            "x-amz-target": headers["x-amz-target"],
            "authorization": authorization,
            "x-amz-date": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
        }

        try:
            response = requests.post(
                f"https://{self.cfg.host}{path}",
                headers=request_headers,
                data=body.encode("utf-8"),
                timeout=self.cfg.timeout,
            )
        except requests.RequestException as exc:
            raise AmazonError(f"falha de rede em {path}: {exc}") from exc

        if response.status_code == 429:
            raise AmazonThrottled(
                "Amazon respondeu 429 (TooManyRequests). Causas comuns: limite de requisições "
                "por segundo, ou conta de associado sem venda nos últimos 30 dias."
            )
        if response.status_code != 200:
            raise AmazonError(f"HTTP {response.status_code} em {path}: {response.text[:400]}")

        data = response.json()
        errors = (data.get("Errors") or [])
        if errors:
            first = errors[0]
            code = first.get("Code", "Unknown")
            if code in {"TooManyRequests", "RequestThrottled"}:
                raise AmazonThrottled(f"{code}: {first.get('Message')}")
            raise AmazonError(f"{code}: {first.get('Message')}")
        return data

    # --- Coleta ---------------------------------------------------------------

    def fetch_products(
        self, *, limit: int | None = None, options: AmazonAdapterOptions | None = None
    ) -> ConnectorBatch:
        """A PA-API não lista "meu catálogo": ela busca por termo.

        Por isso a coleta da Amazon exige um termo de busca. `limit` acima de 10
        requer paginação, que é feita aqui sequencialmente.
        """
        options = options or AmazonAdapterOptions()
        collected_at = datetime.now(UTC)
        warnings = list(options.warnings)

        keyword = self._search_keyword(options)
        products: list[ConnectorProduct] = []
        page = options.item_page

        while len(products) < options.max_items:
            payload = {
                "Keywords": keyword,
                "SearchIndex": options.search_index,
                "ItemCount": min(10, options.max_items - len(products)),
                "ItemPage": page,
                "PartnerTag": self.cfg.partner_tag,
                "PartnerType": "Associates",
                "Marketplace": self.cfg.marketplace,
                "Resources": RESOURCES,
            }
            data = self._call("SearchItems", payload)

            results = data.get("SearchResult") or {}
            items = results.get("Items") or []
            if not items:
                break
            for item in items:
                products.append(self._normalize_item(item))

            total_results = _to_int(results.get("TotalResultCount")) or 0
            # Última página alcançada, ou já temos o suficiente.
            if len(products) >= options.max_items:
                break
            if page * 10 >= total_results:
                break
            page += 1
            if page > 10:
                warnings.append("paginação limitada a 10 páginas (limite da PA-API)")
                break

        return ConnectorBatch(
            connector=self.name,
            products=products[: options.max_items],
            collected_at=collected_at,
            endpoint=f"https://{self.cfg.host}{API_PATH}",
            reliability=self.reliability,
            warnings=warnings,
            raw={"keyword": keyword, "marketplace": self.cfg.marketplace},
        )

    def _search_keyword(self, options: AmazonAdapterOptions) -> str:
        if not options.keyword:
            raise AmazonError(
                "A PA-API não expõe o catálogo do associado; informe um termo de busca "
                "(AmazonAdapterOptions.keyword) para coletar."
            )
        return options.keyword

    def _normalize_item(self, item: dict[str, Any]) -> ConnectorProduct:
        item_info = item.get("ItemInfo") or {}
        title = (item_info.get("Title") or {}).get("DisplayValue")
        by_line = (item_info.get("ByLineInfo") or {})
        brand = (by_line.get("Brand") or {}).get("DisplayValue")
        manufacturer = (by_line.get("Manufacturer") or {}).get("DisplayValue")

        product_info = (item_info.get("ProductInfo") or {})
        model = (product_info.get("Model") or {}).get("DisplayValue")

        listings = ((item.get("Offers") or {}).get("Listings")) or []
        listing = listings[0] if listings else {}
        price_info = listing.get("Price") or {}
        saving_basis = listing.get("SavingBasis") or {}

        price = _to_float(price_info.get("Amount"))
        original_price = _to_float(saving_basis.get("Amount"))
        currency = price_info.get("Currency") or saving_basis.get("Currency")

        discount_pct = None
        if price and original_price and original_price > 0:
            discount_pct = round((1 - price / original_price) * 100, 2)

        availability = (listing.get("Availability") or {}).get("Message")
        images = item.get("Images") or {}
        primary = ((images.get("Primary") or {}).get("Large") or {}).get("URL")

        browse_nodes = ((item.get("BrowseNodeInfo") or {}).get("BrowseNodes")) or []
        category_id = str(browse_nodes[0].get("Id")) if browse_nodes else None

        return ConnectorProduct(
            external_id=str(item.get("ASIN")),
            title=str(title or "").strip(),
            category_id=category_id,
            brand=brand or manufacturer,
            model=model,
            condition=None,
            currency=currency,
            price=price,
            original_price=original_price,
            discount_pct=discount_pct,
            # A PA-API não expõe comissão de associado.
            affiliate_commission_pct=None,
            available_quantity=None,
            sold_quantity=None,
            is_available=availability is not None or price is not None,
            rating=None,
            review_count=None,
            has_promotion=bool(discount_pct) or None,
            product_url=item.get("DetailPageURL"),
            images=[primary] if primary else None,
            attributes={"availability": availability} if availability else None,
        )

    def fetch_sales(self, *, since: datetime | None = None) -> list[SalesRecord]:
        """A PA-API não expõe vendas ao associado; elas ficam no painel do programa."""
        logger.info("fetch_sales da Amazon não implementado: a PA-API não expõe vendas")
        return []

    def search_competitor(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Busca por termo. Serve de proxy para saturação de oferta."""
        options = AmazonAdapterOptions(keyword=query, max_items=min(limit, 10))
        batch = self.fetch_products(options=options)
        return [
            {
                "platform": self.name,
                "query": query,
                "external_id": product.external_id,
                "title": product.title,
                "price": product.price,
                "currency": product.currency,
                "permalink": product.product_url,
                "brand": product.brand,
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
    "AmazonAdapter",
    "AmazonAdapterOptions",
    "AmazonConfig",
    "AmazonError",
    "AmazonNotConfigured",
    "AmazonThrottled",
]
