"""Links curtos rastreados: criar, reaproveitar, sincronizar cliques e medir.

O redirecionador público (Netlify) é simulado: `requests.request` devolve respostas fixas no formato real da
API (`POST /api/links`, `GET /api/links/clicks`). O que os testes travam:

* só se encurta o **link de afiliado** (encurtar o comum daria clique sem comissão);
* mesmo produto + canal + campanha reaproveita o link; colisão de código sorteia outro;
* a sincronização é idempotente (cada clique tem id único) e ignora código que não é nosso;
* "cliques" só aparecem para quem tem link rastreado, e nunca como zero inventado.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from backend.routers import services
from core.db.base import ConnectorKind, Marketplace
from core.db.catalog import Product, SourceRecord
from core.db.portfolio import PortfolioItem
from core.db.service_credentials import ServiceCredential
from core.db.tracking import AffiliateLink, ClickEvent
from core.services import link_shortener as ls
from core.services.product_performance import product_performance

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
BASE = "https://felixsystems.com.br"


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body if body is not None else {}
        self.ok = status < 400

    def json(self):
        return self._body


class _Net:
    def __init__(self, monkeypatch):
        self.calls, self.routes = [], {}
        monkeypatch.setattr(ls.requests, "request", self._request)

    def _request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        handler = self.routes.get((method, url.replace(BASE, "")))
        if handler is None:
            raise AssertionError(f"chamada inesperada {method} {url}")
        return handler(kwargs) if callable(handler) else handler


@pytest.fixture
def net(monkeypatch):
    return _Net(monkeypatch)


@pytest.fixture
def configured(session):
    session.add(ServiceCredential(service="link_shortener", enabled=True, values={"base_url": BASE, "admin_token": "tok-secreto"}))
    session.flush()


def _product(session, affiliate_url="https://s.shopee.com.br/abc123", external_id="p1"):
    source = SourceRecord(marketplace=Marketplace.SHOPEE, connector="shopee", connector_kind=ConnectorKind.OFFICIAL_API,
                          endpoint="x", external_id=external_id, collected_at=NOW)
    session.add(source)
    session.flush()
    product = Product(marketplace=Marketplace.SHOPEE, external_id=external_id, title="Garrafa", price=50.0,
                      affiliate_url=affiliate_url, source_record_id=source.id, first_seen_at=NOW, last_seen_at=NOW)
    session.add(product)
    session.flush()
    return product


def _item(session, product):
    item = PortfolioItem(product_id=product.id, marketplace=product.marketplace, label="x", state_changed_at=NOW)
    session.add(item)
    session.flush()
    return item


def _register_ok(net):
    net.routes[("POST", "/api/links")] = _Resp(201, {"ok": True})


# ------------------------------------------------------------------- criar -----------------


def test_not_configured_and_missing_affiliate_link_are_clear_errors(session, net):
    product = _product(session)
    with pytest.raises(ls.ShortenerError, match="não configurado"):
        ls.create_tracked_link(session, product_id=product.id, channel="instagram")

    session.add(ServiceCredential(service="link_shortener", enabled=True, values={"base_url": BASE, "admin_token": "t"}))
    bare = _product(session, affiliate_url=None, external_id="p2")
    with pytest.raises(ls.ShortenerError, match="clique sem comissão"):
        ls.create_tracked_link(session, product_id=bare.id, channel="instagram")  # só encurta o link de afiliado
    with pytest.raises(ls.ShortenerError, match="canal inválido"):
        ls.create_tracked_link(session, product_id=product.id, channel="orkut")
    assert net.calls == []  # nada foi cadastrado no redirecionador


def test_create_registers_the_affiliate_url_and_stores_the_short_link(session, net, configured):
    product = _product(session)
    item = _item(session, product)
    _register_ok(net)

    link = ls.create_tracked_link(session, portfolio_item_id=item.id, channel="Instagram", campaign=" gancho-preco ")

    method, url, kw = net.calls[0]
    assert (method, url) == ("POST", f"{BASE}/api/links") and kw["headers"] == {"Authorization": "Bearer tok-secreto"}
    assert kw["json"]["url"] == "https://s.shopee.com.br/abc123" and kw["json"]["code"] == link.short_code
    assert len(link.short_code) == 7 and set(link.short_code) <= set(ls.ALPHABET)
    assert link.affiliate_url == f"{BASE}/r/{link.short_code}"  # é este o link que se divulga
    assert link.destination_url == "https://s.shopee.com.br/abc123"
    assert (link.channel, link.campaign, link.product_id, link.portfolio_item_id) == ("instagram", "gancho-preco", product.id, item.id)


def test_same_product_channel_and_campaign_reuses_the_link_but_another_channel_gets_its_own(session, net, configured):
    product = _product(session)
    _register_ok(net)
    first = ls.create_tracked_link(session, product_id=product.id, channel="tiktok")
    again = ls.create_tracked_link(session, product_id=product.id, channel="tiktok")
    other = ls.create_tracked_link(session, product_id=product.id, channel="youtube")
    camp = ls.create_tracked_link(session, product_id=product.id, channel="tiktok", campaign="v2")
    assert again.id == first.id and len({first.id, other.id, camp.id}) == 3
    assert len(net.calls) == 3  # o reaproveitado não chamou o redirecionador


def test_a_code_collision_on_the_public_side_draws_another_code(session, net, configured):
    product = _product(session)
    state = {"n": 0}

    def register(kw):
        state["n"] += 1
        return _Resp(409, {"error": "código já existe"}) if state["n"] == 1 else _Resp(201, {"ok": True})

    net.routes[("POST", "/api/links")] = register
    link = ls.create_tracked_link(session, product_id=product.id, channel="outro")
    assert state["n"] == 2 and link.id is not None


def test_a_rejected_token_and_a_network_failure_are_readable(session, net, configured):
    product = _product(session)
    net.routes[("POST", "/api/links")] = _Resp(401, {"error": "não autorizado"})
    with pytest.raises(ls.ShortenerError, match="recusou o token"):
        ls.create_tracked_link(session, product_id=product.id, channel="outro")
    assert session.scalars(select(AffiliateLink)).all() == []  # nada fica pela metade no banco


# ------------------------------------------------------------------- cliques --------------


def _events(*specs):
    return {"since": "2026-10-22", "until": "2026-10-22", "truncated": False, "events": [
        {"id": i, "code": code, "t": "2026-10-22T11:19:21.914Z", "device": dev, "country": "br", "referrer": ref}
        for i, code, dev, ref in specs]}


def test_sync_creates_click_events_updates_totals_and_is_idempotent(session, net, configured):
    product = _product(session)
    item = _item(session, product)
    _register_ok(net)
    link = ls.create_tracked_link(session, portfolio_item_id=item.id, channel="instagram")
    code = link.short_code
    payload = _events((f"2026-10-22/{code}/1-aaaa|mobile|br|www.instagram.com", code, "mobile", "www.instagram.com"),
                      (f"2026-10-22/{code}/2-bbbb|desktop|br|direto", code, "desktop", "direto"),
                      ("2026-10-22/zzzzzzz/3-cccc|mobile|br|direto", "zzzzzzz", "mobile", "direto"))  # código que não é nosso
    net.routes[("GET", "/api/links/clicks")] = _Resp(200, payload)

    first = ls.sync_clicks(session)
    assert first == {"new_clicks": 2, "links": 1, "truncated": False}
    clicks = session.scalars(select(ClickEvent).order_by(ClickEvent.id)).all()
    assert [(c.device, c.referrer, c.country, c.channel, c.portfolio_item_id) for c in clicks] == [
        ("mobile", "www.instagram.com", "br", "instagram", item.id), ("desktop", "direto", "br", "instagram", item.id)]
    assert link.clicks_total == 2 and item.clicks_total == 2

    assert ls.sync_clicks(session)["new_clicks"] == 0  # de novo: nada duplicado
    assert link.clicks_total == 2 and session.query(ClickEvent).count() == 2


def test_truncated_listing_does_not_advance_the_cursor(session, net, configured):
    product = _product(session)
    _register_ok(net)
    link = ls.create_tracked_link(session, product_id=product.id, channel="tiktok")
    body = _events((f"2026-10-22/{link.short_code}/1-aaaa|mobile|br|direto", link.short_code, "mobile", "direto"))
    body["truncated"] = True
    net.routes[("GET", "/api/links/clicks")] = _Resp(200, body)
    out = ls.sync_clicks(session)
    assert out["truncated"] is True and out["new_clicks"] == 1
    from core.db.app_settings import AppSetting
    assert session.scalar(select(AppSetting).where(AppSetting.key == ls.CURSOR_KEY)) is None  # recomeça de onde parou


def test_sync_without_any_link_says_so_and_does_not_call_the_network(session, net, configured):
    assert ls.sync_clicks(session)["note"] == "ainda não há links rastreados" and net.calls == []


def test_clicks_show_up_in_performance_only_for_products_with_a_tracked_link(session, net, configured):
    from core.services.sales_ingestion import ingest_sales
    from integrations.marketplaces.base import SalesRecord

    tracked = _product(session, external_id="p1")
    item = _item(session, tracked)
    untracked = _product(session, external_id="p2")
    for p in (tracked, untracked):
        ingest_sales(session, [SalesRecord(external_order_id=f"o:{p.external_id}", occurred_at=NOW, gross_amount=50.0,
                                           product_external_id=p.external_id, product_title="G", status="COMPLETED")], Marketplace.SHOPEE)
    _register_ok(net)
    link = ls.create_tracked_link(session, portfolio_item_id=item.id, channel="instagram")
    net.routes[("GET", "/api/links/clicks")] = _Resp(200, _events(
        (f"2026-10-22/{link.short_code}/1-a|mobile|br|direto", link.short_code, "mobile", "direto")))
    ls.sync_clicks(session)

    rows, tracked_flag = product_performance(session, Marketplace.SHOPEE)
    by = {r.product_external_id: r for r in rows}
    assert tracked_flag is True and by["p1"].clicks == 1
    assert by["p2"].clicks is None  # sem link rastreado: "não rastreado", nunca 0


# ------------------------------------------------------------- cartão de configuração ------


def test_the_integration_card_saves_the_token_hidden_and_tests_the_connection(session, net):
    out = services.update_service("link_shortener", services.ServiceUpdate(values={"base_url": BASE + "/", "admin_token": "segredo-xyz-9183"}), session)
    assert out.configured is True and out.icon == "🔗" and out.values_set == {"base_url": True, "admin_token": True}
    assert "segredo-xyz-9183" not in out.model_dump_json()  # o segredo não volta pela API

    net.routes[("GET", "/api/links/ping")] = _Resp(200, {"ok": True})
    ok = services.test_service("link_shortener", session)
    assert ok.last_check_status == "ok" and BASE in ok.last_check_message

    net.routes[("GET", "/api/links/ping")] = _Resp(401, {"error": "não autorizado"})
    bad = services.test_service("link_shortener", session)
    assert bad.last_check_status == "error" and "recusou o token" in bad.last_check_message


def test_sync_keeps_the_ad_campaign_of_an_offer_click(session, net, configured):
    product = _product(session)
    _register_ok(net)
    link = ls.create_tracked_link(session, product_id=product.id, channel="vitrine")
    body = _events((f"2026-10-22/{link.short_code}/1-aaaa|mobile|br|direto|mural-p97-il1", link.short_code, "mobile", "direto"))
    body["events"][0]["campaign"] = "mural-p97-il1"
    net.routes[("GET", "/api/links/clicks")] = _Resp(200, body)
    assert ls.sync_clicks(session)["new_clicks"] == 1
    assert session.scalars(select(ClickEvent)).one().campaign == "mural-p97-il1"
