"""Funil de venda do produto (Trends + Google Ads + economia da comissão).

O que os testes travam:

* dado ausente é `unknown` e não reprova: "sem dado" ≠ "ruim";
* o teto de CPC é comissão por venda × conversão, e a premissa aparece no texto;
* poucos critérios com dado => "insufficient", nunca um veredito;
* a palavra-chave sugerida ignora medidas, códigos e palavras vazias.
"""
from __future__ import annotations

import pytest

from core.services.keyword_metrics import KeywordMetrics
from core.services.product_funnel import commission_per_sale, compute_funnel, suggest_candidates, suggest_keyword


def _m(**kw) -> KeywordMetrics:
    return KeywordMetrics(keyword="x", **kw)


def _funnel(metrics, **kw):
    base = dict(price=100.0, commission_pct=10.0, commission_fixed=None, sold_quantity=None, ranking_position=None)
    base.update(kw)
    return compute_funnel(metrics=metrics, **base)


def _status(funnel, key):
    return next(c.status for c in funnel.checks if c.key == key)


def test_suggest_keyword_drops_noise_codes_and_stopwords():
    assert suggest_keyword("Fone de Ouvido Bluetooth Sem Fio TWS i12 5.3 - Frete Grátis") == "fone ouvido bluetooth"
    assert suggest_keyword("Kit 3 Garrafas Térmicas 500ml Inox") == "garrafas térmicas inox"
    assert suggest_keyword("") is None and suggest_keyword(None) is None
    assert suggest_keyword("123 45 de da") is None


def test_candidates_go_from_short_to_specific_and_dedupe():
    assert suggest_candidates("Lanterna Tática Profissional Recarregável LED Alta Potência") == [
        "lanterna tática", "lanterna tática profissional", "lanterna tática profissional recarregável"]
    assert suggest_candidates("Lanterna") == ["lanterna"]
    assert suggest_candidates("Fonte Carregador") == ["fonte carregador"]  # só há uma de 2 palavras
    assert suggest_candidates("123") == []


def test_commission_per_sale_prefers_percentage_then_fixed():
    assert commission_per_sale(200.0, 12.5, None) == 25.0
    assert commission_per_sale(None, None, 3.0) == 3.0
    assert commission_per_sale(None, 10.0, None) is None


def test_cpc_ceiling_is_commission_times_conversion_and_is_explained():
    f = _funnel(_m(cpc_brl=1.0, trend_direction="rising", growth_pct_30d=10.0, monthly_volume=5000, competition="LOW"),
                conversion_pct=2.0)
    assert f.commission_per_sale == 10.0 and f.breakeven_cpc == 0.2  # R$ 10 × 2%
    cpc = next(c for c in f.checks if c.key == "cpc")
    assert cpc.status == "fail" and "2%" in cpc.detail and "0,20" in cpc.detail


def test_good_funnel_when_most_known_criteria_pass():
    f = _funnel(
        _m(trend_direction="rising", growth_pct_30d=40.0, monthly_volume=9000, cpc_brl=0.10, competition="MEDIUM"),
        sold_quantity=50,
    )
    assert f.verdict == "good"
    assert all(c.status == "pass" for c in f.checks)


def test_weak_funnel_names_what_failed():
    f = _funnel(_m(trend_direction="falling", growth_pct_30d=-30.0, monthly_volume=200, cpc_brl=5.0, competition="HIGH"))
    assert f.verdict == "weak"
    assert "volume" not in f.summary.lower() or "Não passa" in f.summary
    assert "Não passa" in f.summary


def test_strong_demand_with_expensive_ads_is_good_for_organic_but_not_for_paid():
    """Comissão pequena perto do CPC não pode reprovar quem divulga sem pagar clique."""
    f = _funnel(
        _m(trend_direction="rising", growth_pct_30d=30.0, monthly_volume=18000, cpc_brl=1.5, competition="HIGH"),
        sold_quantity=40,
    )
    assert f.demand_verdict == "good" and f.verdict == "good"
    assert f.ads_verdict == "weak"
    assert "Demanda promissora" in f.summary and "tráfego pago não compensa" in f.summary


def test_ads_verdict_is_insufficient_without_google_ads_but_demand_still_judged():
    f = _funnel(_m(trend_direction="rising", growth_pct_30d=30.0), sold_quantity=40)
    assert f.demand_verdict == "uncertain" or f.demand_verdict == "good"
    assert f.ads_verdict == "insufficient" and "tráfego pago sem dado" in f.summary


