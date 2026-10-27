"""Histórico gerencial dos criativos: produto ligado, anúncios com métricas e resultados do produto desde o criativo."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.db.base import ConnectorKind, Marketplace
from core.db.catalog import Product, SourceRecord
from core.db.creatives import CreativeCampaign
from core.db.tracking import AffiliateLink, ClickEvent, Commission, Sale
from core.services import creative_history as ch

NOW = datetime.now(UTC)


@pytest.fixture
def setup(session):
    source = SourceRecord(marketplace=Marketplace.SHOPEE, connector="shopee", connector_kind=ConnectorKind.OFFICIAL_API, endpoint="x",
                          external_id="p", collected_at=NOW)
    session.add(source)
    session.flush()
    product = Product(marketplace=Marketplace.SHOPEE, external_id="p1", title="Garrafa Térmica", price=50.0, source_record_id=source.id,
                      first_seen_at=NOW, last_seen_at=NOW, images=["https://x.com/a.jpg"])
    session.add(product)
    session.flush()
    link = AffiliateLink(product_id=product.id, marketplace=Marketplace.SHOPEE, channel="vitrine", destination_url="https://x.com/a",
                         affiliate_url="https://felixsystems.com.br/r/abc", short_code="abc")
    session.add(link)
    creative = CreativeCampaign(product_id=product.id, external_ref="mural-p1-s1", campaign_id="cmp_1", mode="sandbox", status="completed",
                                quality="economy", budget_usd=2.0, cost_usd=0.5, created_by="claude_agent",
                                manifest={"deliverables": [{"id": "d1", "kind": "copy", "status": "ready", "content": {"caption": "x"}}]})
    session.add(creative)
    session.flush()
    creative.created_at = NOW - timedelta(days=2)
    return product, link, creative


def test_history_links_creative_product_pieces_ads_and_results_since_creation(session, setup):
    product, link, creative = setup
    session.add(ClickEvent(affiliate_link_id=link.id, occurred_at=NOW - timedelta(days=1), external_click_id="c1"))
    session.add(ClickEvent(affiliate_link_id=link.id, occurred_at=NOW - timedelta(days=5), external_click_id="c2"))  # antes do criativo: fora
    sale = Sale(product_id=product.id, marketplace=Marketplace.SHOPEE, external_order_id="o1", occurred_at=NOW - timedelta(hours=5), status="COMPLETED", quantity=1)
    cancelled = Sale(product_id=product.id, marketplace=Marketplace.SHOPEE, external_order_id="o2", occurred_at=NOW, status="CANCELLED", quantity=1)
    session.add_all([sale, cancelled])
    session.flush()
    session.add(Commission(sale_id=sale.id, marketplace=Marketplace.SHOPEE, confirmed_amount=9.35))
    ad = ch.create_ad(session, creative.id, actor="claude_agent", variant="A", daily_budget_brl=5)
    ch.update_ad(session, ad.id, status="active", spent_brl=12.5, impressions=2000, clicks=50)

    h = ch.history(session)
    item = h["items"][0]
    assert item["product"]["title"] == "Garrafa Térmica" and item["mode"] == "sandbox" and item["cost_usd"] == 0.5
    assert item["deliverables"][0]["content"]["caption"] == "x"
    assert item["product_results"] == {"store_clicks": 1, "sales": 1, "commission_brl": 9.35}  # só depois do criativo, sem cancelada
    a = item["ads"][0]
    assert (a["status"], a["spent_brl"], a["impressions"], a["clicks"], a["ctr_pct"], a["cpc_brl"]) == ("active", 12.5, 2000, 50, 2.5, 0.25)
    assert h["totals"] == {"creatives": 1, "cost_usd": 0.5, "ads": 1, "active_ads": 1, "spent_brl": 12.5}


def test_missing_metrics_stay_none_not_zero(session, setup):
    _, _, creative = setup
    ad = ch.create_ad(session, creative.id, actor="x")
    out = ch.ad_out(ad)
    assert out["status"] == "draft" and out["spent_brl"] is None and out["ctr_pct"] is None and out["cpc_brl"] is None
    ch.update_ad(session, ad.id, impressions=100)
    assert ch.ad_out(ad)["ctr_pct"] is None  # sem cliques informados não existe CTR


def test_invalid_ad_data_is_rejected(session, setup):
    _, _, creative = setup
    with pytest.raises(ch.AdError, match="não encontrado"):
        ch.create_ad(session, 999, actor="x")
    with pytest.raises(ch.AdError, match="status inválido"):
        ch.create_ad(session, creative.id, actor="x", status="voando")
    ad = ch.create_ad(session, creative.id, actor="x")
    with pytest.raises(ch.AdError, match="negativo"):
        ch.update_ad(session, ad.id, spent_brl=-1)
    with pytest.raises(ch.AdError, match="passar das impressões"):
        ch.update_ad(session, ad.id, impressions=10, clicks=20)


def test_hidden_creatives_and_removed_ads_leave_the_screen(session, setup):
    from core.db.ads import AdCampaign

    product, _, creative = setup
    session.add_all([AdCampaign(creative_campaign_id=creative.id, product_id=product.id, platform="meta", status="paused"),
                     AdCampaign(creative_campaign_id=creative.id, product_id=product.id, platform="meta", status="removed")])
    session.flush()
    item = ch.history(session)["items"][0]
    assert [a["status"] for a in item["ads"]] == ["paused"]  # o removido não aparece
    creative.hidden = True
    session.flush()
    assert ch.history(session)["items"] == []  # criativo excluído da tela
