"""Publicar no Instagram: link público assinado, texto com divulgação, fluxo container -> publicar e histórico.

A Meta é simulada. O que os testes travam:

* o link público da imagem só vale com a assinatura certa e antes do vencimento;
* o texto leva o link da bio e o aviso de divulgação, dentro do limite do Instagram;
* publicar cria o container com a imagem pública, espera ficar pronto e publica; tudo fica no histórico;
* criativo de teste não publica; falha do Instagram fica registrada e é devolvida com a mensagem.
"""
from __future__ import annotations

from datetime import UTC, datetime

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
from core.db.social import SocialPost
from core.services import instagram as ig
from core.services import meta_ads

NOW = datetime.now(UTC)


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body, self.ok = status, body if body is not None else {}, status < 400

    def json(self):
        return self._body


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s
    engine.dispose()


@pytest.fixture
def meta(monkeypatch):
    class M:
        posts: list = []
        gets: dict = {}
        container_status: list = []

    m = M()
    m.posts, m.gets, m.container_status = [], {}, ["IN_PROGRESS", "FINISHED"]

    def post(url, data=None, timeout=None, **kw):
        path = url.split("/v21.0/")[1]
        m.posts.append((path, dict(data or {})))
        if path.endswith("/media"):
            return _Resp(200, {"id": "container_1"})
        if path.endswith("/media_publish"):
            return _Resp(200, {"id": "media_9"})
        raise AssertionError(path)

    def get(url, params=None, timeout=None):
        if url.endswith("/container_1"):
            return _Resp(200, {"status_code": m.container_status.pop(0) if m.container_status else "FINISHED"})
        for fragment, body in m.gets.items():
            if url.endswith(fragment):
                return _Resp(200, body)
        raise AssertionError(f"GET inesperado {url}")

    monkeypatch.setattr(ig.requests, "post", post)
    monkeypatch.setattr(meta_ads.requests, "get", get)
    m.gets = {"/999": {"instagram_business_account": {"id": "ig_77"}}, "/media_9": {"permalink": "https://www.instagram.com/p/ABC/"}}
    return m


def _cards(session):
    ok = {"last_check_status": "ok"}
    session.add_all([
        ServiceCredential(service="meta_ads", enabled=True, values={"access_token": "tok", "ad_account_id": "123", "page_id": "999"}, **ok),
        ServiceCredential(service="storefront", enabled=True, values={"base_url": "https://x.com", "admin_token": "t",
                                                                       "public_url": "https://mural.felixsystems.com.br"}, **ok),
        ServiceCredential(service="aistudio", enabled=True, values={"base_url": "http://studio/api/v1", "api_key": "k", "webhook_secret": "s",
                                                                     "callback_url": "https://app.exemplo.com/api/integrations/aistudio/webhook"}, **ok),
    ])
    session.flush()


def _creative(session, mode="live", n=1):
    source = SourceRecord(marketplace=Marketplace.SHOPEE, connector="shopee", connector_kind=ConnectorKind.OFFICIAL_API, endpoint="x",
                          external_id=f"p{n}", collected_at=NOW)
    session.add(source)
    session.flush()
    product = Product(marketplace=Marketplace.SHOPEE, external_id=f"p{n}", title="Garrafa Térmica", price=50.0, source_record_id=source.id,
                      first_seen_at=NOW, last_seen_at=NOW)
    session.add(product)
    session.flush()
    manifest = {"deliverables": [
        {"id": "d1", "kind": "image", "status": "ready", "aspect_ratio": "4:5", "url_signed": {"href": "https://studio.exemplo.com/d/1?sig=x"}},
        {"id": "d2", "kind": "copy", "status": "ready", "content": {"headline": "Gelada por 24 h",
                                                                   "caption": "Sua água gelada o dia todo. Ver na loja: https://mural.felixsystems.com.br/#p1"}},
    ]}
    c = CreativeCampaign(product_id=product.id, external_ref=f"mural-p{n}-il1", campaign_id="cmp_1", mode=mode, status="completed", quality="economy",
                         budget_usd=1.0, manifest=manifest)
    session.add(c)
    session.flush()
    return c


