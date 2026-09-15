"""Tendências de busca: keywords observadas e suas leituras ao longo do tempo.

Por que tabela e não CSV: o arquivo `data/trend_alerts.csv` tinha cabeçalho de 5
colunas e linhas de 3, porque o agente fazia append com `header=not exists()`. Pior:
gravava erro de upstream como se fosse fonte de tendência —
`marketing digital cristão,The request failed: Google returned a response with code 400,...`.

Com tabela:

* cada leitura é uma linha com timestamp, e a série histórica é consultável;
* falha de coleta vai para `source_records.warnings`, onde é auditável e **não** se
  confunde com dado;
* campo que a fonte não forneceu fica `NULL`, e o motor de decisão distingue
  "não medimos" de "não há interesse".
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
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

from core.db.base import Base, BigIntPK, TimestampMixin


class TrendKeyword(Base, TimestampMixin):
    """Uma keyword monitorada, por região.

    Normalizada (minúsculas, sem espaços nas pontas) para que "Fone Bluetooth" e
    "fone bluetooth" sejam a mesma série — o CSV antigo tratava como linhas
    distintas.
    """

    __tablename__ = "trend_keywords"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keyword: Mapped[str] = mapped_column(String(255), nullable=False)
    geo: Mapped[str] = mapped_column(String(16), nullable=False, default="BR")
    display_name: Mapped[str | None] = mapped_column(String(255))

    # Nicho ao qual a keyword pertence, quando conhecido.
    niche: Mapped[str | None] = mapped_column(String(64), index=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    series_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    observations: Mapped[list[TrendObservation]] = relationship(
        back_populates="trend_keyword",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("keyword", "geo", name="uq_trend_keywords_keyword_geo"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TrendKeyword {self.keyword!r} ({self.geo})>"


class TrendObservation(Base, TimestampMixin):
    """Uma leitura de uma keyword em um instante.

    Todos os campos numéricos são anuláveis: série curta não permite calcular
    variação, e zero afirmaria que não houve variação.
    """

    __tablename__ = "trend_observations"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)

    trend_keyword_id: Mapped[int] = mapped_column(
        ForeignKey("trend_keywords.id", ondelete="CASCADE"), nullable=False, index=True
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)

    # Quantos pontos a série tinha. `0` é dado legítimo aqui: significa que a
    # fonte respondeu sem série, o que é diferente de falha de coleta.
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    interest_last: Mapped[float | None] = mapped_column(Float)
    interest_mean: Mapped[float | None] = mapped_column(Float)
    interest_peak: Mapped[float | None] = mapped_column(Float)
    change_absolute: Mapped[float | None] = mapped_column(Float)
    change_pct: Mapped[float | None] = mapped_column(Float)
    # "rising" | "falling" | "stable". Calculado com faixa morta para não tratar
    # ruído de medição como tendência.
    trend_direction: Mapped[str | None] = mapped_column(String(16), index=True)

    # Leitura qualitativa da IA, quando houve.
    interpretation: Mapped[dict | None] = mapped_column(JSON)
    interpretation_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_interpretations.id", ondelete="SET NULL"), index=True
    )

    source_record_id: Mapped[int] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text)

    trend_keyword: Mapped[TrendKeyword] = relationship(back_populates="observations")

    __table_args__ = (
        # Uma leitura por keyword por instante de coleta.
        UniqueConstraint(
            "trend_keyword_id", "observed_at", name="uq_trend_observations_keyword_observed"
        ),
        Index("ix_trend_observations_direction_observed", "trend_direction", "observed_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TrendObservation kw={self.trend_keyword_id} {self.trend_direction}>"


__all__ = ["TrendKeyword", "TrendObservation"]
