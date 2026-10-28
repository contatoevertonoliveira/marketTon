"""Campanhas de Pesquisa no Google Ads a partir de um produto da vitrine: criar (sempre PAUSADA), ligar (só o operador), pausar e ler métricas.

Mesmas travas da Meta, em código, mas com **orçamento próprio do Google** (cartão Orçamento de anúncios, campos GOOGLE: o gasto de uma rede não consome o da outra):

* **Nada gasta ao ser criado.** A campanha nasce `PAUSED`; quem liga é o operador. O agente cria e pausa, nunca liga.
* Verba por dia ≤ teto por dia; verba de todas as redes somada ≤ teto por dia; compromisso da semana (verba × dias) ≤ valor da semana;
  produtos distintos na semana ≤ máximo. Duração de 1 a 14 dias (a data final entra ao ligar).
* Só **Pesquisa**, só rede de pesquisa do Google (sem parceiros nem display), só Brasil e português, lance manual com teto de CPC.
* O anúncio é **responsivo de pesquisa** (títulos até 30 caracteres, descrições até 90). Textos e palavras-chave podem vir do agente; sem
  eles o sistema monta os seus a partir do produto, sem prometer o que não sabe (sem "grátis", "garantido", "melhor"...). Títulos não levam
  "!" (regra do Google).
* Destino = a página do produto na loja (com UTM); a venda de afiliado não é atribuível ao anúncio: o resultado é lido como cliques/CPC.
"""
from __future__ import annotations

import logging
import math
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.ads import AdCampaign
from core.db.catalog import Product
from core.db.service_credentials import ServiceCredential
from core.services import product_vetting, storefront
from core.services.meta_campaigns import MAX_DAYS, AdsError, _guard, budget_status
from integrations.google_ads import GoogleAdsClient, GoogleAdsConfig, GoogleAdsError

logger = logging.getLogger(__name__)

MAX_CPC_DEFAULT = 1.0
MAX_CPC_LIMIT = 5.0
NEGATIVES = ("grátis", "gratis", "pdf", "download", "baixar", "usado", "usada", "como fazer", "receita")
# Promessas que não podemos provar: o texto do anúncio não pode tê-las.
FORBIDDEN = re.compile(r"gr[aá]tis|garanti|melhor|n[ºo°]\s*1|100\s*%|milagre|cura|menor pre[cç]o|sem risco|oficial", re.I)


def _client(session: Session) -> GoogleAdsClient:
    row = session.scalar(select(ServiceCredential).where(ServiceCredential.service == "google_ads"))
    if row is None or not row.enabled or row.last_check_status != "ok":
        raise AdsError("o Google Ads não está conectado: preencha e teste o cartão do Google Ads em Integrações.")
    return GoogleAdsClient(GoogleAdsConfig.from_values(row.values or {}))


def _short(text: str, limit: int) -> str:
    """Corta no limite sem quebrar palavra."""
    text = re.sub(r"\s+", " ", text or "").strip(" -–|,.;:")
    if len(text) <= limit:
        return text
    words = text[:limit].rsplit(" ", 1)[0].split()
    while len(words) > 1 and words[-1].lower() in {"e", "ou", "com", "de", "da", "do", "para", "por", "em", "a", "o", "um", "uma"}:
        words.pop()  # não termina em palavra solta ("… Quente ou")
    return " ".join(words).strip(" -–|,.;:") or text[:limit]


def default_copy(product: Product) -> tuple[list[str], list[str], list[str]]:
    """Títulos, descrições e palavras-chave montados do produto, sem promessa que não possamos provar."""
    title = storefront.clean_title(product.title, 90)
    headlines = [_short(title, 30), "Veja no Mural na Web", "Fotos e detalhes do produto", "Confira a oferta hoje", "Seleção do Mural na Web"]
    short = _short(title.replace("…", ""), 48)
    descriptions = [f"{short}. Fotos, detalhes e link para a oferta.",
                    "Achados selecionados no Mural na Web. Compare e abra a oferta no marketplace."]
    words = [w for w in re.findall(r"[\wÀ-ÿ]+", title.lower()) if len(w) > 2]
    keywords = []
    for size in (4, 3, 2):
        phrase = " ".join(words[:size])
        if len(words) >= size and phrase not in keywords:
            keywords.append(phrase)
    if not keywords and words:
        keywords.append(" ".join(words[:2]))  # título curto: pelo menos uma palavra-chave
    return list(dict.fromkeys(h for h in headlines if h)), descriptions, keywords[:3]


