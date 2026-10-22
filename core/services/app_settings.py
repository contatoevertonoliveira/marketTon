"""Leitura e escrita de configurações globais.

O **modo agente** vive aqui: ligado, o agente Claude (papel BOT) pode executar as
ações de escrita que o papel permite; desligado, ele só consulta. O padrão é
DESLIGADO — o sistema nunca nasce entregando o controle.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.app_settings import AppSetting

AGENT_MODE_KEY = "agent_mode"


def _row(session: Session, key: str) -> AppSetting | None:
    return session.scalar(select(AppSetting).where(AppSetting.key == key))


def agent_mode_enabled(session: Session) -> bool:
    row = _row(session, AGENT_MODE_KEY)
    return bool(row and row.value.get("enabled"))


def agent_mode_info(session: Session) -> dict:
    row = _row(session, AGENT_MODE_KEY)
    return {
        "enabled": bool(row and row.value.get("enabled")),
        "updated_by": row.updated_by if row else None,
        "changed_at": row.changed_at.isoformat() if row and row.changed_at else None,
    }


def set_agent_mode(session: Session, *, enabled: bool, actor: str) -> dict:
    row = _row(session, AGENT_MODE_KEY)
    if row is None:
        row = AppSetting(key=AGENT_MODE_KEY, value={})
        session.add(row)
    row.value = {"enabled": enabled}
    row.updated_by = actor
    row.changed_at = datetime.now(UTC)
    session.flush()
    return agent_mode_info(session)


AUTONOMY_KEY = "agent_autonomy"
AUTONOMY_LEVELS = ("supervised", "independent")


def agent_autonomy(session: Session) -> str:
    """`supervised` (padrão) ou `independent`. O agente nasce sob supervisão."""
    row = _row(session, AUTONOMY_KEY)
    level = row.value.get("level") if row else None
    return level if level in AUTONOMY_LEVELS else "supervised"


def set_agent_autonomy(session: Session, *, level: str, actor: str) -> str:
    if level not in AUTONOMY_LEVELS:
        raise ValueError(f"nível de autonomia inválido: {level}")
    row = _row(session, AUTONOMY_KEY)
    if row is None:
        row = AppSetting(key=AUTONOMY_KEY, value={})
        session.add(row)
    row.value = {"level": level}
    row.updated_by = actor
    row.changed_at = datetime.now(UTC)
    session.flush()
    return level
