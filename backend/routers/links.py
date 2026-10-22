"""Links curtos rastreados (criar, listar, sincronizar cliques)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.deps import get_session
from backend.security import Principal, record_action, require
from core.services.link_shortener import CHANNELS, ShortenerError, create_tracked_link, list_links, sync_clicks

router = APIRouter(prefix="/links", tags=["links rastreados"])


class LinkCreate(BaseModel):
    portfolio_item_id: int | None = None
    product_id: int | None = None
    channel: str = "outro"
    campaign: str | None = None


@router.get("/channels", summary="Canais aceitos")
def channels(principal: Principal = Depends(require("portfolio.view"))) -> list[str]:
    return list(CHANNELS)


@router.get("", summary="Links rastreados e quantos cliques cada um recebeu")
def get_links(
    portfolio_item_id: int | None = None,
    product_id: int | None = None,
    principal: Principal = Depends(require("portfolio.view")),
    session: Session = Depends(get_session),
) -> list[dict]:
    return list_links(session, portfolio_item_id=portfolio_item_id, product_id=product_id)


@router.post("", summary="Criar o link curto rastreado de um produto para um canal", status_code=201)
def post_link(
    payload: LinkCreate,
    principal: Principal = Depends(require("portfolio.manage")),
    session: Session = Depends(get_session),
) -> dict:
    if not (payload.portfolio_item_id or payload.product_id):
        raise HTTPException(status_code=422, detail="informe portfolio_item_id ou product_id")
    try:
        link = create_tracked_link(session, portfolio_item_id=payload.portfolio_item_id, product_id=payload.product_id,
                                   channel=payload.channel, campaign=payload.campaign)
    except ShortenerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_action(session, principal, action="links.created", resource_type="affiliate_link", resource_id=str(link.id),
                  detail=f"{link.channel} {link.short_code}")
    session.commit()
    return {"id": link.id, "short_url": link.affiliate_url, "code": link.short_code, "channel": link.channel,
            "campaign": link.campaign, "clicks": link.clicks_total or 0}


@router.post("/sync", summary="Buscar os cliques novos no redirecionador")
def post_sync(
    principal: Principal = Depends(require("portfolio.manage")), session: Session = Depends(get_session)
) -> dict:
    try:
        result = sync_clicks(session)
    except ShortenerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    record_action(session, principal, action="links.clicks_synced", resource_type="affiliate_link",
                  detail=f"{result['new_clicks']} clique(s) novo(s)")
    session.commit()
    return result
