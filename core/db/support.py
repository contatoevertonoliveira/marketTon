"""Modelos das tabelas de suporte operacional.

Estas tabelas vêm da versão anterior do projeto (feedback, preferências, agenda,
bloqueio de grupos, pagamentos). Elas são preservadas porque o dashboard as usa e
porque contêm dado real de operação — diferente do catálogo, que era fabricado.

O que muda: passam a ser definidas **uma única vez**, em SQLAlchemy, e criadas por
migration. Antes existiam três definições incompatíveis das mesmas tabelas (em
`core/db.py`, `backend/main.py` e `backend/init_db.py`), todas com
`CREATE TABLE IF NOT EXISTS`, de modo que a primeira a rodar vencia e as outras
viravam no-op silencioso. Divergência de tipo em `updated_by` (`INTEGER` num
arquivo, `TEXT` no outro) era invisível até quebrar em produção.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, TimestampMixin


class SupportFeedback(Base, TimestampMixin):
    """Feedback recebido pelos canais (Telegram, WhatsApp, etc.)."""

    __tablename__ = "support_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(128))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    sentiment: Mapped[str | None] = mapped_column(String(32))
    tags: Mapped[str | None] = mapped_column(String(255))


class SupportPreference(Base, TimestampMixin):
    """Preferências de notificação por usuário."""

    __tablename__ = "support_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    chat_id: Mapped[int | None] = mapped_column(Integer)
    username: Mapped[str | None] = mapped_column(String(128))
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="pt-BR")
    notify_alerts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_daily_report: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_opportunities: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    muted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    extra: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_support_preferences_user_id"),
    )


class SupportAgendaItem(Base, TimestampMixin):
    """Item de agenda operacional."""

    __tablename__ = "support_agenda"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(String(128))
    channel: Mapped[str | None] = mapped_column(String(64))
    # `index=True` na coluna já cria o índice. Declarar também um `Index(...)` em
    # `__table_args__` faz o SQLAlchemy tentar criar duas vezes e o banco recusa.
    when_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class SupportGroup(Base, TimestampMixin):
    """Estado de bloqueio de um grupo de mensagens."""

    __tablename__ = "support_groups"

    group_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    reason: Mapped[str | None] = mapped_column(Text)
    # Tipo único declarado: antes era INTEGER num arquivo e TEXT no outro.
    updated_by: Mapped[str | None] = mapped_column(String(128))


class SupportPayment(Base, TimestampMixin):
    """Pagamento registrado por gateway."""

    __tablename__ = "support_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tx_id: Mapped[str | None] = mapped_column(String(128))
    provider: Mapped[str | None] = mapped_column(String(64), index=True)
    gateway: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str | None] = mapped_column(String(32), index=True)
    amount: Mapped[float | None] = mapped_column(Float)
    amount_cents: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str | None] = mapped_column(String(8), default="BRL")
    external_id: Mapped[str | None] = mapped_column(String(128))
    reference: Mapped[str | None] = mapped_column(String(128))
    user_id: Mapped[int | None] = mapped_column(Integer)
    raw: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (
        UniqueConstraint("tx_id", name="uq_support_payments_tx_id"),
    )


class SupportTrendAlert(Base, TimestampMixin):
    """Alerta de tendência persistido pelo agente de tendências."""

    __tablename__ = "support_trend_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keyword: Mapped[str] = mapped_column(String(255), nullable=False)
    topic: Mapped[str | None] = mapped_column(String(255))
    source: Mapped[str | None] = mapped_column(String(64))
    geo: Mapped[str | None] = mapped_column(String(16))
    region: Mapped[str | None] = mapped_column(String(64))
    signal: Mapped[str | None] = mapped_column(String(32))
    alert: Mapped[str | None] = mapped_column(String(32))
    score: Mapped[float | None] = mapped_column(Float)
    interest_last: Mapped[float | None] = mapped_column(Float)
    interest_mean: Mapped[float | None] = mapped_column(Float)
    interest_change: Mapped[float | None] = mapped_column(Float)
    # `index=True` na coluna; ver nota em `SupportAgendaItem`.
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    __table_args__ = (
        # Mesma tendência no mesmo dia não precisa de duas linhas.
        UniqueConstraint("keyword", "geo", "collected_at", name="uq_support_trend_alerts_kw_geo_at"),
    )


SUPPORT_MODELS = [
    SupportFeedback,
    SupportPreference,
    SupportAgendaItem,
    SupportGroup,
    SupportPayment,
    SupportTrendAlert,
]

__all__ = [
    "SUPPORT_MODELS",
    "SupportAgendaItem",
    "SupportFeedback",
    "SupportGroup",
    "SupportPayment",
    "SupportPreference",
    "SupportTrendAlert",
]
