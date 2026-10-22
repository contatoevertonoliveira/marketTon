"""Administração pelo agente Claude: interruptor, trava na API e comissão aprendida.

O que os testes travam:

* o modo agente nasce DESLIGADO, e só quem tem `users.manage` o altera;
* com ele desligado, o agente (papel BOT) só consulta: toda escrita é recusada
  **pela API**, não pela tela nem pelo servidor MCP;
* o agente nunca alcança credenciais nem usuários, com o modo ligado ou não;
* a comissão observada só preenche o que está vazio e nunca sobrescreve valor da API.
"""
from __future__ import annotations

import os

os.environ["AUTH_ENABLED"] = "true"
os.environ["JWT_SECRET_KEY"] = "test-secret-for-http-auth-tests"

from contextlib import asynccontextmanager  # noqa: E402
from datetime import UTC, datetime  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import core.db  # noqa: E402, F401
import core.db.support  # noqa: E402, F401
from core.db import Base  # noqa: E402
from core.db.auth import Role  # noqa: E402
from core.db.base import ConnectorKind, Marketplace  # noqa: E402
from core.db.catalog import Product, SourceRecord  # noqa: E402
from core.services.auth import create_user  # noqa: E402
from core.services.commission_learning import SOURCE, apply_commissions, propose_commissions  # noqa: E402
from core.services.sales_ingestion import ingest_sales  # noqa: E402
from integrations.marketplaces.base import SalesRecord  # noqa: E402

PASSWORD = "SenhaDeTeste2026"
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


@asynccontextmanager
async def _noop_lifespan(app):  # noqa: ANN001, ARG001
    yield


