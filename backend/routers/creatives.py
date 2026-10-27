"""Criativos de anúncio feitos pelo AI Studio: pedir, acompanhar e receber o resultado (webhook)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.deps import get_session
from backend.security import Principal, record_action, require
from core.db.ads import AdCampaign
from core.db.creatives import CreativeCampaign
from core.services import ads_manager, aistudio, creative_history, google_campaigns, meta_campaigns
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


@router.get("/creatives/{creative_id}/files/{deliverable_id}", summary="Entrega uma peça do criativo (imagem ou vídeo) pelo marketTon")
def creative_file(creative_id: int, deliverable_id: str, _: Principal = Depends(require("creatives.view")),
                  session: Session = Depends(get_session)) -> Response:
    creative = session.get(CreativeCampaign, creative_id)
    if creative is None:
        raise HTTPException(status_code=404, detail="criativo não encontrado")
    try:
        data, content_type = aistudio.fetch_file(session, creative, deliverable_id)
    except AIStudioError as exc:
        raise HTTPException(status_code=404 if exc.code == "not_found" else 502, detail=str(exc)) from exc
    return Response(content=data, media_type=content_type, headers={"Cache-Control": "private, max-age=3600"})


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


class AdCreate(BaseModel):
    creative_id: int
    daily_brl: float = Field(gt=0)
    days: int = Field(3, ge=1, le=14)
    dry_run: bool = True  # padrão: só mostra o que seria enviado à Meta, sem enviar nada
    variant: str | None = None


class GoogleAdCreate(BaseModel):
    product_id: int
    daily_brl: float = Field(gt=0)
    days: int = Field(3, ge=1, le=14)
    dry_run: bool = True
    max_cpc_brl: float = Field(1.0, gt=0, le=5)
    headlines: list[str] | None = Field(None, max_length=15)
    descriptions: list[str] | None = Field(None, max_length=4)
    keywords: list[str] | None = Field(None, max_length=10)


@router.get("/ads/budget", summary="Orçamento de anúncios por plataforma: teto, verba comprometida e gasto da semana")
def ads_budget_status(principal: Principal = Depends(require("portfolio.view")), session: Session = Depends(get_session)) -> dict:
    return {"meta": meta_campaigns.budget_status(session, platform="meta"), "google": meta_campaigns.budget_status(session, platform="google")}


@router.post("/ads", summary="Criar o anúncio na Meta a partir de um criativo (sempre PAUSADO; dry_run por padrão)", status_code=201)
def create_meta_ad(payload: AdCreate, principal: Principal = Depends(require("portfolio.manage")), session: Session = Depends(get_session)) -> dict:
    try:
        result = meta_campaigns.create_ad(session, payload.creative_id, daily_brl=payload.daily_brl, days=payload.days, dry_run=payload.dry_run,
                                          actor=principal.username, variant=payload.variant)
    except meta_campaigns.AdsError as exc:
        session.commit()  # guarda a tentativa que falhou
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not payload.dry_run:
        record_action(session, principal, action="ads.created_paused", resource_type="creative", resource_id=str(payload.creative_id),
                      detail=f"R$ {payload.daily_brl:g}/dia por {payload.days} dia(s)")
    session.commit()
    return result


@router.post("/ads/google", summary="Criar a campanha de Pesquisa no Google de um produto (sempre PAUSADA; dry_run por padrão)", status_code=201)
def create_google_ad(payload: GoogleAdCreate, principal: Principal = Depends(require("portfolio.manage")),
                     session: Session = Depends(get_session)) -> dict:
    try:
        result = google_campaigns.create_campaign(
            session, payload.product_id, daily_brl=payload.daily_brl, days=payload.days, dry_run=payload.dry_run, actor=principal.username,
            headlines=payload.headlines, descriptions=payload.descriptions, keywords=payload.keywords, max_cpc_brl=payload.max_cpc_brl)
    except meta_campaigns.AdsError as exc:
        session.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not payload.dry_run:
        record_action(session, principal, action="ads.google_created_paused", resource_type="product", resource_id=str(payload.product_id),
                      detail=f"R$ {payload.daily_brl:g}/dia por {payload.days} dia(s)")
    session.commit()
    return result


@router.post("/ads/{ad_id}/activate", summary="LIGAR o anúncio (só o operador: passa a gastar até a verba diária)")
def activate_ad(ad_id: int, principal: Principal = Depends(require("connectors.manage")), session: Session = Depends(get_session)) -> dict:
    try:
        ad = ads_manager.activate(session, ad_id, actor=principal.username)
    except meta_campaigns.AdsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_action(session, principal, action="ads.activated", resource_type="ad", resource_id=str(ad_id),
                  detail=f"R$ {ad.daily_budget_brl:g}/dia por {ad.duration_days} dia(s)")
    session.commit()
    return creative_history.ad_out(ad)


@router.post("/ads/{ad_id}/pause", summary="Pausar um anúncio")
def pause_ad(ad_id: int, principal: Principal = Depends(require("portfolio.manage")), session: Session = Depends(get_session)) -> dict:
    try:
        ad = ads_manager.pause(session, ad_id)
    except meta_campaigns.AdsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_action(session, principal, action="ads.paused", resource_type="ad", resource_id=str(ad_id))
    session.commit()
    return creative_history.ad_out(ad)


@router.post("/ads/{ad_id}/stop", summary="PARAR de vez: pausa e encerra o anúncio (só o operador; não liga mais)")
def stop_ad(ad_id: int, principal: Principal = Depends(require("connectors.manage")), session: Session = Depends(get_session)) -> dict:
    try:
        ad = ads_manager.stop(session, ad_id)
    except meta_campaigns.AdsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_action(session, principal, action="ads.stopped", resource_type="ad", resource_id=str(ad_id))
    session.commit()
    return creative_history.ad_out(ad)


@router.delete("/ads/{ad_id}", summary="EXCLUIR o anúncio: apaga na rede de anúncios e tira da tela (só o operador)")
def delete_ad(ad_id: int, principal: Principal = Depends(require("connectors.manage")), session: Session = Depends(get_session)) -> dict:
    try:
        ads_manager.remove(session, ad_id)
    except meta_campaigns.AdsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_action(session, principal, action="ads.removed", resource_type="ad", resource_id=str(ad_id))
    session.commit()
    return {"removed": ad_id}


@router.delete("/creatives/{creative_id}", summary="EXCLUIR o criativo da tela (fica no banco; só sem anúncio aberto)")
def delete_creative(creative_id: int, principal: Principal = Depends(require("connectors.manage")), session: Session = Depends(get_session)) -> dict:
    creative = session.get(CreativeCampaign, creative_id)
    if creative is None:
        raise HTTPException(status_code=404, detail="criativo não encontrado")
    open_ads = session.query(AdCampaign).filter(AdCampaign.creative_campaign_id == creative_id,
                                                AdCampaign.status.in_(("draft", "paused", "active"))).count()
    if open_ads:
        raise HTTPException(status_code=422, detail=f"este criativo tem {open_ads} anúncio(s) aberto(s): pare ou exclua o anúncio antes.")
    creative.hidden = True
    record_action(session, principal, action="creatives.hidden", resource_type="creative", resource_id=str(creative_id))
    session.commit()
    return {"removed": creative_id}


@router.post("/ads/pause-all", summary="Botão de parada: pausa todos os anúncios ativos (só o operador)")
def pause_all_ads(principal: Principal = Depends(require("connectors.manage")), session: Session = Depends(get_session)) -> dict:
    n = ads_manager.pause_all(session)
    record_action(session, principal, action="ads.paused_all", resource_type="ad", detail=f"{n} anúncio(s)")
    session.commit()
    return {"paused": n}


@router.post("/ads/sync", summary="Ler as métricas da Meta e do Google (gasto, impressões, cliques)")
def sync_ads(principal: Principal = Depends(require("portfolio.manage")), session: Session = Depends(get_session)) -> dict:
    try:
        n = ads_manager.sync_metrics(session)
    except meta_campaigns.AdsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()
    return {"updated": n}


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
