"""Rodadas do agente em segundo plano: quem disparou, como terminou, o que saiu."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, TimestampMixin

TRIGGERS = ("activation", "chat", "morning", "evening", "manual")
STATUSES = ("running", "ok", "failed", "needs_login", "timeout")


class AgentRun(Base, TimestampMixin):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trigger: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    output_tail: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(String(500))
    # Consumo da rodada (lido da saída do Claude Code): permite medir o custo-benefício de cada rotina.
    model: Mapped[str | None] = mapped_column(String(48))
    num_turns: Mapped[int | None] = mapped_column(Integer)
    tokens_in: Mapped[int | None] = mapped_column(Integer)  # entrada total (inclui cache)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AgentRun {self.id} {self.trigger} {self.status}>"
