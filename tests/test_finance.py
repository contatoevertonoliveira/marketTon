"""Painel financeiro: números do período, comissão confirmada x pendente, cancelamentos fora, gasto com anúncios e carteiras.

O que os testes travam:

* pendente (estimada) e confirmada nunca se misturam; venda cancelada não conta;
* o gasto com anúncios sai dos anúncios criados no período e o resultado é comissão − gasto;
* saldo de carteira só entra no total se foi informado; o saldo atual é o lançamento mais recente e o histórico vira série;
* carteira desconhecida, saldo inválido e data no futuro são recusados.
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
from core.db.base import Marketplace
from core.db.tracking import Commission, Sale
from core.services import finance as fin

NOW = datetime.now(UTC).replace(hour=15, minute=0, second=0, microsecond=0)


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s
    engine.dispose()


def _sale(session, order, days_ago, *, status="APPROVED", confirmed=None, estimated=None, gross=100.0, mp=Marketplace.SHOPEE):
    sale = Sale(marketplace=mp, external_order_id=order, occurred_at=NOW - timedelta(days=days_ago), gross_amount=gross, status=status)
    session.add(sale)
    session.flush()
    session.add(Commission(sale_id=sale.id, marketplace=mp, estimated_amount=estimated, confirmed_amount=confirmed))
    session.flush()
    return sale


def test_overview_splits_confirmed_from_pending_and_ignores_cancelled(session):
    _sale(session, "a", 1, confirmed=12.0, estimated=10.0)
    _sale(session, "b", 2, estimated=8.0)  # pendente
    _sale(session, "c", 2, status="CANCELLED", estimated=50.0)  # não conta
    _sale(session, "d", 40, confirmed=30.0)  # fora do período de 30 dias (entra só no anterior)
    d = fin.overview(session, days=30, now=NOW)
    k = d["kpis"]
    assert (k["sales"], k["confirmed_brl"], k["pending_brl"], k["commission_brl"]) == (2, 12.0, 8.0, 20.0)
    assert k["previous_commission_brl"] == 30.0 and k["commission_change_pct"] == -33.3
    assert len(d["series"]) == 30 and d["series"][-1]["cumulative_brl"] == 20.0
    assert d["by_platform"][0]["label"] == "Shopee" and d["by_platform"][0]["sales"] == 2


def test_ads_spend_and_result(session):
    _sale(session, "a", 1, confirmed=20.0)
    session.add_all([AdCampaign(platform="meta", status="active", spent_brl=7.5), AdCampaign(platform="meta", status="paused", spent_brl=None)])
    session.flush()
    k = fin.overview(session, days=7, now=NOW)["kpis"]
    assert k["ads_spent_brl"] == 7.5 and k["result_brl"] == 12.5


def test_wallets_total_counts_only_informed_and_series_follows_history(session):
    assert fin.wallets(session)["total_brl"] == 0 and fin.wallets(session)["known"] == 0
    fin.set_wallet(session, "shopee", 100, actor="op", as_of=NOW - timedelta(days=5))
    fin.set_wallet(session, "monetizze", 50.5, actor="op", as_of=NOW - timedelta(days=2))
    fin.set_wallet(session, "shopee", 130, actor="op", as_of=NOW - timedelta(days=1), note="após saque")  # o mais recente vale
    w = fin.wallets(session)
    by = {i["platform"]: i for i in w["items"]}
    assert w["total_brl"] == 180.5 and w["known"] == 2 and by["shopee"]["balance_brl"] == 130 and by["eduzz"]["balance_brl"] is None
    series = {p["date"]: p["total_brl"] for p in fin.overview(session, days=7, now=NOW)["wallet_series"]}
    days = sorted(series)
    assert series[days[0]] is None  # antes do primeiro lançamento
    assert series[days[-1]] == 180.5 and 100 in series.values() and 150.5 in series.values()


def test_wallet_input_is_validated(session):
    with pytest.raises(fin.FinanceError, match="carteira desconhecida"):
        fin.set_wallet(session, "banco-x", 10, actor="op")
    with pytest.raises(fin.FinanceError, match="saldo inválido"):
        fin.set_wallet(session, "shopee", True, actor="op")
    with pytest.raises(fin.FinanceError, match="futuro"):
        fin.set_wallet(session, "shopee", 10, actor="op", as_of=datetime.now(UTC) + timedelta(days=3))
