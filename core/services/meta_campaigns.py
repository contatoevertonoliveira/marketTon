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

import json
import logging
from datetime import UTC, datetime, timedelta

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.ads import AdCampaign
from core.db.creatives import CreativeCampaign
from core.db.service_credentials import ServiceCredential
from core.services import aistudio, ads_budget, meta_ads, storefront

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


def budget_status(session: Session, now: datetime | None = None) -> dict:
    """Quanto da verba já está comprometido: verba/dia dos anúncios abertos e compromisso da semana (verba × dias)."""
    budget = ads_budget.load(session)
    if budget is None:
        return {"configured": False}
    start, end = week_window(now)
    open_ads = list(session.scalars(select(AdCampaign).where(AdCampaign.status.in_(OPEN_STATUSES))))
    this_week = [a for a in session.scalars(select(AdCampaign)) if (c := a.created_at) is not None and start <= (c if c.tzinfo else c.replace(tzinfo=UTC)) < end]
    committed = sum((a.daily_budget_brl or 0) * (a.duration_days or 1) for a in this_week if a.status != "failed")
    products = {a.product_id for a in this_week if a.product_id and a.status != "failed"}
    return {"configured": True, "weekly_brl": budget.weekly_brl, "daily_cap_brl": budget.daily_cap_brl, "max_products": budget.max_products,
            "creatives_per_product": budget.creatives_per_product, "daily_committed_brl": round(sum(a.daily_budget_brl or 0 for a in open_ads), 2),
            "week_committed_brl": round(committed, 2), "week_products": len(products),
            "week_spent_brl": round(sum(a.spent_brl or 0 for a in this_week), 2)}


def _guard(session: Session, creative: CreativeCampaign, daily_brl: float, days: int, now: datetime | None = None) -> None:
    st = budget_status(session, now)
    if not st["configured"]:
        raise AdsError("defina o Orçamento de anúncios (valor por semana e teto por dia) em Integrações antes de criar anúncios.")
    if not 0 < daily_brl <= st["daily_cap_brl"]:
        raise AdsError(f"verba diária de R$ {daily_brl:g} fora do teto (R$ {st['daily_cap_brl']:g} por dia).")
    if st["daily_committed_brl"] + daily_brl > st["daily_cap_brl"] + 1e-9:
        raise AdsError(f"já há R$ {st['daily_committed_brl']:g}/dia comprometidos em anúncios abertos; mais R$ {daily_brl:g} passaria do teto "
                       f"de R$ {st['daily_cap_brl']:g} por dia. Pause ou encerre um anúncio antes.")
    if not 1 <= days <= MAX_DAYS:
        raise AdsError(f"duração de {days} dia(s) fora do permitido (1 a {MAX_DAYS}).")
    if st["week_committed_brl"] + daily_brl * days > st["weekly_brl"] + 1e-9:
        raise AdsError(f"o compromisso da semana (R$ {st['week_committed_brl']:g}) mais R$ {daily_brl * days:g} passaria do valor da semana "
                       f"(R$ {st['weekly_brl']:g}).")
    same_product = session.query(AdCampaign).filter(AdCampaign.product_id == creative.product_id, AdCampaign.status.in_(OPEN_STATUSES)).count()
    if same_product >= st["creatives_per_product"]:
        raise AdsError(f"este produto já tem {same_product} anúncio(s) aberto(s); o máximo é {st['creatives_per_product']} criativo(s) por produto.")
    this_week_products = st["week_products"]
    already = session.query(AdCampaign).filter(AdCampaign.product_id == creative.product_id).count() > 0
    if not already and this_week_products >= st["max_products"]:
        raise AdsError(f"já há {this_week_products} produto(s) em anúncio nesta semana; o máximo é {st['max_products']}.")


# ----------------------------------------------------------------------------- criar -------------


def _creative_image(creative: CreativeCampaign) -> str | None:
    for d in aistudio.deliverables(creative):
        if d.get("kind") == "image" and d.get("download", "").startswith("https://"):
            return d["download"]
    return None


def _creative_copy(creative: CreativeCampaign) -> dict:
    for d in aistudio.deliverables(creative):
        if d.get("kind") == "copy" and isinstance(d.get("content"), dict):
            return d["content"]
    return {}


