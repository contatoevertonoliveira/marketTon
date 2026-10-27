"""Publicar na Página do Facebook: foto por link público assinado e Reel em três passos (iniciar, enviar por link, finalizar).

A Meta é simulada. O que os testes travam: o texto do Facebook leva o link do produto clicável (e não "link na bio"); a foto e o Reel usam o
link assinado do marketTon; o Reel só finaliza depois de o Facebook receber o vídeo; falha vira erro claro e fica no histórico.
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
from core.services import facebook as fb
from core.services import meta_ads, reels

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
        uploads: list = []
        upload_status: list = []

    m = M()
    m.posts, m.uploads, m.upload_status = [], [], ["in_progress", "complete"]

    def post(url, data=None, headers=None, timeout=None, **kw):
        if "rupload" in url:
            m.uploads.append((url, headers))
            return _Resp(200, {"success": True})
        path = url.split("/v21.0/")[1]
        m.posts.append((path, dict(data or {})))
        if path.endswith("/photos"):
            return _Resp(200, {"id": "ph_1", "post_id": "999_555"})
        if path.endswith("/video_reels") and (data or {}).get("upload_phase") == "start":
            return _Resp(200, {"video_id": "vid_9", "upload_url": "https://rupload.facebook.com/video-upload/v21.0/vid_9"})
        if path.endswith("/video_reels"):
            return _Resp(200, {"success": True})
        raise AssertionError(path)

    def get(url, params=None, timeout=None):
        if url.endswith("/999"):
            return _Resp(200, {"access_token": "pagetoken"})
        if url.endswith("/vid_9"):
            if (params or {}).get("fields") == "status":
                return _Resp(200, {"status": {"uploading_phase": {"status": m.upload_status.pop(0) if m.upload_status else "complete"}}})
            return _Resp(200, {"permalink_url": "/muralnaweb/videos/vid_9/"})
        if url.endswith("/999_555"):
            return _Resp(200, {"permalink_url": "https://www.facebook.com/muralnaweb/posts/555"})
        raise AssertionError(f"GET inesperado {url}")

    monkeypatch.setattr(fb.requests, "post", post)
    monkeypatch.setattr(meta_ads.requests, "get", get)
    return m


def _cards(session):
    ok = {"last_check_status": "ok"}
    session.add_all([
        ServiceCredential(service="meta_ads", enabled=True, values={"access_token": "tok", "ad_account_id": "123", "page_id": "999"}, **ok),
        ServiceCredential(service="storefront", enabled=True, values={"base_url": "https://x.com", "admin_token": "t",
                                                                       "public_url": "https://mural.felixsystems.com.br"}, **ok),
        ServiceCredential(service="aistudio", enabled=True, values={"base_url": "http://studio/api/v1", "api_key": "k", "webhook_secret": "s",
                                                                     "callback_url": "https://app.exemplo.com/api/hook"}, **ok),
    ])
    session.flush()


def _creative(session):
    source = SourceRecord(marketplace=Marketplace.SHOPEE, connector="shopee", connector_kind=ConnectorKind.OFFICIAL_API, endpoint="x",
                          external_id="p1", collected_at=NOW)
    session.add(source)
    session.flush()
    product = Product(marketplace=Marketplace.SHOPEE, external_id="p1", title="Garrafa", price=50.0, source_record_id=source.id,
                      first_seen_at=NOW, last_seen_at=NOW)
    session.add(product)
    session.flush()
    manifest = {"deliverables": [
        {"id": "d1", "kind": "image", "status": "ready", "aspect_ratio": "4:5", "url_signed": {"href": "https://s/d/1"}},
        {"id": "d2", "kind": "copy", "status": "ready", "content": {"headline": "Gelada", "caption": "Sua água gelada o dia todo."}},
    ]}
    c = CreativeCampaign(product_id=product.id, external_ref="mural-p1", campaign_id="c1", mode="live", status="completed", quality="economy",
                         budget_usd=1.0, manifest=manifest)
    session.add(c)
    session.flush()
    return c


def test_caption_has_the_clickable_product_link_instead_of_link_na_bio(session):
    _cards(session)
    c = _creative(session)
    text = fb.caption(session, c.id)
    assert "Link na bio" not in text and f"https://mural.felixsystems.com.br/p/p{c.product_id}?utm_source=facebook&utm_medium=organic" in text
    assert "link de afiliado" in text  # a divulgação continua


def test_photo_uses_the_signed_public_link_and_is_recorded(session, meta):
    _cards(session)
    c = _creative(session)
    post = fb.publish_photo(session, c.id, text="Texto", deliverable_id="d1", actor="agente")
    data = dict(meta.posts)["999/photos"]
    assert data["url"].startswith("https://app.exemplo.com/api/public/media/") and data["published"] == "true" and data["caption"] == "Texto"
    assert (post.platform, post.status, post.external_id, post.permalink) == ("facebook", "published", "999_555", "https://www.facebook.com/muralnaweb/posts/555")


def test_reel_finishes_only_after_the_video_is_received(session, meta, tmp_path, monkeypatch):
    monkeypatch.setenv("REELS_DIR", str(tmp_path))
    _cards(session)
    c = _creative(session)
    with pytest.raises(fb.FacebookError, match="gere o slideshow"):
        fb.publish_reel(session, c.id, text="Reel", actor="agente")
    reels.reel_path(c.id).write_bytes(b"mp4")
    post = fb.publish_reel(session, c.id, text="Reel", actor="agente", sleep=lambda s: None)
    phases = [d.get("upload_phase") for p, d in meta.posts if p.endswith("/video_reels")]
    assert phases == ["start", "finish"] and meta.uploads[0][1]["file_url"].startswith("https://app.exemplo.com/api/public/video/")
    finish = [d for p, d in meta.posts if d.get("upload_phase") == "finish"][0]
    assert finish["video_state"] == "PUBLISHED" and finish["description"] == "Reel"
    assert (post.status, post.permalink) == ("published", "https://www.facebook.com/muralnaweb/videos/vid_9/")


def test_a_failed_reel_is_recorded_and_never_finishes(session, meta, tmp_path, monkeypatch):
    monkeypatch.setenv("REELS_DIR", str(tmp_path))
    _cards(session)
    c = _creative(session)
    reels.reel_path(c.id).write_bytes(b"mp4")
    meta.upload_status = ["error"]
    with pytest.raises(fb.FacebookError, match="não conseguiu receber"):
        fb.publish_reel(session, c.id, text="Reel", actor="agente", sleep=lambda s: None)
    assert session.query(SocialPost).one().status == "failed" and not any(d.get("upload_phase") == "finish" for _, d in meta.posts)
