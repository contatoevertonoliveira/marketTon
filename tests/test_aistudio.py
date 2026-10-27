"""Cliente do AI Studio (contrato v1): sandbox por padrão, travas de gasto, idempotência e webhook assinado.

O AI Studio é simulado (`requests.request`). O que os testes travam:

* geração ao vivo só com a permissão ligada no cartão e dentro do teto em US$;
* o corpo enviado leva a foto real, preço, alegações proibidas e NADA interno (comissão, custo, pontuação);
* produto sensível ou sem link/foto não vira anúncio;
* webhook: assinatura HMAC conferida, janela de 5 min, duplicado ignorado, eventos atualizam estado, custo e manifesto.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime

import pytest

from core.db.base import ConnectorKind, Marketplace
from core.db.catalog import Product, SourceRecord
from core.db.creatives import CreativeCampaign
from core.db.service_credentials import ServiceCredential
from core.services import aistudio as ai

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
BASE = "https://studio.exemplo.com/api/v1"
SECRET = "segredo-do-webhook"


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body, self.ok = status, body if body is not None else {}, status < 400

    def json(self):
        return self._body


@pytest.fixture
def net(monkeypatch):
    class N:
        calls: list = []
        routes: dict = {}

    n = N()
    n.calls, n.routes = [], {}

    def request(method, url, headers=None, timeout=None, **kw):
        n.calls.append((method, url.replace(BASE, ""), headers or {}, kw))
        for (m, path), resp in n.routes.items():
            if m == method and url.replace(BASE, "").startswith(path):
                return resp(kw) if callable(resp) else resp
        raise AssertionError(f"chamada inesperada {method} {url}")

    monkeypatch.setattr(ai.requests, "request", request)
    monkeypatch.setattr(ai, "LOGO_PATH", ai.LOGO_PATH.parent / "nao-existe.png")  # sem upload de logo nestes testes
    return n


def _config(session, **over):
    values = {"base_url": BASE, "api_key": "chave-secreta", "webhook_secret": SECRET, "callback_url": "https://app.exemplo.com/api/hook", **over}
    session.add(ServiceCredential(service="aistudio", enabled=True, values=values))
    session.flush()


def _product(session, title="Garrafa Térmica Inox 1L", affiliate="https://s.shopee.com.br/x", image="https://cf.shopee.com.br/file/a"):
    source = SourceRecord(marketplace=Marketplace.SHOPEE, connector="shopee", connector_kind=ConnectorKind.OFFICIAL_API, endpoint="x",
                          external_id=title[:10], collected_at=NOW)
    session.add(source)
    session.flush()
    p = Product(marketplace=Marketplace.SHOPEE, external_id=title[:10], title=title, price=129.9, original_price=179.9, affiliate_url=affiliate,
                images=[image] if image else None, affiliate_commission_pct=51.5, rating=4.8, sold_quantity=120, source_record_id=source.id,
                first_seen_at=NOW, last_seen_at=NOW)
    session.add(p)
    session.flush()
    return p


CREATED = _Resp(202, {"campaign_id": "cmp_1", "status": "queued", "estimate": {"usd": {"min": 0.5, "max": 0.9}}})


def test_card_check_and_missing_config(session, net):
    with pytest.raises(ai.AIStudioError, match="não está configurado"):
        ai.estimate(session, 1)
    _config(session)
    net.routes[("GET", "/capabilities")] = _Resp(200, {"qualities": ["economy", "standard", "premium"]})
    msg = ai.check(ai.load_config(session))
    assert "somente sandbox" in msg and "economy" in msg
    net.routes[("GET", "/capabilities")] = _Resp(401, {})
    with pytest.raises(ai.AIStudioError, match="recusou a chave"):
        ai.check(ai.load_config(session))


def test_sandbox_campaign_sends_the_real_photo_and_nothing_internal(session, net):
    _config(session)
    product = _product(session)
    net.routes[("POST", "/campaigns")] = CREATED
    record = ai.create(session, product.id, actor="claude_agent")
    method, path, headers, kw = net.calls[-1]
    body = kw["json"]
    assert (method, path) == ("POST", "/campaigns") and headers["Authorization"] == "Bearer chave-secreta"
    assert headers["Idempotency-Key"] == record.external_ref and body["external_ref"] == record.external_ref
    assert body["mode"] == "sandbox" and body["budget"]["max_usd"] == 2.0 and body["approval"] == {"mode": "none"}
    assert body["product"]["images"] == [{"url": "https://cf.shopee.com.br/file/a", "role": "main"}]
    assert body["product"]["price"] == {"amount": 129.9, "currency": "BRL", "compare_at": 179.9}
    assert "cura" in body["product"]["forbidden_claims"] and body["compliance"]["ai_disclosure"] is True
    assert body["callback"]["url"] == "https://app.exemplo.com/api/hook" and body["brand"]["colors"]["primary"] == "#A71920"
    text = json.dumps(body, ensure_ascii=False)
    assert "51.5" not in text and "commission" not in text and "affiliate" not in text.lower()  # nada de comissão nem link de afiliado
    assert (record.campaign_id, record.status, record.mode) == ("cmp_1", "queued", "sandbox")


def test_live_needs_the_operator_permission_and_respects_the_cap(session, net):
    _config(session)
    product = _product(session)
    with pytest.raises(ai.AIStudioError, match="Permitir geração ao vivo"):
        ai.create(session, product.id, mode="live")
    assert not [c for c in net.calls if c[0] == "POST"]  # nada foi enviado

    session.query(ServiceCredential).delete()
    _config(session, allow_live="sim", max_usd="1,5")
    with pytest.raises(ai.AIStudioError, match="passa do teto"):
        ai.create(session, product.id, mode="live", budget_usd=3)
    net.routes[("POST", "/campaigns")] = CREATED
    live = ai.create(session, product.id, mode="live", budget_usd=1.2)
    assert live.mode == "live" and net.calls[-1][3]["json"]["budget"]["max_usd"] == 1.2


def test_unsafe_or_incomplete_products_never_become_ads(session, net):
    _config(session)
    net.routes[("POST", "/campaigns")] = CREATED
    for bad in (_product(session, "Gel Aumento Peniano Potente"), _product(session, "Sem Link", affiliate=None), _product(session, "Sem Foto Aqui", image=None)):
        with pytest.raises(ai.AIStudioError, match="não pode virar anúncio"):
            ai.create(session, bad.id)
    assert session.query(CreativeCampaign).count() == 0


def test_a_failed_request_keeps_the_ref_and_marks_the_attempt(session, net):
    _config(session)
    product = _product(session)
    net.routes[("POST", "/campaigns")] = _Resp(503, {"error": {"code": "capacity_unavailable", "message": "provedores fora", "retryable": True}})
    with pytest.raises(ai.AIStudioError, match="provedores fora") as info:
        ai.create(session, product.id)
    assert info.value.retryable is True
    row = session.query(CreativeCampaign).one()
    assert row.status == "failed" and row.external_ref and "provedores fora" in row.error


def _signed(secret, body: dict, ts=None, event_id="evt_1"):
    raw = json.dumps({"event_id": event_id, **body}).encode()
    ts = int(ts if ts is not None else time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    return raw, {"X-AIStudio-Timestamp": str(ts), "X-AIStudio-Signature": f"v1={sig}", "X-AIStudio-Event-Id": event_id}


def _campaign(session, net):
    _config(session)
    product = _product(session)
    net.routes[("POST", "/campaigns")] = CREATED
    return ai.create(session, product.id)


def test_webhook_signature_window_and_dedup(session, net):
    record = _campaign(session, net)
    event = {"event": "campaign.started", "campaign_id": "cmp_1", "external_ref": record.external_ref, "data": {"status": "planning"}}
    raw, headers = _signed(SECRET, event)
    assert ai.handle_webhook(session, raw, headers) == "ok" and record.status == "planning"
    assert ai.handle_webhook(session, raw, headers) == "duplicate"  # o mesmo evento de novo: ignorado
    for bad_raw, bad_headers in (_signed("outro-segredo", event, event_id="e2"), _signed(SECRET, event, ts=time.time() - 3600, event_id="e3")):
        with pytest.raises(ai.AIStudioError) as info:
            ai.handle_webhook(session, bad_raw, bad_headers)
        assert info.value.code == "bad_signature"
    tampered = raw.replace(b"planning", b"completed")
    with pytest.raises(ai.AIStudioError):
        ai.handle_webhook(session, tampered, headers)


def test_webhook_events_update_pieces_cost_and_final_state(session, net):
    record = _campaign(session, net)
    ref = {"campaign_id": "cmp_1", "external_ref": record.external_ref}
    piece = {"id": "dlv_001", "kind": "video", "channel": "instagram_reels", "variant": "A", "aspect_ratio": "9:16", "duration_s": 15.0, "status": "ready",
             "url_signed": {"href": "https://studio.exemplo.com/d/1?sig=x", "expires_at": "2026-10-23T00:00:00Z"}}
    copy = {"id": "dlv_002", "kind": "copy", "channel": "instagram", "status": "ready", "content": {"caption": "Gelada por 24 h", "hashtags": ["#garrafa"]}}
    for i, (event, data) in enumerate((("campaign.deliverable_ready", {"deliverable": piece}), ("campaign.deliverable_ready", {"deliverable": copy}),
                                       ("campaign.progress", {"cost": {"spent_usd": 0.4}}),
                                       ("campaign.completed", {"status": "completed", "cost": {"spent_usd": 0.71}}))):
        raw, headers = _signed(SECRET, {"event": event, "data": data, **ref}, event_id=f"evt_{i}")
        ai.handle_webhook(session, raw, headers)
    assert (record.status, record.cost_usd) == ("completed", 0.71) and record.finished_at is not None
    pieces = {d["id"]: d for d in ai.deliverables(record)}
    assert pieces["dlv_001"]["download"].startswith("https://studio.exemplo.com/d/1") and pieces["dlv_002"]["content"]["caption"] == "Gelada por 24 h"
    assert "download" not in pieces["dlv_002"]


def test_reconcile_recovers_a_lost_webhook(session, net):
    record = _campaign(session, net)
    net.routes[("GET", "/campaigns/cmp_1")] = _Resp(200, {"status": "completed", "cost": {"spent_usd": 0.5}, "manifest": {"deliverables": [
        {"id": "d1", "kind": "image", "status": "ready", "url": "https://x/1"}, {"id": "d0", "kind": "image", "status": "superseded"}]}})
    assert ai.reconcile(session) == 1
    assert (record.status, record.cost_usd) == ("completed", 0.5) and [d["id"] for d in ai.deliverables(record)] == ["d1"]
    assert ai.reconcile(session) == 0  # já é final: nada a reconciliar


def test_images_only_has_no_video_and_uses_only_true_benefits(session, net):
    _config(session)
    product = _product(session)
    net.routes[("POST", "/campaigns")] = CREATED
    record = ai.create(session, product.id, formats="images", quality="standard")
    body = net.calls[-1][3]["json"]
    kinds = [(d["kind"], d.get("aspect_ratio")) for d in body["deliverables"]]
    assert kinds == [("image", "4:5"), ("image", "1:1"), ("image", "9:16"), ("copy", None), ("slideshow", None)] and "-i" in record.external_ref
    assert body["creative"]["music"]["enabled"] is False and "merchandising" in body["creative"]["notes"]
    assert "Não desenhar texto" in body["creative"]["notes"]
    assert body["product"]["benefits"] == ["Nota 4,8 na Shopee", "120 vendidos", "Preço abaixo do anterior (28% menos)"]  # só o que o marketTon sabe
    assert body["creative"]["offer"] == {"headline": "De R$ 179,90 por R$ 129,90"}
    assert body["product"]["category"] == "casa_cozinha"  # categoria da loja traduzida para a do estúdio


def test_unknown_formats_are_rejected(session, net):
    _config(session)
    with pytest.raises(ai.AIStudioError, match="parâmetros inválidos"):
        ai.create(session, _product(session).id, formats="gif")
