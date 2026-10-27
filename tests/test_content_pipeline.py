"""Publicação automática: o agente só publica com a chave ligada, parecer aprovado, texto com divulgação, dentro da janela e do ritmo do dia.

O Instagram e o Facebook são simulados. O que os testes travam: cada trava recusa com o motivo; quando tudo está certo, publica nas duas redes,
conta no teto do dia, respeita uma publicação por janela (manhã, tarde, noite), intercala imagem e Reel e não repete produto no mesmo dia.
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
from core.services import facebook as fb
from core.services import instagram as ig

NOW = datetime.now(UTC)


def at(hour: int) -> datetime:
    """Hoje, nesta hora local (as janelas valem pela hora local)."""
    return datetime.now().astimezone().replace(hour=hour, minute=0, second=0, microsecond=0)


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
    """Instagram e Facebook simulados. O `created_at` do post é a hora do teste (`now`), não a hora real."""
    calls = {"ig": [], "fb": []}
    clock = {"now": at(9)}

    def make(platform, kind, creative_id, session, caption, actor):
        p = SocialPost(platform=platform, kind=kind, creative_campaign_id=creative_id, product_id=session.get(CreativeCampaign, creative_id).product_id,
                       caption=caption, status="published", external_id="m1", created_by=actor, created_at=clock["now"].astimezone(UTC), deliverable_id="d1")
        session.add(p)
        session.flush()
        return p

    monkeypatch.setattr(ig, "publish_image", lambda session, cid, *, caption, actor, **kw: (calls["ig"].append(("image", cid)), make("instagram", "image", cid, session, caption, actor))[1])
    monkeypatch.setattr(ig, "publish_reel", lambda session, cid, *, caption, actor, **kw: (calls["ig"].append(("reel", cid)), make("instagram", "reel", cid, session, caption, actor))[1])
    monkeypatch.setattr(fb, "caption", lambda session, cid: "texto do facebook")
    monkeypatch.setattr(fb, "publish_photo", lambda session, cid, *, text, deliverable_id, actor: (calls["fb"].append(("image", cid)), make("facebook", "image", cid, session, text, actor))[1])
    monkeypatch.setattr(fb, "publish_reel", lambda session, cid, *, text, actor, **kw: (calls["fb"].append(("reel", cid)), make("facebook", "reel", cid, session, text, actor))[1])
    calls["clock"] = clock
    return calls


def _ready(session, n=1, kinds=("image", "reel")):
    c = _creative(session, n)
    for k in kinds:
        cp.submit_review(session, c.id, k, "approved", "conferi", "agente")
    return c


def test_every_gate_refuses_with_a_reason(session, fake_publish):
    _cards(session)
    c = _creative(session)
    with pytest.raises(cp.ContentError, match="desligada"):
        cp.auto_publish(session, c.id, "image", caption=GOOD, actor="agente", now=at(9))
    cp.set_settings(session, enabled=True, max_per_day=3, actor="dono")
    with pytest.raises(cp.ContentError, match="parecer APROVADO"):
        cp.auto_publish(session, c.id, "image", caption=GOOD, actor="agente", now=at(9))
    cp.submit_review(session, c.id, "image", "approved", "conferi", "agente")
    with pytest.raises(cp.ContentError, match="aviso de divulgação"):
        cp.auto_publish(session, c.id, "image", caption="Compre já!", actor="agente", now=at(9))  # texto sem divulgação
    assert not fake_publish["ig"]


def test_publishes_on_both_networks_once_per_window_and_alternates_kinds(session, fake_publish):
    _cards(session)
    cp.set_settings(session, enabled=True, max_per_day=3, actor="dono")
    a, b, c = _ready(session, 1), _ready(session, 2), _ready(session, 3)

    fake_publish["clock"]["now"] = at(9)  # manhã: a primeira é imagem
    out = cp.auto_publish(session, a.id, "image", caption=GOOD, actor="agente", now=at(9))
    assert out["instagram"].platform == "instagram" and out["facebook"].platform == "facebook" and out["facebook_error"] is None
    with pytest.raises(cp.ContentError, match="da manhã já saiu"):
        cp.auto_publish(session, b.id, "reel", caption=GOOD, actor="agente", now=at(10))  # mesma janela

    with pytest.raises(cp.ContentError, match="fora das janelas"):
        cp.auto_publish(session, b.id, "reel", caption=GOOD, actor="agente", now=at(12))  # meio-dia: hora de preparar
    fake_publish["clock"]["now"] = at(15)  # tarde: a vez é do Reel
    with pytest.raises(cp.ContentError, match="a vez é de Reel"):
        cp.auto_publish(session, b.id, "image", caption=GOOD, actor="agente", now=at(15))
    cp.auto_publish(session, b.id, "reel", caption=GOOD, actor="agente", now=at(15))

    fake_publish["clock"]["now"] = at(20)  # noite: volta a vez da imagem, e o teto fecha o dia
    cp.auto_publish(session, c.id, "image", caption=GOOD, actor="agente", now=at(20))
    assert cp.published_today(session, at(21)) == 3 and cp.slots_used_today(session, at(21)) == {"morning", "afternoon", "evening"}
    assert [k for k, _ in fake_publish["ig"]] == ["image", "reel", "image"] and len(fake_publish["fb"]) == 3
    with pytest.raises(cp.ContentError, match="teto de 3"):
        cp.auto_publish(session, _ready(session, 4).id, "reel", caption=GOOD, actor="agente", now=at(22))


def test_the_same_product_is_not_published_twice_in_a_day_and_facebook_failure_does_not_block(session, fake_publish, monkeypatch):
    _cards(session)
    cp.set_settings(session, enabled=True, max_per_day=3, actor="dono")
    a = _ready(session, 1)
    fake_publish["clock"]["now"] = at(9)
    monkeypatch.setattr(fb, "publish_photo", lambda *a, **k: (_ for _ in ()).throw(fb.FacebookError("página sem permissão")))
    out = cp.auto_publish(session, a.id, "image", caption=GOOD, actor="agente", now=at(9))
    assert out["instagram"].status == "published" and out["facebook"] is None and "sem permissão" in out["facebook_error"]  # o Instagram saiu
    fake_publish["clock"]["now"] = at(15)
    with pytest.raises(cp.ContentError, match="produto já teve publicação hoje"):
        cp.auto_publish(session, a.id, "reel", caption=GOOD, actor="agente", now=at(15))  # mesmo produto, outro tipo, mesmo dia


def test_a_newer_rejection_or_an_old_review_blocks(session, fake_publish):
    _cards(session)
    cp.set_settings(session, enabled=True, max_per_day=3, actor="dono")
    c = _creative(session)
    cp.submit_review(session, c.id, "image", "approved", "ok", "agente")
    cp.submit_review(session, c.id, "image", "rejected", "título cobre o produto", "agente")  # mudou de ideia depois de ver de novo
    with pytest.raises(cp.ContentError, match="parecer APROVADO"):
        cp.auto_publish(session, c.id, "image", caption=GOOD, actor="agente", now=at(9))
    cp.submit_review(session, c.id, "image", "approved", "refeito", "agente")
    session.query(CreativeReview).update({"created_at": datetime.now(UTC) - timedelta(hours=60)})
    with pytest.raises(cp.ContentError, match="48 h"):
        cp.auto_publish(session, c.id, "image", caption=GOOD, actor="agente", now=at(9))


def test_sandbox_never_publishes_and_a_rejection_needs_a_reason(session, fake_publish):
    _cards(session)
    cp.set_settings(session, enabled=True, max_per_day=3, actor="dono")
    t = _creative(session, mode="sandbox")
    with pytest.raises(cp.ContentError, match="ao vivo"):
        cp.auto_publish(session, t.id, "image", caption=GOOD, actor="agente", now=at(9))
    with pytest.raises(cp.ContentError, match="motivo"):
        cp.submit_review(session, _creative(session, 2).id, "image", "rejected", " ", "agente")
    with pytest.raises(cp.ContentError, match="entre 1 e 3"):
        cp.set_settings(session, enabled=True, max_per_day=5, actor="dono")


def test_the_digest_only_wakes_the_agent_when_a_window_is_open_and_it_can_publish(session, fake_publish, monkeypatch):
    from core.services import agent_monitor

    _cards(session)
    a = _creative(session)
    assert cp.pending_content(session)[0]["missing"] == ["image", "reel"]
    since = NOW - timedelta(hours=1)
    monkeypatch.setattr(cp, "current_slot", lambda now=None: "morning")
    assert agent_monitor.digest(session, since)["content"] == []  # chave desligada: não acorda o agente
    cp.set_settings(session, enabled=True, max_per_day=3, actor="dono")
    d = agent_monitor.digest(session, since)
    assert d["notable"] and "sem post e Reel" in d["content"][0]
    monkeypatch.setattr(cp, "current_slot", lambda now=None: None)  # meio-dia: nenhuma janela aberta
    assert agent_monitor.digest(session, since)["content"] == []
    monkeypatch.setattr(cp, "current_slot", lambda now=None: "morning")
    cp.submit_review(session, a.id, "image", "approved", "ok", "agente")
    fake_publish["clock"]["now"] = at(9)
    cp.auto_publish(session, a.id, "image", caption=GOOD, actor="agente", now=at(9))
    assert agent_monitor.digest(session, since)["content"] == []  # a janela da manhã já foi usada
