"""Ingestão de vendas e comissão a partir de `MarketplaceAdapter.fetch_sales`.

`fetch_sales` e as tabelas `sales`/`commissions` existiam desde o começo do
projeto, mas nada ligava os dois — nenhum adapter tinha `fetch_sales`
implementado de verdade. Este módulo é essa ponte, no mesmo espírito de
`core/services/ingestion.py` (produtos): idempotente por `external_order_id`,
nunca inventa comissão confirmada a partir de estimada.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.base import Marketplace
from core.db.catalog import Product
from core.db.portfolio import PortfolioItem
from core.db.tracking import Commission, Sale
from integrations.marketplaces.base import SalesRecord


@dataclass
class SalesIngestStats:
    marketplace: str
    created: int = 0
    updated: int = 0
    skipped: int = 0
    linked_to_product: int = 0
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.marketplace}: {self.created} vendas novas, {self.updated} atualizadas, "
            f"{self.linked_to_product} ligadas a produto do catálogo"
        )


def _as_enum(value: Marketplace | str) -> Marketplace:
    return value if isinstance(value, Marketplace) else Marketplace(value)


def ingest_sales(
    session: Session, records: list[SalesRecord], marketplace: Marketplace | str
) -> SalesIngestStats:
    """Grava vendas e comissão, uma por `external_order_id`.

    Comissão confirmada nunca é sobrescrita por um valor estimado mais novo —
    uma vez confirmada pelo marketplace, permanece confirmada mesmo que uma
    releitura futura só traga o campo estimado (relatórios têm janelas
    diferentes; a confirmação não "desconfirma").
    """
    marketplace_enum = _as_enum(marketplace)
    stats = SalesIngestStats(marketplace=marketplace_enum.value)

    for record in records:
        if not record.external_order_id:
            stats.skipped += 1
            stats.warnings.append("registro sem external_order_id, ignorado")
            continue

        product = None
        if record.product_external_id:
            product = session.scalar(
                select(Product).where(
                    Product.marketplace == marketplace_enum,
                    Product.external_id == record.product_external_id,
                )
            )
        portfolio_item = (
            session.scalar(select(PortfolioItem).where(PortfolioItem.product_id == product.id))
            if product is not None
            else None
        )

        sale = session.scalar(
            select(Sale).where(
                Sale.marketplace == marketplace_enum,
                Sale.external_order_id == record.external_order_id,
            )
        )

        if sale is None:
            sale = Sale(
                marketplace=marketplace_enum,
                external_order_id=record.external_order_id,
                occurred_at=record.occurred_at,
                quantity=record.quantity,
                currency=record.currency,
                gross_amount=record.gross_amount,
                net_amount=record.net_amount,
                channel=record.channel,
                status=record.status,
                product_id=product.id if product else None,
                portfolio_item_id=portfolio_item.id if portfolio_item else None,
            )
            session.add(sale)
            session.flush()
            stats.created += 1
        else:
            sale.status = record.status or sale.status
            if record.gross_amount is not None:
                sale.gross_amount = record.gross_amount
            if record.net_amount is not None:
                sale.net_amount = record.net_amount
            if product is not None and sale.product_id is None:
                sale.product_id = product.id
            if portfolio_item is not None and sale.portfolio_item_id is None:
                sale.portfolio_item_id = portfolio_item.id
            stats.updated += 1

        if product is not None:
            stats.linked_to_product += 1

        _apply_commission(session, sale, record)

    session.flush()
    return stats


def _apply_commission(session: Session, sale: Sale, record: SalesRecord) -> None:
    commission = session.scalar(select(Commission).where(Commission.sale_id == sale.id))
    if commission is None:
        commission = Commission(
            sale_id=sale.id,
            marketplace=sale.marketplace,
            currency=record.currency,
            rate_basis_points=record.commission_rate_basis_points,
        )
        session.add(commission)
        session.flush()

    if record.commission_estimated is not None:
        commission.estimated_amount = record.commission_estimated
        if commission.status != "confirmed":
            commission.status = "estimated"
    if record.commission_confirmed is not None:
        commission.confirmed_amount = record.commission_confirmed
        commission.confirmed_at = record.occurred_at
        commission.status = "confirmed"


__all__ = ["SalesIngestStats", "ingest_sales"]
