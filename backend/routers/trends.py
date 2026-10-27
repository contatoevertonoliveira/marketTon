"""Oportunidades de busca: tendência real do Google Trends + (com credencial)
volume, CPC e concorrência do Planejador de Palavras-chave.

Ao vivo e em cache de processo — nada é gravado no banco aqui. Campos sem fonte
configurada voltam `null`; a resposta diz qual foi a base do ranking para a tela
nunca sugerir que o custo foi considerado quando não foi.
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from agents.product_hunter.agent import DEFAULT_KEYWORDS
from backend.deps import get_session
from backend.security import Principal, require
from config.settings import get_settings
from core.services import trend_radar
from core.services.keyword_metrics import analyze_keywords, planner_provider, rank_opportunities
from sqlalchemy.orm import Session

router = APIRouter(prefix="/trends", tags=["tendências"], dependencies=[Depends(require("catalog.view"))])


class KeywordMetricsOut(BaseModel):
    keyword: str
    geo: str
    trend_direction: str | None = None
    growth_pct_30d: float | None = None
    interest_last: float | None = None
    trend_error: str | None = None
    audience: str | None = None
    monthly_volume: int | None = None
    cpc_usd: float | None = None
    cpc_brl: float | None = None
    competition: str | None = None
    competition_index: int | None = None
    planner_source: str | None = None
    planner_error: str | None = None


class OpportunitiesOut(BaseModel):
    ranking_basis: str  # "cpc_and_growth" | "growth_only"
    planner_configured: bool
    planner_provider: str | None = None
    planner_error: str | None = None
    fx_configured: bool
    top: list[KeywordMetricsOut] = Field(default_factory=list)
    analyzed: list[KeywordMetricsOut] = Field(default_factory=list)


@router.get("/opportunities", response_model=OpportunitiesOut)
def opportunities(
    keywords: str | None = Query(None, description="Palavras-chave separadas por vírgula; padrão: as do Product Hunter"),
    limit: int = Query(5, ge=1, le=20),
) -> OpportunitiesOut:
    terms = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else list(DEFAULT_KEYWORDS)
    analyzed = analyze_keywords(terms[:15])
    top, basis = rank_opportunities(analyzed, limit)
    settings = get_settings()
    provider = planner_provider()
    to_out = lambda m: KeywordMetricsOut(**{k: v for k, v in asdict(m).items() if k != "notes"})  # noqa: E731
    return OpportunitiesOut(
        ranking_basis=basis,
        planner_configured=provider is not None,
        planner_provider=provider,
        planner_error=next((m.planner_error for m in analyzed if m.planner_error), None),
        fx_configured=bool(settings.usd_brl_rate),
        top=[to_out(m) for m in top],
        analyzed=[to_out(m) for m in analyzed],
    )


class WatchIn(BaseModel):
    add: list[str] = Field(default_factory=list, max_length=20)
    remove: list[str] = Field(default_factory=list, max_length=20)


@router.get("/radar", summary="Radar de tendências: o que sobe na busca do Google (semana, quinzena e mês)")
def radar(limit: int = Query(30, ge=1, le=60), only_rising: bool = False, session: Session = Depends(get_session)) -> dict:
    return trend_radar.status(session, limit=limit, only_rising=only_rising)


@router.post("/radar/watch", summary="Adicionar ou remover palavras da vigilância do radar")
def radar_watch(payload: WatchIn, principal: Principal = Depends(require("portfolio.manage")), session: Session = Depends(get_session)) -> dict:
    from fastapi import HTTPException

    try:
        words = trend_radar.set_watch(session, add=payload.add, remove=payload.remove, actor=principal.username)
    except trend_radar.RadarError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()
    return {"watching": words}
