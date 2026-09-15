"""Catálogo: procedência, vendedores, produtos e séries temporais.

Briefing seção 4 — todo dado coletado possui origem, timestamp, marketplace e
nível de confiabilidade. Toda coluna numérica de mercado é anulável porque o
briefing seção 2 proíbe estimativa silenciosa: ausência de dado é `NULL`.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db.base import (
    Base,
    BigIntPK,
    ConnectorKind,
    Marketplace,
    TimestampMixin,
    enum_column,
)


class SourceRecord(Base, TimestampMixin):
    """Procedência de uma coleta. Nada entra no domínio sem passar por aqui."""

    __tablename__ = "source_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    marketplace: Mapped[Marketplace] = mapped_column(
        enum_column(Marketplace, "marketplace"),
        nullable=False,
        index=True,
    )
    # Nome do adapter/connector que produziu o dado (ex.: "mercado_livre").
    connector: Mapped[str] = mapped_column(String(64), nullable=False)
    connector_kind: Mapped[ConnectorKind] = mapped_column(
        enum_column(ConnectorKind, "connector_kind"),
        nullable=False,
    )

    # Endpoint/URL exata consultada. Permite auditar a legitimidade da fonte.
    endpoint: Mapped[str | None] = mapped_column(String(1024))
    external_id: Mapped[str | None] = mapped_column(String(128), index=True)
    external_parent_id: Mapped[str | None] = mapped_column(String(128))

    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    # Confiabilidade auto-declarada pelo connector (0..1). 1.0 = API oficial.
    reliability: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    # De onde veio o dado quando não é campo estruturado (ex.: "html:title").
    field_source: Mapped[str | None] = mapped_column(String(128))
    notes: Mapped[str | None] = mapped_column(Text)

    warnings: Mapped[list | None] = mapped_column(JSON)
    raw: Mapped[dict | None] = mapped_column(JSON)

    products: Mapped[list[Product]] = relationship(back_populates="source_record")

    __table_args__ = (
        Index("ix_source_records_marketplace_collected", "marketplace", "collected_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - conveniência de debug
        return f"<SourceRecord {self.marketplace.value}:{self.external_id} @{self.collected_at:%Y-%m-%d}>"


class Seller(Base, TimestampMixin):
    """Vendedor/produtor. Insumo do Producer Momentum Score."""

    __tablename__ = "sellers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    marketplace: Mapped[Marketplace] = mapped_column(
        enum_column(Marketplace, "marketplace"),
        nullable=False,
        index=True,
    )
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255))

    # Sinais comerciais do produtor. `None` = não exposto pela fonte.
    reputation_level: Mapped[str | None] = mapped_column(String(64))
    reputation_score: Mapped[float | None] = mapped_column(Float)
    total_sales: Mapped[int | None] = mapped_column(Integer)
    positive_rating_pct: Mapped[float | None] = mapped_column(Float)
    feedback_count: Mapped[int | None] = mapped_column(Integer)
    is_official_store: Mapped[bool | None] = mapped_column(Boolean)
    power_seller_status: Mapped[str | None] = mapped_column(String(64))
    registration_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_record_id: Mapped[int] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    products: Mapped[list[Product]] = relationship(back_populates="seller")

    __table_args__ = (
        UniqueConstraint("marketplace", "external_id", name="uq_sellers_marketplace_external_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Seller {self.marketplace.value}:{self.external_id} {self.nickname or ''}>"


class Product(Base, TimestampMixin):
    """Produto normalizado. Campos de mercado ausentes permanecem `NULL`."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # --- Identificação --------------------------------------------------------
    marketplace: Mapped[Marketplace] = mapped_column(
        enum_column(Marketplace, "marketplace"),
        nullable=False,
        index=True,
    )
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)

    # Chave de deduplicação entre marketplaces (título normalizado + marca).
    identity_key: Mapped[str | None] = mapped_column(String(320), index=True)

    # --- Classificação --------------------------------------------------------
    category_id: Mapped[str | None] = mapped_column(String(128))
    category_path: Mapped[list | None] = mapped_column(JSON)
    brand: Mapped[str | None] = mapped_column(String(255))
    model: Mapped[str | None] = mapped_column(String(255))
    condition: Mapped[str | None] = mapped_column(String(64))

    # --- Vendedor -------------------------------------------------------------
    seller_id: Mapped[int | None] = mapped_column(ForeignKey("sellers.id", ondelete="SET NULL"), index=True)

    # --- Comercial ------------------------------------------------------------
    currency: Mapped[str | None] = mapped_column(String(8))
    price: Mapped[float | None] = mapped_column(Float)
    original_price: Mapped[float | None] = mapped_column(Float)
    discount_pct: Mapped[float | None] = mapped_column(Float)
    affiliate_commission_pct: Mapped[float | None] = mapped_column(Float)
    affiliate_commission_fixed: Mapped[float | None] = mapped_column(Float)

    # --- Disponibilidade ------------------------------------------------------
    available_quantity: Mapped[int | None] = mapped_column(Integer)
    sold_quantity: Mapped[int | None] = mapped_column(Integer)
    is_available: Mapped[bool | None] = mapped_column(Boolean)

    # --- Avaliações / sinais de demanda --------------------------------------
    rating: Mapped[float | None] = mapped_column(Float)
    review_count: Mapped[int | None] = mapped_column(Integer)
    ranking_position: Mapped[int | None] = mapped_column(Integer)
    popularity_score: Mapped[float | None] = mapped_column(Float)

    # --- Promoções ------------------------------------------------------------
    has_promotion: Mapped[bool | None] = mapped_column(Boolean)
    coupons: Mapped[list | None] = mapped_column(JSON)

    # --- URLs / mídia ---------------------------------------------------------
    product_url: Mapped[str | None] = mapped_column(String(1024))
    affiliate_url: Mapped[str | None] = mapped_column(String(1024))
    images: Mapped[list | None] = mapped_column(JSON)

    # --- Atributos livres do marketplace -------------------------------------
    attributes: Mapped[dict | None] = mapped_column(JSON)

    # --- Procedência / ciclo de vida -----------------------------------------
    source_record_id: Mapped[int] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    seller: Mapped[Seller | None] = relationship(back_populates="products")
    source_record: Mapped[SourceRecord] = relationship(back_populates="products")
    metrics: Mapped[list[ProductMetric]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    price_history: Mapped[list[PriceHistory]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("marketplace", "external_id", name="uq_products_marketplace_external_id"),
        Index("ix_products_marketplace_category", "marketplace", "category_id"),
        Index("ix_products_active_last_seen", "is_active", "last_seen_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Product {self.marketplace.value}:{self.external_id} {self.title[:40]!r}>"


class ProductMetric(Base, TimestampMixin):
    """Série temporal de sinais de demanda. Base do Heat Score e da evolução temporal.

    Cada linha é uma observação datada. O valor de um sinal ausente é `NULL`,
    nunca 0 — a diferença entre "não vendeu" e "não sabemos" importa.
    """

    __tablename__ = "product_metrics"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    # Sinais de demanda. Todos opcionais.
    sales_rank: Mapped[int | None] = mapped_column(Integer)
    sold_last_period: Mapped[int | None] = mapped_column(Integer)
    visits: Mapped[int | None] = mapped_column(Integer)
    views: Mapped[int | None] = mapped_column(Integer)
    wishlist_count: Mapped[int | None] = mapped_column(Integer)
    search_interest: Mapped[float | None] = mapped_column(Float)
    review_count: Mapped[int | None] = mapped_column(Integer)
    rating: Mapped[float | None] = mapped_column(Float)

    source_record_id: Mapped[int] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    product: Mapped[Product] = relationship(back_populates="metrics")

    __table_args__ = (
        UniqueConstraint("product_id", "observed_at", name="uq_product_metrics_product_observed"),
        Index("ix_product_metrics_product_observed", "product_id", "observed_at"),
    )


class PriceHistory(Base, TimestampMixin):
    """Histórico de preço. Insumo de desconto, promoção e elasticidade."""

    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    price: Mapped[float | None] = mapped_column(Float)
    original_price: Mapped[float | None] = mapped_column(Float)
    discount_pct: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str | None] = mapped_column(String(8))
    available_quantity: Mapped[int | None] = mapped_column(Integer)
    is_available: Mapped[bool | None] = mapped_column(Boolean)

    source_record_id: Mapped[int] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    product: Mapped[Product] = relationship(back_populates="price_history")

    __table_args__ = (
        UniqueConstraint("product_id", "observed_at", name="uq_price_history_product_observed"),
        Index("ix_price_history_product_observed", "product_id", "observed_at"),
    )
