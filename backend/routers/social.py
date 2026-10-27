"""Publicar nas redes do Mural na Web (Instagram): texto sugerido, publicação pelo operador e histórico."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.deps import get_session
from backend.security import Principal, record_action, require
from core.db.creatives import CreativeCampaign
from core.services import aistudio, instagram
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


@router.get("/social/posts", summary="Histórico do que foi publicado nas redes")
def posts(limit: int = 30, principal: Principal = Depends(require("operations.view")), session: Session = Depends(get_session)) -> dict:
    return {"posts": instagram.list_posts(session, limit)}