def _validate(headlines: list[str], descriptions: list[str], keywords: list[str]) -> None:
    if not 3 <= len(headlines) <= 15:
        raise AdsError("o anúncio precisa de 3 a 15 títulos.")
    if not 2 <= len(descriptions) <= 4:
        raise AdsError("o anúncio precisa de 2 a 4 descrições.")
    if not 1 <= len(keywords) <= 10:
        raise AdsError("informe de 1 a 10 palavras-chave.")
    for h in headlines:
        if not 1 <= len(h) <= 30:
            raise AdsError(f"título com {len(h)} caracteres (o máximo é 30): “{h}”")
        if "!" in h:
            raise AdsError(f"o Google não aceita “!” em títulos: “{h}”")
    for d in descriptions:
        if not 1 <= len(d) <= 90:
            raise AdsError(f"descrição com {len(d)} caracteres (o máximo é 90): “{d[:40]}…”")
    for text in [*headlines, *descriptions]:
        if FORBIDDEN.search(text):
            raise AdsError(f"o texto promete algo que não podemos provar (“{FORBIDDEN.search(text).group(0)}”): “{text[:50]}”")
    if len({h.lower() for h in headlines}) != len(headlines):
        raise AdsError("há títulos repetidos.")
    for k in keywords:
        if not 2 <= len(k) <= 80 or re.search(r"[!@%,;]", k):
            raise AdsError(f"palavra-chave inválida: “{k}”")


def build_plan(session: Session, product_id: int, *, daily_brl: float, days: int, headlines: list[str] | None = None,
               descriptions: list[str] | None = None, keywords: list[str] | None = None, max_cpc_brl: float = MAX_CPC_DEFAULT,
               now: datetime | None = None) -> dict:
    """O que seria criado no Google (sem criar). Valida textos e as travas de orçamento."""
    product = session.get(Product, product_id)
    cfg = storefront.load_config(session)
    if product is None or cfg is None:
        raise AdsError("produto ou endereço da loja indisponível.")
    if not product.affiliate_url:
        raise AdsError("o produto não tem link de afiliado: não vai para a loja nem para anúncio.")
    if not 0.1 <= max_cpc_brl <= MAX_CPC_LIMIT:
        raise AdsError(f"o teto de CPC deve ficar entre R$ 0,10 e R$ {MAX_CPC_LIMIT:g}.")
    auto_h, auto_d, auto_k = default_copy(product)
    headlines = [h.strip() for h in (headlines or auto_h)]
    descriptions = [d.strip() for d in (descriptions or auto_d)]
    keywords = [k.strip().lower() for k in (keywords or auto_k)]
    _validate(headlines, descriptions, keywords)
    _guard(session, product_id, daily_brl, days, now, per_product=False, platform="google")
    tag = f"mural-g-p{product.id}-{(now or datetime.now(UTC)):%y%m%d%H%M}"
    link = f"{cfg.public_url}/p/p{product.id}?utm_source=google&utm_medium=cpc&utm_campaign={tag}"
    return {"name": tag, "type": "SEARCH", "daily_budget_brl": daily_brl, "days": days, "max_cpc_brl": max_cpc_brl, "link": link,
            "headlines": headlines, "descriptions": descriptions, "keywords": keywords, "negative_keywords": list(NEGATIVES),
            "targeting": {"country": "BR", "language": "pt", "network": "Pesquisa do Google (sem parceiros nem display)"}}


def _micros(brl: float) -> int:
    return int(round(brl * 1_000_000))