def test_public_media_link_needs_the_right_signature_and_is_time_limited():
    sig = ig._sig(5, "d1", 2_000_000_000)
    assert ig.verify_media(5, "d1", 2_000_000_000, sig, now=1_900_000_000)
    assert not ig.verify_media(5, "d1", 2_000_000_000, "0" * 40, now=1_900_000_000)  # assinatura errada
    assert not ig.verify_media(6, "d1", 2_000_000_000, sig, now=1_900_000_000)  # de outro criativo
    assert not ig.verify_media(5, "d2", 2_000_000_000, sig, now=1_900_000_000)  # de outra peça
    assert not ig.verify_media(5, "d1", 2_000_000_000, sig, now=2_000_000_001)  # vencido


def test_caption_points_to_the_bio_link_and_discloses_affiliation(session):
    _cards(session)
    c = _creative(session)
    cap = ig.default_caption(session, c.id)
    text = cap["caption"]
    assert "Link na bio: mural.felixsystems.com.br" in text and "link de afiliado" in text and len(text) <= ig.CAPTION_MAX
    assert "Ver na loja" not in text.split("👉")[0]  # o link da vitrine do texto do criativo sai
    assert cap["deliverable_id"] == "d1"


def test_publish_creates_container_waits_and_publishes(session, meta):
    _cards(session)
    c = _creative(session)
    post = ig.publish_image(session, c.id, caption="Texto do post", actor="dono", sleep=lambda s: None)
    media = dict(meta.posts)["ig_77/media"]
    assert media["image_url"].startswith("https://app.exemplo.com/api/public/media/") and ".jpg?exp=" in media["image_url"] and media["caption"] == "Texto do post"
    assert dict(meta.posts)["ig_77/media_publish"]["creation_id"] == "container_1"
    assert (post.status, post.external_id, post.permalink) == ("published", "media_9", "https://www.instagram.com/p/ABC/")
    assert ig.list_posts(session)[0]["permalink"] == "https://www.instagram.com/p/ABC/"


def test_sandbox_creative_and_bad_text_do_not_publish_and_failure_is_recorded(session, meta, monkeypatch):
    _cards(session)
    with pytest.raises(ig.InstagramError, match="teste"):
        ig.publish_image(session, _creative(session, mode="sandbox", n=2).id, caption="x", actor="dono")
    live = _creative(session)
    with pytest.raises(ig.InstagramError, match="1 a 2200"):
        ig.publish_image(session, live.id, caption="  ", actor="dono")
    assert not meta.posts
    meta.container_status = ["ERROR"]
    with pytest.raises(ig.InstagramError, match="processar"):
        ig.publish_image(session, live.id, caption="ok", actor="dono", sleep=lambda s: None)
    failed = session.query(SocialPost).one()
    assert failed.status == "failed" and "processar" in failed.error and not any(p.endswith("/media_publish") for p, _ in meta.posts)


def test_reel_needs_the_slideshow_then_publishes_with_a_signed_video_link(session, meta, tmp_path, monkeypatch):
    from core.services import reels

    monkeypatch.setenv("REELS_DIR", str(tmp_path))
    _cards(session)
    c = _creative(session)
    with pytest.raises(ig.InstagramError, match="gere o slideshow"):
        ig.publish_reel(session, c.id, caption="Reel da garrafa", actor="dono")
    reels.reel_path(c.id).write_bytes(b"mp4")
    post = ig.publish_reel(session, c.id, caption="Reel da garrafa", actor="dono", sleep=lambda s: None)
    media = dict(meta.posts)["ig_77/media"]
    assert media["media_type"] == "REELS" and "/api/public/video/" in media["video_url"] and "&sig=" in media["video_url"]
    assert (post.kind, post.status, post.external_id) == ("reel", "published", "media_9")
    exp = int(media["video_url"].split("exp=")[1].split("&")[0])
    assert ig.verify_media(c.id, "reel", exp, media["video_url"].split("sig=")[1], now=exp - 10)
    assert not ig.verify_media(c.id, "d1", exp, media["video_url"].split("sig=")[1], now=exp - 10)  # o link do vídeo não abre imagem
