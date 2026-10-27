"""Anúncios na Meta: criar sempre pausado, só o operador liga, travas de orçamento e leitura das métricas.

A Meta é simulada. O que os testes travam:

* `dry_run` (padrão) não chama a Meta; criativo de teste (sandbox) nunca vira anúncio de verdade;
* o anúncio nasce PAUSADO em campanha, conjunto e anúncio; verba em centavos; destino = página do produto na loja com UTM;
* as travas (verba por dia, compromisso da semana, criativos por produto, produtos por semana) recusam o excesso;
* ligar reconfere as travas e define o fim da veiculação; pausar e "pausar tudo" funcionam;
* métricas vêm da Meta (gasto, impressões, cliques de link) e nunca são estimadas.
"""
from __future__ import annotations

from datetime import timedelta, UTC, datetime

import pytest

from core.db.ads import AdCampaign
from core.db.base import ConnectorKind, Marketplace
from core.db.catalog import Product, SourceRecord
from core.db.creatives import CreativeCampaign
from core.db.service_credentials import ServiceCredential
from core.services import meta_ads
from core.services import meta_campaigns as mc

NOW = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)  # hoje ao meio-dia: created_at do banco é a hora real


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body, self.ok = status, body if body is not None else {}, status < 400

    def json(self):
        return self._body


@pytest.fixture
def meta(monkeypatch):
    class M:
        posts: list = []
        gets: dict = {}
        counter = 0

    m = M()
    m.posts, m.gets = [], {}

    def post(url, data=None, timeout=None, **kw):
        path = url.split("/v21.0/")[1]
        m.posts.append((path, dict(data or {})))
        M.counter += 1
        if path.endswith("/adimages"):
            return _Resp(200, {"images": {"bytes": {"hash": "hash_abc"}}})
        return _Resp(200, {"id": f"id_{M.counter}"})

    def get(url, params=None, timeout=None):
        for fragment, body in m.gets.items():
            if fragment in url:
                return _Resp(200, body)
        raise AssertionError(f"GET inesperado {url}")

    monkeypatch.setattr(mc.requests, "post", post)
    monkeypatch.setattr(mc.aistudio, "fetch_file", lambda session, creative, dlv: (b"PNGDATA", "image/png"))
    monkeypatch.setattr(meta_ads.requests, "get", get)
    return m


def path_ids(meta):
    return {p for p, _ in meta.posts}


def _cards(session, weekly="140", daily="20", products="2", creatives="2"):
    ok = {"last_check_status": "ok"}
    session.add_all([
        ServiceCredential(service="meta_ads", enabled=True, values={"access_token": "tok", "ad_account_id": "123", "page_id": "999"}, **ok),
        ServiceCredential(service="ads_budget", enabled=True, values={"weekly_brl": weekly, "daily_cap_brl": daily, "max_products": products,
                                                                       "creatives_per_product": creatives}, **ok),
        ServiceCredential(service="storefront", enabled=True, values={"base_url": "https://felixsystems.com.br", "admin_token": "t",
                                                                       "public_url": "https://mural.felixsystems.com.br"}, **ok),
    ])
    session.flush()


def _creative(session, n=1, mode="live", status="completed", with_pieces=True):
    source = SourceRecord(marketplace=Marketplace.SHOPEE, connector="shopee", connector_kind=ConnectorKind.OFFICIAL_API, endpoint="x",
                          external_id=f"p{n}", collected_at=NOW)
    session.add(source)
    session.flush()
    product = Product(marketplace=Marketplace.SHOPEE, external_id=f"p{n}", title=f"Garrafa {n}", price=50.0, source_record_id=source.id,
                      first_seen_at=NOW, last_seen_at=NOW)
    session.add(product)
    session.flush()
    manifest = {"deliverables": [
        {"id": "d1", "kind": "image", "status": "ready", "aspect_ratio": "4:5", "url_signed": {"href": "https://studio.exemplo.com/d/1?sig=x"}},
        {"id": "d2", "kind": "copy", "status": "ready", "content": {"headline": "Gelada por 24 h", "caption": "Sua água gelada o dia todo. Veja na loja."}},
    ]} if with_pieces else {"deliverables": []}
    creative = CreativeCampaign(product_id=product.id, external_ref=f"mural-p{n}-il1", campaign_id=f"cmp_{n}", mode=mode, status=status,
                                quality="standard", budget_usd=2.0, manifest=manifest)
    session.add(creative)
    session.flush()
    return creative


