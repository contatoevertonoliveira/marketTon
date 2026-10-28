"""Anúncios na Meta a partir de um criativo: criar (sempre PAUSADO), ligar (só o operador), pausar e ler as métricas.

Regras que valem aqui, todas em código e não em confiança:

* **Nada gasta ao ser criado.** Campanha, conjunto e anúncio nascem `PAUSED`. Quem liga é o operador (`activate`, endpoint que o papel do
  agente não tem). O agente pode pausar, nunca ligar.
* **Travas de orçamento** (cartão "Orçamento de anúncios"): verba diária por anúncio ≤ teto por dia; o que já está planejado ou ativo
  somado ao novo ≤ teto por dia; compromisso da semana (verba × dias) ≤ valor da semana; produtos distintos na semana ≤ máximo; anúncios
  por produto ≤ criativos por produto.
* **Criativo de teste (sandbox) nunca vira anúncio de verdade:** as peças do sandbox são amostras. Em `dry_run` (padrão) o sistema só mostra
  o que enviaria à Meta, sem chamar a Meta.
* Destino do anúncio = a página do produto na loja (com UTM); o clique de compra passa pelo link rastreado. A venda de afiliado não é atribuível
  ao anúncio: o resultado é lido como cliques/CTR/CPC (da Meta) e cliques de compra (nossos).
"""
from __future__ import annotations

import base64
import json
import logging
import re
from datetime import UTC, datetime, timedelta

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.ads import AdCampaign
from core.db.creatives import CreativeCampaign
from core.db.service_credentials import ServiceCredential
from core.services import aistudio, ads_budget, meta_ads, product_vetting, storefront

logger = logging.getLogger(__name__)
TIMEOUT = 40
MAX_DAYS = 14
OPEN_STATUSES = ("draft", "paused", "active")


class AdsError(RuntimeError):
    """Falha ao criar ou gerir um anúncio. A mensagem é segura para exibir."""


def _meta_values(session: Session) -> dict:
    row = session.scalar(select(ServiceCredential).where(ServiceCredential.service == "meta_ads"))
    if row is None or not row.enabled or row.last_check_status != "ok":
        raise AdsError("a Meta não está conectada: preencha e teste o cartão Meta em Integrações.")
    v = row.values or {}
    for need in ("access_token", "ad_account_id", "page_id"):
        if not v.get(need):
            raise AdsError(f"falta {need} no cartão da Meta")
    return v


def _post(path: str, token: str, **data) -> dict:
    try:
        response = requests.post(f"{meta_ads.GRAPH}/{path.lstrip('/')}", data={"access_token": token, **data}, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise AdsError(f"sem conexão com a Meta: {exc}") from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not response.ok:
        err = (body.get("error") or {}) if isinstance(body, dict) else {}
        detail = err.get("error_user_msg") or err.get("message") or "erro desconhecido"
        raise AdsError(f"Meta recusou ({err.get('code', response.status_code)}): {str(detail)[:260]}")
    return body


def _cents(brl: float) -> int:
    return int(round(brl * 100))


# ----------------------------------------------------------------------------- travas ------------


def week_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    local = (now or datetime.now(UTC)).astimezone()
    start = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=7)


def budget_status(session: Session, now: datetime | None = None, platform: str = "meta") -> dict:
    """Quanto da verba **da plataforma** já está comprometido: verba/dia dos anúncios abertos e compromisso da semana (verba × dias)."""
    budget = ads_budget.load(session, platform)
    if budget is None:
        return {"configured": False, "platform": platform}
    start, end = week_window(now)
    open_ads = list(session.scalars(select(AdCampaign).where(AdCampaign.status.in_(OPEN_STATUSES), AdCampaign.platform == platform)))
    this_week = [a for a in session.scalars(select(AdCampaign).where(AdCampaign.platform == platform))
                 if (c := a.created_at) is not None and start <= (c if c.tzinfo else c.replace(tzinfo=UTC)) < end]
    committed = sum((a.daily_budget_brl or 0) * (a.duration_days or 1) for a in this_week if a.status not in ("failed", "removed"))
    products = {a.product_id for a in this_week if a.product_id and a.status not in ("failed", "removed")}
    return {"configured": True, "platform": platform, "weekly_brl": budget.weekly_brl, "daily_cap_brl": budget.daily_cap_brl, "max_products": budget.max_products,
            "creatives_per_product": budget.creatives_per_product, "daily_committed_brl": round(sum(a.daily_budget_brl or 0 for a in open_ads), 2),
            "week_committed_brl": round(committed, 2), "week_products": len(products),
            "week_spent_brl": round(sum(a.spent_brl or 0 for a in this_week), 2)}


