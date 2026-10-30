"""Triagem de produtos antes de gastar com anúncio: procura, demanda, prazo e conta do anúncio.

Trava os pareceres (aprovado_pago, so_organico, reprovado), a conta de empate do anúncio, a regra de prazo de 10 dias, a trava que impede
anúncio pago sem parecer recente e o balanço periódico.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.db  # noqa: F401
from core.db import Base
from core.db.ads import AdCampaign
from core.db.base import ConnectorKind, Marketplace
from core.db.catalog import Product, SourceRecord
from core.db.storefront import StorefrontItem
from core.db.vetting import ProductVetting
from core.services import product_vetting as pv

NOW = datetime.now(UTC)


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s
    engine.dispose()


def _product(session, n=1, *, price=50.0, pct=7.0, sold=3000, rating=4.8, mp=Marketplace.SHOPEE, attrs=None, title="Afiador de facas magnético"):
    src = SourceRecord(marketplace=mp, connector="x", connector_kind=ConnectorKind.OFFICIAL_API, endpoint="x", external_id=f"p{n}", collected_at=NOW)
    session.add(src)
    session.flush()
    p = Product(marketplace=mp, external_id=f"p{n}", title=title, price=price, affiliate_commission_pct=pct, sold_quantity=sold, rating=rating,
                attributes=attrs, source_record_id=src.id, first_seen_at=NOW, last_seen_at=NOW)
    session.add(p)
    session.flush()
    return p


def M(volume=5000, cpc=0.5, trend="stable", growth=0.0):
    return SimpleNamespace(monthly_volume=volume, cpc_brl=cpc, trend_direction=trend, growth_pct_30d=growth)


def test_good_demand_and_a_closing_ad_math_is_approved_for_paid(session):
    p = _product(session, price=100.0)  # comissão R$ 7 contra CPC R$ 0,20: empata com 2,9% dos cliques virando venda
    v = pv.vet(session, p.id, keyword="afiador de facas", metrics=M(cpc=0.2))
    assert v.verdict == "aprovado_pago" and v.breakeven_conversion == pytest.approx(0.029, abs=0.001) and v.commission_per_sale_brl == 7.0


def test_cheap_item_with_a_normal_cpc_sells_but_does_not_justify_paid_ads(session):
    p = _product(session, price=15.0)  # comissão R$ 1,05 contra CPC R$ 0,50 = 48% de conversão para empatar
    v = pv.vet(session, p.id, keyword="x", metrics=M())
    assert v.verdict == "so_organico" and any("não fecha" in r for r in v.reasons)


def test_no_search_demand_or_falling_search_or_low_rating_is_rejected(session):
    assert pv.vet(session, _product(session, 1, sold=20).id, keyword="x", metrics=M(volume=10)).verdict == "reprovado"
    assert pv.vet(session, _product(session, 2).id, keyword="x", metrics=M(trend="falling", growth=-59.0)).verdict == "reprovado"
    assert pv.vet(session, _product(session, 3, rating=3.6).id, keyword="x", metrics=M()).verdict == "reprovado"


def test_delivery_over_10_days_is_rejected_and_unknown_blocks_paid_on_aliexpress(session):
    slow = _product(session, 1, price=100.0, attrs={"delivery_days": 18})
    assert pv.vet(session, slow.id, keyword="x", metrics=M(cpc=0.2)).verdict == "reprovado"
    ali = _product(session, 2, price=100.0, mp=Marketplace.ALIEXPRESS)
    v = pv.vet(session, ali.id, keyword="x", metrics=M(cpc=0.2))
    assert v.verdict == "so_organico" and any("prazo de entrega não confirmado" in r for r in v.reasons)
    fast = _product(session, 3, price=100.0, mp=Marketplace.ALIEXPRESS, attrs={"delivery_days": 7, "ship_from": "BR"})
    assert pv.vet(session, fast.id, keyword="x", metrics=M(cpc=0.2)).verdict == "aprovado_pago"


def test_the_gate_blocks_paid_ads_without_a_fresh_approved_vetting(session, monkeypatch):
    monkeypatch.setattr(pv, "GATE_ENABLED", True)
    p = _product(session, price=100.0)
    with pytest.raises(pv.VettingError, match="ainda não passou pela triagem"):
        pv.require_paid_ok(session, p.id)
    v = pv.vet(session, p.id, keyword="x", metrics=M(cpc=0.2))
    pv.require_paid_ok(session, p.id)  # aprovado e recente: passa
    with pytest.raises(pv.VettingError, match="vale 45"):
        pv.require_paid_ok(session, p.id, now=NOW + timedelta(days=60))
    v.verdict = "so_organico"
    with pytest.raises(pv.VettingError, match="só divulgação orgânica"):
        pv.require_paid_ok(session, p.id)


def test_vet_due_picks_the_stale_and_never_seen_and_reuses_the_last_keyword(session):
    a, b = _product(session, 1), _product(session, 2, title="Porta ovos geladeira")
    for p in (a, b):
        session.add(StorefrontItem(product_id=p.id, highlight=False, hidden=False, position=0))
    session.flush()
    pv.vet(session, a.id, keyword="afiador de facas", metrics=M())
    session.query(ProductVetting).update({"created_at": NOW - timedelta(days=10)})
    asked = []

    def analyzer(kws):
        asked.extend(kws)
        return {k: M() for k in kws}

    rows = pv.vet_due(session, limit=5, analyzer=analyzer)
    assert {r.product_id for r in rows} == {a.id, b.id}
    assert "afiador de facas" in asked  # reaproveita a palavra-chave que o agente escolheu
    assert pv.vet_due(session, limit=5, analyzer=analyzer) == []  # acabou de triar: nada vencido


def test_review_lists_ads_running_without_backing(session):
    p = _product(session, price=15.0)
    pv.vet(session, p.id, keyword="x", metrics=M())
    session.add(AdCampaign(product_id=p.id, platform="meta", status="active", spent_brl=12.0))
    session.flush()
    r = pv.review(session, "monthly")
    assert r["by_verdict"] == {"so_organico": 1} and r["ads_without_backing"][0]["verdict"] == "so_organico"
    with pytest.raises(pv.VettingError):
        pv.review(session, "yearly")


def test_keyword_is_derived_from_the_useful_words_of_the_title():
    assert pv.derive_keyword("Afiador de Faca Magnético 3 Peças (kit novo)") == "afiador faca magnético"


def test_operator_test_authorization_releases_paid_ads_for_14_days_and_survives_a_new_vetting(session, monkeypatch):
    monkeypatch.setattr(pv, "GATE_ENABLED", True)
    p = _product(session, price=15.0)
    pv.vet(session, p.id, keyword="x", metrics=M())  # so_organico
    with pytest.raises(pv.VettingError, match="só divulgação orgânica"):
        pv.require_paid_ok(session, p.id)
    row = pv.authorize_test(session, p.id, actor="operador")
    assert row.verdict == pv.TEST_VERDICT and any("autorizado pelo operador" in r for r in row.reasons)
    pv.require_paid_ok(session, p.id)
    pv.vet(session, p.id, keyword="x", metrics=M())  # triagem nova não revoga
    pv.require_paid_ok(session, p.id)
    with pytest.raises(pv.VettingError):
        pv.require_paid_ok(session, p.id, now=NOW + timedelta(days=15))  # venceu
    session.add(AdCampaign(product_id=p.id, platform="meta", status="active", spent_brl=1.0))
    session.flush()
    r = pv.review(session, "weekly")
    assert r["ads_without_backing"] == [] and r["paid_tests_authorized"][0]["product_id"] == p.id


def test_authorization_is_refused_for_rejected_products(session):
    p = _product(session, sold=20)
    pv.vet(session, p.id, keyword="x", metrics=M(volume=10))
    with pytest.raises(pv.VettingError, match="reprovado"):
        pv.authorize_test(session, p.id, actor="operador")
