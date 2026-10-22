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
        "agent_playbook", "chat_inbox", "chat_send", "request_resource", "complete_task", "system_health",
        "capabilities", "sync_sales", "refresh_catalog", "catalog_refresh_status",
        "create_tracked_link", "sync_clicks", "list_tracked_links",
        "storefront_status", "storefront_update_item", "storefront_publish", "goals_status",
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


# --- chat, ativação, capacidades, saúde e aviso de venda ---------------------------------------


def test_turning_the_mode_on_queues_the_activation_routine_once(api):
    admin, agent = _as(api, "dono"), _as(api, "agente")
    api.put("/agent/mode", json={"enabled": True}, headers=admin)
    api.put("/agent/mode", json={"enabled": True}, headers=admin)  # ligar de novo não duplica

    inbox = api.get("/agent/chat/inbox", headers=agent).json()
    tasks = [m for m in inbox["open_tasks"] if m["meta"]["task"] == "activation_routine"]
    assert len(tasks) == 1 and "rotina de ativação" in tasks[0]["text"]
    assert "sync_sales" in tasks[0]["text"] and "chat_send" in tasks[0]["text"]

    # Ler a caixa marca como lido; a tarefa continua aberta até o agente concluí-la.
    again = api.get("/agent/chat/inbox", headers=agent).json()
    assert again["unread"] == [] and len(again["open_tasks"]) == 1
    done = api.patch(f"/agent/chat/{tasks[0]['id']}", json={"status": "done"}, headers=agent)
    assert done.status_code == 200 and done.json()["status"] == "done"
    assert api.get("/agent/chat/inbox", headers=agent).json()["open_tasks"] == []

    api.put("/agent/mode", json={"enabled": False}, headers=admin)
    texts = [m["text"] for m in api.get("/agent/chat", headers=admin).json()["messages"]]
    assert any("DESLIGADO" in t for t in texts)


def test_chat_author_comes_from_the_role_and_the_agent_cannot_forge_system_messages(api):
    admin, agent, viewer = _as(api, "dono"), _as(api, "agente"), _as(api, "leitor")

    assert api.post("/agent/chat", json={"text": "oi agente"}, headers=viewer).status_code == 403  # leitor não instrui o agente
    mine = api.post("/agent/chat", json={"text": "  analise o catálogo  "}, headers=admin).json()
    assert mine["author"] == "user" and mine["text"] == "analise o catálogo"
    assert api.post("/agent/chat", json={"text": "x", "kind": "alert"}, headers=admin).status_code == 422

    reply = api.post("/agent/chat", json={"text": "Feito."}, headers=agent).json()
    assert reply["author"] == "agent"  # mesmo que o corpo tentasse dizer outro autor
    for forged in ("alert", "task"):
        assert api.post("/agent/chat", json={"text": "x", "kind": forged}, headers=agent).status_code == 422
    assert api.post("/agent/chat", json={"text": "   "}, headers=admin).status_code == 422


def test_resource_requests_can_be_resolved_only_by_the_operator(api):
    admin, agent = _as(api, "dono"), _as(api, "agente")
    req = api.post("/agent/chat", json={"text": "Chave do AI Studio", "kind": "request",
                                        "meta": {"resource": "ai_studio_key"}}, headers=agent).json()
    assert req["status"] == "open"
    counts = api.get("/agent/chat", headers=admin).json()["counts"]
    assert counts["open_requests"] == 1 and counts["unread_for_user"] >= 1

    assert api.patch(f"/agent/chat/{req['id']}", json={"status": "done"}, headers=agent).status_code == 403
    assert api.patch(f"/agent/chat/{req['id']}", json={"status": "done"}, headers=admin).json()["status"] == "done"
    assert api.get("/agent/chat", headers=admin).json()["counts"]["open_requests"] == 0

    api.post("/agent/chat/read", headers=admin)
    assert api.get("/agent/chat", headers=admin).json()["counts"]["unread_for_user"] == 0
    assert api.get("/agent/chat", params={"after_id": req["id"]}, headers=admin).json()["messages"] == []


