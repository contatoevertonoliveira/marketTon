"""Tracking: links de afiliado, cliques, vendas e comissões.

Briefing seções 9, 10 e 11 — o sistema precisa acompanhar publicações e vendas,
exibir receita e comissão, e preservar histórico suficiente para comparar
previsão com resultado real.

Distinção deliberada entre valores *estimados* e *confirmados*: plataformas de
afiliado atrasam a confirmação da comissão. Misturar os dois produziria receita
fabricada, que o briefing seção 2 proíbe.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db.base import (
    Base,
    BigIntPK,
    Marketplace,
    TimestampMixin,
    enum_column,
)

# Valores monetários com 2 casas; somas de relatório precisam fechar.
MONEY = Numeric(14, 2)


class AffiliateLink(Base, TimestampMixin):
    """Link de afiliado rastreável, por produto e canal."""

    __tablename__ = "affiliate_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    portfolio_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolio_items.id", ondelete="CASCADE"), index=True
    )

    marketplace: Mapped[Marketplace] = mapped_column(
        enum_column(Marketplace, "marketplace"),
        nullable=False,
        index=True,
    )
    channel: Mapped[str | None] = mapped_column(String(64), index=True)

    destination_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    affiliate_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    short_code: Mapped[str] = mapped_column(String(32), nullable=False)

    campaign: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    clicks_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sales_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # O `secondary` precisa ser declarado nos DOIS lados de uma associação N:N.
    # Aqui ele é resolvido por string porque a tabela está declarada em
    # `core.db.creative` — direção oposta à importação, para evitar ciclo.
    publications: Mapped[list[Publication]] = relationship(
        secondary="publication_links",
        back_populates="affiliate_links",
    )

    __table_args__ = (
        UniqueConstraint("short_code", name="uq_affiliate_links_short_code"),
        Index("ix_affiliate_links_marketplace_active", "marketplace", "is_active"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AffiliateLink {self.short_code} {self.marketplace.value}>"


class ClickEvent(Base, TimestampMixin):
    """Clique em um link de afiliado. Base de CTR e de atribuição."""

    __tablename__ = "click_events"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)

    affiliate_link_id: Mapped[int] = mapped_column(
        ForeignKey("affiliate_links.id", ondelete="CASCADE"), nullable=False, index=True
    )
    portfolio_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolio_items.id", ondelete="SET NULL"), index=True
    )
    publication_id: Mapped[int | None] = mapped_column(
        ForeignKey("publications.id", ondelete="SET NULL"), index=True
    )

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    # Identificador do marketplace para deduplicação de relatórios de clique.
    external_click_id: Mapped[str | None] = mapped_column(String(128), index=True)

    # Sinais de atribuição. Não identificam pessoa: são agregáveis e ficam
    # sujeitos à LGPD (ver dashboard/config/mural_regras.md, seção 5).
    channel: Mapped[str | None] = mapped_column(String(64), index=True)
    referrer: Mapped[str | None] = mapped_column(String(1024))
    country: Mapped[str | None] = mapped_column(String(8))
    device: Mapped[str | None] = mapped_column(String(32))

    # Custo do clique quando veio de tráfego pago (ROAS/CPA).
    cost: Mapped[float | None] = mapped_column(MONEY)

    __table_args__ = (
        UniqueConstraint("external_click_id", name="uq_click_events_external_click_id"),
        Index("ix_click_events_link_occurred", "affiliate_link_id", "occurred_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ClickEvent link={self.affiliate_link_id} @{self.occurred_at:%Y-%m-%d %H:%M}>"


class Sale(Base, TimestampMixin):
    """Venda atribuída. `external_order_id` garante idempotência da ingestão."""

    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)

    portfolio_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolio_items.id", ondelete="SET NULL"), index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), index=True
    )
    affiliate_link_id: Mapped[int | None] = mapped_column(
        ForeignKey("affiliate_links.id", ondelete="SET NULL"), index=True
    )
    publication_id: Mapped[int | None] = mapped_column(
        ForeignKey("publications.id", ondelete="SET NULL"), index=True
    )

    marketplace: Mapped[Marketplace] = mapped_column(
        enum_column(Marketplace, "marketplace"),
        nullable=False,
        index=True,
    )
    external_order_id: Mapped[str | None] = mapped_column(String(128), index=True)

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    currency: Mapped[str | None] = mapped_column(String(8))

    gross_amount: Mapped[float | None] = mapped_column(MONEY)  # valor pago pelo comprador
    net_amount: Mapped[float | None] = mapped_column(MONEY)  # valor líquido ao vendedor

    channel: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str | None] = mapped_column(String(32), index=True)
    source_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_records.id", ondelete="SET NULL"), index=True
    )

    commissions: Mapped[list[Commission]] = relationship(
        back_populates="sale",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("marketplace", "external_order_id", name="uq_sales_marketplace_order"),
        Index("ix_sales_marketplace_occurred", "marketplace", "occurred_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Sale {self.marketplace.value} {self.external_order_id} {self.gross_amount}>"


class Commission(Base, TimestampMixin):
    """Comissão de uma venda, separando estimado de confirmado.

    O briefing seção 9 pede "receita e comissão geradas". Reportar comissão
    estimada como receita realizada seria exatamente o tipo de fabricação
    silenciosa que a seção 2 proíbe.
    """

    __tablename__ = "commissions"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)

    sale_id: Mapped[int | None] = mapped_column(
        ForeignKey("sales.id", ondelete="CASCADE"), index=True
    )
    portfolio_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolio_items.id", ondelete="SET NULL"), index=True
    )
    marketplace: Mapped[Marketplace] = mapped_column(
        enum_column(Marketplace, "marketplace"),
        nullable=False,
        index=True,
    )

    estimated_amount: Mapped[float | None] = mapped_column(MONEY)
    confirmed_amount: Mapped[float | None] = mapped_column(MONEY)
    currency: Mapped[str | None] = mapped_column(String(8))

    rate_basis_points: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(String(32), index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    external_commission_id: Mapped[str | None] = mapped_column(String(128), index=True)
    source_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_records.id", ondelete="SET NULL"), index=True
    )

    sale: Mapped[Sale | None] = relationship(back_populates="commissions")

    __table_args__ = (
        Index("ix_commissions_status_confirmed", "status", "confirmed_at"),
        Index("ix_commissions_marketplace_confirmed", "marketplace", "confirmed_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Commission {self.marketplace.value} est={self.estimated_amount} conf={self.confirmed_amount}>"
