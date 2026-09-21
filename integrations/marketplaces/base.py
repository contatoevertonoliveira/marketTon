"""Contrato dos adapters de marketplace e modelo de dado normalizado.

Duas decisões de projeto que valem explicação.

**Por que não `DataFrame`.** O adapter anterior devolvia `pandas.DataFrame`, o que
significa que o schema do domínio era "as colunas que aquele `DataFrame` tinha".
Campo ausente e campo nulo eram indistinguíveis, e cada página do dashboard
adivinhava nomes de coluna. Aqui o adapter devolve `ConnectorProduct`, com campo
`None` explícito quando a fonte não expõe o dado — que é a distinção da qual o
motor de scoring depende para calcular `confidence`.

**Por que `ConnectorBatch`.** Um dado sem procedência não entra no domínio. O
adapter não devolve só o produto: devolve também o endpoint consultado, o momento
da coleta, a confiabilidade da fonte e os avisos da chamada. É esse envelope que
permite gravar `source_records` sem inventar metadado depois.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlparse


@dataclass
class ConnectorProduct:
    """Produto normalizado, independente do marketplace de origem.

    Todos os campos além da identidade são opcionais de propósito: `None` significa
    "a fonte não informou", nunca "é zero".
    """

    external_id: str
    title: str

    # --- Classificação --------------------------------------------------------
    category_id: str | None = None
    category_path: list[str] | None = None
    brand: str | None = None
    model: str | None = None
    condition: str | None = None

    # --- Vendedor -------------------------------------------------------------
    seller_external_id: str | None = None
    seller_nickname: str | None = None
    seller_reputation_level: str | None = None
    seller_reputation_score: float | None = None
    seller_total_sales: int | None = None
    seller_positive_rating_pct: float | None = None
    seller_feedback_count: int | None = None
    seller_is_official_store: bool | None = None
    seller_power_seller_status: str | None = None
    seller_active_listings: int | None = None
    seller_active_promotions: int | None = None
    seller_response_rate_pct: float | None = None

    # --- Comercial ------------------------------------------------------------
    currency: str | None = None
    price: float | None = None
    original_price: float | None = None
    discount_pct: float | None = None
    affiliate_commission_pct: float | None = None
    affiliate_commission_fixed: float | None = None

    # --- Disponibilidade ------------------------------------------------------
    available_quantity: int | None = None
    sold_quantity: int | None = None
    is_available: bool | None = None

    # --- Avaliações e sinais de demanda ---------------------------------------
    rating: float | None = None
    review_count: int | None = None
    ranking_position: int | None = None
    popularity_score: float | None = None

    # --- Promoções ------------------------------------------------------------
    has_promotion: bool | None = None
    coupons: list[dict[str, Any]] | None = None

    # --- URLs e mídia ---------------------------------------------------------
    product_url: str | None = None
    affiliate_url: str | None = None
    images: list[str] | None = None

    # --- Sinais temporais (viram `product_metrics`) ---------------------------
    sold_last_period: int | None = None
    visits: int | None = None
    views: int | None = None
    wishlist_count: int | None = None

    # --- Atributos livres do marketplace --------------------------------------
    attributes: dict[str, Any] | None = None

    def identity_key(self) -> str:
        """Chave de deduplicação entre marketplaces.

        Título normalizado + marca. Deliberadamente conservadora: prefere deixar de
        agrupar dois anúncios do mesmo produto a agrupar produtos diferentes, porque
        um falso positivo contamina a série temporal de preço.
        """
        parts = [self.title or ""]
        if self.brand:
            parts.append(self.brand)
        raw = " ".join(parts).lower()
        cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in raw)
        return " ".join(cleaned.split())[:320]

    def has_any_market_signal(self) -> bool:
        """Se não há preço nem demanda, o produto não é analisável."""
        return any(
            value is not None
            for value in (self.price, self.sold_quantity, self.sold_last_period, self.review_count)
        )


@dataclass
class ConnectorBatch:
    """Envelope de uma coleta: os dados e a procedência deles."""

    connector: str
    products: list[ConnectorProduct] = field(default_factory=list)

    collected_at: datetime | None = None
    endpoint: str | None = None
    reliability: float = 1.0
    # Avisos da coleta (paginação incompleta, campo não exposto, rate limit).
    # Ficam gravados em `source_records.warnings` para não se perderem.
    warnings: list[str] = field(default_factory=list)
    raw: dict[str, Any] | None = None

    @property
    def is_empty(self) -> bool:
        return not self.products


@dataclass
class SalesRecord:
    """Venda normalizada. `external_order_id` garante idempotência da ingestão."""

    external_order_id: str | None
    occurred_at: datetime
    quantity: int = 1
    currency: str | None = None
    gross_amount: float | None = None
    net_amount: float | None = None
    product_external_id: str | None = None
    channel: str | None = None
    status: str | None = None
    # Comissão mantém estimado e confirmado separados: plataformas de afiliado
    # atrasam a confirmação, e somar os dois produziria receita fabricada.
    commission_estimated: float | None = None
    commission_confirmed: float | None = None
    commission_rate_basis_points: int | None = None


class MarketplaceAdapter(ABC):
    """Interface de um marketplace.

    `fetch_products` e `search_competitor` são obrigatórios. `fetch_sales` tem
    implementação padrão vazia porque nem todo marketplace expõe vendas de
    afiliado pela mesma API — mas declarar explicitamente o vazio é diferente de
    deixar o método abstrato e descobrir na chamada.
    """

    name: str = "base"
    # Confiabilidade da fonte, gravada em `source_records`. 1.0 = API oficial.
    reliability: float = 1.0
    # Comissão por categoria informada pelo operador (`commission_rates`). Vazio =
    # sem estimativa; nunca há valor embutido.
    commission_rates: dict[str, float] = {}

    @abstractmethod
    def fetch_products(self, *, limit: int | None = None) -> ConnectorBatch:
        """Coleta o catálogo do vendedor/afiliado."""

    @abstractmethod
    def search_competitor(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Busca anúncios concorrentes. Insumo do Creative Saturation Score."""

    def fetch_sales(self, *, since: datetime | None = None) -> list[SalesRecord]:
        """Vendas atribuídas. Vazio por padrão: não inventamos venda."""
        return []

    def is_configured(self) -> bool:
        """Se as credenciais necessárias estão presentes."""
        return True

    @staticmethod
    def host_of(url: str) -> str:
        try:
            return urlparse(url).netloc or url
        except ValueError:
            return url


__all__ = [
    "ConnectorBatch",
    "ConnectorProduct",
    "MarketplaceAdapter",
    "SalesRecord",
]
