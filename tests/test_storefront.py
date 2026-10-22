"""Vitrine pública: o que entra na loja, o que NUNCA vai para ela e como se publica.

O site público (Netlify) é simulado: `requests.request` devolve respostas fixas. O que os testes travam:

* todo item do portfólio entra por padrão; oculto, pausado, sem link de afiliado ou sem foto não entram — com o motivo;
* a fotografia pública **não** contém comissão, pontuação, estado nem identificador interno de portfólio;
* o link da loja é o link curto rastreado (canal `vitrine`); sem encurtador cai no link de afiliado direto;
* publicar manda a fotografia com o token e registra o envio; falhas viram mensagem legível.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from backend.routers import services
from core.db.base import ConnectorKind, Marketplace
from core.db.catalog import Product, SourceRecord
from core.db.portfolio import PortfolioItem, PortfolioState
from core.db.service_credentials import ServiceCredential
from core.db.tracking import AffiliateLink
from core.services import link_shortener as ls
from core.services import storefront as sf

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
BASE = "https://felixsystems.com.br"
IMG = "https://down-br.img.susercontent.com/file/abc"


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body if body is not None else {}
        self.ok = status < 400

    def json(self):
        return self._body


class _Net:
    def __init__(self, monkeypatch):
        self.calls, self.routes = [], {}
        for module in (sf, ls):
            monkeypatch.setattr(module.requests, "request", self._request)

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
    session.add(ServiceCredential(service="storefront", enabled=True, values={"base_url": BASE, "admin_token": "tok-vitrine"}))
    session.flush()


@pytest.fixture
def shortener(session, net):
    session.add(ServiceCredential(service="link_shortener", enabled=True, values={"base_url": BASE, "admin_token": "tok-curto"}))
    session.flush()
    net.routes[("POST", "/api/links")] = _Resp(201, {"ok": True})


def _product(session, n, title="Garrafa Térmica Inox 500ml", affiliate="https://s.shopee.com.br/x", image=IMG, price=50.0):
    source = SourceRecord(marketplace=Marketplace.SHOPEE, connector="shopee", connector_kind=ConnectorKind.OFFICIAL_API,
                          endpoint="x", external_id=f"p{n}", collected_at=NOW)
    session.add(source)
    session.flush()
    product = Product(marketplace=Marketplace.SHOPEE, external_id=f"p{n}", title=title, price=price, original_price=70.0,
                      affiliate_url=affiliate, images=[image] if image else None, affiliate_commission_pct=51.5,
                      source_record_id=source.id, first_seen_at=NOW, last_seen_at=NOW, rating=4.84, sold_quantity=120)
    session.add(product)
    session.flush()
    return product


def _item(session, product, state=PortfolioState.PORTFOLIO_ACTIVE):
    item = PortfolioItem(product_id=product.id, marketplace=product.marketplace, state=state, label="x", state_changed_at=NOW)
    session.add(item)
    session.flush()
    return item


# -------------------------------------------------------------- quem entra -------------------


def test_every_portfolio_item_enters_by_default_and_the_reasons_are_explained(session):
    ok = _product(session, 1)
    no_link = _product(session, 2, affiliate=None)
    no_photo = _product(session, 3, image=None)
    paused = _product(session, 4)
    hidden = _product(session, 5)
    for p in (ok, no_link, no_photo, hidden):
        _item(session, p)
    _item(session, paused, PortfolioState.PAUSED)
    sf.upsert_item(session, hidden.id, hidden=True)

    admin = sf.list_admin(session)
    by = {r["product_id"]: r for r in admin["items"]}
    assert by[ok.id]["eligible"] is True and admin["publishable"] == 1
    assert by[no_link.id]["reason"] == "sem link de afiliado" and by[no_photo.id]["reason"] == "sem foto"
    assert by[paused.id]["reason"] == "pausado no portfólio" and by[hidden.id]["reason"] == "oculto na vitrine"

    snap = sf.build_snapshot(session)
    assert [i["id"] for i in snap["items"]] == [f"p{ok.id}"]
    assert {s["reason"] for s in snap["skipped"]} == {"sem link de afiliado", "sem foto", "pausado no portfólio"}  # oculto não é "problema"


def test_a_product_added_by_hand_enters_without_being_in_the_portfolio(session):
    manual = _product(session, 1)
    sf.upsert_item(session, manual.id, blurb="Cabe na bolsa")
    assert [i["id"] for i in sf.build_snapshot(session)["items"]] == [f"p{manual.id}"]


# ------------------------------------------------------- o que NUNCA vai para a loja ----------


def test_the_public_snapshot_leaks_no_internal_data(session):
    product = _product(session, 1)
    _item(session, product)
    sf.upsert_item(session, product.id, display_title="Garrafa Rabbit", category="Casa",
                   blurb="Mantém gelado o dia todo.", highlight=True)
    snap = sf.build_snapshot(session)
    item_text = json.dumps(snap["items"], ensure_ascii=False)
    for secret in ("commission", "51.5", "score", "portfolio", "PORTFOLIO_ACTIVE", "external_id", "source"):
        assert secret not in item_text, secret
    item = snap["items"][0]
    assert item["title"] == "Garrafa Rabbit" and item["category"] == "Casa" and item["highlight"] is True
    assert item["price"] == 50.0 and item["original_price"] == 70.0 and item["price_date"] == "2026-10-22"
    assert item["rating"] == 4.8 and item["sold"] == 120 and item["marketplace_name"] == "Shopee"
    disclosure = snap["store"]["disclosure"]
    assert "comissão" in disclosure and "parceiros oficiais" in disclosure  # o aviso de afiliado sempre vai junto, sem sugerir parceria oficial


def test_titles_and_categories_are_tidied():
    long = "Personalizado   - COPO CUIA Térmico Inox com Tampa e Canudo " * 3
    cleaned = sf.clean_title(long)
    assert len(cleaned) <= 85 and cleaned.endswith("…") and "  " not in cleaned
    assert sf.guess_category("Tapete Higiênico para Cachorro 50 Unid") == "Pet"  # Pet vence "tapete"
    assert sf.guess_category("Luminária UV LED para unhas") == "Beleza"
    assert sf.guess_category("Calça Legging Fitness") == "Moda"
    assert sf.guess_category("Fone de Ouvido Bluetooth") == "Eletrônicos"
    assert sf.guess_category("Copo Térmico") == "Casa"
    assert sf.guess_category("Controle Gamer sem fio") == "Games"
    assert sf.guess_category("Coisa qualquer") == "Achados diversos"
    assert sf.guess_category("Qualquer nome", "hotmart") == "Cursos"  # plataformas digitais viram Cursos
    assert sf.guess_category("Curso de Excel Completo") == "Cursos"


def test_invalid_category_and_missing_product_are_rejected(session):
    product = _product(session, 1)
    with pytest.raises(sf.StorefrontError, match="categoria inválida"):
        sf.upsert_item(session, product.id, category="Armas")
    with pytest.raises(sf.StorefrontError, match="não encontrado"):
        sf.upsert_item(session, 99999, hidden=True)
    sf.upsert_item(session, product.id, blurb="x" * 400)
    assert len(sf.list_admin(session)["items"][0]["blurb"]) == 280


# ------------------------------------------------------------------ links ----------------------


def test_store_links_are_tracked_short_links_in_the_vitrine_channel(session, net, shortener):
    product = _product(session, 1)
    _item(session, product)
    preview = sf.build_snapshot(session, create_links=False)["items"][0]
    assert preview["url"] == "https://s.shopee.com.br/x" and preview["tracked"] is False  # a prévia não cria link
    assert not [c for c in net.calls if c[0] == "POST"]

    first = sf.build_snapshot(session, create_links=True)["items"][0]
    assert first["tracked"] is True and first["url"].startswith(f"{BASE}/r/")
    again = sf.build_snapshot(session, create_links=True)["items"][0]
    assert again["url"] == first["url"] and len([c for c in net.calls if c[0] == "POST"]) == 1  # reaproveita
    assert session.scalar(select(AffiliateLink.channel)) == "vitrine"
    assert sf.build_snapshot(session, create_links=False)["items"][0]["url"] == first["url"]  # agora a prévia já mostra o curto


def test_without_the_shortener_the_store_uses_the_affiliate_link(session):
    product = _product(session, 1)
    _item(session, product)
    item = sf.build_snapshot(session, create_links=True)["items"][0]
    assert item["url"] == "https://s.shopee.com.br/x" and item["tracked"] is False


# --------------------------------------------------------------- publicar ----------------------


def test_publish_sends_the_snapshot_with_the_token_and_records_it(session, net, configured, shortener):
    product = _product(session, 1)
    _item(session, product)
    net.routes[("POST", "/api/loja/publicar")] = _Resp(200, {"ok": True, "count": 1})
    result = sf.publish(session, actor="claude_agent")
    _, _, kw = [c for c in net.calls if c[1].endswith("/api/loja/publicar")][0]
    assert kw["headers"] == {"Authorization": "Bearer tok-vitrine"} and kw["json"]["items"][0]["id"] == f"p{product.id}"
    assert "skipped" not in kw["json"]  # o que ficou de fora é só para o operador
    assert result["count"] == 1 and result["by"] == "claude_agent" and result["public_url"] == f"{BASE}/loja"
    assert sf.list_admin(session)["last_publish"]["count"] == 1


def test_publish_errors_are_readable(session, net, configured):
    with pytest.raises(sf.StorefrontError, match="nenhum produto pronto"):
        sf.publish(session, actor="x")
    product = _product(session, 1)
    _item(session, product)
    net.routes[("POST", "/api/loja/publicar")] = _Resp(401, {"error": "não autorizado"})
    with pytest.raises(sf.StorefrontError, match="recusou o token"):
        sf.publish(session, actor="x")


def test_publish_without_configuration_says_what_to_fill(session):
    with pytest.raises(sf.StorefrontError, match="não está configurada"):
        sf.publish(session, actor="x")


# ----------------------------------------------------- cartão em Integrações --------------------


def test_the_integration_card_hides_the_token_and_tests_the_connection(session, net):
    out = services.update_service(
        "storefront", services.ServiceUpdate(values={"base_url": BASE + "/", "admin_token": "segredo-loja-4471"}), session)
    assert out.configured is True and out.icon == "🛍️"
    assert "segredo-loja-4471" not in out.model_dump_json()

    net.routes[("GET", "/api/loja/ping")] = _Resp(200, {"ok": True})
    assert services.test_service("storefront", session).last_check_status == "ok"
    net.routes[("GET", "/api/loja/ping")] = _Resp(401, {"error": "não autorizado"})
    assert "recusou o token" in services.test_service("storefront", session).last_check_message


def test_store_name_and_tagline_have_defaults_and_can_change(session):
    assert sf.get_meta(session)["name"] == "Mural na Web"
    sf.set_meta(session, name="  Garimpo  ", tagline=None, actor="x")
    meta = sf.get_meta(session)
    assert meta["name"] == "Garimpo" and meta["tagline"] == sf.DEFAULT_TAGLINE and meta["socials"] == {}


def test_social_links_must_be_https_and_known(session):
    sf.set_meta(session, name=None, tagline=None, actor="x",
                socials={"instagram": "https://instagram.com/muralnaweb", "youtube": "", "whatsapp": "https://chat.whatsapp.com/abc"})
    assert sf.get_meta(session)["socials"] == {"instagram": "https://instagram.com/muralnaweb", "whatsapp": "https://chat.whatsapp.com/abc"}
    with pytest.raises(sf.StorefrontError, match="https://"):
        sf.set_meta(session, name=None, tagline=None, actor="x", socials={"facebook": "javascript:alert(1)"})
    with pytest.raises(sf.StorefrontError, match="rede desconhecida"):
        sf.set_meta(session, name=None, tagline=None, actor="x", socials={"orkut": "https://orkut.com/x"})


def test_sensitive_products_never_enter_the_store_and_cannot_be_forced(session):
    ok = _product(session, 1, title="Garrafa Térmica Inox")
    sensitive = [_product(session, 10 + i, title=t) for i, t in enumerate((
        "Destruidor de Ejaculação Precoce", "Super Gel Volumão Super Aumento Peniano", "Libid Gel Men", "Maca X Power Potência Sexual"))]
    for p in [ok, *sensitive]:
        _item(session, p)
    for p in sensitive:
        sf.upsert_item(session, p.id, hidden=False, highlight=True)  # tentar "forçar" não adianta
    admin = sf.list_admin(session)
    reasons = {r["product_id"]: r["reason"] for r in admin["items"] if not r["eligible"]}
    assert set(reasons) == {p.id for p in sensitive} and all("sensível" in r for r in reasons.values())
    assert [i["id"] for i in sf.build_snapshot(session)["items"]] == [f"p{ok.id}"]
