"""Plano de verba e de campanhas: total, divisão Meta/Google/marketplaces e a lista de marketplaces com campanha."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.db  # noqa: F401
from core.db import Base
from core.services import ads_budget, ads_plan


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s
    engine.dispose()


def _payload(**over):
    base = {"total_weekly_brl": "150", "meta_pct": 60, "google_pct": 30, "marketplace_pct": 10,
            "marketplaces": [{"slug": "shopee", "enabled": True, "weekly_brl": "80", "own_ads_weekly_brl": "10"},
                             {"slug": "aliexpress", "enabled": True}, {"slug": "mercado_livre", "enabled": False, "weekly_brl": "30"}]}
    base.update(over)
    return base


def test_saving_the_plan_fills_the_budget_card_the_guards_read(session):
    plan = ads_plan.save(session, _payload())
    assert (plan["meta_brl"], plan["google_brl"], plan["marketplace_ads_brl"]) == (90.0, 45.0, 15.0)
    meta, google = ads_budget.load(session, "meta"), ads_budget.load(session, "google")
    assert (meta.weekly_brl, meta.daily_cap_brl, google.weekly_brl, google.daily_cap_brl) == (90.0, 27.0, 45.0, 14.0)
    assert ads_budget.marketplace_allowed(session, "shopee") and ads_budget.marketplace_allowed(session, "aliexpress")
    assert not ads_budget.marketplace_allowed(session, "mercado_livre") and not ads_budget.marketplace_allowed(session, "amazon")
    assert ads_budget.load_marketplace(session, "shopee") == (80.0, 24.0)  # teto por dia padrão: 30% da semana
    assert ads_budget.load_marketplace(session, "aliexpress") is None  # na lista, sem teto próprio
    assert ads_budget.load_marketplace(session, "mercado_livre") is None  # fora da lista: o teto digitado é descartado
    by = {m["slug"]: m for m in plan["marketplaces"]}
    assert by["shopee"]["enabled"] and by["shopee"]["own_ads_weekly_brl"] == 10.0 and not by["mercado_livre"]["enabled"]


def test_a_platform_with_zero_share_gets_no_budget_and_the_split_must_sum_100(session):
    plan = ads_plan.save(session, _payload(meta_pct=100, google_pct=0, marketplace_pct=0, marketplaces=[{"slug": "shopee", "enabled": True}]))
    assert plan["google_brl"] == 0 and ads_budget.load(session, "google") is None and ads_budget.load(session, "meta").weekly_brl == 150.0
    with pytest.raises(ads_plan.PlanError, match="somar 100"):
        ads_plan.save(session, _payload(meta_pct=50))


def test_caps_cannot_exceed_the_paid_budget_and_own_ads_cannot_exceed_its_share(session):
    with pytest.raises(ads_plan.PlanError, match="passa da verba de Meta"):
        ads_plan.save(session, _payload(marketplaces=[{"slug": "shopee", "enabled": True, "weekly_brl": "999"}]))
    with pytest.raises(ads_plan.PlanError, match="propaganda dentro dos marketplaces"):
        ads_plan.save(session, _payload(marketplaces=[{"slug": "shopee", "enabled": True, "own_ads_weekly_brl": "40"}]))
    with pytest.raises(ads_plan.PlanError, match="desconhecido"):
        ads_plan.save(session, _payload(marketplaces=[{"slug": "banca_do_ze", "enabled": True}]))


def test_reading_without_a_saved_plan_does_not_create_one(session):
    plan = ads_plan.read(session)
    assert plan["total_weekly_brl"] == 0 and not any(m["enabled"] for m in plan["marketplaces"])
    assert {m["slug"] for m in plan["marketplaces"]} >= {"shopee", "aliexpress", "mercado_livre", "amazon"}
