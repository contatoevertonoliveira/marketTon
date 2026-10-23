"""Criativos de anúncio feitos pelo AI Studio: pedir, acompanhar e receber o resultado (webhook)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.deps import get_session
from backend.security import Principal, record_action, require
from core.db.creatives import CreativeCampaign
from core.services import aistudio, creative_history
from core.services.aistudio import AIStudioError

router = APIRouter(tags=["criativos (AI Studio)"])


class CreativeIn(BaseModel):
    product_id: int
    mode: str = "sandbox"  # "live" gasta créditos: só com a permissão ligada no cartão do AI Studio
    quality: str = "economy"
    angle: str = "problem_solution"
    hook_variants: int = Field(2, ge=1, le=4)
    budget_usd: float | None = Field(None, gt=0)
    formats: str = "video"  # "images" = só imagens e texto (sem vídeo)


def _out(c: CreativeCampaign) -> dict:
    return {"id": c.id, "product_id": c.product_id, "external_ref": c.external_ref, "campaign_id": c.campaign_id, "mode": c.mode,
            "status": c.status, "quality": c.quality, "angle": c.angle, "budget_usd": c.budget_usd, "cost_usd": c.cost_usd,
            "error": c.error, "created_at": c.created_at.isoformat() if c.created_at else None,
            "deliverables": aistudio.deliverables(c)}


@router.post("/integrations/aistudio/webhook", summary="Webhook do AI Studio (assinado; sem login)", include_in_schema=False)
async def webhook(request: Request, session: Session = Depends(get_session)) -> dict:
    raw = await request.body()
    try:
        result = aistudio.handle_webhook(session, raw, dict(request.headers))
    except AIStudioError as exc:
        session.rollback()
        raise HTTPException(status_code=401 if exc.code == "bad_signature" else 400, detail=exc.code or "erro") from exc
    session.commit()
    return {"ok": True, "result": result}


@router.get("/creatives", summary="Campanhas de criativos (use refresh=true para reconciliar com o AI Studio)")
def list_creatives(refresh: bool = False, limit: int = 20, principal: Principal = Depends(require("portfolio.view")),
                   session: Session = Depends(get_session)) -> list[dict]:
    if refresh:
        try:
            aistudio.reconcile(session)
            session.commit()
        except AIStudioError:
            session.rollback()
    rows = session.scalars(select(CreativeCampaign).order_by(CreativeCampaign.id.desc()).limit(max(1, min(limit, 100))))
    return [_out(c) for c in rows]


class AdIn(BaseModel):
    platform: str = "meta"
    status: str = "draft"
    variant: str | None = None
    daily_budget_brl: float | None = None
    notes: str | None = None


class AdUpdate(BaseModel):
    status: str | None = None
    spent_brl: float | None = None
    impressions: int | None = None
    clicks: int | None = None
    daily_budget_brl: float | None = None
    notes: str | None = None


@router.get("/creatives/history", summary="Histórico gerencial: criativos, produto, anúncios e resultados")
def get_history(limit: int = 50, principal: Principal = Depends(require("portfolio.view")), session: Session = Depends(get_session)) -> dict:
    return creative_history.history(session, limit=limit)


@router.post("/creatives/{creative_id}/ads", summary="Registrar um anúncio feito sobre um criativo", status_code=201)
def post_ad(creative_id: int, payload: AdIn, principal: Principal = Depends(require("portfolio.manage")),
            session: Session = Depends(get_session)) -> dict:
    try:
        ad = creative_history.create_ad(session, creative_id, actor=principal.username, **payload.model_dump())
    except creative_history.AdError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_action(session, principal, action="ads.registered", resource_type="creative", resource_id=str(creative_id), detail=f"{ad.platform} {ad.status}")
    session.commit()
    return creative_history.ad_out(ad)


@router.put("/creatives/ads/{ad_id}", summary="Atualizar estado e métricas de um anúncio")
def put_ad(ad_id: int, payload: AdUpdate, principal: Principal = Depends(require("portfolio.manage")),
           session: Session = Depends(get_session)) -> dict:
    try:
        ad = creative_history.update_ad(session, ad_id, **payload.model_dump())
    except creative_history.AdError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()
    return creative_history.ad_out(ad)


@router.post("/creatives/estimate", summary="Estimar custo e prazo (não gasta)")
def estimate(payload: CreativeIn, principal: Principal = Depends(require("portfolio.view")), session: Session = Depends(get_session)) -> dict:
    try:
        return aistudio.estimate(session, payload.product_id, quality=payload.quality, angle=payload.angle, hook_variants=payload.hook_variants,
                               formats=payload.formats)
    except AIStudioError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/creatives", summary="Pedir os criativos de um produto ao AI Studio", status_code=201)
def create_creative(payload: CreativeIn, principal: Principal = Depends(require("portfolio.manage")),
                    session: Session = Depends(get_session)) -> dict:
    try:
        record = aistudio.create(session, payload.product_id, mode=payload.mode, quality=payload.quality, angle=payload.angle,
                                 hook_variants=payload.hook_variants, budget_usd=payload.budget_usd, actor=principal.username,
                                 formats=payload.formats)
    except AIStudioError as exc:
        session.commit()  # guarda a tentativa (external_ref) mesmo quando falha
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_action(session, principal, action="creatives.requested", resource_type="product", resource_id=str(payload.product_id),
                  detail=f"{record.mode} {record.quality} US$ {record.budget_usd:g} ({record.external_ref})")
    session.commit()
    return _out(record)