def build_plan(session: Session, creative: CreativeCampaign, *, daily_brl: float, days: int, now: datetime | None = None) -> dict:
    """O que seria enviado à Meta (sem enviar). Valida tudo, inclusive as travas."""
    if creative.status not in ("completed", "partial"):
        raise AdsError(f"o criativo está “{creative.status}”: só dá para anunciar criativo pronto.")
    image = _creative_image(creative)
    if not image:
        raise AdsError("o criativo não tem imagem pronta (peça `image` com endereço de download).")
    copy = _creative_copy(creative)
    headline = str(copy.get("headline") or "").strip()[:40]
    caption = str(copy.get("caption") or "").strip()[:500]
    if not headline or not caption:
        raise AdsError("o criativo não tem título e legenda prontos.")
    product = creative.product_id and session.get(storefront.Product, creative.product_id)
    cfg = storefront.load_config(session)
    if not product or not cfg:
        raise AdsError("produto ou endereço da loja indisponível.")
    _guard(session, creative, daily_brl, days, now)
    tag = f"mural-{creative.external_ref}"[:80]
    url = f"{cfg.public_url}/p/p{product.id}?utm_source=meta&utm_medium=paid&utm_campaign={tag}"
    return {"name": tag, "objective": "OUTCOME_TRAFFIC", "daily_budget_brl": daily_brl, "days": days, "headline": headline, "message": caption,
            "image": image, "link": url, "targeting": {"geo_locations": {"countries": ["BR"]}, "age_min": 18, "age_max": 65,
                                                           "publisher_platforms": ["facebook", "instagram"]}}


def create_ad(session: Session, creative_id: int, *, daily_brl: float, days: int = 3, dry_run: bool = True, actor: str = "agent",
              variant: str | None = None, now: datetime | None = None) -> dict:
    creative = session.get(CreativeCampaign, creative_id)
    if creative is None:
        raise AdsError(f"criativo {creative_id} não encontrado")
    plan = build_plan(session, creative, daily_brl=daily_brl, days=days, now=now)
    if dry_run:
        return {"dry_run": True, "plan": plan, "note": "Nada foi enviado à Meta. Use dry_run=false para criar o anúncio PAUSADO."}
    if creative.mode != "live":
        raise AdsError("criativo de teste (sandbox) tem peças de exemplo e não pode virar anúncio de verdade. Gere o criativo em modo ao vivo.")
    values = _meta_values(session)
    token, account, page = values["access_token"], meta_ads.normalize_account(values["ad_account_id"]), values["page_id"]
    ad = AdCampaign(creative_campaign_id=creative.id, product_id=creative.product_id, platform="meta", status="draft", variant=variant,
                    daily_budget_brl=daily_brl, duration_days=days, destination_url=plan["link"], created_by=actor[:64])
    session.add(ad)
    session.flush()
    try:
        campaign = _post(f"{account}/campaigns", token, name=plan["name"], objective=plan["objective"], status="PAUSED", special_ad_categories="[]")
        ad.external_campaign_id = campaign["id"]
        adset = _post(f"{account}/adsets", token, name=plan["name"], campaign_id=campaign["id"], daily_budget=_cents(daily_brl),
                      billing_event="IMPRESSIONS", optimization_goal="LINK_CLICKS", bid_strategy="LOWEST_COST_WITHOUT_CAP",
                      targeting=json.dumps(plan["targeting"]), status="PAUSED")
        ad.external_adset_id = adset["id"]
        story = {"page_id": page, "link_data": {"link": plan["link"], "message": plan["message"], "name": plan["headline"], "picture": plan["image"],
                                                "call_to_action": {"type": "LEARN_MORE", "value": {"link": plan["link"]}}}}
        adcreative = _post(f"{account}/adcreatives", token, name=plan["name"], object_story_spec=json.dumps(story))
        made = _post(f"{account}/ads", token, name=plan["name"], adset_id=adset["id"], creative=json.dumps({"creative_id": adcreative["id"]}), status="PAUSED")
        ad.external_ad_id, ad.status, ad.meta_status = made["id"], "paused", "PAUSED"
    except (AdsError, KeyError) as exc:
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


def pause_all(session: Session) -> int:
    """Botão de parada: pausa todos os anúncios ativos."""
    n = 0
    for ad in session.scalars(select(AdCampaign).where(AdCampaign.status == "active")):
        try:
            pause(session, ad.id)
            n += 1
        except AdsError as exc:
            logger.warning("não consegui pausar o anúncio %s: %s", ad.id, exc)
    return n


def sync_metrics(session: Session, now: datetime | None = None) -> int:
    """Lê gasto, impressões e cliques de cada anúncio existente na Meta (leitura; nunca estima)."""
    ads = list(session.scalars(select(AdCampaign).where(AdCampaign.external_ad_id.is_not(None), AdCampaign.status.in_(("active", "paused", "ended")))))
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
