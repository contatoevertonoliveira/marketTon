"""Conversa entre o operador e o agente Claude, e fila de tarefas/pedidos do agente.

O agente só trabalha enquanto uma sessão do Claude está aberta, então a conversa é
**assíncrona**: cada lado deixa mensagens e o outro lê quando puder. As mesmas linhas
carregam alertas do sistema (ex.: venda nova), pedidos de recurso do agente
("preciso da chave X") e tarefas (ex.: rotina de ativação).
"""
from __future__ import annotations

from sqlalchemy import JSON, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, TimestampMixin

AUTHORS = ("user", "agent", "system")
KINDS = ("message", "request", "report", "alert", "task")
STATUSES = ("open", "done", "dismissed")


class AgentMessage(Base, TimestampMixin):
    __tablename__ = "agent_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    author: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="message", index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSON)
    # Só para `request` e `task`: open -> done | dismissed.
    status: Mapped[str | None] = mapped_column(String(16), index=True)
    read_by_user: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    read_by_agent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AgentMessage {self.id} {self.author}/{self.kind}>"
