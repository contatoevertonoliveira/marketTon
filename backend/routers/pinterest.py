"""Pinterest: rascunhos de pin, aprovação, publicação (só o operador), kit para postar à mão e métricas."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.deps import get_session
from backend.security import Principal, record_action, require
from core.db.catalog import Product
from core.db.pinterest import PinterestPin
from core.services import pinterest, storefront

router = APIRouter(prefix="/pinterest", tags=["pinterest"])


def _fail(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


def _view(session: Session, pin: PinterestPin) -> dict:
    return pinterest.out(pin, session.get(Product, pin.product_id))


@router.get("/status", summary="Pinterest: modo, teto por dia, contagem por situação e quantos produtos ainda podem virar pin")
def status(principal: Principal = Depends(require("portfolio.view")), session: Session = Depends(get_session)) -> dict:
    counts = dict(session.execute(select(PinterestPin.status, func.count()).group_by(PinterestPin.status)).all())
    cfg = pinterest.settings(session)
    return {**cfg, "counts": counts, "published_last_24h": pinterest.published_last_24h(session), "candidates": len(pinterest.candidates(session, 50))}


@router.get("/pins", summary="Pins (mais recentes primeiro); `status` filtra")
def pins(status: str | None = None, limit: int = 60, principal: Principal = Depends(require("portfolio.view")), session: Session = Depends(get_session)) -> dict:
    pinterest.refresh_images(session)  # imagens novas que o estúdio acabou de entregar
    session.commit()
    return {"pins": pinterest.list_pins(session, status, limit)}


class DraftsIn(BaseModel):
    count: int = Field(3, ge=1, le=20)
    product_ids: list[int] | None = Field(None, max_length=20)
    board: str | None = Field(None, max_length=120)


@router.post("/drafts", summary="Gerar rascunhos de pin (produtos da vitrine ainda sem pin, ou os que você escolher)", status_code=201)
def drafts(payload: DraftsIn, principal: Principal = Depends(require("portfolio.manage")), session: Session = Depends(get_session)) -> dict:
    try:
        made = pinterest.create_drafts(session, actor=principal.username, count=payload.count, product_ids=payload.product_ids, board=payload.board)
    except pinterest.PinterestError as exc:
        session.commit()
        raise _fail(exc) from exc
    record_action(session, principal, action="pinterest.drafts", resource_type="pinterest", detail=f"{len(made)} rascunho(s)")
    session.commit()
    return {"pins": [_view(session, p) for p in made]}


class EditIn(BaseModel):
    title: str | None = Field(None, max_length=100)
    description: str | None = Field(None, max_length=800)
    alt_text: str | None = Field(None, max_length=500)
    keywords: str | None = Field(None, max_length=300)
    board_name: str | None = Field(None, max_length=120)
    scheduled_for: datetime | None = None


@router.patch("/pins/{pin_id}", summary="Editar texto, quadro ou horário de um pin que ainda não saiu")
def edit(pin_id: int, payload: EditIn, principal: Principal = Depends(require("portfolio.manage")), session: Session = Depends(get_session)) -> dict:
    try:
        pin = pinterest.update(session, pin_id, payload.model_dump(exclude_unset=True))
    except pinterest.PinterestError as exc:
        raise _fail(exc) from exc
    session.commit()
    return _view(session, pin)


class ApproveIn(BaseModel):
    scheduled_for: datetime | None = None


@router.post("/pins/{pin_id}/approve", summary="Aprovar o pin (sai sozinho no horário, dentro do teto por dia)")
def approve(pin_id: int, payload: ApproveIn | None = None, principal: Principal = Depends(require("connectors.manage")), session: Session = Depends(get_session)) -> dict:
    try:
        pin = pinterest.approve(session, pin_id, payload.scheduled_for if payload else None)
    except pinterest.PinterestError as exc:
        raise _fail(exc) from exc
    record_action(session, principal, action="pinterest.approved", resource_type="pin", resource_id=str(pin_id))
    session.commit()
    return _view(session, pin)


@router.post("/pins/{pin_id}/reject", summary="Descartar o pin")
def reject(pin_id: int, principal: Principal = Depends(require("portfolio.manage")), session: Session = Depends(get_session)) -> dict:
    try:
        pin = pinterest.reject(session, pin_id)
    except pinterest.PinterestError as exc:
        raise _fail(exc) from exc
    session.commit()
    return _view(session, pin)


@router.post("/pins/{pin_id}/publish", summary="PUBLICAR agora no Pinterest (só o operador)", status_code=201)
def publish(pin_id: int, principal: Principal = Depends(require("connectors.manage")), session: Session = Depends(get_session)) -> dict:
    pin = session.get(PinterestPin, pin_id)
    if pin is None:
        raise HTTPException(status_code=404, detail="pin não encontrado")
    try:  # a página do produto no Mural precisa existir antes: o pin aponta para ela
        storefront.ensure_listed(session, pin.product_id, actor=principal.username)
        storefront.publish_if_needed(session, actor=principal.username)
        session.commit()
        pin = pinterest.publish(session, pin_id, actor=principal.username)
    except (pinterest.PinterestError, storefront.StorefrontError) as exc:
        session.commit()  # guarda a falha no pin
        raise _fail(exc) from exc
    record_action(session, principal, action="pinterest.published", resource_type="pin", resource_id=str(pin_id), detail=pin.permalink)
    session.commit()
    return _view(session, pin)


@router.post("/pins/{pin_id}/new-image", summary="Pedir ao AI Studio uma imagem NOVA para o pin (limpa, nítida, em ambiente que realce o produto)", status_code=201)
def new_image(pin_id: int, principal: Principal = Depends(require("portfolio.manage")), session: Session = Depends(get_session)) -> dict:
    pin = session.get(PinterestPin, pin_id)
    if pin is None:
        raise HTTPException(status_code=404, detail="pin não encontrado")
    try:
        pinterest.request_image(session, pin, actor=principal.username)
    except pinterest.PinterestError as exc:
        session.commit()
        raise _fail(exc) from exc
    record_action(session, principal, action="pinterest.new_image", resource_type="pin", resource_id=str(pin_id))
    session.commit()
    return _view(session, pin)


@router.get("/pins/{pin_id}/image", summary="A imagem do pin em JPEG (para ver e baixar)")
def image(pin_id: int, principal: Principal = Depends(require("portfolio.view")), session: Session = Depends(get_session)) -> Response:
    pin = session.get(PinterestPin, pin_id)
    if pin is None:
        raise HTTPException(status_code=404, detail="pin não encontrado")
    try:
        data = pinterest.fetch_image(session, pin.image_ref)
    except pinterest.PinterestError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=600"})


@router.get("/boards", summary="Quadros da conta no Pinterest")
def boards(principal: Principal = Depends(require("portfolio.view")), session: Session = Depends(get_session)) -> dict:
    try:
        return {"boards": pinterest.boards(pinterest._require(session))}
    except pinterest.PinterestError as exc:
        raise _fail(exc) from exc


@router.post("/sync-metrics", summary="Ler impressões, salvamentos e cliques dos pins publicados")
def sync_metrics(principal: Principal = Depends(require("portfolio.manage")), session: Session = Depends(get_session)) -> dict:
    n = pinterest.sync_metrics(session)
    session.commit()
    return {"updated": n}
