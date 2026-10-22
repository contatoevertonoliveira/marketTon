"""Desempenho por produto afiliado (página Produtos > Desempenho).

O que os testes travam:

* vende-se produto que não está no catálogo local — ele precisa aparecer, com o
  nome que o marketplace informou;
* cancelada não conta como venda nem como comissão;
* comissão confirmada e estimada ficam separadas, nunca somadas;
* produto vinculado sem nenhuma venda aparece zerado (não some);
* cliques sem rastreio são `None`, não `0`.
"""
from __future__ import annotations

from datetime import UTC, datetime

from core.db.base import Marketplace
from core.db.portfolio import PortfolioItem
from core.db.tracking import AffiliateLink, ClickEvent, Commission
from core.services.product_performance import product_performance
from core.services.sales_ingestion import ingest_sales
from integrations.marketplaces.base import SalesRecord

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _record(order, item, *, qty=1, gross=100.0, status="COMPLETED", title="Garrafa Térmica", est=None, conf=None):
    return SalesRecord(
        external_order_id=f"{order}:{item}",
        occurred_at=NOW,
        quantity=qty,
        currency="BRL",
        gross_amount=gross,
        product_external_id=item,
        product_title=title,
        status=status,
        commission_estimated=est,
        commission_confirmed=conf,
    )


def test_sale_of_product_outside_catalog_is_listed_with_its_title(session):
    ingest_sales(session, [_record("O1", "111", qty=2, gross=80.0, conf=8.0)], Marketplace.SHOPEE)

    rows, tracked = product_performance(session)

    assert tracked is False
    assert len(rows) == 1
    row = rows[0]
    assert (row.title, row.product_external_id, row.product_id) == ("Garrafa Térmica", "111", None)
    assert (row.orders, row.units, row.revenue, row.commission_confirmed) == (1, 2, 80.0, 8.0)


def test_same_product_across_orders_is_aggregated(session):
    ingest_sales(
        session,
        [_record("O1", "111", qty=1, gross=50.0, conf=5.0), _record("O2", "111", qty=3, gross=150.0, est=15.0)],
        Marketplace.SHOPEE,
    )

    (row,), _ = product_performance(session)

    assert (row.orders, row.units, row.revenue) == (2, 4, 200.0)
    # Confirmada e estimada separadas: somar as duas seria receita fabricada.
    assert (row.commission_confirmed, row.commission_estimated) == (5.0, 15.0)


def test_cancelled_order_counts_neither_as_sale_nor_commission(session):
    ingest_sales(
        session,
        [_record("O1", "111", gross=50.0, conf=5.0), _record("O2", "111", gross=999.0, status="CANCELLED", est=99.0)],
        Marketplace.SHOPEE,
    )

    (row,), _ = product_performance(session)

    assert (row.orders, row.cancelled_orders, row.revenue) == (1, 1, 50.0)
    assert row.commission_estimated == 0.0


def test_linked_product_without_sales_still_appears(session, product):
    item = PortfolioItem(
        product_id=product.id, marketplace=Marketplace.MERCADO_LIVRE, label="Fone", state_changed_at=NOW
    )
    session.add(item)
    session.flush()

    rows, _ = product_performance(session)

    (row,) = rows
    assert (row.orders, row.units, row.revenue) == (0, 0, 0.0)
    assert row.portfolio_item_id == item.id
    assert row.portfolio_state == "DISCOVERED"
    assert row.title == "Fone Bluetooth Mini"
    assert row.price == 150.0


def test_sale_of_catalog_product_links_to_item_and_commission_carries_it(session, product):
    item = PortfolioItem(
        product_id=product.id, marketplace=Marketplace.MERCADO_LIVRE, label="Fone", state_changed_at=NOW
    )
    session.add(item)
    session.flush()

    ingest_sales(
        session,
        [_record("O1", product.external_id, gross=150.0, title=None, conf=15.0)],
        Marketplace.MERCADO_LIVRE,
    )

    (row,), _ = product_performance(session)
    assert row.portfolio_item_id == item.id and row.product_id == product.id
    assert row.units == 1 and row.title == "Fone Bluetooth Mini"
    assert session.query(Commission).one().portfolio_item_id == item.id


def test_marketplace_filter(session):
    ingest_sales(session, [_record("O1", "111")], Marketplace.SHOPEE)
    ingest_sales(session, [_record("O2", "MLB9", title="Outro")], Marketplace.MERCADO_LIVRE)

    rows, _ = product_performance(session, Marketplace.SHOPEE)

    assert [r.product_external_id for r in rows] == ["111"]


def test_clicks_are_none_until_tracked_then_counted(session, product):
    item = PortfolioItem(
        product_id=product.id, marketplace=Marketplace.MERCADO_LIVRE, label="Fone", state_changed_at=NOW
    )
    session.add(item)
    session.flush()

    (row,), tracked = product_performance(session)
    assert tracked is False and row.clicks is None

    link = AffiliateLink(
        portfolio_item_id=item.id,
        product_id=product.id,
        marketplace=Marketplace.MERCADO_LIVRE,
        destination_url="https://x",
        affiliate_url="https://y",
        short_code="abc",
    )
    session.add(link)
    session.flush()
    for n in range(3):
        session.add(
            ClickEvent(affiliate_link_id=link.id, portfolio_item_id=item.id, occurred_at=NOW, external_click_id=f"c{n}")
        )
    session.flush()

    (row,), tracked = product_performance(session)
    assert tracked is True and row.clicks == 3
