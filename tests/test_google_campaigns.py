"""Campanhas de Pesquisa no Google: sempre pausadas, textos validados, orçamento único com a Meta, ligar só pelo operador.

O Google é simulado (`GoogleAdsClient.mutate/search`). O que os testes travam:

* `dry_run` não chama o Google; a campanha real nasce `PAUSED` (campanha, orçamento, grupo, palavras e anúncio numa chamada só);
* textos fora das regras (título > 30, "!" em título, promessas como "grátis") são recusados antes de qualquer chamada;
* o teto por dia e o valor da semana valem para Meta + Google juntos;
* ligar define `ENABLED` com data final pela duração; pausar volta a `PAUSED`; métricas vêm do Google, nunca estimadas.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.db  # noqa: F401
from core.db import Base
from core.db.ads import AdCampaign
from core.db.base import ConnectorKind, Marketplace
from core.db.catalog import Product, SourceRecord
from core.db.service_credentials import ServiceCredential
from core.services import ads_manager
from core.services import google_campaigns as gc
from integrations.google_ads import GoogleAdsClient

NOW = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s
    engine.dispose()


@pytest.fixture
def google(monkeypatch):
    class G:
        mutations: list = []
        rows: list = []

    g = G()
    g.mutations, g.rows = [], []

    def mutate(self, operations):
        g.mutations.append(operations)
        kinds = [next(iter(op)) for op in operations]
        if "campaignBudgetOperation" in kinds:  # criação
            return [{"campaignBudgetResult": {"resourceName": "customers/1/campaignBudgets/11"}},
                    {"campaignResult": {"resourceName": "customers/1/campaigns/222"}},
                    {}, {},
                    {"adGroupResult": {"resourceName": "customers/1/adGroups/333"}},
                    {"adGroupAdResult": {"resourceName": "customers/1/adGroupAds/333~444"}}]
        return [{}]

    monkeypatch.setattr(GoogleAdsClient, "mutate", mutate)
    monkeypatch.setattr(GoogleAdsClient, "search", lambda self, q: g.rows)
    return g


def _cards(session, weekly="140", daily="30", products="3"):
    ok = {"last_check_status": "ok"}
    session.add_all([
        ServiceCredential(service="google_ads", enabled=True, values={"client_id": "c", "client_secret": "s", "refresh_token": "r", "customer_id": "1"}, **ok),
        ServiceCredential(service="ads_budget", enabled=True, values={"google_weekly_brl": weekly, "google_daily_cap_brl": daily,
                                                                       "google_max_products": products, "weekly_brl": "500", "daily_cap_brl": "100"}, **ok),
        ServiceCredential(service="storefront", enabled=True, values={"base_url": "https://x.com", "admin_token": "t",
                                                                       "public_url": "https://mural.felixsystems.com.br"}, **ok),
    ])
    session.flush()


def _product(session, n=1, title="Garrafa Térmica Infantil Canudo 500ml Quente ou Frio", affiliate="https://s.shopee.com.br/x"):
    source = SourceRecord(marketplace=Marketplace.SHOPEE, connector="shopee", connector_kind=ConnectorKind.OFFICIAL_API, endpoint="x",
                          external_id=f"p{n}", collected_at=NOW)
    session.add(source)
    session.flush()
    p = Product(marketplace=Marketplace.SHOPEE, external_id=f"p{n}", title=title, price=39.9, affiliate_url=affiliate, source_record_id=source.id,
                first_seen_at=NOW, last_seen_at=NOW)
    session.add(p)
    session.flush()
    return p


def test_dry_run_builds_a_valid_plan_and_calls_nothing(session, google):
    _cards(session)
    p = _product(session)
    out = gc.create_campaign(session, p.id, daily_brl=10, days=3, now=NOW)
    plan = out["plan"]
    assert out["dry_run"] is True and not google.mutations and session.query(AdCampaign).count() == 0
    assert 3 <= len(plan["headlines"]) <= 15 and all(len(h) <= 30 and "!" not in h for h in plan["headlines"])
    assert all(len(d) <= 90 and "…" not in d for d in plan["descriptions"]) and plan["keywords"] and "grátis" in plan["negative_keywords"]
    assert plan["link"].startswith(f"https://mural.felixsystems.com.br/p/p{p.id}?utm_source=google&utm_medium=cpc&utm_campaign=mural-g-")


def test_real_creation_is_paused_in_one_atomic_call(session, google):
    _cards(session)
    p = _product(session)
    out = gc.create_campaign(session, p.id, daily_brl=12.5, days=3, dry_run=False, actor="claude_agent", now=NOW)
    ops = google.mutations[0]
    created = {next(iter(o)): next(iter(o.values()))["create"] for o in ops}
    assert created["campaignBudgetOperation"]["amountMicros"] == "12500000"
    camp = created["campaignOperation"]
    assert camp["status"] == "PAUSED" and camp["advertisingChannelType"] == "SEARCH"
    assert camp["networkSettings"] == {"targetGoogleSearch": True, "targetSearchNetwork": False, "targetContentNetwork": False}
    assert created["adGroupOperation"]["cpcBidMicros"] == "1000000"
    assert any("negative" in str(o) for o in ops) and any("responsiveSearchAd" in str(o) for o in ops)
    ad = session.get(AdCampaign, out["ad_id"])
    assert (ad.platform, ad.status, ad.external_campaign_id, ad.external_adset_id, ad.external_ad_id) == ("google", "paused", "222", "333", "333~444")
    assert ad.creative_campaign_id is None and ad.daily_budget_brl == 12.5 and ad.created_by == "claude_agent"


def test_bad_copy_is_refused_before_calling_google(session, google):
    _cards(session)
    p = _product(session)
    cases = [(dict(headlines=["Um título bem maior do que trinta caracteres", "B", "C"]), "30"),
             (dict(headlines=["Compre agora!", "Outro", "Mais um"]), "!"),
             (dict(descriptions=["Entrega grátis para todo o Brasil", "Segunda descrição"]), "promete"),
             (dict(max_cpc_brl=9), "CPC")]
    for extra, msg in cases:
        with pytest.raises(gc.AdsError, match=msg):
            gc.create_campaign(session, p.id, daily_brl=10, days=3, now=NOW, **extra)
    assert not google.mutations


def test_budgets_are_separate_per_platform(session, google):
    _cards(session, weekly="100", daily="20")
    p, q = _product(session, 1), _product(session, 2, title="Outro produto")
    # a Meta já usa o dela inteiro: não pesa no Google
    session.add(AdCampaign(platform="meta", status="paused", daily_budget_brl=99, duration_days=1, product_id=q.id))
    session.flush()
    gc.create_campaign(session, p.id, daily_brl=15, days=4, dry_run=False)  # 60 na semana, 15/dia: cabe no Google (100 / 20)
    with pytest.raises(gc.AdsError, match="do Google"):
        gc.create_campaign(session, q.id, daily_brl=10, days=2)  # 15 + 10 > 20 por dia NO GOOGLE
    st = gc.budget_status(session, platform="google")
    assert st["daily_committed_brl"] == 15 and st["week_committed_brl"] == 60 and st["platform"] == "google"
    assert gc.budget_status(session, platform="meta")["daily_committed_brl"] == 99  # a Meta só enxerga os dela
    session.query(ServiceCredential).filter_by(service="google_ads").delete()
    session.query(AdCampaign).filter(AdCampaign.platform == "google").update({"status": "ended"})
    with pytest.raises(gc.AdsError, match="não está conectado"):
        gc.create_campaign(session, _product(session, 3, title="Terceiro").id, daily_brl=0.5, days=1, dry_run=False)


def test_google_without_its_own_budget_is_refused(session, google):
    _cards(session)
    row = session.query(ServiceCredential).filter_by(service="ads_budget").one()
    row.values = {"weekly_brl": "500", "daily_cap_brl": "100"}  # só a Meta tem orçamento
    session.flush()
    with pytest.raises(gc.AdsError, match="Orçamento de anúncios do Google"):
        gc.create_campaign(session, _product(session).id, daily_brl=5, days=1)


def test_activate_pause_and_metrics(session, google):
    _cards(session)
    p = _product(session)
    ad_id = gc.create_campaign(session, p.id, daily_brl=10, days=3, dry_run=False)["ad_id"]
    google.mutations.clear()
    ad = ads_manager.activate(session, ad_id, actor="dono", now=NOW)
    upd = google.mutations[0][0]["campaignOperation"]
    assert ad.status == "active" and upd["update"]["status"] == "ENABLED" and upd["updateMask"] == "status,endDate"
    assert upd["update"]["endDate"] == f"{(NOW.astimezone() + timedelta(days=2)):%Y-%m-%d}"  # 3 dias contando hoje
    google.rows = [{"campaign": {"id": "222", "status": "ENABLED"}, "metrics": {"costMicros": "4500000", "impressions": "300", "clicks": "12"}}]
    assert ads_manager.sync_metrics(session, now=NOW) == 1
    assert (ad.spent_brl, ad.impressions, ad.clicks, ad.meta_status) == (4.5, 300, 12, "ENABLED")
    assert ads_manager.pause(session, ad_id).status == "paused"
    assert google.mutations[-1][0]["campaignOperation"]["update"]["status"] == "PAUSED"
    with pytest.raises(gc.AdsError):
        ads_manager.activate(session, 9999, actor="dono")


def test_stop_and_remove_on_google(session, google):
    _cards(session)
    a = gc.create_campaign(session, _product(session, 1).id, daily_brl=5, days=3, dry_run=False)["ad_id"]
    b = gc.create_campaign(session, _product(session, 2, title="Outro produto aqui").id, daily_brl=5, days=3, dry_run=False)["ad_id"]
    ads_manager.activate(session, a, actor="dono", now=NOW)
    google.mutations.clear()
    assert ads_manager.stop(session, a, now=NOW).status == "ended"
    assert google.mutations[-1][0]["campaignOperation"]["update"]["status"] == "PAUSED"
    google.mutations.clear()
    assert ads_manager.remove(session, b).status == "removed"
    assert google.mutations[-1][0]["campaignOperation"]["remove"] == "customers/1/campaigns/222"  # operação própria de remoção
