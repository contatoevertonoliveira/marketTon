"""Publicação automática: o agente só publica com a chave ligada, parecer aprovado, texto com divulgação e dentro do teto do dia.

O Instagram é simulado. O que os testes travam: cada trava recusa com o motivo e, quando tudo está certo, publica e conta no teto do dia.
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
from core.db.content_review import CreativeReview
from core.db.creatives import CreativeCampaign
from core.db.service_credentials import ServiceCredential
from core.db.social import SocialPost
from core.services import content_pipeline as cp
from core.services import instagram as ig

NOW = datetime.now(UTC)


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s
    engine.dispose()


def _cards(session):
    ok = {"last_check_status": "ok"}
    session.add_all([
        ServiceCredential(service="storefront", enabled=True, values={"base_url": "https://x.com", "admin_token": "t",
                                                                       "public_url": "https://mural.felixsystems.com.br"}, **ok),
        ServiceCredential(service="aistudio", enabled=True, values={"base_url": "http://studio/api/v1", "api_key": "k", "webhook_secret": "s",
                                                                     "callback_url": "https://app.exemplo.com/api/hook"}, **ok),
    ])
    session.flush()


def _creative(session, n=1, mode="live"):
    source = SourceRecord(marketplace=Marketplace.SHOPEE, connector="shopee", connector_kind=ConnectorKind.OFFICIAL_API, endpoint="x",
                          external_id=f"p{n}", collected_at=NOW)
    session.add(source)
    session.flush()
    product = Product(marketplace=Marketplace.SHOPEE, external_id=f"p{n}", title=f"Garrafa {n}", price=50.0, source_record_id=source.id,
                      first_seen_at=NOW, last_seen_at=NOW)
    session.add(product)
    session.flush()
    manifest = {"deliverables": [
        {"id": "d1", "kind": "image", "status": "ready", "aspect_ratio": "4:5", "url_signed": {"href": "https://s/d/1"}},
        {"id": "d2", "kind": "copy", "status": "ready", "content": {"headline": "Gelada", "caption": "Sua água gelada o dia todo."}},
    ]}
    c = CreativeCampaign(product_id=product.id, external_ref=f"mural-p{n}", campaign_id=f"c{n}", mode=mode, status="completed", quality="economy",
                         budget_usd=1.0, manifest=manifest)
    session.add(c)
    session.flush()
    return c


GOOD = "Sua água gelada.\n\n👉 Link na bio: mural.felixsystems.com.br\nDivulgação: link de afiliado, podemos receber comissão.\n\n#achadinhos"


@pytest.fixture
def fake_publish(monkeypatch):
    calls = []

    def publish_image(session, creative_id, *, caption, actor, **kw):
        calls.append(("image", creative_id, actor))
        p = SocialPost(platform="instagram", kind="image", creative_campaign_id=creative_id, caption=caption, status="published", external_id="m1",
                       created_by=actor)
        session.add(p)
        session.flush()
        return p

    monkeypatch.setattr(ig, "publish_image", publish_image)
    return calls


def test_every_gate_refuses_with_a_reason(session, fake_publish):
    _cards(session)
    c = _creative(session)
    with pytest.raises(cp.ContentError, match="desligada"):
        cp.auto_publish(session, c.id, "image", caption=GOOD, actor="agente")
    cp.set_settings(session, enabled=True, max_per_day=2, actor="dono")
    with pytest.raises(cp.ContentError, match="parecer APROVADO"):
        cp.auto_publish(session, c.id, "image", caption=GOOD, actor="agente")
    cp.submit_review(session, c.id, "image", "approved", "conferi", "agente")
    with pytest.raises(cp.ContentError, match="aviso de divulgação"):
        cp.auto_publish(session, c.id, "image", caption="Compre já!", actor="agente")  # texto sem divulgação
    assert not fake_publish


def test_approved_review_publishes_once_and_counts_against_the_daily_cap(session, fake_publish):
    _cards(session)
    cp.set_settings(session, enabled=True, max_per_day=1, actor="dono")
    a, b = _creative(session, 1), _creative(session, 2)
    for c in (a, b):
        cp.submit_review(session, c.id, "image", "approved", "ok", "agente")
    cp.auto_publish(session, a.id, "image", caption=GOOD, actor="agente")
    assert fake_publish == [("image", a.id, "agente")] and cp.published_today(session) == 1
    with pytest.raises(cp.ContentError, match="já foi publicado"):
        cp.auto_publish(session, a.id, "image", caption=GOOD, actor="agente")
    with pytest.raises(cp.ContentError, match="teto de 1"):
        cp.auto_publish(session, b.id, "image", caption=GOOD, actor="agente")  # o teto do dia vale para todos os criativos


def test_a_newer_rejection_or_an_old_review_blocks(session, fake_publish):
    _cards(session)
    cp.set_settings(session, enabled=True, max_per_day=3, actor="dono")
    c = _creative(session)
    cp.submit_review(session, c.id, "image", "approved", "ok", "agente")
    cp.submit_review(session, c.id, "image", "rejected", "título cobre o produto", "agente")  # mudou de ideia depois de ver de novo
    with pytest.raises(cp.ContentError, match="parecer APROVADO"):
        cp.auto_publish(session, c.id, "image", caption=GOOD, actor="agente")
    cp.submit_review(session, c.id, "image", "approved", "refeito", "agente")
    session.query(CreativeReview).update({"created_at": NOW - timedelta(hours=60)})
    with pytest.raises(cp.ContentError, match="48 h"):
        cp.auto_publish(session, c.id, "image", caption=GOOD, actor="agente")


def test_sandbox_never_publishes_and_a_rejection_needs_a_reason(session, fake_publish):
    _cards(session)
    cp.set_settings(session, enabled=True, max_per_day=3, actor="dono")
    t = _creative(session, mode="sandbox")
    with pytest.raises(cp.ContentError, match="ao vivo"):
        cp.auto_publish(session, t.id, "image", caption=GOOD, actor="agente")
    with pytest.raises(cp.ContentError, match="motivo"):
        cp.submit_review(session, _creative(session, 2).id, "image", "rejected", " ", "agente")
    with pytest.raises(cp.ContentError, match="entre 1 e 6"):
        cp.set_settings(session, enabled=True, max_per_day=9, actor="dono")


def test_pending_content_and_the_digest_only_wake_the_agent_when_it_can_publish(session, fake_publish):
    from core.services import agent_monitor

    _cards(session)
    a = _creative(session)
    assert cp.pending_content(session)[0]["missing"] == ["image", "reel"]
    since = NOW - timedelta(hours=1)
    assert agent_monitor.digest(session, since)["content"] == []  # chave desligada: não acorda o agente
    cp.set_settings(session, enabled=True, max_per_day=1, actor="dono")
    d = agent_monitor.digest(session, since)
    assert d["notable"] and "sem post e Reel" in d["content"][0]
    cp.submit_review(session, a.id, "image", "approved", "ok", "agente")
    cp.auto_publish(session, a.id, "image", caption=GOOD, actor="agente")
    assert agent_monitor.digest(session, since)["content"] == []  # teto do dia atingido: sem motivo para acordar