def marketplace_status(session: Session, marketplace: str, now: datetime | None = None) -> dict:
    """Verba já comprometida em anúncios de produtos deste marketplace, somando Meta e Google."""
    cap = ads_budget.load_marketplace(session, marketplace)
    name = ads_budget.MP_NAMES.get(marketplace, marketplace)
    allowed = ads_budget.marketplace_allowed(session, marketplace)
    start, end = week_window(now)
    rows = [(a, p) for a, p in session.execute(select(AdCampaign, storefront.Product).join(storefront.Product, storefront.Product.id == AdCampaign.product_id))
            if p.marketplace.value == marketplace]
    open_ads = [a for a, _ in rows if a.status in OPEN_STATUSES]
    this_week = [a for a, _ in rows if (c := a.created_at) is not None and start <= (c if c.tzinfo else c.replace(tzinfo=UTC)) < end]
    committed = sum((a.daily_budget_brl or 0) * (a.duration_days or 1) for a in this_week if a.status not in ("failed", "removed"))
    return {"configured": cap is not None, "allowed": allowed, "marketplace": marketplace, "name": name,
            "weekly_brl": cap[0] if cap else None, "daily_cap_brl": cap[1] if cap else None,
            "daily_committed_brl": round(sum(a.daily_budget_brl or 0 for a in open_ads), 2), "week_committed_brl": round(committed, 2),
            "week_spent_brl": round(sum(a.spent_brl or 0 for a in this_week), 2)}


def _guard_marketplace(session: Session, product_id: int | None, daily_brl: float, days: int, now: datetime | None = None) -> None:
    product = session.get(storefront.Product, product_id) if product_id else None
    if product is None:
        return
    mp = product.marketplace.value
    st = marketplace_status(session, mp, now)
    if not st["allowed"]:
        raise AdsError(f"{st['name']} está fora da lista de marketplaces com campanha (Verba e campanhas): só divulgação orgânica. Peça ao operador para incluí-lo na lista.")
    if not st["configured"]:
        return  # na lista e sem teto próprio: valem só os limites de Meta e Google
    if daily_brl > st["daily_cap_brl"] + 1e-9 or st["daily_committed_brl"] + daily_brl > st["daily_cap_brl"] + 1e-9:
        raise AdsError(f"o teto por dia de {st['name']} é R$ {st['daily_cap_brl']:g} e já há R$ {st['daily_committed_brl']:g}/dia comprometidos: mais R$ {daily_brl:g} passaria.")
    if st["week_committed_brl"] + daily_brl * days > st["weekly_brl"] + 1e-9:
        raise AdsError(f"o compromisso da semana em {st['name']} (R$ {st['week_committed_brl']:g}) mais R$ {daily_brl * days:g} passaria do teto do marketplace "
                       f"(R$ {st['weekly_brl']:g} por semana).")


def _guard(session: Session, product_id: int | None, daily_brl: float, days: int, now: datetime | None = None, *, per_product: bool = True,
           platform: str = "meta") -> None:
    st = budget_status(session, now, platform)
    who = ads_budget.NAMES[platform]
    if not st["configured"]:
        raise AdsError(f"defina o Orçamento de anúncios do {who} (valor por semana e teto por dia) em Integrações antes de criar anúncios.")
    if not 0 < daily_brl <= st["daily_cap_brl"]:
        raise AdsError(f"verba diária de R$ {daily_brl:g} fora do teto (R$ {st['daily_cap_brl']:g} por dia).")
    if st["daily_committed_brl"] + daily_brl > st["daily_cap_brl"] + 1e-9:
        raise AdsError(f"já há R$ {st['daily_committed_brl']:g}/dia comprometidos em anúncios abertos do {who}; mais R$ {daily_brl:g} passaria do teto "
                       f"de R$ {st['daily_cap_brl']:g} por dia. Pause ou encerre um anúncio antes.")
    if not 1 <= days <= MAX_DAYS:
        raise AdsError(f"duração de {days} dia(s) fora do permitido (1 a {MAX_DAYS}).")
    if st["week_committed_brl"] + daily_brl * days > st["weekly_brl"] + 1e-9:
        raise AdsError(f"o compromisso da semana no {who} (R$ {st['week_committed_brl']:g}) mais R$ {daily_brl * days:g} passaria do valor da semana "
                       f"do {who} (R$ {st['weekly_brl']:g}).")
    same_product = session.query(AdCampaign).filter(AdCampaign.product_id == product_id, AdCampaign.status.in_(OPEN_STATUSES),
                                                    AdCampaign.platform == platform).count()
    if per_product and same_product >= st["creatives_per_product"]:
        raise AdsError(f"este produto já tem {same_product} anúncio(s) aberto(s); o máximo é {st['creatives_per_product']} criativo(s) por produto.")
    _guard_marketplace(session, product_id, daily_brl, days, now)
    this_week_products = st["week_products"]
    already = session.query(AdCampaign).filter(AdCampaign.product_id == product_id, AdCampaign.platform == platform).count() > 0
    if not already and this_week_products >= st["max_products"]:
        raise AdsError(f"já há {this_week_products} produto(s) em anúncio nesta semana; o máximo é {st['max_products']}.")


