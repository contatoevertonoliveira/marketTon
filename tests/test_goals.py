"""Metas do agente: o placar do mês com dados reais, ritmo esperado e projeção.

Trava: metas começam como sugestão e só o operador as define; só entra no placar o que foi medido (cliques de pessoas,
vendas não canceladas, comissão confirmada ou estimada, publicações PUBLISHED); o ritmo compara com o dia do mês.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.db.base import ConnectorKind, Marketplace
from core.db.catalog import Product, SourceRecord
from core.db.tracking import AffiliateLink, ClickEvent, Commission, Sale
from core.services import agent_goals as goals
from core.db.app_settings import AppSetting

NOW = datetime(2026, 10, 16, 12, 0).astimezone()  # dia 16 de 31 (hora local)


@pytest.fixture
def link(session):
    source = SourceRecord(marketplace=Marketplace.SHOPEE, connector="shopee", connector_kind=ConnectorKind.OFFICIAL_API,
                          endpoint="x", external_id="p1", collected_at=NOW)
    session.add(source)
    session.flush()
    product = Product(marketplace=Marketplace.SHOPEE, external_id="p1", title="G", price=10.0, source_record_id=source.id,
                      first_seen_at=NOW, last_seen_at=NOW)
    session.add(product)
    session.flush()
    link = AffiliateLink(product_id=product.id, marketplace=Marketplace.SHOPEE, channel="vitrine", destination_url="https://x.com/a",
                         affiliate_url="https://felixsystems.com.br/r/abc", short_code="abc")
    session.add(link)
    session.flush()
    return link


def _click(session, link, when):
    session.add(ClickEvent(affiliate_link_id=link.id, occurred_at=when, external_click_id=f"{when.isoformat()}-{id(when)}"))


def _sale(session, order, status, confirmed=None, estimated=None, when=NOW):
    sale = Sale(marketplace=Marketplace.SHOPEE, external_order_id=order, occurred_at=when, status=status, quantity=1)
    session.add(sale)
    session.flush()
    session.add(Commission(sale_id=sale.id, marketplace=Marketplace.SHOPEE, confirmed_amount=confirmed, estimated_amount=estimated))
    session.flush()


def test_targets_start_as_suggestions_and_only_valid_numbers_are_saved(session):
    t = goals.get_targets(session)
    assert all(v["suggested"] for v in t.values()) and t["clicks"]["target"] == 500
    saved = goals.set_targets(session, {"clicks": 1200, "commission_brl": 450.5}, actor="admin")
    assert saved["clicks"] == {"target": 1200, "suggested": False} and saved["commission_brl"]["target"] == 450.5
    assert saved["sales"]["suggested"] is True  # o que não foi tocado continua sugestão
    for bad in ({"orkut": 1}, {"clicks": -1}, {"clicks": "muitos"}, {"clicks": True}):
        with pytest.raises(goals.GoalsError):
            goals.set_targets(session, bad, actor="x")


def test_progress_counts_only_this_month_and_only_real_sales(session, link):
    for _ in range(3):
        _click(session, link, datetime(2026, 10, 10, 9, 0, tzinfo=UTC))
    _click(session, link, datetime(2026, 9, 28, 9, 0, tzinfo=UTC))  # mês passado: fora
    _sale(session, "a", "COMPLETED", confirmed=9.35)
    _sale(session, "b", "PENDING", estimated=4.0)
    _sale(session, "c", "CANCELLED", estimated=50.0)  # cancelada não conta
    _sale(session, "d", "COMPLETED", confirmed=7.0, when=datetime(2026, 9, 20, tzinfo=UTC))  # mês passado
    goals.set_targets(session, {"clicks": 10, "sales": 4, "commission_brl": 100, "posts": 0, "store_products": 0}, actor="x")
    p = goals.progress(session, NOW)
    by = {m["key"]: m for m in p["metrics"]}
    assert by["clicks"]["current"] == 3 and by["sales"]["current"] == 2 and by["commission_brl"]["current"] == pytest.approx(13.35)
    assert (p["day"], p["days"], p["period"]) == (16, 31, "10/2026")


def test_pace_projection_and_status(session, link):
    for _ in range(4):
        _click(session, link, datetime(2026, 10, 5, tzinfo=UTC))
    goals.set_targets(session, {"clicks": 40, "sales": 10, "commission_brl": 0, "posts": 0, "store_products": 0}, actor="x")
    by = {m["key"]: m for m in goals.progress(session, NOW)["metrics"]}
    clicks = by["clicks"]
    assert clicks["pct"] == 10.0 and clicks["expected_pct"] == pytest.approx(51.6, abs=0.1)
    assert clicks["projection"] == pytest.approx(7.75, abs=0.05)  # 4 cliques em 16 dias -> ~7,75 no mês
    assert clicks["status"] == "atrasada" and clicks["missing"] == 36
    assert by["sales"]["status"] == "atrasada" and by["posts"]["status"] == "sem_meta"
    summary = goals.progress(session, NOW)
    assert "clicks" in summary["behind"] and "Atrasadas" in summary["summary"]

    goals.set_targets(session, {"clicks": 4}, actor="x")
    assert {m["key"]: m for m in goals.progress(session, NOW)["metrics"]}["clicks"]["status"] == "adiantada"  # bateu a meta


def test_store_products_use_the_last_publication_and_are_not_pro_rated(session):
    session.add(AppSetting(key="storefront_last_publish", value={"count": 12, "at": NOW.isoformat()}))
    session.flush()
    goals.set_targets(session, {"store_products": 24, "clicks": 0, "sales": 0, "commission_brl": 0, "posts": 0}, actor="x")
    m = {m["key"]: m for m in goals.progress(session, NOW)["metrics"]}["store_products"]
    assert m["current"] == 12 and m["pct"] == 50.0 and m["expected_pct"] == 100.0 and m["projection"] is None
    assert m["status"] == "atrasada"  # a meta de vitrine vale desde já, não proporcional ao dia do mês


def test_period_pace_splits_the_monthly_goal_by_days(session):
    from datetime import datetime

    from core.services import agent_goals as g

    g.set_targets(session, {"sales": 30, "commission_brl": 300}, actor="t")
    now = datetime(2026, 10, 14, 12, 0).astimezone()  # quarta-feira, mês de 31 dias
    periods = {p["key"]: p for p in g.progress(session, now)["periods"]}
    assert list(periods) == ["day", "week", "fortnight", "month"]
    sales = {k: next(m for m in p["metrics"] if m["key"] == "sales") for k, p in periods.items()}
    assert sales["day"]["target"] == 0.97 and sales["week"]["target"] == 6.77 and sales["fortnight"]["target"] == 14.52
    assert sales["month"]["target"] == 30
    assert periods["week"]["start"].startswith("2026-10-12") and periods["fortnight"]["start"].startswith("2026-10-01")
    assert all(m["key"] != "store_products" for m in periods["day"]["metrics"])  # vitrine é estado, não se reparte
