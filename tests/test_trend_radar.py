"""Radar de tendências: retrato diário por palavra, crescimento em 7/15/30 dias, "começou a subir" e a lista de vigilância.

O Google Trends e o Planejador são simulados. O que os testes travam:

* crescimento = média dos últimos N dias sobre a dos N anteriores; série curta vira `None`, nunca zero;
* "em alta" exige alta no mês (ou forte na semana com a quinzena subindo) e volume mínimo quando o volume é conhecido;
* só chega ao agente quem COMEÇOU a subir desde o último retrato; quem já estava em alta não repete;
* o scan roda no máximo uma vez a cada 20 h, olha as palavras mais antigas primeiro, e a lista de vigilância tem teto de 40.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.db  # noqa: F401
from core.db import Base
from core.db.trend_radar import TrendSnapshot
from core.services import trend_radar as tr

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s
    engine.dispose()


def _frame(values):
    end = pd.Timestamp("2026-10-26")
    dates = [end - pd.Timedelta(days=len(values) - 1 - i) for i in range(len(values))]
    return pd.DataFrame({"date": dates, "interest": values})


class _Series:
    def __init__(self, frame):
        self.frame = frame


@pytest.fixture
def trends(monkeypatch):
    data = {}
    monkeypatch.setattr(tr, "fetch_keyword_interest", lambda k, geo="BR", window_days=90: _Series(data[k]))
    monkeypatch.setattr(tr.keyword_metrics, "planner_provider", lambda: "google_ads")
    monkeypatch.setattr(tr.keyword_metrics, "_planner_metrics", lambda kws: (
        {k: {"search_volume": 1000, "competition": "HIGH", "cpc": 0.5, "currency": "BRL"} for k in kws}, "google_ads", None))
    return data


def test_growth_compares_each_window_with_the_one_before():
    flat_then_up = _frame([10] * 60 + [20] * 30)  # 90 dias: os últimos 30 dobraram sobre os 30 anteriores
    assert tr._growth(flat_then_up, 30) == 100.0 and tr._growth(flat_then_up, 7) == 0.0
    assert tr._growth(_frame([5, 5, 5]), 30) is None  # série curta: sem número
    assert tr._growth(_frame([0] * 60 + [5] * 30), 30) is None  # período anterior zerado: sem número


def test_rising_needs_growth_and_minimum_volume():
    assert tr.is_rising(5, 10, 30, 500) and tr.is_rising(50, 10, 0, None)  # forte na semana com a quinzena subindo
    assert not tr.is_rising(5, 10, 30, 100)  # volume baixo demais
    assert not tr.is_rising(50, -5, 10, 900)  # semana forte mas a quinzena cai
    assert not tr.is_rising(None, None, None, 900)


def test_scan_stores_snapshots_once_per_20h_and_oldest_first(session, trends):
    tr.set_watch(session, add=["tênis running"], remove=[k for k in tr.get_watch(session) if k != "lanterna tática"], actor="t")
    assert tr.get_watch(session) == ["lanterna tática", "tênis running"]
    trends["lanterna tática"] = _frame([10] * 60 + [20] * 30)
    trends["tênis running"] = _frame([10] * 90)
    assert tr.scan(session, now=NOW) == 2
    assert tr.scan(session, now=NOW + timedelta(hours=5)) == 0  # cedo demais
    rows = {r["keyword"]: r for r in tr.status(session)["items"]}
    assert rows["lanterna tática"]["rising"] is True and rows["lanterna tática"]["growth_30d"] == 100.0 and rows["lanterna tática"]["monthly_volume"] == 1000
    assert rows["tênis running"]["rising"] is False
    assert tr.status(session, only_rising=True)["rising"] == 1 and [i["keyword"] for i in tr.status(session, only_rising=True)["items"]] == ["lanterna tática"]
    assert tr.scan(session, now=NOW + timedelta(hours=21), max_keywords=1) == 1  # a rotação pega a palavra mais antiga


def test_only_words_that_started_rising_reach_the_agent(session, trends):
    tr.set_watch(session, add=[], remove=[k for k in tr.get_watch(session) if k != "garrafa térmica"], actor="t")
    trends["garrafa térmica"] = _frame([10] * 90)
    tr.scan(session, now=NOW)
    assert tr.new_rising(session, NOW - timedelta(hours=1)) == []  # não sobe
    trends["garrafa térmica"] = _frame([10] * 60 + [20] * 30)
    tr.scan(session, now=NOW + timedelta(days=1))
    news = tr.new_rising(session, NOW + timedelta(hours=1))
    assert [n["keyword"] for n in news] == ["garrafa térmica"]
    tr.scan(session, now=NOW + timedelta(days=2))  # continua subindo: já foi avisado
    assert tr.new_rising(session, NOW + timedelta(days=1, hours=12)) == []


def test_digest_makes_a_check_notable_when_something_starts_rising(session, trends):
    from core.services import agent_monitor

    tr.set_watch(session, add=[], remove=[k for k in tr.get_watch(session) if k != "lanterna tática"], actor="t")
    trends["lanterna tática"] = _frame([10] * 60 + [20] * 30)
    since = datetime.now(UTC) - timedelta(hours=1)
    tr.scan(session, now=datetime.now(UTC))
    d = agent_monitor.digest(session, since)
    assert d["notable"] is True and "lanterna tática" in d["radar"][0] and "tendências começando a subir" in agent_monitor.digest_text(d)


def test_watch_list_is_capped_and_validated(session):
    with pytest.raises(tr.RadarError):
        tr.set_watch(session, add=["ab"], actor="t")
    with pytest.raises(tr.RadarError, match="comporta"):
        tr.set_watch(session, add=[f"produto numero {i}" for i in range(45)], actor="t")