# ----------------------------------------------------------------------------- criar -------------


def _creative_image(creative: CreativeCampaign) -> dict | None:
    """A imagem do anúncio: a primeira peça `image` pronta (o formato 4:5 vem primeiro, o melhor para o feed)."""
    for d in aistudio.deliverables(creative):
        if d.get("kind") == "image" and d.get("download"):
            return d
    return None


def _fit(text: str, limit: int) -> str:
    """Corta no limite sem partir palavra ("… na Sho")."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    words = (text[:limit].rsplit(" ", 1)[0] or text[:limit]).split()
    while len(words) > 1 and words[-1].lower() in {"na", "no", "de", "da", "do", "e", "ou", "com", "para", "em", "a", "o", "um", "uma", "-", "–"}:
        words.pop()  # não termina em palavra solta ("… Nota 5,0 na")
    return " ".join(words).rstrip(" -–:,;.")


def _creative_copy(creative: CreativeCampaign) -> dict:
    for d in aistudio.deliverables(creative):
        if d.get("kind") == "copy" and isinstance(d.get("content"), dict):
            return d["content"]
    return {}


def build_plan(session: Session, creative: CreativeCampaign, *, daily_brl: float, days: int, now: datetime | None = None,
               check_budget: bool = True) -> dict:
    """O que seria enviado à Meta (sem enviar). Valida tudo, inclusive as travas."""
    if creative.status not in ("completed", "partial"):
        raise AdsError(f"o criativo está “{creative.status}”: só dá para anunciar criativo pronto.")
    piece = _creative_image(creative)
    if not piece:
        raise AdsError("o criativo não tem imagem pronta (peça `image` com endereço de download).")
    copy = _creative_copy(creative)
    headline = _fit(str(copy.get("headline") or ""), 40)
    caption = str(copy.get("caption") or "").strip()[:500]
    if not headline or not caption:
        raise AdsError("o criativo não tem título e legenda prontos.")
    product = creative.product_id and session.get(storefront.Product, creative.product_id)
    cfg = storefront.load_config(session)
    if not product or not cfg:
        raise AdsError("produto ou endereço da loja indisponível.")
    if check_budget:
        _guard(session, creative.product_id, daily_brl, days, now)
    tag = f"mural-{creative.external_ref}"[:80]
    url = f"{cfg.public_url}/p/p{product.id}?utm_source=meta&utm_medium=paid&utm_campaign={tag}"
    return {"name": tag, "objective": "OUTCOME_TRAFFIC", "daily_budget_brl": daily_brl, "days": days, "headline": headline, "message": caption,
            "image": piece["download"], "image_id": piece["id"], "link": url, "targeting": {"geo_locations": {"countries": ["BR"]}, "age_min": 18, "age_max": 65,
                                                           "publisher_platforms": ["facebook", "instagram"]}}


def _page_token(session: Session) -> str:
    """Token da Página (para ler os posts dela), obtido do token do operador."""
    values = _meta_values(session)
    try:
        token = meta_ads._get(values["page_id"], values["access_token"], fields="access_token").get("access_token")
    except meta_ads.MetaError as exc:
        raise AdsError(f"não consegui acesso à Página: {exc}") from exc
    if not token:
        raise AdsError("a Meta não liberou o acesso à Página para este token (permissões de Página).")
    return token


def list_page_posts(session: Session, limit: int = 10) -> list[dict]:
    """Posts publicados na Página (os mais recentes), com o link que cada um leva."""
    values = _meta_values(session)
    try:
        data = meta_ads._get(f"{values['page_id']}/posts", _page_token(session), limit=max(1, min(limit, 25)),
                             fields="id,message,created_time,permalink_url,full_picture,attachments{unshimmed_url,url}")
    except meta_ads.MetaError as exc:
        raise AdsError(f"não consegui ler os posts da Página: {exc}") from exc
    out = []
    for p in data.get("data", []):
        attach = ((p.get("attachments") or {}).get("data") or [{}])[0]
        out.append({"id": p.get("id"), "message": (p.get("message") or "")[:200], "created_time": p.get("created_time"),
                    "permalink_url": p.get("permalink_url"), "image": p.get("full_picture"),
                    "link": attach.get("unshimmed_url") or attach.get("url")})
    return out


def post_kit(session: Session, creative_id: int) -> dict:
    """O que o operador publica na Página (texto, link com UTM e a imagem) para depois anunciar esse post."""
    creative = session.get(CreativeCampaign, creative_id)
    if creative is None:
        raise AdsError(f"criativo {creative_id} não encontrado")
    plan = build_plan(session, creative, daily_brl=1, days=1, check_budget=False)
    # O texto do criativo traz "Ver na loja: <vitrine>": tira, porque o link do post é o da página do produto (com UTM).
    message = re.sub(r"\s*Ver na loja:?\s*https?://\S+", "", plan["message"], flags=re.I).strip()
    return {"creative_id": creative.id, "headline": plan["headline"], "message": message, "link": plan["link"],
            "image_file": next((d["file"] for d in aistudio.deliverables(creative) if d["id"] == plan["image_id"]), None),
            "steps": ["Baixe a imagem (4:5) e publique na Página com o texto e o link abaixo (cole o link no texto do post).",
                      "Volte aqui, atualize a lista de posts e escolha o post.", "O anúncio nasce pausado: você liga depois."]}


def _check_post(session: Session, post_id: str, plan: dict) -> str:
    """Confere que o post existe, está publicado na Página e leva o link do produto. Devolve o id completo (página_post)."""
    values = _meta_values(session)
    page = values["page_id"]
    full = post_id if "_" in post_id else f"{page}_{post_id}"
    try:
        post = meta_ads._get(full, _page_token(session), fields="id,is_published,message,attachments{unshimmed_url,url}")
    except meta_ads.MetaError as exc:
        raise AdsError(f"não encontrei esse post na Página: {exc}") from exc
    if post.get("is_published") is False:
        raise AdsError("esse post não está publicado (é rascunho ou agendado): publique antes de anunciar.")
    haystack = json.dumps(post, ensure_ascii=False)
    product_path = plan["link"].split("?")[0].split("/p/")[-1]  # "p56"
    if f"/p/{product_path}" not in haystack:
        raise AdsError("o post não tem o link do produto no Mural (use o link do kit): sem ele o anúncio levaria a outro lugar.")
    return post.get("id") or full


def create_ad(session: Session, creative_id: int, *, daily_brl: float, days: int = 3, dry_run: bool = True, actor: str = "agent",
              variant: str | None = None, now: datetime | None = None, post_id: str | None = None) -> dict:
    creative = session.get(CreativeCampaign, creative_id)
    if creative is None:
        raise AdsError(f"criativo {creative_id} não encontrado")
    plan = build_plan(session, creative, daily_brl=daily_brl, days=days, now=now)
    if post_id:
        plan["post_id"] = post_id
        plan["origin"] = "post já publicado na Página (não usa a imagem do criativo: a Meta usa o post)"
    if dry_run:
        return {"dry_run": True, "plan": plan, "triagem": product_vetting.out(product_vetting.latest(session, creative.product_id)) if creative.product_id else None,
                "note": "Nada foi enviado à Meta. Use dry_run=false para criar o anúncio PAUSADO. Anúncio pago exige triagem `aprovado_pago` (product_vet)."}
    product_vetting.require_paid_ok(session, creative.product_id)
    if creative.mode != "live":
        raise AdsError("criativo de teste (sandbox) tem peças de exemplo e não pode virar anúncio de verdade. Gere o criativo em modo ao vivo.")
    values = _meta_values(session)
    token, account, page = values["access_token"], meta_ads.normalize_account(values["ad_account_id"]), values["page_id"]
    story_id = _check_post(session, str(post_id).strip(), plan) if post_id else None
    ad = AdCampaign(creative_campaign_id=creative.id, product_id=creative.product_id, platform="meta", status="draft", variant=variant,
                    daily_budget_brl=daily_brl, duration_days=days, destination_url=plan["link"], created_by=actor[:64])
    session.add(ad)
    session.flush()
    try:
        campaign = _post(f"{account}/campaigns", token, name=plan["name"], objective=plan["objective"], status="PAUSED", special_ad_categories="[]",
                         is_adset_budget_sharing_enabled="false")  # orçamento por conjunto, sem compartilhar (a Meta passou a exigir o campo)
        ad.external_campaign_id = campaign["id"]
        adset = _post(f"{account}/adsets", token, name=plan["name"], campaign_id=campaign["id"], daily_budget=_cents(daily_brl),
                      billing_event="IMPRESSIONS", optimization_goal="LINK_CLICKS", bid_strategy="LOWEST_COST_WITHOUT_CAP",
                      targeting=json.dumps(plan["targeting"]), status="PAUSED")
        ad.external_adset_id = adset["id"]
        if story_id:  # anúncio em cima de um post que o operador publicou na Página (não é criado pelo app)
            adcreative = _post(f"{account}/adcreatives", token, name=plan["name"], object_story_id=story_id)
        else:
            # A Meta não alcança o AI Studio (rede interna): o marketTon baixa a imagem e a envia à conta de anúncios.
            try:
                data, _ = aistudio.fetch_file(session, creative, plan["image_id"])
            except aistudio.AIStudioError as exc:
                raise AdsError(f"não foi possível baixar a imagem do criativo: {exc}") from exc
            uploaded = _post(f"{account}/adimages", token, bytes=base64.b64encode(data).decode())
            image_hash = next(iter((uploaded.get("images") or {}).values()), {}).get("hash")
            if not image_hash:
                raise AdsError("a Meta não devolveu o código da imagem enviada")
            story = {"page_id": page, "link_data": {"link": plan["link"], "message": plan["message"], "name": plan["headline"], "image_hash": image_hash,
                                                    "call_to_action": {"type": "LEARN_MORE", "value": {"link": plan["link"]}}}}
            adcreative = _post(f"{account}/adcreatives", token, name=plan["name"], object_story_spec=json.dumps(story))
        made = _post(f"{account}/ads", token, name=plan["name"], adset_id=adset["id"], creative=json.dumps({"creative_id": adcreative["id"]}), status="PAUSED")
        ad.external_ad_id, ad.status, ad.meta_status = made["id"], "paused", "PAUSED"
    except (AdsError, KeyError) as exc:
        for obj in (ad.external_adset_id, ad.external_campaign_id):  # não deixa campanha/conjunto pela metade na conta de anúncios
            if obj:
                try:
                    _post(obj, token, status="DELETED")
                except AdsError:
                    logger.warning("não consegui apagar %s na Meta após a falha", obj)
        ad.status, ad.notes = "failed", f"falhou ao criar na Meta: {exc}"[:500]
        session.flush()
        raise AdsError(str(exc) if isinstance(exc, AdsError) else f"resposta inesperada da Meta ({exc})") from exc
    session.flush()
    return {"dry_run": False, "ad_id": ad.id, "status": ad.status, "external_ad_id": ad.external_ad_id,
            "note": "Anúncio criado PAUSADO na Meta: nada está gastando. O operador liga em Criativos e anúncios."}


# ----------------------------------------------------------------------------- operar ------------


def _set_remote_status(session: Session, ad: AdCampaign, status: str, **extra) -> None:
    if not ad.external_ad_id:
        raise AdsError("este anúncio ainda não existe na Meta.")
    values = _meta_values(session)
    token = values["access_token"]
    if ad.external_adset_id and extra:
        _post(ad.external_adset_id, token, **extra)
    for obj in (ad.external_ad_id, ad.external_adset_id, ad.external_campaign_id):
        if obj:
            _post(obj, token, status=status)
    ad.meta_status = status


def activate(session: Session, ad_id: int, *, actor: str, now: datetime | None = None) -> AdCampaign:
    """Liga o anúncio (só o operador). Reconfere as travas e define o fim da veiculação (`end_time`) pela duração planejada."""
    ad = session.get(AdCampaign, ad_id)
    if ad is None:
        raise AdsError(f"anúncio {ad_id} não encontrado")
    if ad.status not in ("paused", "draft") or not ad.external_ad_id:
        raise AdsError(f"o anúncio está “{ad.status}”: só dá para ligar um anúncio pausado que já existe na Meta.")
    st = budget_status(session, now)
    others = st.get("daily_committed_brl", 0) - (ad.daily_budget_brl or 0)  # `paused` conta como aberto: não soma duas vezes
    if not st["configured"] or others + (ad.daily_budget_brl or 0) > st["daily_cap_brl"] + 1e-9:
        raise AdsError("ligar este anúncio passaria do teto de verba por dia.")
    end = (now or datetime.now(UTC)) + timedelta(days=ad.duration_days or 1)
    _set_remote_status(session, ad, "ACTIVE", end_time=int(end.timestamp()))
    ad.status, ad.started_at, ad.ended_at = "active", now or datetime.now(UTC), end
    session.flush()
    logger.info("anúncio %s ligado por %s", ad.id, actor)
    return ad


def pause(session: Session, ad_id: int) -> AdCampaign:
    ad = session.get(AdCampaign, ad_id)
    if ad is None:
        raise AdsError(f"anúncio {ad_id} não encontrado")
    if ad.status == "active":
        _set_remote_status(session, ad, "PAUSED")
        ad.status = "paused"
        session.flush()
    return ad


def stop(session: Session, ad_id: int, *, now: datetime | None = None) -> AdCampaign:
    """Para de vez: pausa na Meta e encerra (não dá mais para ligar). O histórico e as métricas ficam."""
    ad = session.get(AdCampaign, ad_id)
    if ad is None or ad.platform != "meta":
        raise AdsError(f"anúncio {ad_id} não encontrado")
    if ad.status in ("ended", "removed"):
        return ad
    if ad.external_ad_id and ad.status == "active":
        _set_remote_status(session, ad, "PAUSED")
    ad.status, ad.ended_at = "ended", now or datetime.now(UTC)
    session.flush()
    return ad


def remove(session: Session, ad_id: int) -> AdCampaign:
    """Exclui: apaga na Meta (anúncio, conjunto e campanha) e tira da tela. Anúncio ativo é pausado antes."""
    ad = session.get(AdCampaign, ad_id)
    if ad is None or ad.platform != "meta":
        raise AdsError(f"anúncio {ad_id} não encontrado")
    if ad.status == "removed":
        return ad
    if ad.external_ad_id:
        _set_remote_status(session, ad, "DELETED")
    ad.status = "removed"
    session.flush()
    return ad


def pause_all(session: Session) -> int:
    """Botão de parada: pausa todos os anúncios ativos."""
    n = 0
    for ad in session.scalars(select(AdCampaign).where(AdCampaign.status == "active", AdCampaign.platform == "meta")):
        try:
            pause(session, ad.id)
            n += 1
        except AdsError as exc:
            logger.warning("não consegui pausar o anúncio %s: %s", ad.id, exc)
    return n


def sync_metrics(session: Session, now: datetime | None = None) -> int:
    """Lê gasto, impressões e cliques de cada anúncio existente na Meta (leitura; nunca estima)."""
    ads = list(session.scalars(select(AdCampaign).where(AdCampaign.platform == "meta", AdCampaign.external_ad_id.is_not(None),
                                          AdCampaign.status.in_(("active", "paused", "ended")))))
    if not ads:
        return 0
    token = _meta_values(session)["access_token"]
    done = 0
    for ad in ads:
        try:
            info = meta_ads._get(ad.external_ad_id, token, fields="effective_status,insights.date_preset(maximum){spend,impressions,inline_link_clicks}")
        except meta_ads.MetaError as exc:
            logger.info("métricas do anúncio %s indisponíveis: %s", ad.id, exc)
            continue
        ad.meta_status = info.get("effective_status") or ad.meta_status
        rows = (info.get("insights") or {}).get("data") or []
        if rows:
            row = rows[0]
            ad.spent_brl = float(row.get("spend") or 0)
            ad.impressions = int(row.get("impressions") or 0)
            ad.clicks = int(row.get("inline_link_clicks") or 0)
        ad.last_metrics_at = now or datetime.now(UTC)
        if ad.status == "active" and ad.ended_at is not None and (ad.ended_at if ad.ended_at.tzinfo else ad.ended_at.replace(tzinfo=UTC)) <= (now or datetime.now(UTC)):
            ad.status = "ended"
        done += 1
    session.flush()
    return done
