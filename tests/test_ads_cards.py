"""Cartões de Integrações para anúncios: Meta (conferência somente leitura) e orçamento (travas de gasto)."""
from __future__ import annotations

import pytest

from backend.routers import services
from core.services import ads_budget, meta_ads


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body, self.ok = status, body if body is not None else {}, status < 400

    def json(self):
        return self._body


@pytest.fixture
def graph(monkeypatch):
    routes, calls = {}, []

    def get(url, params=None, timeout=None):
        calls.append((url, params))
        for fragment, resp in routes.items():
            if fragment in url:
                return resp
        raise AssertionError(f"chamada inesperada {url}")

    monkeypatch.setattr(meta_ads.requests, "get", get)
    return type("G", (), {"routes": routes, "calls": calls})


VALUES = {"access_token": "tok-secreto-xyz", "ad_account_id": "123456", "page_id": "999", "app_id": "11", "app_secret": "s"}


def test_meta_check_reports_token_permissions_account_and_page(graph):
    graph.routes.update({
        "/me": _Resp(200, {"id": "1", "name": "Agente Mural"}),
        "/debug_token": _Resp(200, {"data": {"is_valid": True, "scopes": ["ads_management", "ads_read", "pages_read_engagement", "x"]}}),
        "/act_123456": _Resp(200, {"name": "Mural Ads", "account_status": 1, "currency": "BRL"}),
        "/999": _Resp(200, {"name": "Mural na Web"}),
    })
    msg = meta_ads.check(VALUES)
    assert "Agente Mural" in msg and "permissões ok" in msg and "Mural Ads" in msg and "Mural na Web" in msg
    assert all(p.get("access_token") for _, p in graph.calls)  # o token vai em parâmetro, nunca montado na URL


def test_meta_check_fails_clearly(graph):
    graph.routes.update({"/me": _Resp(200, {"id": "1", "name": "x"}),
                         "/debug_token": _Resp(200, {"data": {"is_valid": True, "scopes": ["ads_read"]}})})
    with pytest.raises(meta_ads.MetaError, match="faltam permissões.*ads_management"):
        meta_ads.check(VALUES)
    graph.routes["/debug_token"] = _Resp(200, {"data": {"is_valid": False}})
    with pytest.raises(meta_ads.MetaError, match="não é mais válido"):
        meta_ads.check(VALUES)
    graph.routes.clear()
    graph.routes["/me"] = _Resp(400, {"error": {"code": 190, "message": "Invalid OAuth access token"}})
    with pytest.raises(meta_ads.MetaError, match="190"):
        meta_ads.check(VALUES)
    graph.routes.clear()
    graph.routes.update({"/me": _Resp(200, {"id": "1", "name": "x"}), "/act_123456": _Resp(200, {"name": "A", "account_status": 3, "currency": "BRL"})})
    with pytest.raises(meta_ads.MetaError, match="pendência de pagamento"):
        meta_ads.check({k: v for k, v in VALUES.items() if k not in ("app_id", "app_secret")})


def test_budget_rules_protect_against_nonsense():
    ok = ads_budget.parse({"weekly_brl": "R$ 150,00", "daily_cap_brl": "30"})
    assert (ok.weekly_brl, ok.daily_cap_brl, ok.max_products, ok.creatives_per_product, ok.approval_required) == (150.0, 30.0, 3, 2, True)
    for bad, msg in (({"weekly_brl": "100", "daily_cap_brl": "200"}, "não pode passar"), ({"weekly_brl": "700", "daily_cap_brl": "10"}, "baixo demais"),
                     ({"weekly_brl": "abc", "daily_cap_brl": "5"}, "número"), ({"weekly_brl": "100", "daily_cap_brl": "20", "max_products": "2,5"}, "inteiro")):
        with pytest.raises(ads_budget.BudgetError, match=msg):
            ads_budget.parse(bad)
    assert "pausada" in ads_budget.check({"weekly_brl": "150", "daily_cap_brl": "30"})


def test_cards_hide_secrets_and_the_budget_card_tests_numbers(session, graph):
    out = services.update_service("meta_ads", services.ServiceUpdate(values=VALUES), session)
    assert out.configured and out.help and "tok-secreto-xyz" not in out.model_dump_json() and out.icon == "📣"
    services.update_service("ads_budget", services.ServiceUpdate(values={"weekly_brl": "140", "daily_cap_brl": "25"}), session)
    assert services.test_service("ads_budget", session).last_check_status == "ok"
    assert ads_budget.load(session).weekly_brl == 140.0
    services.update_service("ads_budget", services.ServiceUpdate(values={"weekly_brl": "10", "daily_cap_brl": "50"}), session)
    assert services.test_service("ads_budget", session).last_check_status == "error" and ads_budget.load(session) is None
