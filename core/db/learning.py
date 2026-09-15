"""Motor de aprendizado: previsão → decisão → execução → resultado real.

Briefing seção 11: o sistema deve preservar dados históricos suficientes para
comparar a previsão com o resultado real, e esse resultado deve alimentar
calibrações futuras. Estas duas tabelas são o que fecha o ciclo — sem elas o
sistema apenas exibe dados e nunca aprende (briefing seção 16).
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
    ScoreDimension,
    TimestampMixin,
    enum_column,
)


class PredictionOutcome(Base, TimestampMixin):
    """Uma previsão congelada confrontada com o que de fato aconteceu.

    `predicted_score` é copiado do `ScoreRun` no momento da previsão, não
    referenciado: se o algoritmo for recalibrado depois, a previsão original
    precisa permanecer intacta para a comparação continuar válida.
    """

    __tablename__ = "prediction_outcomes"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)

    score_run_id: Mapped[int] = mapped_column(
        ForeignKey("score_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    portfolio_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolio_items.id", ondelete="SET NULL"), index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), index=True
    )
    recommendation_id: Mapped[int | None] = mapped_column(
        ForeignKey("recommendations.id", ondelete="SET NULL"), index=True
    )

    dimension: Mapped[ScoreDimension] = mapped_column(
        enum_column(ScoreDimension, "score_dimension"),
        nullable=False,
        index=True,
    )
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    marketplace: Mapped[Marketplace | None] = mapped_column(enum_column(Marketplace, "marketplace"))

    predicted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    predicted_score: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False)
    predicted_confidence: Mapped[float | None] = mapped_column(Float)

    # Janela de observação do resultado real.
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)

    # --- Resultado real observado --------------------------------------------
    actual_revenue: Mapped[float | None] = mapped_column(Numeric(14, 2))
    actual_commission: Mapped[float | None] = mapped_column(Numeric(14, 2))
    actual_clicks: Mapped[int | None] = mapped_column(Integer)
    actual_conversions: Mapped[int | None] = mapped_column(Integer)
    actual_ctr: Mapped[float | None] = mapped_column(Float)
    actual_conversion_rate: Mapped[float | None] = mapped_column(Float)

    # Erro da previsão. Positivo = superestimou o desempenho.
    score_error: Mapped[float | None] = mapped_column(Float)
    was_profitable: Mapped[bool | None] = mapped_column(Boolean)
    outcome_summary: Mapped[str | None] = mapped_column(Text)

    # Dados brutos da medição, para reprocessar a análise sem recoletar.
    observed_payload: Mapped[dict | None] = mapped_column(JSON)

    calibration_id: Mapped[int | None] = mapped_column(
        ForeignKey("score_calibrations.id", ondelete="SET NULL"), index=True
    )

    calibration: Mapped[ScoreCalibration | None] = relationship(
        back_populates="outcomes",
        foreign_keys=[calibration_id],
    )

    __table_args__ = (
        UniqueConstraint("score_run_id", "window_days", name="uq_prediction_outcomes_run_window"),
        Index("ix_prediction_outcomes_version_evaluated", "algorithm_version", "evaluated_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PredictionOutcome v{self.algorithm_version} err={self.score_error}>"


class ScoreCalibration(Base, TimestampMixin):
    """Recomendação de recalibração derivada dos resultados observados.

    Não altera pesos automaticamente. Registra a evidência e a proposta para
    revisão humana — o briefing exige que nenhuma pontuação crítica seja uma
    opinião opaca, e uma mudança de pesos sem revisão seria exatamente isso.
    """

    __tablename__ = "score_calibrations"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)

    dimension: Mapped[ScoreDimension] = mapped_column(
        enum_column(ScoreDimension, "score_dimension"),
        nullable=False,
        index=True,
    )
    # Versão analisada e versão proposta (nova linha em score_algorithms).
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    proposed_version: Mapped[str | None] = mapped_column(String(32))

    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)

    # Qualidade preditiva observada.
    mean_absolute_error: Mapped[float | None] = mapped_column(Float)
    correlation: Mapped[float | None] = mapped_column(Float)
    hit_rate: Mapped[float | None] = mapped_column(Float)

    weights_before: Mapped[dict | None] = mapped_column(JSON)
    weights_after: Mapped[dict | None] = mapped_column(JSON)
    proposal_rationale: Mapped[str | None] = mapped_column(Text)

    # Aprovação humana antes de virar versão ativa.
    is_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_by: Mapped[str | None] = mapped_column(String(128))
    rejected_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_score_calibrations_dimension_period", "dimension", "period_end"),
    )

    outcomes: Mapped[list[PredictionOutcome]] = relationship(
        back_populates="calibration",
        foreign_keys="PredictionOutcome.calibration_id",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ScoreCalibration {self.dimension.value} v{self.algorithm_version} n={self.sample_size}>"
