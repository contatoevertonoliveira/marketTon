"""Links de afiliado colados à mão (Mercado Livre e Amazon): o painel do marketplace gera o link, o operador cola aqui."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.deps import get_session
from backend.security import Principal, record_action, require
from core.db.catalog import Product
from core.services import manual_affiliate_links as mal

router = APIRouter(prefix="/affiliate-links", tags=["links de afiliado manuais"])


class OneLink(BaseModel):
    url: str = Field(..., max_length=4000)


class ManyLinks(BaseModel):
    text: str = Field(..., max_length=60000)
    marketplace: str = "mercado_livre"


@router.get("/missing", summary="Produtos do marketplace que ainda não têm link de afiliado")
def missing(marketplace: str = "mercado_livre", limit: int = 50, _: Principal = Depends(require("portfolio.view")), session: Session = Depends(get_session)) -> dict:
    rows = session.scalars(select(Product).where(Product.marketplace == marketplace, Product.affiliate_url.is_(None), Product.is_active.is_(True))
                           .order_by(Product.price.desc().nullslast()).limit(max(1, min(limit, 200))))
    return {"marketplace": marketplace, "hosts": mal.ALLOWED_HOSTS.get(marketplace, ()),
            "items": [{"product_id": p.id, "title": (p.title or "")[:90], "price": p.price, "product_url": p.product_url} for p in rows]}


@router.put("/product/{product_id}", summary="Guardar o link de afiliado de um produto (só o operador)")
def put_link(product_id: int, payload: OneLink, principal: Principal = Depends(require("connectors.manage")), session: Session = Depends(get_session)) -> dict:
    try:
        p = mal.set_affiliate_url(session, product_id, payload.url)
    except mal.AffiliateLinkError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_action(session, principal, action="affiliate_link.set", resource_type="product", resource_id=str(product_id), detail=p.marketplace.value)
    session.commit()
    return {"product_id": p.id, "affiliate_url": p.affiliate_url}


@router.post("/import", summary="Importar vários links (uma linha por produto: endereço do produto e link de afiliado) — só o operador")
def import_links(payload: ManyLinks, principal: Principal = Depends(require("connectors.manage")), session: Session = Depends(get_session)) -> dict:
    result = mal.import_links(session, payload.text, payload.marketplace)
    record_action(session, principal, action="affiliate_link.imported", resource_type="product", detail=f"{len(result['saved'])} salvo(s)")
    session.commit()
    return result