def _operations(cid: str, plan: dict) -> list[dict]:
    budget, campaign, adgroup = f"customers/{cid}/campaignBudgets/-1", f"customers/{cid}/campaigns/-2", f"customers/{cid}/adGroups/-3"
    ops: list[dict] = [
        {"campaignBudgetOperation": {"create": {"resourceName": budget, "name": plan["name"], "amountMicros": str(_micros(plan["daily_budget_brl"])),
                                                 "deliveryMethod": "STANDARD", "explicitlyShared": False}}},
        {"campaignOperation": {"create": {
            "resourceName": campaign, "name": plan["name"], "status": "PAUSED", "advertisingChannelType": "SEARCH", "campaignBudget": budget,
            "manualCpc": {"enhancedCpcEnabled": False},
            "networkSettings": {"targetGoogleSearch": True, "targetSearchNetwork": False, "targetContentNetwork": False},
            "containsEuPoliticalAdvertising": "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING"}}},
        {"campaignCriterionOperation": {"create": {"campaign": campaign, "location": {"geoTargetConstant": "geoTargetConstants/2076"}}}},
        {"campaignCriterionOperation": {"create": {"campaign": campaign, "language": {"languageConstant": "languageConstants/1014"}}}},
        {"adGroupOperation": {"create": {"resourceName": adgroup, "name": plan["name"], "campaign": campaign, "status": "ENABLED",
                                         "type": "SEARCH_STANDARD", "cpcBidMicros": str(_micros(plan["max_cpc_brl"]))}}},
    ]
    for k in plan["keywords"]:
        ops.append({"adGroupCriterionOperation": {"create": {"adGroup": adgroup, "status": "ENABLED", "keyword": {"text": k, "matchType": "PHRASE"}}}})
    for k in plan["negative_keywords"]:
        ops.append({"adGroupCriterionOperation": {"create": {"adGroup": adgroup, "negative": True, "keyword": {"text": k, "matchType": "BROAD"}}}})
    ops.append({"adGroupAdOperation": {"create": {"adGroup": adgroup, "status": "ENABLED", "ad": {
        "finalUrls": [plan["link"]],
        "responsiveSearchAd": {"headlines": [{"text": h} for h in plan["headlines"]], "descriptions": [{"text": d} for d in plan["descriptions"]]}}}}})
    return ops


def _last_id(resource: str | None) -> str | None:
    return resource.rsplit("/", 1)[-1] if resource else None


def create_campaign(session: Session, product_id: int, *, daily_brl: float, days: int = 3, dry_run: bool = True, actor: str = "agent",
                    headlines: list[str] | None = None, descriptions: list[str] | None = None, keywords: list[str] | None = None,
                    max_cpc_brl: float = MAX_CPC_DEFAULT, now: datetime | None = None) -> dict:
    plan = build_plan(session, product_id, daily_brl=daily_brl, days=days, headlines=headlines, descriptions=descriptions,
                      keywords=keywords, max_cpc_brl=max_cpc_brl, now=now)
    if dry_run:
        return {"dry_run": True, "plan": plan, "triagem": product_vetting.out(product_vetting.latest(session, product_id)),
                "note": "Nada foi enviado ao Google. Use dry_run=false para criar a campanha PAUSADA. Anúncio pago exige triagem `aprovado_pago` (product_vet)."}
    product_vetting.require_paid_ok(session, product_id)
    client = _client(session)
    ad = AdCampaign(creative_campaign_id=None, product_id=product_id, platform="google", status="draft", daily_budget_brl=daily_brl,
                    duration_days=days, destination_url=plan["link"], created_by=actor[:64],
                    notes=("Pesquisa. Palavras-chave: " + ", ".join(plan["keywords"]))[:500])
    session.add(ad)
    session.flush()
    try:
        responses = client.mutate(_operations(client.cfg.customer_id, plan))
    except GoogleAdsError as exc:
        ad.status, ad.notes = "failed", f"falhou ao criar no Google: {exc}"[:500]
        session.flush()
        raise AdsError(f"o Google recusou: {exc}") from exc
    found = {}
    for r in responses:
        for key in ("campaignResult", "adGroupResult", "adGroupAdResult"):
            if key in r:
                found[key] = (r[key] or {}).get("resourceName")
    ad.external_campaign_id = _last_id(found.get("campaignResult"))
    ad.external_adset_id = _last_id(found.get("adGroupResult"))
    ad.external_ad_id = _last_id(found.get("adGroupAdResult"))
    if not ad.external_campaign_id:
        ad.status = "failed"
        session.flush()
        raise AdsError("resposta inesperada do Google (sem o código da campanha)")
    ad.status, ad.meta_status = "paused", "PAUSED"
    session.flush()
    return {"dry_run": False, "ad_id": ad.id, "status": ad.status, "external_campaign_id": ad.external_campaign_id,
            "note": "Campanha criada PAUSADA no Google: nada está gastando. O operador liga em Criativos e anúncios."}


def _set_status(session: Session, ad: AdCampaign, status: str, *, end_date: str | None = None, validate_only: bool = False) -> None:
    if ad.platform != "google" or not ad.external_campaign_id:
        raise AdsError("esta campanha ainda não existe no Google.")
    client = _client(session)
    update = {"resourceName": f"customers/{client.cfg.customer_id}/campaigns/{ad.external_campaign_id}", "status": status}
    mask = "status"
    if end_date:  # a API nova usa data e hora (`end_date_time`), não mais `end_date`; vale até o fim desse dia
        update["endDateTime"], mask = f"{end_date} 23:59:59", "status,end_date_time"
    try:
        client.mutate([{"campaignOperation": {"update": update, "updateMask": mask}}], validate_only=validate_only)
    except GoogleAdsError as exc:
        raise AdsError(f"o Google recusou: {exc}") from exc
    ad.meta_status = status


