"""Adapter da Amazon — Creators API.

Documentação: https://affiliate-program.amazon.com/creatorsapi/docs/

Isto substitui a Product Advertising API 5.0 (AWS Signature V4): confirmado ao
vivo que a PA-API está aposentada — uma chamada real devolveu HTTP 403 com
`"Product Advertising API is deprecated. Please migrate to Creators API."`
(abril/maio de 2026 é a janela de desativação oficial da Amazon). Não é um bug
para corrigir: a API inteira que o adapter anterior usava não existe mais.

A Creators API troca a assinatura AWS SigV4 por OAuth2 `client_credentials`
(Bearer token) — mais simples, sem `Access Key`/`Secret Key` de IAM, só
`Client ID`/`Client Secret` do app cadastrado em Associates Central. O token
é cacheado e renovado via o mesmo `TokenStore` (Postgres) que Mercado Livre e
TikTok Shop já usam.

Notas de honestidade dos dados:

* **Comissão de associado** continua não exposta pela API: é definida por
  categoria no programa, não por item. Fica `None`.
* **Vendas** não são expostas ao associado; ficam no painel do programa.
* **Elegibilidade**: a Creators API exige conta de Associado aprovada com
  histórico de vendas — inicialmente 3 vendas qualificadas em 180 dias, e para
  manter acesso contínuo, 10 vendas qualificadas nos últimos 30 dias. Sem
  vendas recentes o acesso é suspenso temporariamente (não é erro de
  configuração, é a regra do programa).
* Confiança moderada no path exato de `SearchItems` (`/catalog/v1/searchItems`)
  e no formato de resposta: montados a partir de fragmentos de documentação
  de terceiros, já que a doc oficial completa não abre para scraping — validar
  contra uma chamada real assim que houver credenciais da Creators API.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from config.settings import get_settings
from integrations.marketplaces.base import (
    ConnectorBatch,
    ConnectorProduct,
    MarketplaceAdapter,
    SalesRecord,
)
from integrations.marketplaces.token_store import TokenSet, TokenStore

logger = logging.getLogger(__name__)

DEFAULT_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
DEFAULT_API_URL = "https://creatorsapi.amazon"
SEARCH_ITEMS_PATH = "/catalog/v1/searchItems"
SCOPE = "creatorsapi::default"
RESOURCES = [
    "itemInfo.title",
    "itemInfo.byLineInfo",
    "itemInfo.features",
    "offersV2.listings.price",
    "offersV2.listings.availability",
    "images.primary.large",
    "browseNodeInfo.browseNodes",
]


class AmazonError(RuntimeError):
    """Falha ao falar com a Amazon."""


class AmazonNotConfigured(AmazonError):
    """Credenciais ausentes. Erro de configuração, não de rede."""


class AmazonThrottled(AmazonError):
    """Acesso negado ou limitado.

    A Creators API suspende o acesso quando a conta de associado não tem 10
    vendas qualificadas nos últimos 30 dias — motivo frequente e pouco óbvio
    por trás de um 401/403 aparentemente de credencial.
    """


@dataclass
class AmazonConfig:
    client_id: str = ""
    client_secret: str = ""
    partner_tag: str = ""
    marketplace: str = "www.amazon.com.br"
    token_url: str = DEFAULT_TOKEN_URL
    api_url: str = DEFAULT_API_URL
    access_token: str = ""
    token_expires_at: datetime | None = None
    timeout: float = 20.0


@dataclass
class AmazonAdapterOptions:
    """Opções de coleta. `keyword` é obrigatório: a Creators API busca por
    termo (ou marca/autor/ator), não lista o catálogo do associado."""

    keyword: str = ""
    max_items: int = 10  # tamanho de página observado na documentação
    warnings: list[str] = field(default_factory=list)


class AmazonAdapter(MarketplaceAdapter):
    name = "amazon"
    reliability = 1.0  # API oficial

    def __init__(self, cfg: AmazonConfig | None = None, token_store: TokenStore | None = None):
        self.cfg = cfg or self._load_config()
        self.tokens = token_store or TokenStore()
        self._load_persisted_token()

    @staticmethod
    def _load_config() -> AmazonConfig:
        settings = get_settings()
        return AmazonConfig(
            client_id=settings.amazon_client_id,
            client_secret=settings.amazon_client_secret,
            partner_tag=settings.amazon_partner_tag,
            marketplace=settings.amazon_marketplace,
            token_url=settings.amazon_token_url,
            api_url=settings.amazon_api_url,
            timeout=settings.connector_timeout_seconds,
        )

    def _load_persisted_token(self) -> None:
        stored = self.tokens.load(self.name)
        if stored is None:
            return
        if stored.access_token:
            self.cfg.access_token = stored.access_token
        self.cfg.token_expires_at = stored.expires_at

    def _persist_token(self) -> None:
        self.tokens.save(
            self.name,
            TokenSet(access_token=self.cfg.access_token, expires_at=self.cfg.token_expires_at),
        )

    def is_configured(self) -> bool:
        return bool(self.cfg.client_id and self.cfg.client_secret and self.cfg.partner_tag)

    def get_status(self) -> dict[str, Any]:
        return {
            "connector": self.name,
            "configured": self.is_configured(),
            "has_access_token": bool(self.cfg.access_token),
            "token_expires_at": self.cfg.token_expires_at.isoformat() if self.cfg.token_expires_at else None,
            "marketplace": self.cfg.marketplace,
            "reliability": self.reliability,
            "note": (
                "Creators API exige conta de Associado com pelo menos 10 vendas qualificadas "
                "nos últimos 30 dias para manter o acesso ativo; comissão por categoria não é "
                "exposta pela API."
            ),
        }

    # --- OAuth2 client_credentials ----------------------------------------------

    def _ensure_access_token(self) -> str:
        if self.cfg.access_token and self.cfg.token_expires_at:
            if datetime.now(UTC) < self.cfg.token_expires_at - timedelta(minutes=2):
                return self.cfg.access_token

        if not (self.cfg.client_id and self.cfg.client_secret):
            raise AmazonNotConfigured(
                "Credenciais da Amazon incompletas. São necessários client_id, client_secret e "
                "partner_tag (MARKETPLACE_AMAZON_* no .env, ou salvos em Integrações)."
            )

        try:
            response = requests.post(
                self.cfg.token_url,
                json={
                    "grant_type": "client_credentials",
                    "client_id": self.cfg.client_id,
                    "client_secret": self.cfg.client_secret,
                    "scope": SCOPE,
                },
                headers={"Content-Type": "application/json"},
                timeout=self.cfg.timeout,
            )
        except requests.RequestException as exc:
            raise AmazonError(f"falha de rede ao obter token em {self.cfg.token_url}: {exc}") from exc

        if response.status_code != 200:
            raise AmazonError(
                f"obtenção de token falhou: HTTP {response.status_code} — {response.text[:500]}"
            )

        data = response.json()
        access_token = data.get("access_token", "")
        expires_in = data.get("expires_in")
        self.cfg.access_token = access_token
        self.cfg.token_expires_at = (
            datetime.now(UTC) + timedelta(seconds=int(expires_in)) if expires_in else None
        )
        self._persist_token()
        return access_token

    # --- HTTP ---------------------------------------------------------------------

    def _call(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.is_configured():
            raise AmazonNotConfigured(
                "Credenciais da Amazon incompletas. São necessários client_id, client_secret e "
                "partner_tag (MARKETPLACE_AMAZON_* no .env, ou salvos em Integrações)."
            )
        token = self._ensure_access_token()

        try:
            response = requests.post(
                f"{self.cfg.api_url}{path}",
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "x-marketplace": self.cfg.marketplace,
                },
                timeout=self.cfg.timeout,
            )
        except requests.RequestException as exc:
            raise AmazonError(f"falha de rede em {path}: {exc}") from exc

        if response.status_code in (401, 403):
            raise AmazonThrottled(
                f"Amazon respondeu {response.status_code}. Causas comuns: token expirado, ou "
                "conta de associado sem 10 vendas qualificadas nos últimos 30 dias. "
                f"Corpo: {response.text[:300]}"
            )
        if response.status_code == 429:
            raise AmazonThrottled("Amazon respondeu 429 (limite de requisições por segundo).")
        if response.status_code != 200:
            raise AmazonError(f"HTTP {response.status_code} em {path}: {response.text[:400]}")

        return response.json()

    # --- Coleta ---------------------------------------------------------------------

    def fetch_products(
        self, *, limit: int | None = None, options: AmazonAdapterOptions | None = None
    ) -> ConnectorBatch:
        """Busca por termo — a Creators API não lista o catálogo do associado."""
        options = options or AmazonAdapterOptions()
        if limit is not None:
            options.max_items = limit
        if not options.keyword:
            raise AmazonError(
                "a Creators API não expõe o catálogo do associado; informe um termo de busca "
                "(AmazonAdapterOptions.keyword) para coletar."
            )

        collected_at = datetime.now(UTC)
        payload = {
            "partnerTag": self.cfg.partner_tag,
            "keywords": options.keyword,
            "itemCount": min(options.max_items, 10),
            "resources": RESOURCES,
        }
        data = self._call(SEARCH_ITEMS_PATH, payload)

        result = data.get("searchResult") or {}
        items = result.get("items") or []
        products = [self._normalize_item(item) for item in items]

        return ConnectorBatch(
            connector=self.name,
            products=products[: options.max_items],
            collected_at=collected_at,
            endpoint=f"{self.cfg.api_url}{SEARCH_ITEMS_PATH}",
            reliability=self.reliability,
            warnings=list(options.warnings),
            raw={"keyword": options.keyword, "marketplace": self.cfg.marketplace},
        )

    def _normalize_item(self, item: dict[str, Any]) -> ConnectorProduct:
        item_info = item.get("itemInfo") or {}
        title = (item_info.get("title") or {}).get("displayValue")
        by_line = item_info.get("byLineInfo") or {}
        brand = (by_line.get("brand") or {}).get("displayValue")

        listings = ((item.get("offersV2") or {}).get("listings")) or []
        listing = listings[0] if listings else {}
        price_money = ((listing.get("price") or {}).get("money")) or {}
        price = _to_float(price_money.get("amount"))
        currency = price_money.get("currency")

        availability = (listing.get("availability") or {}).get("type")

        images = item.get("images") or {}
        primary = ((images.get("primary") or {}).get("large") or {}).get("url")

        browse_nodes = ((item.get("browseNodeInfo") or {}).get("browseNodes")) or []
        category_id = str(browse_nodes[0].get("id")) if browse_nodes else None

        return ConnectorProduct(
            external_id=str(item.get("asin")),
            title=str(title or "").strip(),
            category_id=category_id,
            brand=brand,
            currency=currency,
            price=price,
            # A Creators API não expõe comissão de associado (é por categoria,
            # definida pelo programa — não por item).
            affiliate_commission_pct=None,
            is_available=availability == "IN_STOCK" if availability else None,
            product_url=item.get("detailPageURL"),
            images=[primary] if primary else None,
            attributes={"availability": availability} if availability else None,
        )

    def fetch_sales(self, *, since: datetime | None = None) -> list[SalesRecord]:
        """Vendas de associado ficam no painel do programa, não na API."""
        logger.info("fetch_sales da Amazon não implementado: a Creators API não expõe vendas")
        return []

    def search_competitor(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Busca por termo. Serve de proxy para saturação de oferta."""
        try:
            batch = self.fetch_products(options=AmazonAdapterOptions(keyword=query, max_items=min(limit, 10)))
        except AmazonError:
            return []
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