def test_dry_run_shows_the_plan_without_calling_meta_and_sandbox_never_goes_live(session, meta):
    _cards(session)
    creative = _creative(session, mode="sandbox")
    out = mc.create_ad(session, creative.id, daily_brl=10, days=3, now=NOW)
    assert out["dry_run"] is True and not meta.posts
    plan = out["plan"]
    assert plan["objective"] == "OUTCOME_TRAFFIC" and plan["headline"] == "Gelada por 24 h" and plan["targeting"]["geo_locations"] == {"countries": ["BR"]}
    assert plan["link"].startswith(f"https://mural.felixsystems.com.br/p/p{creative.product_id}?utm_source=meta&utm_medium=paid&utm_campaign=mural-")
    with pytest.raises(mc.AdsError, match="sandbox"):
        mc.create_ad(session, creative.id, daily_brl=10, days=3, dry_run=False, now=NOW)
    assert not meta.posts and session.query(AdCampaign).count() == 0


def test_real_creation_makes_everything_paused_with_the_right_money(session, meta):
    _cards(session)
    creative = _creative(session)
    out = mc.create_ad(session, creative.id, daily_brl=12.5, days=3, dry_run=False, actor="claude_agent", now=NOW)
    paths = [p for p, _ in meta.posts]
    assert paths == ["act_123/campaigns", "act_123/adsets", "act_123/adimages", "act_123/adcreatives", "act_123/ads"]
    statuses = {p: d.get("status") for p, d in meta.posts}
    assert statuses["act_123/campaigns"] == statuses["act_123/adsets"] == statuses["act_123/ads"] == "PAUSED"  # nada gasta ao criar
    adset = dict(meta.posts)["act_123/adsets"]
    assert adset["daily_budget"] == 1250 and adset["optimization_goal"] == "LINK_CLICKS" and adset["billing_event"] == "IMPRESSIONS"
    assert "act_123/adcreatives" in paths and "hash_abc" in dict(meta.posts)["act_123/adcreatives"]["object_story_spec"]
    ad = session.get(AdCampaign, out["ad_id"])
    assert (ad.status, ad.meta_status, ad.daily_budget_brl, ad.duration_days, ad.created_by) == ("paused", "PAUSED", 12.5, 3, "claude_agent") and ad.external_ad_id


def test_budget_guards_refuse_the_excess(session, meta):
    _cards(session)  # semana 140, dia 20, 2 produtos, 2 criativos por produto
    c1, c2 = _creative(session, 1), _creative(session, 2)
    for bad, msg in ((dict(daily_brl=25, days=2), "fora do teto"), (dict(daily_brl=10, days=15), "duração"), (dict(daily_brl=0.0, days=2), "fora do teto")):
        with pytest.raises(mc.AdsError, match=msg):
            mc.create_ad(session, c1.id, now=NOW, **bad)
    mc.create_ad(session, c1.id, daily_brl=15, days=4, dry_run=False, now=NOW)  # compromete 60 na semana e 15/dia
    with pytest.raises(mc.AdsError, match="teto"):
        mc.create_ad(session, c2.id, daily_brl=10, days=2, now=NOW)  # 15 + 10 > 20 por dia
    mc.create_ad(session, c2.id, daily_brl=5, days=2, dry_run=False, now=NOW)  # 2º produto
    st = mc.budget_status(session, NOW)
    assert st["week_committed_brl"] == 70.0 and st["daily_committed_brl"] == 20.0 and st["week_products"] == 2


def test_products_per_week_is_a_hard_limit(session, meta):
    _cards(session, weekly="500", daily="100", products="2")
    creatives = [_creative(session, n) for n in (1, 2, 3)]
    for c in creatives[:2]:
        mc.create_ad(session, c.id, daily_brl=5, days=1, dry_run=False, now=NOW)
    with pytest.raises(mc.AdsError, match="máximo é 2"):
        mc.create_ad(session, creatives[2].id, daily_brl=5, days=1, now=NOW)


