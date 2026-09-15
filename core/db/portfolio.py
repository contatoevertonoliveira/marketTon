"""Portfólio operacional, transições de estado e recomendações acionáveis.

Briefing seção 7: os produtos aprovados entram no portfólio e as transições de
estado são controladas pelo backend. Briefing seção 16: o sistema transforma
dados em recomendação e ação, portanto toda recomendação fica registrada com o
score que a originou — é isso que permite auditar a decisão depois.
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
    PortfolioState,
    RecommendationKind,
    ScoreDimension,
    TimestampMixin,
    enum_column,
)


class PortfolioItem(Base, TimestampMixin):
    """Produto incorporado à operação, com estado corrente e resultado real."""

    __tablename__ = "portfolio_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    marketplace: Mapped[Marketplace] = mapped_column(
        enum_column(Marketplace, "marketplace"),
        nullable=False,
        index=True,
    )
    label: Mapped[str | None] = mapped_column(String(255))

    state: Mapped[PortfolioState] = mapped_column(
        enum_column(PortfolioState, "portfolio_state"),
        nullable=False,
        default=PortfolioState.DISCOVERED,
        index=True,
    )
    state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Score de oportunidade vigente no momento da entrada. Congelado de propósito:
    # o motor de aprendizado compara esta previsão com o resultado real abaixo.
    entry_score_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("score_runs.id", ondelete="SET NULL"), index=True
    )
    entry_score: Mapped[float | None] = mapped_column(Numeric(6, 3))

    added_by: Mapped[str | None] = mapped_column(String(128))
    notes: Mapped[str | None] = mapped_column(Text)

    # --- Resultado real (briefing seções 10 e 11) -----------------------------
    # Todos anuláveis: só existem depois que o produto começa a vender.
    revenue_total: Mapped[float | None] = mapped_column(Float)
    commission_total: Mapped[float | None] = mapped_column(Float)
    clicks_total: Mapped[int | None] = mapped_column(Integer)
    conversions_total: Mapped[int | None] = mapped_column(Integer)
    # CTR/conversão podem ser armazenados ou derivados; derivados são calculados.
    last_metrics_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    paused_reason: Mapped[str | None] = mapped_column(Text)
    removed_reason: Mapped[str | None] = mapped_column(Text)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    transitions: Mapped[list[PortfolioTransition]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="PortfolioTransition.occurred_at",
    )
    recommendations: Mapped[list[Recommendation]] = relationship(
        back_populates="portfolio_item",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("product_id", name="uq_portfolio_items_product_id"),
        Index("ix_portfolio_items_state_changed", "state", "state_changed_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PortfolioItem {self.id} {self.state.value}>"


class PortfolioTransition(Base, TimestampMixin):
    """Trilha de auditoria de cada mudança de estado."""

    __tablename__ = "portfolio_transitions"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)

    portfolio_item_id: Mapped[int] = mapped_column(
        ForeignKey("portfolio_items.id", ondelete="CASCADE"), nullable=False, index=True
    )

    from_state: Mapped[PortfolioState | None] = mapped_column(
        enum_column(PortfolioState, "portfolio_state")
    )
    to_state: Mapped[PortfolioState] = mapped_column(
        enum_column(PortfolioState, "portfolio_state"),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    # Quem/o que disparou: "operator:everton", "agent:master", "scheduler".
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)

    # Recomendação que embasou a transição, quando houve.
    triggered_by_recommendation_id: Mapped[int | None] = mapped_column(
        ForeignKey("recommendations.id", ondelete="SET NULL")
    )

    item: Mapped[PortfolioItem] = relationship(back_populates="transitions")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PortfolioTransition {self.from_state}->{self.to_state}>"


class Recommendation(Base, TimestampMixin):
    """Sugestão acionável do sistema, com justificativa e desfecho.

    `is_actioned` + `actioned_at` fecham o ciclo previsão → decisão: o motor de
    aprendizado precisa saber não só o que foi sugerido, mas o que o operador
    de fato fez e qual foi o resultado.
    """

    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)

    portfolio_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolio_items.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )

    kind: Mapped[RecommendationKind] = mapped_column(
        enum_column(RecommendationKind, "recommendation_kind"),
        nullable=False,
        index=True,
    )
    dimension: Mapped[ScoreDimension | None] = mapped_column(
        enum_column(ScoreDimension, "score_dimension")
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Explicação legível: "por que este produto foi recomendado?".
    rationale: Mapped[str | None] = mapped_column(Text)
    # Contribuições positivas e negativas já formatadas para exibição.
    positive_factors: Mapped[list | None] = mapped_column(JSON)
    negative_factors: Mapped[list | None] = mapped_column(JSON)

    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[float | None] = mapped_column(Float)

    score_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("score_runs.id", ondelete="SET NULL"), index=True
    )

    is_actioned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    actioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actioned_by: Mapped[str | None] = mapped_column(String(128))
    # Desfecho observado após a ação. Alimenta a calibração.
    outcome: Mapped[str | None] = mapped_column(Text)

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    portfolio_item: Mapped[PortfolioItem | None] = relationship(back_populates="recommendations")

    __table_args__ = (
        Index("ix_recommendations_open", "is_actioned", "priority"),
        Index("ix_recommendations_kind_created", "kind", "created_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Recommendation {self.kind.value} {self.title[:40]!r}>"
