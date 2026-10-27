"""Histórico gerencial dos criativos: o que foi criado, para qual produto, que anúncios saíram dele e o que aconteceu depois.

Dois blocos de números, sempre separados:

* **do anúncio** (vêm da plataforma de anúncios, podem faltar): gasto, impressões, cliques, CTR e CPC. Faltou dado = `None`, nunca zero;
* **do produto desde o criativo** (medidos aqui): cliques de pessoas nos links da loja e vendas/comissão. Não são "do anúncio": a venda
  do afiliado sai do marketplace dias depois e não diz qual anúncio a trouxe. Servem para ver se o produto reagiu, não para atribuir.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.ads import AdCampaign
from core.db.catalog import Product
from core.db.creatives import CreativeCampaign
from core.db.tracking import AffiliateLink, ClickEvent, Commission, Sale
from core.services import aistudio, storefront

CANCELLED = {"CANCELLED", "CANCELED", "REFUNDED", "CHARGEBACK", "EXPIRED", "DUPLICATED"}
AD_STATUSES = ("draft", "paused", "active", "ended", "failed", "removed")


class AdError(ValueError):
    """Dado de anúncio inválido; a mensagem é segura para exibir."""


def _aware(dt: datetime | None) -> datetime | None:
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=UTC))


def ad_out(ad: AdCampaign) -> dict:
    ctr = round(ad.clicks / ad.impressions * 100, 2) if ad.clicks is not None and ad.impressions else None
    cpc = round(ad.spent_brl / ad.clicks, 2) if ad.spent_brl is not None and ad.clicks else None
    return {"id": ad.id, "platform": ad.platform, "status": ad.status, "variant": ad.variant, "daily_budget_brl": ad.daily_budget_brl,
            "spent_brl": ad.spent_brl, "impressions": ad.impressions, "clicks": ad.clicks, "ctr_pct": ctr, "cpc_brl": cpc,
            "meta_status": ad.meta_status, "duration_days": ad.duration_days, "destination_url": ad.destination_url,
            "on_meta": bool(ad.external_ad_id),
            "started_at": ad.started_at.isoformat() if ad.started_at else None, "ended_at": ad.ended_at.isoformat() if ad.ended_at else None,
            "last_metrics_at": ad.last_metrics_at.isoformat() if ad.last_metrics_at else None, "notes": ad.notes}


def _product_results(session: Session, product_id: int, since: datetime) -> dict:
    link_ids = [i for (i,) in session.execute(select(AffiliateLink.id).where(AffiliateLink.product_id == product_id))]
    clicks = 0
    if link_ids:
        clicks = sum(1 for (t,) in session.execute(select(ClickEvent.occurred_at).where(ClickEvent.affiliate_link_id.in_(link_ids)))
                     if (a := _aware(t)) is not None and a >= since)
    sales = [(sid, st) for sid, st, t in session.execute(select(Sale.id, Sale.status, Sale.occurred_at).where(Sale.product_id == product_id))
             if (a := _aware(t)) is not None and a >= since and str(st or "").upper() not in CANCELLED]
    commission = 0.0
    if sales:
        for confirmed, estimated in session.execute(select(Commission.confirmed_amount, Commission.estimated_amount)
                                                    .where(Commission.sale_id.in_([s for s, _ in sales]))):
            commission += float(confirmed if confirmed is not None else (estimated or 0))
    return {"store_clicks": clicks, "sales": len(sales), "commission_brl": round(commission, 2)}


def history(session: Session, *, limit: int = 50) -> dict:
    rows = list(session.scalars(select(CreativeCampaign).where(CreativeCampaign.hidden.is_(False))
                                .order_by(CreativeCampaign.id.desc()).limit(max(1, min(limit, 200)))))
    ads_by_creative: dict[int, list[AdCampaign]] = {}
    for ad in session.scalars(select(AdCampaign).where(AdCampaign.status != "removed").order_by(AdCampaign.id)):
        ads_by_creative.setdefault(ad.creative_campaign_id or 0, []).append(ad)
    items, spent, usd, active = [], 0.0, 0.0, 0
    for c in rows:
        product = session.get(Product, c.product_id) if c.product_id else None
        ads = ads_by_creative.get(c.id, [])
        spent += sum(a.spent_brl or 0 for a in ads)
        usd += c.cost_usd or 0
        active += sum(1 for a in ads if a.status == "active")
        created = _aware(c.created_at) or datetime.now(UTC)
        items.append({
            "id": c.id, "external_ref": c.external_ref, "created_at": created.isoformat(), "mode": c.mode, "status": c.status, "quality": c.quality,
            "angle": c.angle, "budget_usd": c.budget_usd, "cost_usd": c.cost_usd, "error": c.error, "created_by": c.created_by,
            "product": ({"id": product.id, "title": storefront.clean_title(product.title, 90), "image": storefront._first_image(product),
                         "marketplace": product.marketplace.value, "price": product.price} if product else None),
            "deliverables": aistudio.deliverables(c),
            "ads": [ad_out(a) for a in ads],
            "product_results": _product_results(session, product.id, created) if product else None,
        })
    search_ads = []
    for ad in ads_by_creative.get(0, []):  # campanhas sem criativo: pesquisa no Google
        product = session.get(Product, ad.product_id) if ad.product_id else None
        spent += ad.spent_brl or 0
        active += 1 if ad.status == "active" else 0
        search_ads.append(ad_out(ad) | {"product": ({"id": product.id, "title": storefront.clean_title(product.title, 90)} if product else None)})
    return {"items": items, "search_ads": search_ads, "totals": {"creatives": len(items), "cost_usd": round(usd, 4), "ads": sum(len(v) for v in ads_by_creative.values()),
                                       "active_ads": active, "spent_brl": round(spent, 2)}}


def create_ad(session: Session, creative_id: int, *, actor: str, platform: str = "meta", status: str = "draft", variant: str | None = None,
              daily_budget_brl: float | None = None, notes: str | None = None) -> AdCampaign:
    creative = session.get(CreativeCampaign, creative_id)
    if creative is None:
        raise AdError(f"criativo {creative_id} não encontrado")
    if status not in AD_STATUSES:
        raise AdError(f"status inválido: use {', '.join(AD_STATUSES)}")
    if daily_budget_brl is not None and not 0 < daily_budget_brl <= 100000:
        raise AdError("orçamento diário inválido")
    ad = AdCampaign(creative_campaign_id=creative.id, product_id=creative.product_id, platform=platform[:16], status=status,
                    variant=(variant or None) and variant[:8], daily_budget_brl=daily_budget_brl, notes=(notes or None) and notes[:500],
                    created_by=actor[:64])
    session.add(ad)
    session.flush()
    return ad


def update_ad(session: Session, ad_id: int, **fields) -> AdCampaign:
    """Atualiza estado e métricas lidas da plataforma. Valores negativos são recusados; campo ausente não muda."""
    ad = session.get(AdCampaign, ad_id)
    if ad is None:
        raise AdError(f"anúncio {ad_id} não encontrado")
    if fields.get("status") is not None:
        if fields["status"] not in AD_STATUSES:
            raise AdError(f"status inválido: use {', '.join(AD_STATUSES)}")
        ad.status = fields["status"]
        now = datetime.now(UTC)
        if ad.status == "active" and ad.started_at is None:
            ad.started_at = now
        if ad.status in ("ended", "failed") and ad.ended_at is None:
            ad.ended_at = now
    for name in ("spent_brl", "daily_budget_brl", "impressions", "clicks"):
        if fields.get(name) is not None:
            value = fields[name]
            if value < 0:
                raise AdError(f"{name} não pode ser negativo")
            setattr(ad, name, int(value) if name in ("impressions", "clicks") else float(value))
            if name in ("spent_brl", "impressions", "clicks"):
                ad.last_metrics_at = datetime.now(UTC)
    if ad.clicks is not None and ad.impressions is not None and ad.clicks > ad.impressions:
        raise AdError("cliques não podem passar das impressões")
    if fields.get("notes") is not None:
        ad.notes = fields["notes"][:500] or None
    session.flush()
    return ad
