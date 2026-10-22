"""Desempenho dos produtos afiliados: vendas, receita e comissão por produto."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.deps import get_session
from backend.security import require
from core.db.base import Marketplace
from core.services.product_performance import product_performance

router = APIRouter(
    prefix="/performance", tags=["desempenho"], dependencies=[Depends(require("portfolio.view"))]
)


class ProductPerformanceOut(BaseModel):
    marketplace: str
    product_external_id: str | None = None
    title: str | None = None
    product_id: int | None = None
    portfolio_item_id: int | None = None
    portfolio_state: str | None = None
    image: str | None = None
    product_url: str | None = None
    affiliate_url: str | None = None
    price: float | None = None
    commission_pct: float | None = None
    orders: int
    units: int
    cancelled_orders: int
    revenue: float
    commission_estimated: float
    commission_confirmed: float
    first_sale_at: datetime | None = None
    last_sale_at: datetime | None = None
    clicks: int | None = None


class PerformanceOut(BaseModel):
    clicks_tracked: bool
    products: list[ProductPerformanceOut] = Field(default_factory=list)


@router.get("/products", response_model=PerformanceOut)
def products_performance(
    marketplace: Marketplace | None = Query(None), session: Session = Depends(get_session)
) -> PerformanceOut:
    rows, clicks_tracked = product_performance(session, marketplace)
    return PerformanceOut(
        clicks_tracked=clicks_tracked,
        products=[
            ProductPerformanceOut(**{k: v for k, v in asdict(r).items() if k != "sale_ids"}) for r in rows
        ],
    )
