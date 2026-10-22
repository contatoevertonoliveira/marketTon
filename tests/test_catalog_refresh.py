"""Atualização do catálogo pelo agente: elegibilidade, intervalo mínimo, uma por vez e falha sem travar.

O que os testes travam:

* só marketplaces configurados entram; Hotmart/Eduzz (sem catálogo para afiliar) ficam de fora com motivo;
* o intervalo mínimo de 6 h por marketplace é respeitado, e só o operador pode forçar;
* uma atualização por vez; um registro "em andamento" velho (processo que caiu) não bloqueia para sempre;
* se a coleta falha, nada é marcado como atualizado e dá para tentar de novo, e o chat recebe o aviso.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import core.services.catalog_refresh as cr
from core.db.agent_chat import AgentMessage


class _Adapter:
    def __init__(self, configured=True):
        self._configured = configured

    def is_configured(self):
        return self._configured


ADAPTERS = {
    "shopee": _Adapter(), "mercado_livre": _Adapter(), "amazon": _Adapter(False),
    "hotmart": _Adapter(), "eduzz": _Adapter(), "monetizze": _Adapter(),
}


@pytest.fixture(autouse=True)
def _same_session(session, monkeypatch):
    """A thread de coleta abre `session_scope()`; nos testes ela usa a sessão do teste."""

    @contextmanager
    def scope():
        yield session
        session.flush()

    monkeypatch.setattr(cr, "session_scope", scope)


def _hunter(calls, ok=True, boom=None):
    def run(memory, *, session, adapters, options):
        calls.append(options)
        if boom:
            raise boom
        return SimpleNamespace(ok=ok, summary="12 produtos novos, 40 atualizados", artifacts={"collect_errors": []})

    return run


def test_plan_picks_only_configured_catalog_marketplaces_and_explains_the_rest(session):
    chosen, skipped = cr.plan(session, ADAPTERS, marketplaces=None, force=False)
    assert chosen == ["shopee", "mercado_livre", "monetizze"]
    assert "sem credencial" in skipped["amazon"]
    assert "catálogo de produtos para afiliar" in skipped["hotmart"] and "eduzz" in skipped
    only, _ = cr.plan(session, ADAPTERS, marketplaces=["shopee"], force=False)
    assert only == ["shopee"]


def test_a_refresh_runs_the_hunter_with_the_requested_keywords_and_reports_in_the_chat(session):
    calls = []
    out = cr.start_refresh(session, ADAPTERS, marketplaces=["shopee"], keywords=["lanterna tática"], limit=500,
                           hunter=_hunter(calls), background=False)

    assert out["started"] is True and out["marketplaces"] == ["shopee"]
    (options,) = calls
    assert options.adapter_names == ["shopee"] and options.keywords == ["lanterna tática"]
    assert options.use_ai is False and options.max_items_per_adapter == 100  # limite travado em 100

    st = cr.status(session)
    assert st["running"] is False and st["ok"] is True and "12 produtos novos" in st["summary"]
    assert "shopee" in st["last_by_marketplace"]
    (message,) = session.scalars(select(AgentMessage)).all()
    assert message.author == "system" and message.kind == "message" and "Catálogo atualizado" in message.text


def test_minimum_interval_blocks_a_second_request_until_forced(session):
    cr.start_refresh(session, ADAPTERS, marketplaces=["shopee"], hunter=_hunter([]), background=False)

    again = cr.start_refresh(session, ADAPTERS, marketplaces=["shopee"], hunter=_hunter([]), background=False)
    assert again["started"] is False and "atualizado há pouco" in again["skipped"]["shopee"]

    calls = []
    forced = cr.start_refresh(session, ADAPTERS, marketplaces=["shopee"], force=True, hunter=_hunter(calls), background=False)
    assert forced["started"] is True and len(calls) == 1  # o operador pode forçar

    # Outro marketplace não é afetado pelo intervalo do primeiro.
    other = cr.start_refresh(session, ADAPTERS, marketplaces=["mercado_livre"], hunter=_hunter([]), background=False)
    assert other["started"] is True


def test_only_one_refresh_at_a_time_and_a_stale_running_mark_does_not_block_forever(session):
    cr._save_state(session, {"running": True, "started_at": datetime.now(UTC).isoformat()})
    busy = cr.start_refresh(session, ADAPTERS, hunter=_hunter([]), background=False)
    assert busy["started"] is False and "em andamento" in busy["reason"]

    cr._save_state(session, {"running": True, "started_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat()})
    assert cr.status(session)["running"] is False  # processo que caiu: não vale
    assert cr.start_refresh(session, ADAPTERS, marketplaces=["shopee"], hunter=_hunter([]), background=False)["started"] is True


def test_a_failed_collection_marks_nothing_as_fresh_and_allows_an_immediate_retry(session):
    out = cr.start_refresh(session, ADAPTERS, marketplaces=["shopee"], hunter=_hunter([], boom=RuntimeError("API fora")), background=False)
    assert out["started"] is True
    st = cr.status(session)
    assert st["ok"] is False and "API fora" in st["summary"] and st["running"] is False
    assert "shopee" not in st.get("last_by_marketplace", {})  # não conta como atualizado

    alert = session.scalars(select(AgentMessage).where(AgentMessage.kind == "alert")).one()
    assert "não terminou bem" in alert.text

    retry = cr.start_refresh(session, ADAPTERS, marketplaces=["shopee"], hunter=_hunter([]), background=False)
    assert retry["started"] is True  # sem esperar 6 h depois de uma falha


def test_nothing_eligible_says_why_instead_of_starting(session):
    out = cr.start_refresh(session, ADAPTERS, marketplaces=["hotmart", "amazon"], hunter=_hunter([]), background=False)
    assert out["started"] is False and set(out["skipped"]) == {"hotmart", "amazon"}