@pytest.fixture
def factory():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def api(factory):
    from backend import deps
    from backend.main import app

    def override_session():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[deps.get_session] = override_session
    app.router.lifespan_context = _noop_lifespan
    setup = factory()
    create_user(setup, username="dono", password=PASSWORD, role=Role.ADMIN)
    create_user(setup, username="agente", password=PASSWORD, role=Role.BOT)
    create_user(setup, username="leitor", password=PASSWORD, role=Role.VIEWER)
    setup.commit()
    setup.close()
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _as(client, username):
    token = client.post("/auth/login", json={"username": username, "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# --- interruptor ---------------------------------------------------------------


def test_agent_mode_defaults_to_off_and_only_admin_changes_it(api):
    admin, agent, viewer = _as(api, "dono"), _as(api, "agente"), _as(api, "leitor")
    assert api.get("/agent/mode", headers=agent).json()["enabled"] is False

    assert api.put("/agent/mode", json={"enabled": True}, headers=viewer).status_code == 403
    assert api.put("/agent/mode", json={"enabled": True}, headers=agent).status_code == 403  # o agente não se liga sozinho

    on = api.put("/agent/mode", json={"enabled": True}, headers=admin)
    assert on.status_code == 200 and on.json()["enabled"] is True and on.json()["updated_by"] == "dono"
    assert api.get("/agent/mode", headers=viewer).json()["enabled"] is True

    api.put("/agent/mode", json={"enabled": False}, headers=admin)
    assert api.get("/agent/mode", headers=agent).json()["enabled"] is False


def test_mode_changes_are_audited(api):
    admin = _as(api, "dono")
    api.put("/agent/mode", json={"enabled": True}, headers=admin)
    actions = [(a["action"], a["detail"]) for a in api.get("/auth/audit", headers=admin).json()]
    assert ("agent.mode_changed", "ligado") in actions


def test_generate_access_creates_a_bot_user_and_rotation_invalidates_the_old_password(api):
    admin = _as(api, "dono")
    assert api.get("/agent/mode", headers=admin).json()["agent_user_exists"] is False
    assert api.post("/agent/access", headers=_as(api, "leitor")).status_code == 403
    assert api.post("/agent/access", headers=_as(api, "agente")).status_code == 403  # o agente não se dá acesso

    first = api.post("/agent/access", headers=admin).json()
    assert first["username"] == "claude_agent" and first["rotated"] is False and len(first["password"]) >= 20
    login = api.post("/auth/login", json={"username": "claude_agent", "password": first["password"]})
    assert login.status_code == 200

    mode = api.get("/agent/mode", headers=admin).json()
    assert mode["agent_user_exists"] is True and mode["agent_last_login_at"]  # "Claude conectado"

    second = api.post("/agent/access", headers=admin).json()
    assert second["rotated"] is True and second["password"] != first["password"]
    assert api.post("/auth/login", json={"username": "claude_agent", "password": first["password"]}).status_code == 401
    # O usuário gerado é um agente de verdade: consulta, e escrita só com o modo ligado.
    headers = {"Authorization": "Bearer " + api.post(
        "/auth/login", json={"username": "claude_agent", "password": second["password"]}).json()["access_token"]}
    assert api.get("/catalog/products", headers=headers).status_code == 200
    assert api.post("/portfolio/items", json={"product_id": 1}, headers=headers).status_code == 403


def test_generate_access_refuses_to_hijack_a_non_agent_account(api, factory):
    session = factory()
    create_user(session, username="claude_agent", password=PASSWORD, role=Role.VIEWER)
    session.commit()
    session.close()
    assert api.post("/agent/access", headers=_as(api, "dono")).status_code == 409


# --- trava na API ----------------------------------------------------------------


def test_agent_can_read_but_not_write_while_mode_is_off(api):
    agent = _as(api, "agente")
    assert api.get("/catalog/products", headers=agent).status_code == 200
    assert api.get("/portfolio/items", headers=agent).status_code == 200
    assert api.get("/agent/checklist", headers=agent).status_code == 200

    blocked = api.post("/portfolio/items", json={"product_id": 1}, headers=agent)
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["agent_mode"] is False
    assert "modo agente desligado" in blocked.json()["detail"]["message"]
    assert api.post("/agent/commissions/apply", headers=agent).status_code == 403


def test_agent_can_write_once_the_mode_is_on(api):
    api.put("/agent/mode", json={"enabled": True}, headers=_as(api, "dono"))
    agent = _as(api, "agente")
    # Produto inexistente: 404 prova que a trava deixou passar (com ela seria 403).
    assert api.post("/portfolio/items", json={"product_id": 9999}, headers=agent).status_code == 404
    assert api.post("/agent/commissions/apply", headers=agent).status_code == 200


def test_agent_never_reaches_credentials_or_users_even_with_mode_on(api):
    api.put("/agent/mode", json={"enabled": True}, headers=_as(api, "dono"))
    agent = _as(api, "agente")
    for path in ("/marketplaces/credentials", "/integrations/services", "/auth/users", "/auth/audit"):
        r = api.get(path, headers=agent)
        assert r.status_code == 403, path
        assert r.json()["detail"].get("agent_mode") is None  # negado por permissão, não pelo modo
    assert api.put("/integrations/services/google_ads", json={"values": {"client_id": "x"}}, headers=agent).status_code == 403


def test_human_roles_are_not_affected_by_the_agent_switch(api):
    admin = _as(api, "dono")
    api.put("/agent/mode", json={"enabled": False}, headers=admin)
    assert api.post("/portfolio/items", json={"product_id": 9999}, headers=admin).status_code == 404  # passou pela trava


def test_checklist_flags_missing_marketplace_on_empty_system(api):
    items = api.get("/agent/checklist", headers=_as(api, "agente")).json()["items"]
    assert items and items[0]["severity"] == "alta" and items[0]["key"] == "no_marketplace"
    status = api.get("/agent/status", headers=_as(api, "agente")).json()
    assert status["agent_mode"]["enabled"] is False
    assert all("values" not in i for i in status["integrations"])  # nenhum segredo no status


# --- comissão aprendida -----------------------------------------------------------


def _product(session, external_id, pct=None, attributes=None, title="Garrafa"):
    source = SourceRecord(
        marketplace=Marketplace.SHOPEE, connector="shopee", connector_kind=ConnectorKind.OFFICIAL_API,
        endpoint="x", external_id=external_id, collected_at=NOW,
    )
    session.add(source)
    session.flush()
    product = Product(
        marketplace=Marketplace.SHOPEE, external_id=external_id, title=title, price=100.0,
        affiliate_commission_pct=pct, attributes=attributes, source_record_id=source.id,
        first_seen_at=NOW, last_seen_at=NOW,
    )
    session.add(product)
    session.flush()
    return product


def _sale(order, item, gross, *, conf=None, est=None, status="COMPLETED"):
    return SalesRecord(
        external_order_id=f"{order}:{item}", occurred_at=NOW, quantity=1, currency="BRL", gross_amount=gross,
        product_external_id=item, product_title="Garrafa", status=status,
        commission_confirmed=conf, commission_estimated=est,
    )


def test_observed_rate_fills_a_product_with_no_commission(session):
    product = _product(session, "111")
    ingest_sales(session, [_sale("A", "111", 100.0, conf=12.0), _sale("B", "111", 50.0, conf=6.0)], Marketplace.SHOPEE)

    (proposal,) = propose_commissions(session)
    assert proposal.proposed_pct == 12.0 and proposal.sales_count == 2 and proposal.basis == "confirmed"
    assert proposal.confidence == "media"

    assert apply_commissions(session, [proposal]) == 1
    assert product.affiliate_commission_pct == 12.0
    assert product.attributes["commission_source"] == SOURCE and product.attributes["commission_sample_sales"] == 2


def test_never_overwrites_a_commission_that_came_from_the_api_or_the_operator(session):
    _product(session, "222", pct=8.0)  # veio da API / tabela / digitado
    ingest_sales(session, [_sale("A", "222", 100.0, conf=20.0)], Marketplace.SHOPEE)
    assert propose_commissions(session) == []


def test_cancelled_sales_and_missing_amounts_are_ignored_and_confirmed_beats_estimated(session):
    _product(session, "333")
    ingest_sales(
        session,
        [
            _sale("A", "333", 100.0, conf=10.0),
            _sale("B", "333", 900.0, est=900.0, status="CANCELLED"),  # cancelada: não conta
            _sale("C", "333", 100.0, est=14.0, status="PENDING"),  # estimada: entra, mas rebaixa a base
        ],
        Marketplace.SHOPEE,
    )
    (proposal,) = propose_commissions(session)
    assert proposal.sales_count == 2 and proposal.proposed_pct == 12.0  # (10 + 14) / (100 + 100)
    assert proposal.basis == "mixed"


def test_a_learned_rate_is_refreshed_by_new_sales_but_stays_labelled(session):
    product = _product(session, "444")
    ingest_sales(session, [_sale("A", "444", 100.0, conf=10.0)], Marketplace.SHOPEE)
    apply_commissions(session, propose_commissions(session))
    assert product.affiliate_commission_pct == 10.0 and propose_commissions(session) == []  # nada novo

    ingest_sales(session, [_sale("B", "444", 100.0, conf=20.0)], Marketplace.SHOPEE)
    (proposal,) = propose_commissions(session)
    assert proposal.current_pct == 10.0 and proposal.proposed_pct == 15.0  # (10 + 20) / 200
    apply_commissions(session, [proposal])
    assert product.affiliate_commission_pct == 15.0 and product.attributes["commission_sample_sales"] == 2


def test_min_sales_and_confidence(session):
    _product(session, "555")
    ingest_sales(session, [_sale("A", "555", 100.0, conf=9.0)], Marketplace.SHOPEE)
    (one,) = propose_commissions(session)
    assert one.confidence == "baixa"
    assert propose_commissions(session, min_sales=2) == []


def test_ingestion_keeps_the_learned_marker_when_attributes_are_replaced(session):
    from core.services.ingestion import _apply_product_fields
    from integrations.marketplaces.base import ConnectorProduct

    product = _product(session, "666")
    ingest_sales(session, [_sale("A", "666", 100.0, conf=11.0)], Marketplace.SHOPEE)
    apply_commissions(session, propose_commissions(session))

    item = ConnectorProduct(external_id="666", title="Garrafa", attributes={"shop": "x"})
    _apply_product_fields(product, item)
    assert product.affiliate_commission_pct == 11.0  # coleta sem comissão não apaga
    assert product.attributes["shop"] == "x" and product.attributes["commission_source"] == SOURCE

    # Se a coleta trouxer comissão própria, ela vale e a marca de "aprendida" some.
    api_item = ConnectorProduct(external_id="666", title="Garrafa",
                                affiliate_commission_pct=7.0, attributes={"shop": "x"})
    _apply_product_fields(product, api_item)
    assert product.affiliate_commission_pct == 7.0 and "commission_source" not in product.attributes


# --- servidor MCP, ponta a ponta (cliente -> API real, sem rede) -----------------------


class _Resp:
    """Faz a resposta do TestClient (httpx) parecer a do `requests`, que o cliente MCP usa."""

    def __init__(self, r):
        self._r = r
        self.status_code, self.ok, self.reason, self.text = r.status_code, r.is_success, r.reason_phrase, r.text

    def json(self):
        return self._r.json()


@pytest.fixture
def mcp_tools(api, monkeypatch):
    from mcp_server import client as client_module
    from mcp_server import server

    def request(method, url, params=None, json=None, headers=None, timeout=None):
        return _Resp(api.request(method, url.replace("http://t", ""), params=params, json=json, headers=headers))

    def post(url, json=None, timeout=None):
        return request("POST", url, json=json)

    monkeypatch.setattr(client_module.requests, "request", request)
    monkeypatch.setattr(client_module.requests, "post", post)
    monkeypatch.setattr(server, "_client", client_module.MarkettonClient("http://t", "agente", PASSWORD))
    return server


def test_mcp_exposes_exactly_the_intended_tools():
    import asyncio

    from mcp_server import server

    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert names == {
        "marketton_status", "marketton_checklist", "list_products", "get_product", "product_funnel",
        "search_opportunities", "trending_abroad", "sales_performance", "list_portfolio", "commission_proposals",
        "daily_review", "add_to_portfolio", "move_portfolio_item", "set_manual_signals", "apply_observed_commissions",
    }
    # Nada de credenciais, usuários ou anúncios: o agente só tem o que a API do portfólio oferece.
    assert not any(w in n for n in names for w in ("credential", "user", "password", "ads_", "campaign"))


def test_mcp_read_tools_work_with_the_mode_off(api, mcp_tools):
    status = mcp_tools.marketton_status()
    assert status["agent_mode"]["enabled"] is False
    review = mcp_tools.daily_review()
    assert {"status", "checklist", "commissions_to_learn", "sales_by_marketplace"} <= set(review)
    assert mcp_tools.list_products() == []


def test_mcp_write_tool_explains_when_the_mode_is_off_and_works_when_on(api, mcp_tools):
    off = mcp_tools.add_to_portfolio(9999)
    assert off["ok"] is False and off["agent_mode"] == "desligado" and "ativar" in off["message"]

    api.put("/agent/mode", json={"enabled": True}, headers=_as(api, "dono"))
    on = mcp_tools.add_to_portfolio(9999)
    assert on["ok"] is False and on["status"] == 404  # passou pela trava; o produto é que não existe


def test_mcp_reports_missing_credentials_clearly(monkeypatch):
    from mcp_server import client as client_module
    from mcp_server import server

    monkeypatch.setattr(server, "_client", client_module.MarkettonClient("http://t", "", ""))
    out = server.marketton_status()
    assert out["ok"] is False and "MARKETTON_AGENT_USER" in out["message"]


def test_mcp_reports_an_unreachable_backend_in_plain_words(monkeypatch):
    import requests

    from mcp_server import client as client_module
    from mcp_server import server

    def boom(*args, **kwargs):
        raise requests.ConnectionError("recusada")

    monkeypatch.setattr(client_module.requests, "post", boom)
    monkeypatch.setattr(server, "_client", client_module.MarkettonClient("http://t", "agente", PASSWORD))
    out = server.marketton_status()
    assert out["ok"] is False and "backend está no ar" in out["message"]