def test_weekly_value_is_a_hard_limit_and_creatives_per_product_too(session, meta):
    _cards(session, weekly="30", daily="20", creatives="1")
    c1 = _creative(session, 1)
    with pytest.raises(mc.AdsError, match="valor da semana"):
        mc.create_ad(session, c1.id, daily_brl=15, days=3, now=NOW)  # 45 > 30
    mc.create_ad(session, c1.id, daily_brl=10, days=3, dry_run=False, now=NOW)  # 30 = a semana inteira
    other = CreativeCampaign(product_id=c1.product_id, external_ref="mural-p1-il2", campaign_id="cmp_x", mode="live", status="completed", quality="standard",
                             budget_usd=2.0, manifest=c1.manifest)
    session.add(other)
    session.flush()
    with pytest.raises(mc.AdsError, match="valor da semana|máximo é 1"):
        mc.create_ad(session, other.id, daily_brl=1, days=1, now=NOW)


def test_incomplete_creatives_and_missing_setup_are_refused(session, meta):
    with pytest.raises(mc.AdsError, match="indisponível"):
        mc.create_ad(session, _creative(session, 9).id, daily_brl=5, days=1, now=NOW)  # sem loja configurada
    session.add(ServiceCredential(service="storefront", enabled=True, values={"base_url": "https://x.com", "admin_token": "t"}, last_check_status="ok"))
    session.flush()
    with pytest.raises(mc.AdsError, match="Orçamento de anúncios"):
        mc.create_ad(session, _creative(session, 8).id, daily_brl=5, days=1, now=NOW)  # sem orçamento definido
    session.query(ServiceCredential).delete()
    _cards(session)
    for n, kw, msg in ((5, dict(status="generating"), "só dá para anunciar criativo pronto"), (6, dict(with_pieces=False), "não tem imagem")):
        with pytest.raises(mc.AdsError, match=msg):
            mc.create_ad(session, _creative(session, n, **kw).id, daily_brl=5, days=1, now=NOW)


def test_only_activate_turns_on_and_it_sets_the_end_and_rechecks_the_cap(session, meta):
    _cards(session)
    ad_id = mc.create_ad(session, _creative(session).id, daily_brl=10, days=3, dry_run=False, now=NOW)["ad_id"]
    meta.posts.clear()
    ad = mc.activate(session, ad_id, actor="operador", now=NOW)
    assert ad.status == "active" and ad.started_at == NOW
    ends = [d["end_time"] for path, d in meta.posts if "end_time" in d]
    assert path_ids(meta) and ends == [int((NOW + timedelta(days=3)).timestamp())]  # 3 dias depois
    assert {d["status"] for _, d in meta.posts if "status" in d} == {"ACTIVE"}
    with pytest.raises(mc.AdsError, match="só dá para ligar"):
        mc.activate(session, ad_id, actor="operador", now=NOW)  # já ativo

    meta.posts.clear()
    mc.pause(session, ad_id)
    assert session.get(AdCampaign, ad_id).status == "paused" and {d["status"] for _, d in meta.posts} == {"PAUSED"}


def test_pause_all_is_the_stop_button(session, meta):
    _cards(session)
    ids = [mc.create_ad(session, _creative(session, n).id, daily_brl=8, days=2, dry_run=False, now=NOW)["ad_id"] for n in (1, 2)]
    for i in ids:
        mc.activate(session, i, actor="operador", now=NOW)
    assert mc.pause_all(session) == 2 and {session.get(AdCampaign, i).status for i in ids} == {"paused"}


def test_metrics_come_from_meta_and_a_finished_flight_is_marked_ended(session, meta):
    _cards(session)
    ad_id = mc.create_ad(session, _creative(session).id, daily_brl=10, days=1, dry_run=False, now=NOW)["ad_id"]
    ad = mc.activate(session, ad_id, actor="operador", now=NOW)
    meta.gets[ad.external_ad_id] = {"effective_status": "ACTIVE", "insights": {"data": [{"spend": "7.35", "impressions": "1800", "inline_link_clicks": "41"}]}}
    assert mc.sync_metrics(session, now=NOW + timedelta(hours=8)) == 1
    assert (ad.spent_brl, ad.impressions, ad.clicks, ad.status, ad.meta_status) == (7.35, 1800, 41, "active", "ACTIVE")
    meta.gets[ad.external_ad_id] = {"effective_status": "ACTIVE", "insights": {"data": []}}  # sem linha: nada muda, nada é inventado
    mc.sync_metrics(session, now=NOW + timedelta(days=1, hours=1))
    assert (ad.spent_brl, ad.status) == (7.35, "ended")  # passou do fim da veiculação