def test_capabilities_never_present_unbuilt_things_as_ready(api):
    data = api.get("/agent/capabilities", headers=_as(api, "agente")).json()
    by_key = {c["key"]: c for c in data["capabilities"]}
    for key in ("social_publishing", "ads_management", "meta_ads_library", "marketplace_kirvano"):
        assert by_key[key]["status"] == "nao_construido" and by_key[key]["needs"], key
    # Hotmart, Monetizze e Eduzz já têm adaptador: falta só o operador configurar as credenciais.
    for key in ("marketplace_hotmart", "marketplace_monetizze", "marketplace_eduzz"):
        assert by_key[key]["status"] == "configurar" and by_key[key]["needs"], key
    assert by_key["link_clicks"]["status"] == "configurar" and by_key["link_clicks"]["needs"]  # sem o encurtador configurado
    assert by_key["google_trends"]["status"] == "pronto"
    assert by_key["google_ads_keyword_planner"]["status"] == "configurar"  # sem credencial no banco de teste
    assert by_key["ai_creatives"]["status"] == "configurar" and any("AI_API_KEY" in n for n in by_key["ai_creatives"]["needs"])
    assert sum(data["summary"].values()) == len(data["capabilities"])


def test_health_reports_database_and_empty_catalog(api):
    health = api.get("/agent/health", headers=_as(api, "agente")).json()
    by_name = {c["name"]: c for c in health["checks"]}
    assert by_name["banco_de_dados"]["status"] == "ok"
    assert by_name["catalogo"]["status"] == "aviso" and "vazio" in by_name["catalogo"]["detail"]
    assert health["overall"] in ("aviso", "erro")


class _FakeShopee:
    def __init__(self, records):
        self.records = records

    def is_configured(self):
        return True

    def fetch_sales(self, since=None):
        return self.records


def test_sales_sync_alerts_only_for_new_sales_and_learns_commission(session):
    from core.db.agent_chat import AgentMessage
    from core.services.sales_sync import sync_sales

    product = _product(session, "777")
    first = [_sale("A", "777", 100.0, conf=10.0), _sale("B", "777", 50.0, est=5.0, status="PENDING")]

    out = sync_sales(session, {"shopee": _FakeShopee(first)})
    assert out["new_sales"] == 2 and out["marketplaces"][0]["commissions_learned"] == 1
    assert product.affiliate_commission_pct == 10.0
    alerts = session.query(AgentMessage).filter_by(kind="alert").all()
    assert len(alerts) == 2 and all(a.author == "system" for a in alerts)
    assert any("Nova venda na shopee" in a.text and "R$ 100,00" in a.text and "confirmada" in a.text for a in alerts)
    assert any("pendente" in a.text for a in alerts)

    # Rodar de novo com uma venda a mais: só a nova gera alerta.
    out2 = sync_sales(session, {"shopee": _FakeShopee(first + [_sale("C", "777", 80.0, conf=8.0)])})
    assert out2["new_sales"] == 1
    assert session.query(AgentMessage).filter_by(kind="alert").count() == 3


def test_sales_sync_skips_unconfigured_and_reports_errors_without_stopping(session):
    from core.services.sales_sync import sync_sales

    class Unconfigured:
        def is_configured(self):
            return False

    class Broken:
        def is_configured(self):
            return True

        def fetch_sales(self, since=None):
            raise RuntimeError("api fora do ar")

    out = sync_sales(session, {"amazon": Unconfigured(), "shopee": Broken()})
    by = {m["marketplace"]: m for m in out["marketplaces"]}
    assert by["amazon"]["skipped"] and by["shopee"]["error"] == "api fora do ar" and out["new_sales"] == 0


def test_sales_sync_endpoint_requires_the_mode_for_the_agent(api):
    agent = _as(api, "agente")
    assert api.post("/agent/sales/sync", headers=agent).status_code == 403
    api.put("/agent/mode", json={"enabled": True}, headers=_as(api, "dono"))
    assert api.post("/agent/sales/sync", headers=agent).status_code == 200


# --- calibragem, autonomia e cobrança diária ------------------------------------------------------


def _check(report, key):
    return next(c for c in report["checks"] if c["key"] == key)


