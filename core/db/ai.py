"""Registro das saídas de IA.

Motivo de existir: se um agente usa um modelo para interpretar dados e influenciar
uma decisão, essa interpretação precisa ser auditável depois. Sem esta tabela, a
resposta do modelo sumiria no log e a pergunta "por que o sistema recomendou isso?"
não teria resposta verificável — que é exatamente a preocupação do briefing seção 5.

O que fica gravado: qual agente, qual versão de prompt, qual modelo, quais insumos
exatos produziram a saída, a saída bruta e a interpretada, e o custo em tokens.
"""
from __future__ import annotations

import enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, BigIntPK, TimestampMixin, enum_column


class AIInterpretationKind(str, enum.Enum):
    """O que a IA estava fazendo. Deixa claro o papel dela em cada caso."""

    TREND_READING = "TREND_READING"
    PRODUCT_EVALUATION = "PRODUCT_EVALUATION"
    SATURATION_READING = "SATURATION_READING"
    PERFORMANCE_DIAGNOSIS = "PERFORMANCE_DIAGNOSIS"
    CREATIVE_BRIEF = "CREATIVE_BRIEF"
    CATALOG_HEALTH_READING = "CATALOG_HEALTH_READING"


class AIInterpretation(Base, TimestampMixin):
    """Uma chamada de IA com insumos e resposta preservados."""

    __tablename__ = "ai_interpretations"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)

    # Agente que solicitou (ex.: "growth_analyst", "product_hunter").
    agent: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kind: Mapped[AIInterpretationKind] = mapped_column(
        enum_column(AIInterpretationKind, "ai_interpretation_kind"),
        nullable=False,
        index=True,
    )

    # Versão do prompt: mudar o prompt muda o comportamento, então precisa rastrear.
    prompt_key: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)

    # Insumos exatos entregues ao modelo. É o que permite reconstruir a avaliação.
    inputs: Mapped[dict | None] = mapped_column(JSON)
    inputs_hash: Mapped[str | None] = mapped_column(String(64), index=True)

    # Texto bruto e objeto interpretado, quando a resposta era JSON.
    raw_text: Mapped[str | None] = mapped_column(Text)
    output: Mapped[dict | None] = mapped_column(JSON)
    parse_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error_message: Mapped[str | None] = mapped_column(Text)

    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_seconds: Mapped[float | None] = mapped_column(Float)

    # Vínculo com o alvo da avaliação, quando houver.
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[int | None] = mapped_column(BigInteger)
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )

    __table_args__ = (
        Index("ix_ai_interpretations_agent_created", "agent", "created_at"),
        Index("ix_ai_interpretations_target", "target_type", "target_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AIInterpretation {self.agent}:{self.kind.value} {self.model}>"


__all__ = ["AIInterpretation", "AIInterpretationKind"]
