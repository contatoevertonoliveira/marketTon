"""Administração da vitrine pública (o que aparece na loja e a publicação)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.deps import get_session
from backend.security import Principal, record_action, require
from core.services import storefront
from core.services.storefront import StorefrontError

router = APIRouter(prefix="/storefront", tags=["vitrine pública"])


class ItemUpdate(BaseModel):
    category: str | None = None
    display_title: str | None = None
    blurb: str | None = None
    highlight: bool | None = None
    hidden: bool | None = None
    position: int | None = None


class MetaUpdate(BaseModel):
    name: str | None = None
    tagline: str | None = None
    subtitle: str | None = None
    socials: dict[str, str] | None = None  # facebook, instagram, youtube, whatsapp, telegram, tiktok (https://...)


@router.get("", summary="Produtos da vitrine, o que pode ser publicado e o último envio")
def get_storefront(
    principal: Principal = Depends(require("portfolio.view")), session: Session = Depends(get_session)
) -> dict:
    return storefront.list_admin(session)


@router.get("/preview", summary="A fotografia pública exatamente como seria publicada agora (sem criar links)")
def preview(
    principal: Principal = Depends(require("portfolio.view")), session: Session = Depends(get_session)
) -> dict:
    return storefront.build_snapshot(session, create_links=False)


@router.put("/items/{product_id}", summary="Ajustar como um produto aparece na vitrine (cria o ajuste se não existir)")
def put_item(
    product_id: int,
    payload: ItemUpdate,
    principal: Principal = Depends(require("portfolio.manage")),
    session: Session = Depends(get_session),
) -> dict:
    try:
        row = storefront.upsert_item(session, product_id, **payload.model_dump())
    except StorefrontError as exc:
        status = 404 if "não encontrado" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    changed = ", ".join(k for k, v in payload.model_dump().items() if v is not None) or "nada"
    record_action(session, principal, action="storefront.item_updated", resource_type="product",
                  resource_id=str(product_id), detail=changed)
    session.commit()
    return {"product_id": product_id, "category": row.category, "hidden": row.hidden, "highlight": row.highlight}


@router.put("/meta", summary="Nome e frase da loja")
def put_meta(
    payload: MetaUpdate,
    principal: Principal = Depends(require("portfolio.manage")),
    session: Session = Depends(get_session),
) -> dict:
    try:
        meta = storefront.set_meta(session, name=payload.name, tagline=payload.tagline, subtitle=payload.subtitle,
                                   socials=payload.socials, actor=principal.username)
    except StorefrontError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_action(session, principal, action="storefront.meta_updated", resource_type="storefront", detail=meta["name"])
    session.commit()
    return meta


@router.post("/publish", summary="Publicar a vitrine (envia a fotografia ao site público)")
def post_publish(
    principal: Principal = Depends(require("portfolio.manage")), session: Session = Depends(get_session)
) -> dict:
    try:
        result = storefront.publish(session, actor=principal.username)
    except StorefrontError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_action(session, principal, action="storefront.published", resource_type="storefront",
                  detail=f"{result['count']} produto(s)")
    session.commit()
    return result
