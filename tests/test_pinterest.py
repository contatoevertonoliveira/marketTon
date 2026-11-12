"""Pinterest: rascunho com texto e imagem prontos, aprovação do operador, publicação, teto por dia e métricas.

O Pinterest é simulado. O que os testes travam:

* o texto cabe nos limites do Pinterest, leva o aviso de divulgação e não inventa característica do produto;
* o rascunho usa a imagem do criativo (2:3 primeiro) e, sem criativo, a foto do produto; o link aponta para a página do produto no Mural;
* o produto entra na vitrine ao virar pin (regra do operador) e não ganha dois pins ativos;
* publicar cria o quadro se faltar, manda a imagem em base64 e guarda o link do pin; falha fica no pin, com o motivo, e pode ser refeita;
* só pin APROVADO sai sozinho, respeitando o teto por dia e o intervalo entre pins.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.db  # noqa: F401
from core.db import Base
from core.db.base import ConnectorKind, Marketplace
from core.db.catalog import Product, SourceRecord
from core.db.creatives import CreativeCampaign
from core.db.service_credentials import ServiceCredential
from core.db.storefront import StorefrontItem
from core.services import pinterest as pin_svc

NOW = datetime(2026, 11, 12, 15, 0, tzinfo=UTC)


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body, self.ok, self.text = status, body if body is not None else {}, status < 400, ""

    def json(self):
        return self._body


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s
    engine.dispose()


def _cards(session, **pinterest_values):
    ok = {"last_check_status": "ok"}
    session.add_all([
        ServiceCredential(service="storefront", enabled=True, values={"base_url": "https://x.com", "admin_token": "t", "public_url": "https://mural.felixsystems.com.br"}, **ok),
        ServiceCredential(service="pinterest", enabled=True, values={"access_token": "tok", **pinterest_values}, **ok),
    ])
    session.flush()


def _product(session, n=1, title="[Frete Grátis] Espelho de Corpo Inteiro 2026 Moldura Preta 150x50cm"):
    source = SourceRecord(marketplace=Marketplace.SHOPEE, connector="shopee", connector_kind=ConnectorKind.OFFICIAL_API, endpoint="x", external_id=f"p{n}", collected_at=NOW)
    session.add(source)
    session.flush()
    product = Product(marketplace=Marketplace.SHOPEE, external_id=f"p{n}", title=title, price=189.9, affiliate_url="https://s.shopee.com.br/x", images=["https://cf.shopee.com.br/file/x"],
                      source_record_id=source.id, first_seen_at=NOW, last_seen_at=NOW, category_id="100636")
    session.add(product)
    session.flush()
    return product


def _creative(session, product, aspect="2:3"):
    manifest = {"deliverables": [{"id": "d9", "kind": "image", "status": "ready", "aspect_ratio": aspect, "url_signed": {"href": "https://studio.exemplo.com/d/9?sig=x"}}]}
    c = CreativeCampaign(product_id=product.id, external_ref=f"mural-p{product.id}-pl1-2611120000", campaign_id="cmp_1", mode="live", status="completed", quality="economy", budget_usd=1.0, manifest=manifest)
    session.add(c)
    session.flush()
    return c


@pytest.fixture
def api(monkeypatch):
    class A:
        calls: list = []
        boards: list = []

    a = A()
    a.calls, a.boards = [], [{"id": "b1", "name": "Decoração"}]

    def request(method, url, headers=None, timeout=None, json=None, params=None, **kw):
        path = url.split("/v5")[1]
        a.calls.append((method, path, json))
        if method == "GET" and path == "/boards":
            return _Resp(200, {"items": a.boards})
        if method == "POST" and path == "/boards":
            a.boards.append({"id": "b_new", "name": json["name"]})
            return _Resp(201, {"id": "b_new"})
        if method == "POST" and path == "/pins":
            return _Resp(201, {"id": f"pin_{len([c for c in a.calls if c[1] == '/pins'])}"})
        if method == "GET" and path == "/user_account":
            return _Resp(200, {"username": "muralnaweb"})
        if path.endswith("/analytics"):
            return _Resp(200, {"all": {"summary_metrics": {"IMPRESSION": 5100, "SAVE": 8, "PIN_CLICK": 151, "OUTBOUND_CLICK": 40}}})
        raise AssertionError(f"chamada inesperada {method} {path}")

    monkeypatch.setattr(pin_svc.requests, "request", request)
    monkeypatch.setattr(pin_svc, "fetch_image", lambda session, ref: b"\xff\xd8jpeg")
    return a


def test_copy_fits_limits_discloses_and_does_not_invent():
    p = Product(title="[Frete Grátis] Espelho de Corpo Inteiro 2026 Moldura Preta 150x50cm " * 3, price=189.9, marketplace=Marketplace.SHOPEE)
    c = pin_svc.suggest_copy(p, "Casa e Decoração")
    assert len(c["title"]) <= 100 and "Frete" not in c["title"] and "2026" not in c["title"]
    assert len(c["description"]) <= 800 and "link de afiliado" in c["description"] and "R$ 189,90" in c["description"]
    assert "espelho" in c["keywords"] and "casa e decoração" in c["keywords"].lower()
    assert len(c["alt_text"]) <= 500


def test_draft_prefers_the_creative_image_and_links_to_the_mural_page(session):
    _cards(session)
    prod = _product(session)
    cr = _creative(session, prod)
    pin = pin_svc.create_draft(session, prod.id, actor="op")
    assert pin.status == "draft" and pin.image_ref == f"creative:{cr.id}:d9" and pin.creative_campaign_id == cr.id
    assert pin.link_url == f"https://mural.felixsystems.com.br/p/p{prod.id}?utm_source=pinterest&utm_medium=organic&utm_campaign=pin{pin.id}"
    assert session.query(StorefrontItem).filter_by(product_id=prod.id).count() == 1  # entrou na vitrine
    assert pin_svc.candidates(session) == []  # produto com pin ativo não volta para a fila de candidatos


def test_draft_without_a_pin_image_asks_the_studio_for_a_new_one_and_waits(session, monkeypatch, api):
    _cards(session)
    prod = _product(session)
    asked = []

    class Cfg:
        max_usd = 1.0

    def fake_create(sess, product_id, **kw):
        asked.append(kw)
        c = CreativeCampaign(product_id=product_id, external_ref=f"mural-p{product_id}-pl1-2611120001", campaign_id="cmp_7", mode="live", status="queued", quality=kw["quality"],
                             budget_usd=kw["budget_usd"], manifest={})
        sess.add(c)
        sess.flush()
        return c

    monkeypatch.setattr(pin_svc.aistudio, "_require", lambda s: Cfg())
    monkeypatch.setattr(pin_svc.aistudio, "create", fake_create)
    monkeypatch.setattr(pin_svc.aistudio, "refresh", lambda sess, c: c)  # o estúdio ainda está gerando
    pin = pin_svc.create_draft(session, prod.id, actor="op")
    assert asked == [{"mode": "live", "quality": "premium", "budget_usd": 0.5, "actor": "op", "formats": "pin"}]  # imagem nova, a mais nítida (2K), só imagem
    assert pin.image_ref.startswith("product:") and pin.creative_campaign_id and pin_svc.out(pin)["image_ready"] is False
    with pytest.raises(pin_svc.PinterestError, match="imagem nova"):  # a foto crua do marketplace nunca vai para o Pinterest
        pin_svc.publish(session, pin.id, actor="op")
    pin_svc.approve(session, pin.id)
    assert pin_svc.publish_due(session, now=NOW) == []
    c = session.get(CreativeCampaign, pin.creative_campaign_id)  # o estúdio entrega
    c.status, c.manifest = "completed", {"deliverables": [{"id": "dlv_1", "kind": "image", "status": "ready", "aspect_ratio": "9:16", "url_signed": {"href": "https://studio/x"}}]}
    assert pin_svc.refresh_images(session) == 1 and pin.image_ref == f"creative:{c.id}:dlv_1" and pin_svc.out(pin)["image_ready"]
    assert pin_svc.publish_due(session, now=NOW) == [pin.id]


def test_ad_images_with_price_and_badge_are_not_used_for_pins(session):
    _cards(session)
    prod = _product(session)
    ad = _creative(session, prod)
    ad.external_ref = f"mural-p{prod.id}-il1-2611120000"  # arte de anúncio (tem preço e selo): não serve para o pin
    assert pin_svc.pick_image(session, prod)[0].startswith("product:")


def test_publish_creates_the_board_sends_base64_and_keeps_the_link(session, api):
    _cards(session)
    prod = _product(session)
    _creative(session, prod)
    pin = pin_svc.create_draft(session, prod.id, actor="op", board="Espelhos")
    pin_svc.approve(session, pin.id)
    done = pin_svc.publish(session, pin.id, actor="op", now=NOW)
    body = next(c[2] for c in api.calls if c[1] == "/pins")
    assert done.status == "published" and done.permalink == "https://www.pinterest.com/pin/pin_1/" and done.published_at == NOW
    assert body["board_id"] == "b_new" and body["link"] == pin.link_url and body["media_source"]["source_type"] == "image_base64"
    assert len(body["title"]) <= 100 and len(body["description"]) <= 800 and body["alt_text"]


def test_failure_is_saved_on_the_pin_and_can_be_retried(session, monkeypatch, api):
    _cards(session)
    prod = _product(session)
    _creative(session, prod)
    pin = pin_svc.create_draft(session, prod.id, actor="op")
    monkeypatch.setattr(pin_svc.requests, "request", lambda *a, **k: _Resp(403, {"message": "sem permissão"}))
    with pytest.raises(pin_svc.PinterestError, match="pins:write"):
        pin_svc.publish(session, pin.id, actor="op")
    assert pin.status == "failed" and "sem permissão" in pin.error
    assert pin_svc.approve(session, pin.id).status == "approved"  # pode refazer


def test_only_approved_pins_go_out_within_the_daily_cap_and_gap(session, api):
    _cards(session, max_per_day="2")
    pins = []
    for n in range(1, 5):
        prod = _product(session, n)
        _creative(session, prod)
        pins.append(pin_svc.create_draft(session, prod.id, actor="op"))
    assert pin_svc.publish_due(session, now=NOW) == []  # rascunho não sai sozinho
    for p in pins[:3]:
        pin_svc.approve(session, p.id)
    assert pin_svc.publish_due(session, now=NOW) == [pins[0].id]  # o intervalo entre pins segura o segundo
    assert pin_svc.publish_due(session, now=NOW + timedelta(minutes=30)) == []
    assert pin_svc.publish_due(session, now=NOW + timedelta(minutes=61)) == [pins[1].id]
    assert pin_svc.publish_due(session, now=NOW + timedelta(hours=3)) == []  # teto de 2 por dia
    assert pins[2].status == "approved" and pins[3].status == "draft"


def test_scheduled_pin_waits_for_its_time(session, api):
    _cards(session)
    prod = _product(session)
    _creative(session, prod)
    pin = pin_svc.create_draft(session, prod.id, actor="op")
    pin_svc.approve(session, pin.id, scheduled_for=NOW + timedelta(hours=2))
    assert pin_svc.publish_due(session, now=NOW) == []
    assert pin_svc.publish_due(session, now=NOW + timedelta(hours=2)) == [pin.id]


def test_without_the_key_nothing_goes_out_but_the_kit_is_ready(session):
    session.add(ServiceCredential(service="storefront", enabled=True, values={"base_url": "https://x.com", "admin_token": "t", "public_url": "https://mural.felixsystems.com.br"}, last_check_status="ok"))
    session.flush()
    prod = _product(session)
    pin = pin_svc.create_draft(session, prod.id, actor="op")
    pin_svc.approve(session, pin.id)
    assert pin_svc.publish_due(session, now=NOW) == []
    with pytest.raises(pin_svc.PinterestError, match="não está conectado"):
        pin_svc.publish(session, pin.id, actor="op")
    assert pin_svc.out(pin)["image_file"] == f"/pinterest/pins/{pin.id}/image" and pin_svc.out(pin)["link_url"]


def test_edit_rules_and_metrics(session, api):
    _cards(session)
    prod = _product(session)
    _creative(session, prod)
    pin = pin_svc.create_draft(session, prod.id, actor="op")
    assert pin_svc.update(session, pin.id, {"title": "Espelho grande para quarto"}).title == "Espelho grande para quarto"
    with pytest.raises(pin_svc.PinterestError):
        pin_svc.update(session, pin.id, {"title": "x" * 101})
    with pytest.raises(pin_svc.PinterestError):
        pin_svc.update(session, pin.id, {"title": "  "})
    pin_svc.publish(session, pin.id, actor="op", now=NOW)
    with pytest.raises(pin_svc.PinterestError, match="já foi publicado"):
        pin_svc.update(session, pin.id, {"title": "outro"})
    assert pin_svc.sync_metrics(session, now=NOW + timedelta(days=3)) == 1
    assert (pin.impressions, pin.saves, pin.pin_clicks, pin.outbound_clicks) == (5100, 8, 151, 40)


def test_check_reports_the_account_and_the_mode(session, api):
    assert "muralnaweb" in pin_svc.check({"access_token": "t"}) and "produção" in pin_svc.check({"access_token": "t"})
    assert "SANDBOX" in pin_svc.check({"access_token": "t", "api_base": "https://api-sandbox.pinterest.com/v5"})
    with pytest.raises(pin_svc.PinterestError):
        pin_svc.check({})
