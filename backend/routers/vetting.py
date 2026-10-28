"""Triagem de produtos: procura, demanda, prazo e conta de anúncio antes de gastar dinheiro."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.deps import get_session
from backend.security import Principal, require
from core.db.vetting import ProductVetting
from core.services import product_vetting as pv

router = APIRouter(prefix="/vetting", tags=["triagem de produtos"])


class VetIn(BaseModel):
    keyword: str | None = Field(None, max_length=120)  # a busca que as pessoas fazem para achar este produto (ex.: "afiador de facas")


@router.get("", summary="Últimos pareceres de triagem")
def list_vettings(verdict: str | None = None, limit: int = 50, _: Principal = Depends(require("portfolio.view")),
                  session: Session = Depends(get_session)) -> dict:
    rows, seen = [], set()
    for v in session.scalars(select(ProductVetting).order_by(ProductVetting.id.desc())):
        if v.product_id in seen:
            continue
        seen.add(v.product_id)
        if verdict is None or v.verdict == verdict:
            rows.append(pv.out(v))
        if len(rows) >= max(1, min(limit, 200)):
            break
    return {"items": rows}


@router.get("/review", summary="Balanço semanal, quinzenal ou mensal")
def review(period: str = "weekly", _: Principal = Depends(require("portfolio.view")), session: Session = Depends(get_session)) -> dict:
    try:
        return pv.review(session, period)
    except pv.VettingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/due", summary="Refaz a triagem dos produtos sem parecer ou com parecer velho", status_code=201)
def run_due(limit: int = 10, principal: Principal = Depends(require("portfolio.manage")), session: Session = Depends(get_session)) -> dict:
    rows = pv.vet_due(session, limit=max(1, min(limit, 25)), actor=principal.username if hasattr(principal, "username") else "agente")
    session.commit()
    return {"vetted": [pv.out(v) for v in rows]}


@router.post("/{product_id}", summary="Tria um produto (procura no Google, demanda, prazo e conta do anúncio)", status_code=201)
def vet_product(product_id: int, payload: VetIn, principal: Principal = Depends(require("portfolio.manage")),
                session: Session = Depends(get_session)) -> dict:
    try:
        row = pv.vet(session, product_id, keyword=payload.keyword, actor=getattr(principal, "username", "agente"))
    except pv.VettingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.commit()
    return pv.out(row)
