"""Painel financeiro: vendas, comissão, gasto com anúncios e saldo das carteiras."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.deps import get_session
from backend.security import Principal, record_action, require
from core.services import finance

router = APIRouter(prefix="/finance", tags=["financeiro"])


class WalletIn(BaseModel):
    platform: str
    balance_brl: float
    as_of: datetime | None = None
    note: str | None = Field(None, max_length=200)


@router.get("/overview", summary="Vendas, comissão, anúncios e carteiras no período")
def overview(days: int = Query(30, ge=1, le=365), _: Principal = Depends(require("operations.view")),
             session: Session = Depends(get_session)) -> dict:
    return finance.overview(session, days=days)


@router.get("/wallets", summary="Saldo atual de cada carteira")
def get_wallets(_: Principal = Depends(require("operations.view")), session: Session = Depends(get_session)) -> dict:
    return finance.wallets(session)


@router.post("/wallets", summary="Informar o saldo de uma carteira (operador; o agente não lança saldo)", status_code=201)
def set_wallet(payload: WalletIn, principal: Principal = Depends(require("connectors.manage")),
               session: Session = Depends(get_session)) -> dict:
    try:
        row = finance.set_wallet(session, payload.platform, payload.balance_brl, actor=principal.username, as_of=payload.as_of, note=payload.note)
    except finance.FinanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_action(session, principal, action="finance.wallet_set", resource_type="wallet", resource_id=str(row.id),
                  detail=f"{row.platform}: R$ {row.balance_brl:.2f}")
    session.commit()
    return finance.wallets(session)