def test_missing_data_is_unknown_not_failure():
    f = _funnel(_m(trend_direction="rising", growth_pct_30d=12.0))  # sem Google Ads, sem vendas
    assert _status(f, "volume") == "unknown" and _status(f, "cpc") == "unknown"
    assert _status(f, "ad_competition") == "unknown" and _status(f, "marketplace_demand") == "unknown"
    # Só 1 critério com dado: não dá veredito, e o texto diz por quê.
    assert f.verdict == "insufficient" and "insuficientes" in f.summary


def test_no_commission_means_cpc_unknown_even_with_cpc():
    f = _funnel(_m(cpc_brl=0.5, trend_direction="stable", monthly_volume=3000, competition="LOW"),
                commission_pct=None)
    assert f.commission_per_sale is None and f.breakeven_cpc is None
    assert _status(f, "cpc") == "unknown"


def test_trend_without_series_is_unknown_with_reason():
    f = _funnel(_m(trend_error="série curta ou vazia no Google Trends"))
    trend = next(c for c in f.checks if c.key == "trend")
    assert trend.status == "unknown" and "série curta" in trend.detail


def test_ranking_counts_as_marketplace_demand():
    f = _funnel(_m(trend_direction="stable"), ranking_position=3)
    assert _status(f, "marketplace_demand") == "pass"


# --- endpoint ------------------------------------------------------------------


@pytest.fixture
def api(monkeypatch):
    from backend.routers import catalog

    fake = _m(trend_direction="rising", growth_pct_30d=20.0,
              monthly_volume=8000, cpc_brl=0.15, competition="MEDIUM", planner_source="google_ads")
    calls = []
    monkeypatch.setattr(catalog, "analyze_keywords", lambda terms: calls.append(terms) or [fake])
    monkeypatch.setattr(catalog, "planner_provider", lambda: "google_ads")
    # Volumes medidos das candidatas: a mais curta é a mais buscada.
    monkeypatch.setattr(catalog, "planner_volumes", lambda cands: {"garrafa térmica": 9000, "garrafa térmica inox": 1200})
    return catalog, calls


def test_endpoint_uses_title_keyword_then_manual_override(session, product, api):
    catalog, calls = api
    product.title = "Garrafa Térmica Inox 1L Original"
    product.affiliate_commission_pct = 10.0
    product.price = 100.0
    session.flush()

    auto = catalog.product_funnel(product.id, keyword=None, conversion_pct=1.5, session=session)
    # Entre as candidatas, fica a de maior volume (9.000 > 1.200).
    assert calls[-1] == ["garrafa térmica"] and auto.keyword_source == "title"
    assert auto.candidates == [
        {"keyword": "garrafa térmica", "monthly_volume": 9000},
        {"keyword": "garrafa térmica inox", "monthly_volume": 1200},
    ]
    assert auto.commission_per_sale == 10.0 and auto.breakeven_cpc == 0.15
    assert auto.planner_provider == "google_ads"
    assert next(c.status for c in auto.checks if c.key == "cpc") == "pass"  # 0,15 <= 0,15

    manual = catalog.product_funnel(product.id, keyword="  copo térmico ", conversion_pct=1.5, session=session)
    assert calls[-1] == ["copo térmico"] and manual.keyword_source == "manual"


def test_without_volumes_falls_back_to_the_shortest_candidate(session, product, api, monkeypatch):
    catalog, calls = api
    monkeypatch.setattr(catalog, "planner_volumes", lambda cands: {})
    product.title = "Garrafa Térmica Inox 1L"
    session.flush()
    out = catalog.product_funnel(product.id, keyword=None, conversion_pct=1.5, session=session)
    assert calls[-1] == ["garrafa térmica"]
    assert all(c["monthly_volume"] is None for c in out.candidates)


def test_endpoint_404_and_untitled_product(session, product, api):
    from fastapi import HTTPException

    catalog, _ = api
    with pytest.raises(HTTPException) as exc:
        catalog.product_funnel(99999, keyword=None, conversion_pct=1.5, session=session)
    assert exc.value.status_code == 404

    product.title = "123 45"
    session.flush()
    out = catalog.product_funnel(product.id, keyword=None, conversion_pct=1.5, session=session)
    assert out.verdict == "insufficient" and out.keyword is None