def _agent_session(api):
    """Liga o modo agente e devolve (admin, agent) já autenticados."""
    admin, agent = _as(api, "dono"), _as(api, "agente")
    api.put("/agent/mode", json={"enabled": True}, headers=admin)
    return admin, agent


def test_calibration_before_any_activation(api):
    report = api.get("/agent/calibration", headers=_as(api, "dono")).json()
    assert report["stage"] == "sem_ativacao" and report["ready_for_independence"] is False
    # O agente não corrige a própria nota.
    assert api.get("/agent/calibration", headers=_as(api, "agente")).status_code == 403


def test_calibration_tracks_progress_and_blocks_release_until_the_activation_routine_is_done(api):
    admin, agent = _agent_session(api)
    first = api.get("/agent/calibration", headers=admin).json()
    assert first["stage"] == "em_andamento" and first["ready_for_independence"] is False
    assert _check(first, "relatorio")["status"] == "pendente"

    refused = api.put("/agent/autonomy", json={"level": "independent"}, headers=admin)
    assert refused.status_code == 409 and "calibragem" in refused.json()["detail"]["message"]
    assert api.get("/agent/mode", headers=admin).json()["autonomy"] == "supervised"

    # O agente faz a rotina: lê a caixa, pede os recursos que faltam, posta o relatório, conclui a tarefa.
    inbox = api.get("/agent/chat/inbox", headers=agent).json()
    task = inbox["open_tasks"][0]
    api.post("/agent/chat", json={"text": "Chave do AI Studio", "kind": "request", "meta": {"resource": "ai_studio_key"}}, headers=agent)
    api.post("/agent/chat", json={"text": "Relatório: catálogo vazio, sem produtos para escolher.", "kind": "report"}, headers=agent)
    api.patch(f"/agent/chat/{task['id']}", json={"status": "done"}, headers=agent)

    done = api.get("/agent/calibration", headers=admin).json()
    assert done["ready_for_independence"] is True and done["stage"] == "pronto_para_independente", done["summary"]

    released = api.put("/agent/autonomy", json={"level": "independent"}, headers=admin)
    assert released.status_code == 200 and released.json()["autonomy"] == "independent"
    assert api.get("/agent/mode", headers=agent).json()["autonomy"] == "independent"
    assert api.get("/agent/status", headers=agent).json()["agent_mode"]["autonomy"] == "independent"
    texts = [m["text"] for m in api.get("/agent/chat", headers=admin).json()["messages"]]
    assert any("LIBERADO" in t for t in texts)

    back = api.put("/agent/autonomy", json={"level": "supervised"}, headers=admin)
    assert back.json()["autonomy"] == "supervised"


def test_autonomy_is_admin_only_and_force_is_recorded(api):
    admin, agent = _agent_session(api)
    assert api.put("/agent/autonomy", json={"level": "independent", "force": True}, headers=agent).status_code == 403
    assert api.put("/agent/autonomy", json={"level": "talvez"}, headers=admin).status_code == 422
    forced = api.put("/agent/autonomy", json={"level": "independent", "force": True}, headers=admin)
    assert forced.status_code == 200
    audit = [a["detail"] for a in api.get("/auth/audit", headers=admin).json() if a["action"] == "agent.autonomy_changed"]
    assert any("forçado" in d for d in audit)


def test_calibration_fails_when_the_agent_does_not_ask_for_missing_resources_or_leaks_a_secret(api):
    admin, agent = _agent_session(api)
    task = api.get("/agent/chat/inbox", headers=agent).json()["open_tasks"][0]
    api.post("/agent/chat", json={"text": "Tudo certo. A senha é Xk29fQ8vLm3PzR7tYb1WcN5hD0sJ4aGu", "kind": "report"}, headers=agent)
    api.patch(f"/agent/chat/{task['id']}", json={"status": "done"}, headers=agent)

    report = api.get("/agent/calibration", headers=admin).json()
    assert report["ready_for_independence"] is False and report["stage"] == "ajustar"
    assert _check(report, "cobrou_recursos")["status"] == "falha"
    assert _check(report, "sem_segredos_no_chat")["status"] == "falha"


