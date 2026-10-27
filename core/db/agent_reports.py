"""Relatório do agente: uma linha por verificação, achado, ação ou ideia (a tabela da página Relatórios)."""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, TimestampMixin

KINDS = ("monitor", "resumo", "achado", "acao", "ideia", "alerta")


class AgentReport(Base, TimestampMixin):
    __tablename__ = "agent_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True)
    kind: Mapped[str] = mapped_column(String(12), nullable=False, default="resumo", index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(16), nullable=False, default="agent")  # agent | system (feito por código, sem IA)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AgentReport {self.id} {self.kind}>"
