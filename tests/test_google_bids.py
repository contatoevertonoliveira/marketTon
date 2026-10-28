"""Lance máximo por clique das campanhas do Google: estimativa, sugestão automática e a mesma trava de teto de R$ 5 da criação.

O Google é simulado (`GoogleAdsClient.mutate/search`). O que os testes travam:

* a sugestão vem do 3º quartil das estimativas por palavra, com folga, em múltiplos de R$ 0,05 e nunca acima do teto;
* sem estimativa (pouco volume) não há sugestão e o modo automático não mexe na campanha;
* trocar o lance atualiza só `cpc_bid_micros` do grupo de anúncios; acima de R$ 5, abaixo de R$ 0,01 ou campanha encerrada é recusado antes do Google.
"""
from __future__ import annotations

import pytest

from core.db.ads import AdCampaign
from core.services import google_campaigns as gc
from core.services.meta_campaigns import AdsError
from tests.test_google_campaigns import _cards, _product, google, session  # noqa: F401


def test_suggest_bid_uses_the_upper_quartile_with_margin_and_the_cap():
    assert gc.suggest_bid([1.10, 0.81, 0.82, 0.11, 1.43]) == 1.30  # p75 = 1,10 × 1,15 = 1,265 → R$ 1,30
    assert gc.suggest_bid([2.30, 2.50, 4.80]) == 4.20  # p75 = 3,65 × 1,15 = 4,1975 → R$ 4,20
    assert gc.suggest_bid([9.0, 9.5]) == gc.MAX_CPC_LIMIT  # nunca passa do teto
    assert gc.suggest_bid([0.01]) == gc.BID_MIN
    assert gc.suggest_bid([]) is None and gc.suggest_bid([None, 0]) is None


def _ad(session, status="paused", adset="333"):
    p = _product(session)
    ad = AdCampaign(creative_campaign_id=None, product_id=p.id, platform="google", status=status, daily_budget_brl=4.0, duration_days=3,
                    external_campaign_id="222", external_adset_id=adset, created_by="t")
    session.add(ad)
    session.flush()
    return ad


def _rows(google, estimates):
    def search(self, q):
        if "FROM ad_group " in q:
            return [{"campaign": {"id": "222"}, "adGroup": {"id": "333", "cpcBidMicros": "800000"}}]
        if "FROM ad_group_criterion" in q:
            return [{"campaign": {"id": "222"}, "adGroupCriterion": {"keyword": {"text": f"k{i}"}, "positionEstimates": {"firstPageCpcMicros": str(int(v * 1e6)), "topOfPageCpcMicros": str(int(v * 1e6))}}}
                    for i, v in enumerate(estimates)]
        return [{"campaign": {"id": "222"}, "metrics": {"searchRankLostImpressionShare": 0.9}}]
    from integrations.google_ads import GoogleAdsClient
    return search, GoogleAdsClient


def test_overview_shows_current_entry_and_suggested_bid(session, google, monkeypatch):
    _cards(session)
    _ad(session)
    search, cls = _rows(google, [1.10, 0.81, 0.82, 0.11, 1.43])
    monkeypatch.setattr(cls, "search", search)
    [row] = gc.bid_overview(session)
    assert row["current_bid_brl"] == 0.8 and row["entry_bid_brl"] == 0.82 and row["min_word_bid_brl"] == 0.11
    assert row["suggested_bid_brl"] == 1.30 and row["rank_lost_pct"] == 90 and row["has_estimate"]


def test_set_bid_updates_only_the_ad_group_bid_and_respects_the_cap(session, google):
    _cards(session)
    ad = _ad(session)
    r = gc.set_bid(session, ad.id, 1.5)
    assert r["max_cpc_brl"] == 1.5
    op = google.mutations[-1][0]["adGroupOperation"]
    assert op["update"] == {"resourceName": "customers/1/adGroups/333", "cpcBidMicros": "1500000"} and op["updateMask"] == "cpc_bid_micros"
    for bad in (5.01, 0, -1, "abc"):
        with pytest.raises(AdsError):
            gc.set_bid(session, ad.id, bad)
    assert len(google.mutations) == 1  # as recusas nem chegaram ao Google


def test_set_bid_refuses_ended_or_missing_campaigns(session, google):
    _cards(session)
    ad = _ad(session, status="ended")
    with pytest.raises(AdsError):
        gc.set_bid(session, ad.id, 1.0)
    with pytest.raises(AdsError):
        gc.set_bid(session, 9999, 1.0)
    assert google.mutations == []


def test_auto_applies_the_suggestion_and_skips_without_estimate(session, google, monkeypatch):
    _cards(session)
    ad = _ad(session)
    search, cls = _rows(google, [1.10, 0.81, 0.82, 0.11, 1.43])
    monkeypatch.setattr(cls, "search", search)
    [r] = gc.apply_suggested_bids(session)
    assert r["ad_id"] == ad.id and r["max_cpc_brl"] == 1.30 and r["from_brl"] == 0.8
    search, cls = _rows(google, [])
    monkeypatch.setattr(cls, "search", search)
    [r] = gc.apply_suggested_bids(session)
    assert "skipped" in r and len(google.mutations) == 1