def activate(session: Session, ad_id: int, *, actor: str, now: datetime | None = None) -> AdCampaign:
    """Liga a campanha (só o operador): reconfere o teto por dia e define a data final pela duração planejada."""
    ad = session.get(AdCampaign, ad_id)
    if ad is None or ad.platform != "google":
        raise AdsError(f"campanha {ad_id} não encontrada")
    if ad.status not in ("paused", "draft") or not ad.external_campaign_id:
        raise AdsError(f"a campanha está “{ad.status}”: só dá para ligar uma campanha pausada que já existe no Google.")
    st = budget_status(session, now, "google")
    others = st.get("daily_committed_brl", 0) - (ad.daily_budget_brl or 0)
    if not st["configured"] or others + (ad.daily_budget_brl or 0) > st["daily_cap_brl"] + 1e-9:
        raise AdsError("ligar esta campanha passaria do teto de verba por dia.")
    start = (now or datetime.now(UTC)).astimezone()
    end = start + timedelta(days=max(1, ad.duration_days or 1) - 1)
    _set_status(session, ad, "ENABLED", end_date=f"{end:%Y-%m-%d}")
    ad.status, ad.started_at, ad.ended_at = "active", now or datetime.now(UTC), end
    session.flush()
    logger.info("campanha do Google %s ligada por %s", ad.id, actor)
    return ad


def pause(session: Session, ad_id: int) -> AdCampaign:
    ad = session.get(AdCampaign, ad_id)
    if ad is None or ad.platform != "google":
        raise AdsError(f"campanha {ad_id} não encontrada")
    if ad.status == "active":
        _set_status(session, ad, "PAUSED")
        ad.status = "paused"
        session.flush()
    return ad


def stop(session: Session, ad_id: int, *, now: datetime | None = None) -> AdCampaign:
    """Para de vez: pausa no Google e encerra (não dá mais para ligar). O histórico e as métricas ficam."""
    ad = session.get(AdCampaign, ad_id)
    if ad is None or ad.platform != "google":
        raise AdsError(f"campanha {ad_id} não encontrada")
    if ad.status in ("ended", "removed"):
        return ad
    if ad.external_campaign_id and ad.status == "active":
        _set_status(session, ad, "PAUSED")
    ad.status, ad.ended_at = "ended", now or datetime.now(UTC)
    session.flush()
    return ad


def remove(session: Session, ad_id: int) -> AdCampaign:
    """Exclui: remove a campanha no Google e tira da tela."""
    ad = session.get(AdCampaign, ad_id)
    if ad is None or ad.platform != "google":
        raise AdsError(f"campanha {ad_id} não encontrada")
    if ad.status == "removed":
        return ad
    if ad.external_campaign_id:
        client = _client(session)
        try:  # remover é uma operação própria (`remove`), não uma troca de estado
            client.mutate([{"campaignOperation": {"remove": f"customers/{client.cfg.customer_id}/campaigns/{ad.external_campaign_id}"}}])
        except GoogleAdsError as exc:
            raise AdsError(f"o Google recusou: {exc}") from exc
        ad.meta_status = "REMOVED"
    ad.status = "removed"
    session.flush()
    return ad


def pause_all(session: Session) -> int:
    n = 0
    for ad in session.scalars(select(AdCampaign).where(AdCampaign.status == "active", AdCampaign.platform == "google")):
        try:
            pause(session, ad.id)
            n += 1
        except AdsError as exc:
            logger.warning("não consegui pausar a campanha %s do Google: %s", ad.id, exc)
    return n


