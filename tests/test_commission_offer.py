"""Comissão Extra do vendedor: guarda o prazo da oferta e avisa quando a taxa não é confiável.

A API da Shopee devolve `sellerCommissionRate` e o período (`periodStartTime`/`periodEndTime`, em segundos). Comissão
extra é de campanha: expirada, sem prazo ou prestes a acabar, ela não pode virar plano de conteúdo sem aviso.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.routers import catalog
from core.db.base import ConnectorKind, Marketplace
from core.db.catalog import Product, SourceRecord
from core.services.keyword_metrics import KeywordMetrics
from core.services.commission_offer import offer_info, offer_note
from integrations.marketplaces.shopee import ShopeeAdapter, ShopeeConfig, _epoch_iso

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


def _attrs(extra=50.0, starts=None, ends=None):
    return {"seller_commission_pct": extra, "offer_starts_at": starts and starts.isoformat(), "offer_ends_at": ends and ends.isoformat()}


def test_adapter_stores_the_offer_period_from_epoch_seconds():
    node = {"itemId": 1, "productName": "Copo", "commissionRate": "0.83", "sellerCommissionRate": "0.80",
            "priceMin": "40", "periodStartTime": 1792000000, "periodEndTime": 1793000000}
    product = ShopeeAdapter(cfg=ShopeeConfig())._normalize_offer(node)
    assert product.attributes["seller_commission_pct"] == pytest.approx(80.0)
    assert product.attributes["offer_starts_at"].startswith("2026-10-14") and product.attributes["offer_ends_at"].startswith("2026-10-26")
    assert _epoch_iso(1793000000000) == _epoch_iso(1793000000)  # milissegundos também
    assert _epoch_iso(32503651199) is None  # a Shopee usa o ano 2999 para "sem data de término"
    assert _epoch_iso(0) is None and _epoch_iso(None) is None and _epoch_iso("x") is None  # nunca inventa prazo

    bare = ShopeeAdapter(cfg=ShopeeConfig())._normalize_offer({"itemId": 2, "productName": "x", "sellerCommissionRate": "0.1"})
    assert bare.attributes["offer_ends_at"] is None


def test_status_follows_the_period():
    assert offer_info({}, NOW) is None and offer_info({"seller_commission_pct": 0}, NOW) is None  # sem comissão extra
    day = timedelta(days=1)
    assert offer_info(_attrs(starts=NOW - 5 * day, ends=NOW + 20 * day), NOW)["status"] == "ativa"
    soon = offer_info(_attrs(starts=NOW - 5 * day, ends=NOW + 2 * day), NOW)
    assert soon["status"] == "acabando" and soon["days_left"] == 2
    assert offer_info(_attrs(starts=NOW - 9 * day, ends=NOW - day), NOW)["status"] == "expirada"
    assert offer_info(_attrs(starts=NOW + 3 * day, ends=NOW + 9 * day), NOW)["status"] == "futura"
    open_ended = offer_info(_attrs(starts=NOW - 5 * day), NOW)  # começou e não tem fim marcado (caso comum na API real)
    assert open_ended["status"] == "sem_fim" and open_ended["days_left"] is None and offer_note(open_ended) is None
    assert offer_info(_attrs(), NOW)["status"] == "sem_prazo"  # catálogo antigo: diz que não sabe, não chuta


def test_note_warns_unless_the_offer_is_comfortably_active():
    day = timedelta(days=1)
    assert offer_note(offer_info(_attrs(starts=NOW - day, ends=NOW + 20 * day), NOW)) is None
    assert offer_note(None) is None
    expired = offer_note(offer_info(_attrs(80.0, ends=NOW - day), NOW))
    assert "acabou em 21/10/2026" in expired and "Confira no portal" in expired
    assert "acaba em" in offer_note(offer_info(_attrs(ends=NOW + 2 * day), NOW))
    assert "recolha o catálogo" in offer_note(offer_info(_attrs(), NOW))


@pytest.fixture
def product(session):
    source = SourceRecord(marketplace=Marketplace.SHOPEE, connector="shopee", connector_kind=ConnectorKind.OFFICIAL_API,
                          endpoint="x", external_id="p1", collected_at=NOW)
    session.add(source)
    session.flush()
    item = Product(marketplace=Marketplace.SHOPEE, external_id="p1", title="Copo Térmico Inox 500ml", price=50.0,
                   affiliate_commission_pct=81.5, source_record_id=source.id, first_seen_at=NOW, last_seen_at=NOW,
                   attributes=_attrs(80.0, ends=datetime.now(UTC) - timedelta(days=2)))
    session.add(item)
    session.flush()
    return item


def test_funnel_endpoint_carries_the_offer_and_the_warning(session, product, monkeypatch):
    monkeypatch.setattr(catalog, "planner_volumes", lambda c: {})
    monkeypatch.setattr(catalog, "planner_provider", lambda: None)
    monkeypatch.setattr(catalog, "analyze_keywords", lambda terms: [KeywordMetrics(keyword=terms[0])])
    out = catalog.product_funnel(product.id, keyword=None, conversion_pct=1.5, session=session)
    assert out.commission_offer["status"] == "expirada" and out.commission_offer["extra_pct"] == 80.0
    assert "Confira no portal" in out.commission_note
