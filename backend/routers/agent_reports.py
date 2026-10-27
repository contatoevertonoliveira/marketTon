"""Relatórios do agente: tabela do que ele verificou, fez, encontrou e sugere."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.deps import get_session
from backend.security import Principal, require
from core.db.agent_reports import KINDS
from core.services import agent_monitor

router = APIRouter(prefix="/agent/reports", tags=["agente: relatórios"])

AGENT_KINDS = ("resumo", "achado", "acao", "ideia", "alerta")  # "monitor" é só do sistema


class ReportIn(BaseModel):
    kind: str = "achado"
    title: str = Field(..., max_length=160)
    body: str | None = Field(None, max_length=4000)


@router.get("", summary="Relatórios do agente")
def list_reports(kind: str | None = None, limit: int = 100, _: Principal = Depends(require("operations.view")),
                 session: Session = Depends(get_session)) -> dict:
    if kind and kind not in KINDS:
        raise HTTPException(status_code=422, detail=f"tipo inválido: use {', '.join(KINDS)}")
    return {"kinds": list(KINDS), "items": agent_monitor.list_reports(session, kind=kind, limit=limit)}


@router.post("", summary="O agente registra um achado, ação ou ideia", status_code=201)
def add_report(payload: ReportIn, _: Principal = Depends(require("operations.view")),
               session: Session = Depends(get_session)) -> dict:
    if payload.kind not in AGENT_KINDS:
        raise HTTPException(status_code=422, detail=f"tipo inválido: use {', '.join(AGENT_KINDS)}")
    try:
        report = agent_monitor.add_report(session, kind=payload.kind, title=payload.title, body=payload.body)
    except agent_monitor.ReportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()
    return agent_monitor.report_out(report)