def sync_metrics(session: Session, now: datetime | None = None) -> int:
    """Lê gasto, impressões e cliques das campanhas existentes no Google (leitura; nunca estima)."""
    ads = {a.external_campaign_id: a for a in session.scalars(select(AdCampaign).where(
        AdCampaign.platform == "google", AdCampaign.external_campaign_id.is_not(None), AdCampaign.status.in_(("active", "paused", "ended"))))}
    if not ads:
        return 0
    client = _client(session)
    ids = ", ".join(i for i in ads if i.isdigit())
    if not ids:
        return 0
    try:
        rows = client.search("SELECT campaign.id, campaign.status, metrics.cost_micros, metrics.impressions, metrics.clicks "
                             f"FROM campaign WHERE campaign.id IN ({ids})")
    except GoogleAdsError as exc:
        raise AdsError(f"o Google recusou a leitura: {exc}") from exc
    done, stamp = 0, now or datetime.now(UTC)
    for row in rows:
        ad = ads.get(str((row.get("campaign") or {}).get("id")))
        if ad is None:
            continue
        m = row.get("metrics") or {}
        ad.spent_brl = round(int(m.get("costMicros") or 0) / 1_000_000, 2)
        ad.impressions, ad.clicks = int(m.get("impressions") or 0), int(m.get("clicks") or 0)
        ad.meta_status = (row.get("campaign") or {}).get("status") or ad.meta_status
        ad.last_metrics_at = stamp
        if ad.status == "active" and ad.ended_at is not None and (ad.ended_at if ad.ended_at.tzinfo else ad.ended_at.replace(tzinfo=UTC)) <= stamp:
            ad.status = "ended"
        done += 1
    session.flush()
    return done


# --- Lance máximo por clique (CPC) das campanhas que já existem ---------------------------------------------------------------------------------------
BID_MIN = 0.20
BID_STEP = 0.05
BID_MARGIN = 1.15  # folga sobre a estimativa do Google, para disputar a primeira página em vez de ficar na beirada


def _round_up(value: float) -> float:
    return round(math.ceil(value / BID_STEP - 1e-9) * BID_STEP, 2)


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    low, high = math.floor(pos), math.ceil(pos)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def suggest_bid(estimates: list[float]) -> float | None:
    """Lance sugerido a partir das estimativas de CPC de topo de página por palavra (R$): o 3º quartil das palavras com folga de 15%, em
    múltiplos de R$ 0,05 e dentro de [BID_MIN, MAX_CPC_LIMIT]. Um lance só vale para o grupo todo, então cobre a maioria das palavras sem pagar
    o preço da mais cara. Sem estimativa nenhuma (palavras com pouco volume), não há sugestão."""
    values = [v for v in estimates if v and v > 0]
    if not values:
        return None
    return min(MAX_CPC_LIMIT, max(BID_MIN, _round_up(_percentile(values, 0.75) * BID_MARGIN)))


def _gaql_in(ids: list[str]) -> str:
    return ", ".join(i for i in ids if i.isdigit())


def bid_overview(session: Session) -> list[dict]:
    """Campanhas do Google que existem (ligadas, pausadas ou planejadas) com o lance atual, o que o Google estima para aparecer na primeira
    página e o lance sugerido. Só leitura."""
    ads = list(session.scalars(select(AdCampaign).where(AdCampaign.platform == "google", AdCampaign.external_campaign_id.is_not(None),
                                                       AdCampaign.status.in_(("active", "paused", "draft"))).order_by(AdCampaign.id)))
    if not ads:
        return []
    client = _client(session)
    ids = _gaql_in([a.external_campaign_id for a in ads])
    try:
        groups = client.search(f"SELECT campaign.id, ad_group.id, ad_group.cpc_bid_micros FROM ad_group WHERE campaign.id IN ({ids}) AND ad_group.status != 'REMOVED'")
        kws = client.search("SELECT campaign.id, ad_group_criterion.keyword.text, ad_group_criterion.position_estimates.first_page_cpc_micros, "
                            "ad_group_criterion.position_estimates.top_of_page_cpc_micros FROM ad_group_criterion "
                            f"WHERE ad_group_criterion.type = 'KEYWORD' AND ad_group_criterion.negative = false AND ad_group_criterion.status != 'REMOVED' "
                            f"AND campaign.id IN ({ids})")
        stats = client.search("SELECT campaign.id, metrics.impressions, metrics.clicks, metrics.search_rank_lost_impression_share "
                              f"FROM campaign WHERE campaign.id IN ({ids})")
    except GoogleAdsError as exc:
        raise AdsError(f"o Google recusou a leitura: {exc}") from exc
    bid_by = {str((g.get("campaign") or {}).get("id")): int((g.get("adGroup") or {}).get("cpcBidMicros") or 0) / 1_000_000 for g in groups}
    lost_by = {str((s.get("campaign") or {}).get("id")): (s.get("metrics") or {}).get("searchRankLostImpressionShare") for s in stats}
    words: dict[str, list[dict]] = {}
    for row in kws:
        est = (row.get("adGroupCriterion") or {}).get("positionEstimates") or {}
        first, top = int(est.get("firstPageCpcMicros") or 0) / 1_000_000, int(est.get("topOfPageCpcMicros") or 0) / 1_000_000
        words.setdefault(str((row.get("campaign") or {}).get("id")), []).append(
            {"text": ((row.get("adGroupCriterion") or {}).get("keyword") or {}).get("text"), "first_page_brl": first or None, "top_of_page_brl": top or None})
    out = []
    for ad in ads:
        cid = ad.external_campaign_id
        ws = words.get(cid, [])
        firsts = [w["first_page_brl"] for w in ws if w["first_page_brl"]]
        tops = [w["top_of_page_brl"] or w["first_page_brl"] for w in ws if w["top_of_page_brl"] or w["first_page_brl"]]
        suggested = suggest_bid(tops)
        product = session.get(Product, ad.product_id) if ad.product_id else None
        current = bid_by.get(cid)
        lost = lost_by.get(cid)
        out.append({"ad_id": ad.id, "product_id": ad.product_id, "product_title": product.title if product else None, "status": ad.status,
                    "daily_budget_brl": ad.daily_budget_brl, "current_bid_brl": current,
                    "entry_bid_brl": round(_percentile(firsts, 0.5), 2) if firsts else None,
                    "min_word_bid_brl": round(min(firsts), 2) if firsts else None,
                    "suggested_bid_brl": suggested, "has_estimate": suggested is not None, "max_allowed_brl": MAX_CPC_LIMIT,
                    "rank_lost_pct": round(float(lost) * 100) if lost is not None else None,
                    "impressions": ad.impressions, "clicks": ad.clicks,
                    "keywords": sorted(ws, key=lambda w: -(w["top_of_page_brl"] or w["first_page_brl"] or 0))})
    return out