def test_blocked_write_attempts_are_audited_and_counted(api):
    admin = _as(api, "dono")
    agent = _as(api, "agente")
    api.put("/agent/mode", json={"enabled": True}, headers=admin)   # ativação
    api.put("/agent/mode", json={"enabled": False}, headers=admin)  # o operador desliga
    assert api.post("/portfolio/items", json={"product_id": 1}, headers=agent).status_code == 403

    audit = api.get("/auth/audit", headers=admin).json()
    blocked = [a for a in audit if a["action"] == "agent.write_blocked"]
    assert len(blocked) == 1 and blocked[0]["actor"] == "agente" and blocked[0]["outcome"] == "denied"
    assert _check(api.get("/agent/calibration", headers=admin).json(), "respeitou_o_modo")["status"] == "aviso"


def test_repeating_a_resource_request_refreshes_the_open_card_instead_of_duplicating(api):
    admin, agent = _as(api, "dono"), _as(api, "agente")
    body = {"text": "Chave do AI Studio", "kind": "request", "meta": {"resource": "AI_Studio_Key", "category": "api"}}
    first = api.post("/agent/chat", json=body, headers=agent).json()
    api.post("/agent/chat/read", headers=admin)  # o operador viu
    assert api.get("/agent/chat", headers=admin).json()["counts"]["unread_for_user"] == 0

    again = api.post("/agent/chat", json={**body, "text": "Ainda preciso da chave do AI Studio"}, headers=agent).json()
    assert again["deduplicated"] is True and again["id"] == first["id"]
    assert again["meta"]["reminders"] == 1 and again["meta"]["category"] == "api" and again["meta"]["last_reminded_at"]
    counts = api.get("/agent/chat", headers=admin).json()["counts"]
    assert counts["open_requests"] == 1 and counts["unread_for_user"] == 1  # o aviso do menu volta

    # Depois de resolvido, um novo pedido do mesmo recurso abre um cartão novo.
    api.patch(f"/agent/chat/{first['id']}", json={"status": "done"}, headers=admin)
    fresh = api.post("/agent/chat", json=body, headers=agent).json()
    assert fresh["id"] != first["id"] and "deduplicated" not in fresh


def test_agent_actions_are_signed_with_its_own_username_whatever_the_body_says(api, factory):
    from core.db.portfolio import PortfolioItem

    session = factory()
    product = _product(session, "888")
    session.commit()
    session.close()

    api.put("/agent/mode", json={"enabled": True}, headers=_as(api, "dono"))
    agent = _as(api, "agente")
    created = api.post("/portfolio/items", json={"product_id": product.id, "added_by": "everton", "notes": "demanda em alta"}, headers=agent)
    assert created.status_code == 201
    session = factory()
    item = session.query(PortfolioItem).one()
    assert item.added_by == "agente"  # assina com o próprio usuário; não deu para assinar como outra pessoa
    item_id = item.id
    session.close()

    moved = api.post(f"/portfolio/items/{item_id}/transition",
                     json={"to_state": "ANALYZING", "actor": "everton", "reason": "vou testar"}, headers=agent)
    assert moved.status_code == 200 and moved.json()["actor"] == "agente"


def test_mcp_server_module_keeps_real_annotations_for_old_sdk_versions():
    """O SDK do MCP 1.12 e anterior quebra com anotações em texto; foi o que derrubou o servidor na máquina do operador."""
    import inspect

    from mcp_server import server

    source = inspect.getsource(server)
    assert not any(line.strip() == "from __future__ import annotations" for line in source.splitlines())
    assert all(not isinstance(p.annotation, str) for fn in (server.list_products, server.product_funnel, server.request_resource)
               for p in inspect.signature(fn).parameters.values())


# --- agente em segundo plano: usuário automático e endpoints do supervisor -----------------------------


