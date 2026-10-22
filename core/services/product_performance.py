"""Desempenho por produto afiliado: o que vendeu, quanto rendeu, e o que não vendeu.

A fonte de "produtos que eu afiliei" é o que o sistema consegue observar:

* **vendas ingeridas** (`sales`) — qualquer produto com conversão, esteja ou não
  no catálogo local;
* **itens de portfólio** — produtos que entraram na operação, mesmo sem nenhuma
  venda ainda (aparecem zerados, com a situação da filiação).

Afiliar-se a um produto direto no app do marketplace não deixa rastro que a
API exponha; só a primeira conversão o revela. Por isso um produto afiliado que
nunca converteu e não está no portfólio não aparece aqui — a tela diz isso.

Cliques: só existem se `click_events` tiver registros. A API de afiliados da
Shopee devolve cliques apenas dentro de conversões, então hoje esse número é
"não rastreado" (`None`), nunca zero inventado.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.db.base import Marketplace
from core.db.catalog import Product
from core.db.portfolio import PortfolioItem
from core.db.tracking import ClickEvent, Commission, Sale

CANCELLED = "CANCELLED"


@dataclass
class ProductPerformance:
    marketplace: str
    product_external_id: str | None
    title: str | None
    product_id: int | None = None
    portfolio_item_id: int | None = None
    portfolio_state: str | None = None
    image: str | None = None
    product_url: str | None = None
    affiliate_url: str | None = None
    price: float | None = None
    commission_pct: float | None = None  # taxa anunciada no catálogo, quando há

    orders: int = 0
    units: int = 0
    cancelled_orders: int = 0
    revenue: float = 0.0
    commission_estimated: float = 0.0  # pendente de confirmação
    commission_confirmed: float = 0.0
    first_sale_at: datetime | None = None
    last_sale_at: datetime | None = None
    clicks: int | None = None  # None = não rastreado

    sale_ids: list[int] = field(default_factory=list, repr=False)


def _is_cancelled(status: str | None) -> bool:
    return (status or "").upper() == CANCELLED


def product_performance(
    session: Session, marketplace: Marketplace | None = None
) -> tuple[list[ProductPerformance], bool]:
    """Devolve (linhas por produto, se há rastreio de cliques)."""
    sales_stmt = select(Sale)
    if marketplace is not None:
        sales_stmt = sales_stmt.where(Sale.marketplace == marketplace)
    sales = session.scalars(sales_stmt).all()

    commissions: dict[int, list[Commission]] = {}
    sale_ids = [s.id for s in sales]
    if sale_ids:
        for commission in session.scalars(select(Commission).where(Commission.sale_id.in_(sale_ids))):
            commissions.setdefault(commission.sale_id, []).append(commission)

    rows: dict[tuple[str, str], ProductPerformance] = {}

    def row_for(mp: Marketplace, external_id: str | None, title: str | None, sale_id: int) -> ProductPerformance:
        # Venda sem id de produto (ingerida antes da migração 0010) cai num
        # grupo próprio por venda — não funde produtos diferentes.
        key = (mp.value, external_id or f"sale:{sale_id}")
        if key not in rows:
            rows[key] = ProductPerformance(marketplace=mp.value, product_external_id=external_id, title=title)
        elif title and not rows[key].title:
            rows[key].title = title
        return rows[key]

    for sale in sales:
        row = row_for(sale.marketplace, sale.product_external_id, sale.product_title, sale.id)
        row.sale_ids.append(sale.id)
        if sale.product_id and row.product_id is None:
            row.product_id = sale.product_id
        if sale.portfolio_item_id and row.portfolio_item_id is None:
            row.portfolio_item_id = sale.portfolio_item_id

        row.first_sale_at = min(filter(None, [row.first_sale_at, sale.occurred_at]))
        row.last_sale_at = max(filter(None, [row.last_sale_at, sale.occurred_at]))

        if _is_cancelled(sale.status):
            row.cancelled_orders += 1
            continue
        row.orders += 1
        row.units += sale.quantity or 1
        row.revenue += float(sale.gross_amount or 0)
        for commission in commissions.get(sale.id, []):
            if commission.status == "confirmed" and commission.confirmed_amount is not None:
                row.commission_confirmed += float(commission.confirmed_amount)
            elif commission.estimated_amount is not None:
                row.commission_estimated += float(commission.estimated_amount)

    # Itens de portfólio sem venda: "tudo referente à minha filiação" mesmo zerado.
    items_stmt = select(PortfolioItem)
    if marketplace is not None:
        items_stmt = items_stmt.where(PortfolioItem.marketplace == marketplace)
    for item in session.scalars(items_stmt):
        product = session.get(Product, item.product_id)
        existing = next(
            (r for r in rows.values() if r.portfolio_item_id == item.id or (product and r.product_id == product.id)),
            None,
        )
        if existing is None:
            existing = ProductPerformance(
                marketplace=item.marketplace.value,
                product_external_id=product.external_id if product else None,
                title=(product.title if product else None) or item.label,
            )
            rows[(item.marketplace.value, f"item:{item.id}")] = existing
        existing.portfolio_item_id = item.id
        existing.portfolio_state = item.state.value
        existing.product_id = existing.product_id or item.product_id

    # Enriquecimento com o catálogo, quando o produto está nele.
    catalog_ids = {r.product_id for r in rows.values() if r.product_id}
    by_external: dict[tuple[str, str], Product] = {}
    by_id: dict[int, Product] = {}
    if catalog_ids:
        for product in session.scalars(select(Product).where(Product.id.in_(catalog_ids))):
            by_id[product.id] = product
    pending_external = [(r.marketplace, r.product_external_id) for r in rows.values() if r.product_external_id and not r.product_id]
    for mp_value, external_id in pending_external:
        product = session.scalar(
            select(Product).where(Product.marketplace == Marketplace(mp_value), Product.external_id == external_id)
        )
        if product is not None:
            by_external[(mp_value, external_id)] = product

    for row in rows.values():
        product = by_id.get(row.product_id) if row.product_id else by_external.get((row.marketplace, row.product_external_id or ""))
        if product is None:
            continue
        row.product_id = product.id
        row.title = row.title or product.title
        row.image = (product.images or [None])[0]
        row.product_url = product.product_url
        row.affiliate_url = product.affiliate_url
        row.price = product.price
        row.commission_pct = product.affiliate_commission_pct

    # Cliques: só rastreados se existir algum ClickEvent.
    clicks_tracked = session.scalar(select(func.count()).select_from(ClickEvent)) > 0
    if clicks_tracked:
        counts = dict(
            session.execute(
                select(ClickEvent.portfolio_item_id, func.count())
                .where(ClickEvent.portfolio_item_id.is_not(None))
                .group_by(ClickEvent.portfolio_item_id)
            ).all()
        )
        for row in rows.values():
            row.clicks = counts.get(row.portfolio_item_id, 0) if row.portfolio_item_id else None

    return list(rows.values()), clicks_tracked


__all__ = ["ProductPerformance", "product_performance"]