def set_bid(session: Session, ad_id: int, max_cpc_brl: float, *, validate_only: bool = False) -> dict:
    """Troca o lance máximo por clique do grupo de anúncios de uma campanha que já existe no Google. Mesma trava de teto da criação."""
    ad = session.get(AdCampaign, ad_id)
    if ad is None or ad.platform != "google":
        raise AdsError(f"campanha {ad_id} não encontrada")
    if not ad.external_adset_id or ad.status not in ("active", "paused", "draft"):
        raise AdsError(f"a campanha está “{ad.status}”: só dá para mudar o lance de uma campanha que existe no Google e não foi encerrada.")
    try:
        bid = round(float(max_cpc_brl), 2)
    except (TypeError, ValueError):
        raise AdsError("informe o lance em reais, por exemplo 1,50.") from None
    if bid < 0.01 or bid > MAX_CPC_LIMIT:
        raise AdsError(f"o lance máximo por clique deve ficar entre R$ 0,01 e R$ {MAX_CPC_LIMIT:g} (trava de segurança).")
    client = _client(session)
    resource = f"customers/{client.cfg.customer_id}/adGroups/{ad.external_adset_id}"
    try:
        client.mutate([{"adGroupOperation": {"update": {"resourceName": resource, "cpcBidMicros": str(_micros(bid))}, "updateMask": "cpc_bid_micros"}}],
                      validate_only=validate_only)
    except GoogleAdsError as exc:
        raise AdsError(f"o Google recusou: {exc}") from exc
    return {"ad_id": ad.id, "max_cpc_brl": bid, "validated_only": validate_only}


def apply_suggested_bids(session: Session, ad_ids: list[int] | None = None) -> list[dict]:
    """Modo automático: aplica a sugestão a cada campanha que tem estimativa e ainda não está nesse lance. Devolve o resultado de cada uma."""
    results = []
    for row in bid_overview(session):
        if ad_ids is not None and row["ad_id"] not in ad_ids:
            continue
        new, old = row["suggested_bid_brl"], row["current_bid_brl"]
        if new is None:
            results.append({"ad_id": row["ad_id"], "skipped": "sem estimativa do Google para estas palavras (pouco volume): defina o lance à mão."})
        elif old is not None and abs(old - new) < 0.005:
            results.append({"ad_id": row["ad_id"], "skipped": "já está no lance sugerido.", "max_cpc_brl": old})
        else:
            try:
                results.append({**set_bid(session, row["ad_id"], new), "from_brl": old})
            except AdsError as exc:
                results.append({"ad_id": row["ad_id"], "error": str(exc)})
    return results