def test_turning_the_mode_on_creates_the_agent_user_without_a_known_password(api):
    from core.db.auth import User

    admin = _as(api, "dono")
    api.put("/agent/mode", json={"enabled": True}, headers=admin)
    mode = api.get("/agent/mode", headers=admin).json()
    assert mode["agent_user_exists"] is True and mode["agent_last_login_at"] is None  # existe, ainda não entrou
    audit = [a["action"] for a in api.get("/auth/audit", headers=admin).json()]
    assert "agent.user_created" in audit
    # Ninguém conhece a senha: o supervisor emite a sessão. Quem quiser usar no terminal gera uma nova.
    assert api.post("/auth/login", json={"username": "claude_agent", "password": "palpite12345"}).status_code == 401
    fresh = api.post("/agent/access", headers=admin).json()
    assert fresh["rotated"] is True and api.post("/auth/login", json={"username": "claude_agent", "password": fresh["password"]}).status_code == 200


def test_runtime_endpoint_is_readable_by_the_agent_and_run_now_is_admin_only(api):
    admin, agent = _as(api, "dono"), _as(api, "agente")
    rt = api.get("/agent/runtime", headers=agent).json()
    assert {"autorun", "supervisor_alive", "claude_found", "running_now", "waiting_for_login", "schedule", "runs"} <= set(rt)

    assert api.post("/agent/runtime/run", headers=agent).status_code == 403  # o agente não se dispara
    assert api.post("/agent/runtime/run", headers=admin).status_code == 409  # modo desligado
    api.put("/agent/mode", json={"enabled": True}, headers=admin)
    assert api.post("/agent/runtime/run", headers=admin).status_code == 503  # supervisor não sobe nos testes (AGENT_AUTORUN=false)


# --- atualização do catálogo: endpoint -------------------------------------------------------------


def test_catalog_refresh_endpoint_respects_the_agent_mode_the_force_flag_and_validation(api, monkeypatch):
    import core.services.catalog_refresh as cr

    seen = []
    monkeypatch.setattr(cr, "start_refresh", lambda session, adapters, **kw: seen.append(kw) or {"started": True, "marketplaces": ["shopee"], "skipped": {}})
    admin, agent = _as(api, "dono"), _as(api, "agente")

    assert api.post("/agent/catalog/refresh", json={}, headers=agent).status_code == 403  # modo manual: só consulta
    assert api.get("/agent/catalog/refresh", headers=agent).status_code == 200  # o estado, sim

    api.put("/agent/mode", json={"enabled": True}, headers=admin)
    ok = api.post("/agent/catalog/refresh", json={"keywords": ["  lanterna tática ", ""], "marketplaces": ["shopee"]}, headers=agent)
    assert ok.status_code == 202 and ok.json()["started"] is True
    assert seen[-1]["keywords"] == ["lanterna tática"] and seen[-1]["force"] is False

    forced = api.post("/agent/catalog/refresh", json={"force": True}, headers=agent)
    assert forced.status_code == 403 and "forçar" in forced.json()["detail"]  # o agente não ignora o intervalo
    assert api.post("/agent/catalog/refresh", json={"force": True}, headers=admin).status_code == 202  # o operador pode

    too_many = api.post("/agent/catalog/refresh", json={"keywords": [f"k{i}" for i in range(11)]}, headers=agent)
    assert too_many.status_code == 422
    audit = [a["action"] for a in api.get("/auth/audit", headers=admin).json()]
    assert "agent.catalog_refresh" in audit


# --- links rastreados: endpoints e travas -----------------------------------------------------------


def test_tracked_link_endpoints_respect_roles_the_agent_mode_and_inputs(api):
    admin, agent, viewer = _as(api, "dono"), _as(api, "agente"), _as(api, "leitor")
    body = {"product_id": 1, "channel": "instagram"}

    assert api.post("/links", json=body, headers=agent).status_code == 403  # modo manual: só consulta
    assert api.post("/links", json=body, headers=viewer).status_code == 403
    assert api.get("/links", headers=agent).status_code == 200 and api.get("/links", headers=viewer).status_code == 200
    assert api.get("/links/channels", headers=agent).json()[0] == "instagram"

    api.put("/agent/mode", json={"enabled": True}, headers=admin)
    assert api.post("/links", json={"channel": "tiktok"}, headers=agent).status_code == 422  # falta o produto
    no_setup = api.post("/links", json=body, headers=agent)
    assert no_setup.status_code == 422 and "não configurado" in no_setup.json()["detail"]
    assert api.post("/links/sync", headers=agent).status_code == 502  # sem encurtador configurado
