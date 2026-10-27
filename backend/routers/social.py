"""Publicar nas redes do Mural na Web (Instagram): texto sugerido, publicação pelo operador e histórico."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.deps import get_session
from backend.security import Principal, record_action, require
from core.db.creatives import CreativeCampaign
from core.services import aistudio, content_pipeline, instagram, reels
from core.services.aistudio import AIStudioError

router = APIRouter(tags=["redes sociais"])


class PublishIn(BaseModel):
    creative_id: int
    caption: str = Field(..., min_length=1, max_length=2200)
    deliverable_id: str | None = Field(None, max_length=64)


@router.get("/public/media/{creative_id}/{name}", summary="Imagem do criativo em JPEG por link assinado (o Instagram busca aqui; sem login)", include_in_schema=False)
def public_media(creative_id: int, name: str, exp: int, sig: str, session: Session = Depends(get_session)) -> Response:
    deliverable_id = name.removesuffix(".jpg")
    if not instagram.verify_media(creative_id, deliverable_id, exp, sig):
        raise HTTPException(status_code=403, detail="link inválido ou vencido")
    creative = session.get(CreativeCampaign, creative_id)
    if creative is None:
        raise HTTPException(status_code=404, detail="não encontrado")
    try:
        data, _ = aistudio.fetch_file(session, creative, deliverable_id)
    except AIStudioError as exc:
        raise HTTPException(status_code=404, detail="peça não encontrada") from exc
    return Response(content=instagram.to_jpeg(data), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=600"})


@router.get("/public/video/{name}", summary="Slideshow em MP4 por link assinado (o Instagram busca aqui; sem login)", include_in_schema=False)
def public_video(name: str, exp: int, sig: str) -> FileResponse:
    try:
        creative_id = int(name.removesuffix(".mp4"))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="não encontrado") from exc
    if not instagram.verify_media(creative_id, "reel", exp, sig):
        raise HTTPException(status_code=403, detail="link inválido ou vencido")
    path = reels.reel_path(creative_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="não encontrado")
    return FileResponse(path, media_type="video/mp4")


@router.post("/social/reel/{creative_id}/build", summary="Montar o slideshow vertical (Reels/TikTok/Shorts) do criativo", status_code=201)
def build_reel(creative_id: int, principal: Principal = Depends(require("portfolio.manage")), session: Session = Depends(get_session)) -> dict:
    try:
        return reels.build(session, creative_id)
    except (reels.ReelError, AIStudioError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/social/reel/{creative_id}/video", summary="O slideshow já montado (para ver e baixar)")
def reel_video(creative_id: int, principal: Principal = Depends(require("portfolio.view"))) -> FileResponse:
    path = reels.reel_path(creative_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="ainda não foi gerado")
    return FileResponse(path, media_type="video/mp4", filename=f"mural-reel-{creative_id}.mp4")


@router.post("/social/instagram/publish-reel", summary="PUBLICAR o slideshow como Reel (só o operador)", status_code=201)
def publish_reel(payload: PublishIn, principal: Principal = Depends(require("connectors.manage")), session: Session = Depends(get_session)) -> dict:
    try:
        post = instagram.publish_reel(session, payload.creative_id, caption=payload.caption, actor=principal.username)
    except instagram.InstagramError as exc:
        session.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_action(session, principal, action="social.instagram_reel_published", resource_type="creative", resource_id=str(payload.creative_id),
                  detail=post.permalink or post.external_id)
    session.commit()
    return instagram.out(post)


@router.get("/social/instagram/caption/{creative_id}", summary="Texto sugerido para o post do Instagram")
def caption(creative_id: int, principal: Principal = Depends(require("portfolio.view")), session: Session = Depends(get_session)) -> dict:
    try:
        return instagram.default_caption(session, creative_id)
    except instagram.InstagramError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/social/instagram/publish", summary="PUBLICAR no Instagram agora (só o operador; o agente não publica)", status_code=201)
def publish(payload: PublishIn, principal: Principal = Depends(require("connectors.manage")), session: Session = Depends(get_session)) -> dict:
    try:
        post = instagram.publish_image(session, payload.creative_id, caption=payload.caption, deliverable_id=payload.deliverable_id,
                                       actor=principal.username)
    except instagram.InstagramError as exc:
        session.commit()  # guarda a tentativa que falhou
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_action(session, principal, action="social.instagram_published", resource_type="creative", resource_id=str(payload.creative_id),
                  detail=post.permalink or post.external_id)
    session.commit()
    return instagram.out(post)


class AutoIn(BaseModel):
    enabled: bool
    max_per_day: int = Field(2, ge=1, le=6)


class ReviewIn(BaseModel):
    creative_id: int
    kind: str
    verdict: str
    notes: str | None = Field(None, max_length=1500)


class AutoPublishIn(BaseModel):
    creative_id: int
    kind: str
    caption: str | None = Field(None, max_length=2200)


@router.get("/social/autopublish", summary="Publicação automática: chave, teto por dia, quantas saíram hoje e os últimos posts")
def autopublish_status(principal: Principal = Depends(require("operations.view")), session: Session = Depends(get_session)) -> dict:
    return content_pipeline.status(session)


@router.put("/social/autopublish", summary="Ligar/desligar a publicação automática e o teto por dia (só o operador)")
def autopublish_set(payload: AutoIn, principal: Principal = Depends(require("connectors.manage")), session: Session = Depends(get_session)) -> dict:
    try:
        content_pipeline.set_settings(session, enabled=payload.enabled, max_per_day=payload.max_per_day, actor=principal.username)
    except content_pipeline.ContentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_action(session, principal, action="social.autopublish_set", resource_type="social", detail=f"ligada={payload.enabled}, teto={payload.max_per_day}/dia")
    session.commit()
    return content_pipeline.status(session)


@router.get("/social/pending", summary="Criativos prontos que ainda não têm post de imagem ou Reel")
def pending(principal: Principal = Depends(require("portfolio.view")), session: Session = Depends(get_session)) -> dict:
    return {"settings": content_pipeline.get_settings(session), "published_today": content_pipeline.published_today(session),
            "pending": content_pipeline.pending_content(session)}


@router.get("/social/review/{creative_id}", summary="Imagens pequenas e fatos para o agente conferir o criativo e o slideshow")
def review_assets(creative_id: int, principal: Principal = Depends(require("portfolio.view")), session: Session = Depends(get_session)) -> dict:
    try:
        return content_pipeline.review_assets(session, creative_id)
    except (content_pipeline.ContentError, AIStudioError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/social/review", summary="Registrar o parecer (aprovado ou recusado) sobre um criativo ou slideshow", status_code=201)
def submit_review(payload: ReviewIn, principal: Principal = Depends(require("portfolio.manage")), session: Session = Depends(get_session)) -> dict:
    try:
        row = content_pipeline.submit_review(session, payload.creative_id, payload.kind, payload.verdict, payload.notes, principal.username)
    except content_pipeline.ContentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()
    return {"id": row.id, "verdict": row.verdict}


@router.post("/social/auto/publish", summary="Publicar automaticamente (só com a chave ligada, parecer aprovado e dentro do teto do dia)", status_code=201)
def auto_publish(payload: AutoPublishIn, principal: Principal = Depends(require("portfolio.manage")), session: Session = Depends(get_session)) -> dict:
    try:
        post = content_pipeline.auto_publish(session, payload.creative_id, payload.kind, caption=payload.caption, actor=principal.username)
    except content_pipeline.ContentError as exc:
        session.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_action(session, principal, action="social.auto_published", resource_type="creative", resource_id=str(payload.creative_id),
                  detail=f"{payload.kind}: {post.permalink or post.external_id}")
    session.commit()
    return instagram.out(post)


@router.get("/social/posts", summary="Histórico do que foi publicado nas redes")
def posts(limit: int = 30, principal: Principal = Depends(require("operations.view")), session: Session = Depends(get_session)) -> dict:
    return {"posts": instagram.list_posts(session, limit)}
