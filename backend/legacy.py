"""Endpoints de suporte herdados da versão anterior.

Preservados para não quebrar o dashboard durante a transição. A diferença é que
agora falam SQLAlchemy sobre PostgreSQL, com os modelos de `core/db/support.py`, em
vez de `sqlite3` bruto com DDL escrita em tempo de execução.

Uma correção de segurança veio junto: `PUT /preferences/{user_id}` aceitava
sobrescrever as preferências de **qualquer** usuário sem autenticação. O endpoint
continua aberto porque ainda não há camada de autenticação implementada, mas o
problema está declarado aqui em vez de silenciado — e a lista de endpoints que
dependem de auth está em `PROJECT_STATUS.md`.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.deps import get_session
from backend.security import require
from core.db.support import SupportAgendaItem, SupportFeedback, SupportGroup, SupportPayment, SupportPreference, SupportTrendAlert

# Rotas de suporte exigem `support.view` para leitura. Antes deste ajuste elas eram
# públicas: `GET /support/feedback` expunha ids e nomes de usuários e
# `PUT /support/preferences/{user_id}` permitia sobrescrever preferências de
# qualquer pessoa. Escrita exige `support.manage`, declarado por endpoint.
legacy_router = APIRouter(
    prefix="/support",
    tags=["suporte (legado)"],
    dependencies=[Depends(require("support.view"))],
)


class FeedbackIn(BaseModel):
    channel: str
    user_id: int
    username: str | None = None
    text: str
    sentiment: str | None = None
    tags: str | None = None


class PreferenceIn(BaseModel):
    user_id: int
    chat_id: int | None = None
    username: str | None = None
    language: str = "pt-BR"
    notify_alerts: bool = True
    notify_daily_report: bool = True
    notify_opportunities: bool = True
    muted: bool = False
    extra: dict | None = None


class GroupStatusIn(BaseModel):
    """Substitui o `payload: dict` sem validação do endpoint anterior."""

    status: str
    reason: str | None = None
    updated_by: str | None = None


@legacy_router.get("/feedback")
def list_feedback(
    session: Session = Depends(get_session), limit: int = Query(50, ge=1, le=500)
) -> list[dict]:
    rows = session.scalars(
        select(SupportFeedback).order_by(desc(SupportFeedback.created_at)).limit(limit)
    )
    return [
        {
            "id": row.id,
            "channel": row.channel,
            "user_id": row.user_id,
            "username": row.username,
            "text": row.text,
            "sentiment": row.sentiment,
            "tags": row.tags,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


@legacy_router.post(
    "/feedback",
    status_code=201,
    dependencies=[Depends(require("support.manage"))],
)
def add_feedback(payload: FeedbackIn, session: Session = Depends(get_session)) -> dict:
    record = SupportFeedback(**payload.model_dump())
    session.add(record)
    session.commit()
    session.refresh(record)
    return {"id": record.id}


@legacy_router.get("/preferences")
def list_preferences(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.scalars(select(SupportPreference).order_by(desc(SupportPreference.updated_at)))
    return [
        {
            "user_id": row.user_id,
            "chat_id": row.chat_id,
            "username": row.username,
            "language": row.language,
            "notify_alerts": row.notify_alerts,
            "notify_daily_report": row.notify_daily_report,
            "notify_opportunities": row.notify_opportunities,
            "muted": row.muted,
            "extra": row.extra,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in rows
    ]


@legacy_router.put(
    "/preferences/{user_id}",
    dependencies=[Depends(require("support.manage"))],
)
def upsert_preference(
    user_id: int, payload: PreferenceIn, session: Session = Depends(get_session)
) -> dict:
    """Cria ou atualiza as preferências do usuário."""
    existing = session.scalar(
        select(SupportPreference).where(SupportPreference.user_id == user_id)
    )
    data = payload.model_dump()
    data["user_id"] = user_id

    if existing is None:
        session.add(SupportPreference(**data))
    else:
        for key, value in data.items():
            setattr(existing, key, value)
    session.commit()
    return {"ok": True}


@legacy_router.get("/alerts/trends")
def trend_alerts(
    session: Session = Depends(get_session), limit: int = Query(20, ge=1, le=200)
) -> list[dict]:
    rows = session.scalars(
        select(SupportTrendAlert).order_by(desc(SupportTrendAlert.collected_at)).limit(limit)
    )
    return [
        {
            "id": row.id,
            "keyword": row.keyword,
            "geo": row.geo,
            "alert": row.alert,
            "score": row.score,
            "interest_last": row.interest_last,
            "interest_change": row.interest_change,
            "collected_at": row.collected_at.isoformat() if row.collected_at else None,
        }
        for row in rows
    ]


@legacy_router.get("/payments")
def payments(
    session: Session = Depends(get_session), limit: int = Query(50, ge=1, le=500)
) -> list[dict]:
    rows = session.scalars(
        select(SupportPayment).order_by(desc(SupportPayment.created_at)).limit(limit)
    )
    return [
        {
            "id": row.id,
            "provider": row.provider,
            "gateway": row.gateway,
            "status": row.status,
            "amount": row.amount,
            "currency": row.currency,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


@legacy_router.get("/agenda")
def agenda(
    session: Session = Depends(get_session), limit: int = Query(50, ge=1, le=500)
) -> list[dict]:
    rows = session.scalars(
        select(SupportAgendaItem).order_by(desc(SupportAgendaItem.when_date)).limit(limit)
    )
    return [
        {
            "id": row.id,
            "title": row.title,
            "description": row.description,
            "owner": row.owner,
            "channel": row.channel,
            "when_date": row.when_date.isoformat() if row.when_date else None,
        }
        for row in rows
    ]


@legacy_router.post(
    "/agenda",
    status_code=201,
    dependencies=[Depends(require("support.manage"))],
)
def create_agenda_item(payload: dict, session: Session = Depends(get_session)) -> dict:
    title = payload.get("title")
    if not title:
        raise HTTPException(status_code=422, detail="campo obrigatório: title")

    when_raw = payload.get("when_date")
    when_date = None
    if when_raw:
        try:
            when_date = datetime.fromisoformat(str(when_raw))
        except ValueError:
            raise HTTPException(
                status_code=422, detail="when_date deve estar em formato ISO 8601"
            ) from None

    item = SupportAgendaItem(
        title=title,
        description=payload.get("description"),
        owner=payload.get("owner"),
        channel=payload.get("channel"),
        when_date=when_date,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return {"id": item.id}


@legacy_router.get("/groups")
def groups(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.scalars(select(SupportGroup))
    return [
        {
            "group_id": row.group_id,
            "title": row.title,
            "status": row.status,
            "reason": row.reason,
            "updated_by": row.updated_by,
        }
        for row in rows
    ]


@legacy_router.post(
    "/groups/{group_id}/status",
    dependencies=[Depends(require("support.manage"))],
)
def set_group_status(
    group_id: int, payload: GroupStatusIn, session: Session = Depends(get_session)
) -> dict:
    """Define o estado de um grupo.

    O endpoint anterior recebia `payload: dict` sem validação de schema; agora o
    corpo é um modelo Pydantic, então um campo faltante ou de tipo errado devolve
    422 em vez de gravar `None` numa coluna que esperava texto.
    """
    existing = session.get(SupportGroup, group_id)
    if existing is None:
        existing = SupportGroup(group_id=group_id)
        session.add(existing)

    existing.status = payload.status
    existing.reason = payload.reason
    existing.updated_by = payload.updated_by
    session.commit()
    return {"ok": True, "group_id": group_id, "status": payload.status}


__all__ = ["legacy_router"]