def test_stop_ends_for_good_and_remove_deletes_on_meta_and_frees_the_budget(session, meta):
    _cards(session)
    a, b = [mc.create_ad(session, _creative(session, n).id, daily_brl=8, days=2, dry_run=False, now=NOW)["ad_id"] for n in (1, 2)]
    mc.activate(session, a, actor="operador", now=NOW)
    meta.posts.clear()
    ad = mc.stop(session, a, now=NOW)
    assert ad.status == "ended" and ad.ended_at == NOW and {d["status"] for _, d in meta.posts} == {"PAUSED"}  # parou na Meta
    with pytest.raises(mc.AdsError, match="só dá para ligar"):
        mc.activate(session, a, actor="operador", now=NOW)  # parado não liga mais
    before = mc.budget_status(session, NOW)["week_committed_brl"]
    meta.posts.clear()
    removed = mc.remove(session, b)
    assert removed.status == "removed" and {d["status"] for _, d in meta.posts} == {"DELETED"} and len(meta.posts) == 3  # anúncio, conjunto, campanha
    assert mc.budget_status(session, NOW)["week_committed_brl"] == before - 16  # o excluído deixa de contar no compromisso
    assert mc.remove(session, b).status == "removed"  # de novo: nada acontece


def test_headline_is_cut_on_a_word_and_campaign_disables_budget_sharing(session, meta):
    assert mc._fit("Garrafa Infantil 500ml - Nota 5,0 na Shopee", 40) == "Garrafa Infantil 500ml - Nota 5,0 na"
    assert mc._fit("Curto", 40) == "Curto"
    _cards(session)
    mc.create_ad(session, _creative(session).id, daily_brl=10, days=3, dry_run=False, now=NOW)
    assert dict(meta.posts)["act_123/campaigns"]["is_adset_budget_sharing_enabled"] == "false"


def test_ad_on_an_existing_page_post_skips_the_image_and_checks_the_post(session, meta):
    _cards(session)
    creative = _creative(session)
    link = mc.build_plan(session, creative, daily_brl=1, days=1, check_budget=False)["link"]
    post = {"id": "999_555", "is_published": True, "attachments": {"data": [{"unshimmed_url": link}]}}
    meta.gets = {"999_555": post, "999/posts": {"data": [{**post, "message": "Garrafa", "full_picture": "https://img/x.jpg"}]}, "999": {"access_token": "pagetoken"}}

    kit = mc.post_kit(session, creative.id)
    assert kit["link"] == link and kit["headline"] == "Gelada por 24 h" and kit["image_file"] == f"/creatives/{creative.id}/files/d1"
    assert mc.list_page_posts(session)[0]["link"] == link

    plan = mc.create_ad(session, creative.id, daily_brl=10, days=3, now=NOW, post_id="555")["plan"]
    assert plan["post_id"] == "555" and not meta.posts  # ensaio: nada enviado
    out = mc.create_ad(session, creative.id, daily_brl=10, days=3, dry_run=False, now=NOW, post_id="555")
    paths = [p for p, _ in meta.posts]
    assert "act_123/adimages" not in paths and dict(meta.posts)["act_123/adcreatives"]["object_story_id"] == "999_555"
    assert "object_story_spec" not in dict(meta.posts)["act_123/adcreatives"] and session.get(AdCampaign, out["ad_id"]).status == "paused"


def test_a_post_without_the_product_link_or_not_published_is_refused(session, meta):
    _cards(session)
    creative = _creative(session)
    meta.gets = {"999_555": {"id": "999_555", "is_published": True, "attachments": {"data": [{"unshimmed_url": "https://outro-site.com/x"}]}},
                 "999": {"access_token": "pagetoken"}}
    with pytest.raises(mc.AdsError, match="não tem o link do produto"):
        mc.create_ad(session, creative.id, daily_brl=10, days=3, dry_run=False, now=NOW, post_id="555")
    link = mc.build_plan(session, creative, daily_brl=1, days=1, check_budget=False)["link"]
    meta.gets["999_555"] = {"id": "999_555", "is_published": False, "attachments": {"data": [{"unshimmed_url": link}]}}
    with pytest.raises(mc.AdsError, match="não está publicado"):
        mc.create_ad(session, creative.id, daily_brl=10, days=3, dry_run=False, now=NOW, post_id="555")
    assert not meta.posts and session.query(AdCampaign).count() == 0  # nada foi criado na Meta nem guardado
