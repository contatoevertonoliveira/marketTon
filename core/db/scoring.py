"""Scoring versionado e explicável.

Briefing seção 5: para cada cálculo devem ser armazenados inputs, pesos,
fórmula/algoritmo, versão, resultado e timestamp. Briefing seção 6: toda
recomendação deve ser justificável ("por que este produto foi recomendado?").

O par `ScoreRun` + `ScoreContribution` é o que torna a explicação nativa em vez
de reconstruída: o score é literalmente a soma documentada das contribuições.
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
    BigIntCol,
    BigIntPK,
    Marketplace,
    ScoreDimension,
    ScoreRunStatus,
    TimestampMixin,
    enum_column,
)

# Scores são persistidos com 3 casas: precisão suficiente e comparação estável.
SCORE_PRECISION = Numeric(6, 3)


class ScoreAlgorithm(Base, TimestampMixin):
    """Versão publicada de um algoritmo de score.

    Imutável na prática: mudar pesos ou fórmula exige uma nova versão. É isto
    que permite ao motor de aprendizado comparar a previsão de uma versão com o
    resultado real obtido por ela.
    """

    __tablename__ = "score_algorithms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    dimension: Mapped[ScoreDimension] = mapped_column(
        enum_column(ScoreDimension, "score_dimension"),
        nullable=False,
        index=True,
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # Identificador estável da implementação em Python (ex.: "opportunity.v1").
    # Aponta para a função registrada, não para um caminho de arquivo.
    algorithm_key: Mapped[str] = mapped_column(String(64), nullable=False)

    # Pesos nomeados das dimensões/componentes usados pela fórmula.
    weights: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Parâmetros não-peso (limiares, janelas, saturações). Parte da "fórmula".
    parameters: Mapped[dict | None] = mapped_column(JSON)
    # Fórmula legível por humano, para exibição na explicação.
    formula: Mapped[str | None] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    runs: Mapped[list[ScoreRun]] = relationship(back_populates="algorithm")

    __table_args__ = (
        UniqueConstraint("dimension", "version", name="uq_score_algorithms_dimension_version"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ScoreAlgorithm {self.dimension.value} v{self.version}>"


class ScoreRun(Base, TimestampMixin):
    """Uma execução de score sobre um alvo. Guarda o cálculo inteiro.

    `target_type`/`target_id` formam uma referência polimórfica deliberada:
    Produto, Item de portfólio e Criativo são pontuados pela mesma máquina.
    """

    __tablename__ = "score_runs"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)

    algorithm_id: Mapped[int] = mapped_column(
        ForeignKey("score_algorithms.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    dimension: Mapped[ScoreDimension] = mapped_column(
        enum_column(ScoreDimension, "score_dimension"),
        nullable=False,
        index=True,
    )
    # Redundância proposital da versão: a explicação precisa continuar legível
    # mesmo se o registro do algoritmo for algum dia arquivado.
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)

    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[int] = mapped_column(BigIntCol, nullable=False)

    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    # Snapshot exato dos insumos. Nunca recalculado: é evidência histórica.
    inputs: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Cópia dos pesos vigentes no momento do cálculo.
    weights: Mapped[dict] = mapped_column(JSON, nullable=False)
    formula: Mapped[str | None] = mapped_column(Text)
    # Hash do payload de inputs: detecta recálculo idêntico e viabiliza cache.
    inputs_hash: Mapped[str | None] = mapped_column(String(64), index=True)

    score: Mapped[float] = mapped_column(SCORE_PRECISION, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    # False quando o algoritmo rodou mas os dados eram insuficientes.
    is_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[ScoreRunStatus] = mapped_column(
        enum_column(ScoreRunStatus, "score_run_status"),
        nullable=False,
        default=ScoreRunStatus.SUCCEEDED,
    )
    # Preenchido quando status != SUCCEEDED. Explica o que faltou.
    insufficient_reasons: Mapped[list | None] = mapped_column(JSON)

    marketplace: Mapped[Marketplace | None] = mapped_column(enum_column(Marketplace, "marketplace"))
    source_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_records.id", ondelete="SET NULL"), index=True
    )

    algorithm: Mapped[ScoreAlgorithm] = relationship(back_populates="runs")
    contributions: Mapped[list[ScoreContribution]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="ScoreContribution.position",
    )

    __table_args__ = (
        Index("ix_score_runs_target", "target_type", "target_id", "dimension", "computed_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ScoreRun {self.dimension.value} {self.target_type}:{self.target_id}={self.score}>"


class ScoreContribution(Base):
    """Um fator individual do cálculo. É a explicação propriamente dita.

    `impact` é a contribuição já ponderada para o score final. A soma dos
    `impact` das contribuições reconstrói o `ScoreRun.score` — a explicação não
    é uma narrativa gerada à parte, é a própria aritmética do score.
    """

    __tablename__ = "score_contributions"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)

    run_id: Mapped[int] = mapped_column(
        ForeignKey("score_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Ordem de exibição na explicação.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    factor: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)

    raw_value: Mapped[float | None] = mapped_column(Float)
    raw_unit: Mapped[str | None] = mapped_column(String(32))
    # Valor após normalização para a escala do score.
    normalized_value: Mapped[float | None] = mapped_column(Float)
    weight: Mapped[float | None] = mapped_column(Float)

    # Contribuição final (normalized_value * weight). Positiva soma, negativa subtrai.
    impact: Mapped[float] = mapped_column(Numeric(8, 3), nullable=False, default=0)

    # True quando o fator foi favorável. Vira o sinal "+" / "-" da explicação.
    is_positive: Mapped[bool | None] = mapped_column(Boolean)
    # False quando o dado base não estava disponível: o fator foi ignorado.
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Texto já formatado para o operador ("+ forte crescimento recente").
    explanation: Mapped[str | None] = mapped_column(Text)

    run: Mapped[ScoreRun] = relationship(back_populates="contributions")

    __table_args__ = (
        UniqueConstraint("run_id", "factor", name="uq_score_contributions_run_factor"),
    )
