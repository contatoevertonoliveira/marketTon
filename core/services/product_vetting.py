"""Triagem de produtos: procura (Google), demanda (plataforma), prazo de entrega e conta de anúncio, antes de gastar dinheiro.

O mesmo processo que o operador pediu para a escolha dos produtos, feito por código (sem gastar token de IA):

1. Uma palavra-chave de busca para o produto (o agente informa a melhor; sem ela, o sistema deduz do título).
2. Procura no Google: volume mensal, CPC e tendência (Planejador de Palavras-chave + Google Trends).
3. Demanda na plataforma: vendas, nota.
4. Prazo de entrega: acima de 10 dias reprova; sem a informação, fica "desconhecido" e não aprova anúncio pago do AliExpress.
5. A conta do anúncio: quanto % dos cliques precisa virar venda para o CPC empatar com a comissão. Item barato com CPC alto não fecha a conta.

Pareceres: `aprovado_pago` (pode receber anúncio), `so_organico` (vende, mas a conta do anúncio não fecha ou falta dado: só Instagram/Facebook/vitrine)
e `reprovado` (sem procura, em queda, nota baixa ou entrega lenta). A trava em `require_paid_ok` impede criar anúncio pago sem parecer
`aprovado_pago` recente. Reprovar é barato; gastar à toa não.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.ads import AdCampaign
from core.db.catalog import Product
from core.db.storefront import StorefrontItem
from core.db.vetting import ProductVetting
from core.services import storefront

GATE_ENABLED = True  # os testes de outros módulos desligam; em produção a trava vale
VALID_DAYS = 45  # parecer mais velho que isso não libera anúncio pago
MAX_DELIVERY_DAYS = 10
MIN_VOLUME_FOR_PAID = 300
MIN_SOLD_FOR_PAID = 500
MAX_BREAKEVEN_CONVERSION = 0.04  # anúncio só empata com até 4% dos cliques virando venda (realista é 1 a 3%)
PAID_VERDICT = "aprovado_pago"
TEST_VERDICT = "teste_operador"  # exceção do OPERADOR: libera anúncio pago de um produto sem parecer favorável, por prazo curto
TEST_DAYS = 14

_STOP = {"de", "da", "do", "das", "dos", "para", "com", "sem", "em", "e", "ou", "a", "o", "as", "os", "um", "uma", "kit", "peças", "pecas",
         "pçs", "pcs", "unidade", "unidades", "novo", "nova", "alta", "qualidade", "premium", "original", "multifuncional", "portátil", "portatil"}


class VettingError(ValueError):
    pass


def derive_keyword(title: str | None) -> str:
    """Palavra-chave provável de busca: as primeiras palavras úteis do título (sem números, medidas e enfeites). O agente deve informar uma melhor."""
    text = re.sub(r"\([^)]*\)", " ", (title or "").lower())
    words = [w for w in re.findall(r"[a-zà-ú]+", text) if w not in _STOP and len(w) > 2]
    return " ".join(words[:3])[:120] or (title or "")[:60].lower()


def _score(sig: dict[str, Any]) -> tuple[float, str, list[str]]:
    reasons: list[str] = []
    score = 0.0
    vol, sold, rating, trend, growth = sig["volume"], sig["sold"], sig["rating"], sig["trend"], sig["growth"]
    if vol is None:
        reasons.append("sem volume de busca (Google não devolveu dados)")
    else:
        score += 3 if vol >= 1000 else 2 if vol >= MIN_VOLUME_FOR_PAID else 1 if vol >= 100 else 0
        reasons.append(f"{vol} buscas por mês")
    if sold is None:
        reasons.append("vendas na plataforma desconhecidas")
    else:
        score += 3 if sold >= 5000 else 2 if sold >= 1000 else 1 if sold >= 200 else 0
        reasons.append(f"{sold} vendidos na plataforma")
    if trend == "rising":
        score += 1
        reasons.append(f"busca em alta ({growth:+.0f}% em 30 dias)" if growth is not None else "busca em alta")
    elif trend == "falling":
        score -= 2 if (growth is not None and growth <= -30) else 1
        reasons.append(f"busca em queda ({growth:+.0f}% em 30 dias)" if growth is not None else "busca em queda")
    if rating is not None:
        score += 1 if rating >= 4.5 else -2 if rating < 4.0 else 0
        reasons.append(f"nota {rating:g}")
    be = sig["breakeven"]
    if be is not None:
        score += 2 if be <= MAX_BREAKEVEN_CONVERSION else 1 if be <= 0.08 else 0
        reasons.append(f"para o anúncio empatar, {be * 100:.0f}% dos cliques precisam virar venda")
    else:
        reasons.append("conta do anúncio não calculada (falta CPC ou comissão)")
    days = sig["delivery_days"]
    if days is not None:
        score += 1 if days <= MAX_DELIVERY_DAYS else -3
        reasons.append(f"entrega em {days} dias" + (f", enviado de {sig['ship_from']}" if sig["ship_from"] else ""))
    else:
        reasons.append("prazo de entrega desconhecido")
    score = max(0.0, min(10.0, score))

    fail = []
    if days is not None and days > MAX_DELIVERY_DAYS:
        fail.append(f"entrega em {days} dias (limite {MAX_DELIVERY_DAYS})")
    if vol is not None and vol < 50 and (sold or 0) < 200:
        fail.append("quase ninguém procura e quase não vende")
    if trend == "falling" and growth is not None and growth <= -30:
        fail.append("a procura está em queda forte")
    if rating is not None and rating < 4.0:
        fail.append(f"nota baixa ({rating:g})")
    if vol is None and sold is None:
        fail.append("sem nenhum dado de procura ou demanda")
    if fail:
        return score, "reprovado", [f"REPROVADO: {m}" for m in fail] + reasons

    demand_ok = vol is not None and vol >= MIN_VOLUME_FOR_PAID and sold is not None and sold >= MIN_SOLD_FOR_PAID and trend != "falling"
    money_ok = be is not None and be <= MAX_BREAKEVEN_CONVERSION
    delivery_ok = days is not None or not sig["needs_delivery_proof"]
    if demand_ok and money_ok and delivery_ok:
        return score, PAID_VERDICT, reasons
    why = []
    if not demand_ok:
        why.append(f"procura e demanda ainda não bastam para pagar anúncio (precisa de {MIN_VOLUME_FOR_PAID}+ buscas, {MIN_SOLD_FOR_PAID}+ vendas e busca sem queda)")
    if not money_ok:
        why.append("a conta do anúncio não fecha (ou falta CPC/comissão)")
    if not delivery_ok:
        why.append("prazo de entrega não confirmado")
    return score, "so_organico", [f"SÓ ORGÂNICO: {m}" for m in why] + reasons


def _signals(product: Product, metrics: Any | None) -> dict[str, Any]:
    attrs = product.attributes or {}
    price, pct = product.price, product.affiliate_commission_pct
    commission = round(price * pct / 100, 2) if price and pct else None
    cpc = getattr(metrics, "cpc_brl", None)
    breakeven = round(cpc / commission, 3) if cpc and commission else None
    days = attrs.get("delivery_days")
    return {
        "volume": getattr(metrics, "monthly_volume", None), "cpc": cpc, "trend": getattr(metrics, "trend_direction", None),
        "growth": getattr(metrics, "growth_pct_30d", None), "sold": product.sold_quantity, "rating": product.rating or None,
        "commission": commission, "breakeven": breakeven, "delivery_days": int(days) if days is not None else None,
        "ship_from": attrs.get("ship_from"), "needs_delivery_proof": product.marketplace.value == "aliexpress",
    }


def _analyze(keywords: list[str]) -> dict[str, Any]:
    from core.services.keyword_metrics import analyze_keywords

    return {m.keyword: m for m in analyze_keywords(keywords)}


def vet(session: Session, product_id: int, *, keyword: str | None = None, actor: str = "agent", metrics: Any | None = None,
        analyzer: Callable[[list[str]], dict[str, Any]] = _analyze) -> ProductVetting:
    product = session.get(Product, product_id)
    if product is None:
        raise VettingError(f"produto {product_id} não encontrado")
    kw = (keyword or "").strip().lower() or _last_keyword(session, product_id) or derive_keyword(storefront.clean_title(product.title, 90))
    if metrics is None:
        metrics = analyzer([kw]).get(kw)
    sig = _signals(product, metrics)
    score, verdict, reasons = _score(sig)
    row = ProductVetting(product_id=product_id, keyword=kw, verdict=verdict, score=score, monthly_volume=sig["volume"], cpc_brl=sig["cpc"],
                         trend_direction=sig["trend"], growth_pct_30d=sig["growth"], platform_sold=sig["sold"], rating=sig["rating"],
                         commission_per_sale_brl=sig["commission"], breakeven_conversion=sig["breakeven"], delivery_days=sig["delivery_days"],
                         ship_from=sig["ship_from"], reasons=reasons, created_by=actor[:64])
    session.add(row)
    session.flush()
    return row


def _last_keyword(session: Session, product_id: int) -> str | None:
    return session.scalar(select(ProductVetting.keyword).where(ProductVetting.product_id == product_id).order_by(ProductVetting.id.desc()).limit(1))


def latest(session: Session, product_id: int) -> ProductVetting | None:
    return session.scalar(select(ProductVetting).where(ProductVetting.product_id == product_id).order_by(ProductVetting.id.desc()).limit(1))


def out(v: ProductVetting | None) -> dict | None:
    if v is None:
        return None
    return {"product_id": v.product_id, "keyword": v.keyword, "verdict": v.verdict, "score": v.score, "monthly_volume": v.monthly_volume,
            "cpc_brl": v.cpc_brl, "trend": v.trend_direction, "growth_pct_30d": v.growth_pct_30d, "platform_sold": v.platform_sold,
            "rating": v.rating, "commission_per_sale_brl": v.commission_per_sale_brl, "breakeven_conversion": v.breakeven_conversion,
            "delivery_days": v.delivery_days, "ship_from": v.ship_from, "reasons": v.reasons or [],
            "at": v.created_at.isoformat() if v.created_at else None}


def _aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=UTC)


def active_test_authorization(session: Session, product_id: int | None, *, now: datetime | None = None) -> ProductVetting | None:
    """A autorização de teste pago do operador ainda válida (14 dias), se houver. Uma triagem nova não a revoga: só o prazo."""
    if product_id is None:
        return None
    since = (now or datetime.now(UTC)) - timedelta(days=TEST_DAYS)
    for v in session.scalars(select(ProductVetting).where(ProductVetting.product_id == product_id, ProductVetting.verdict == TEST_VERDICT)
                             .order_by(ProductVetting.id.desc())):
        if _aware(v.created_at) >= since:
            return v
    return None


def authorize_test(session: Session, product_id: int, *, actor: str, now: datetime | None = None) -> ProductVetting:
    """Só o operador (a rota exige `connectors.manage`; o agente não tem esta ferramenta): libera anúncio pago do produto por 14 dias para um teste
    de campanha mesmo sem parecer `aprovado_pago`. Guarda os números da última triagem e o motivo, para o balanço mostrar o que foi aposta."""
    product = session.get(Product, product_id)
    if product is None:
        raise VettingError(f"produto {product_id} não encontrado")
    base = latest(session, product_id)
    if base is not None and base.verdict == "reprovado":
        raise VettingError(f"produto {product_id} foi reprovado na triagem ({'; '.join((base.reasons or [])[:2])}): não dá para liberar teste pago.")
    b = base
    reasons = [f"teste pago autorizado pelo operador {actor} por {TEST_DAYS} dias (sem parecer favorável na triagem)", *((b.reasons or []) if b else [])]
    row = ProductVetting(product_id=product_id, keyword=(b.keyword if b else derive_keyword(storefront.clean_title(product.title, 90))),
                         verdict=TEST_VERDICT, score=(b.score if b else 0.0), monthly_volume=b.monthly_volume if b else None,
                         cpc_brl=b.cpc_brl if b else None, trend_direction=b.trend_direction if b else None,
                         growth_pct_30d=b.growth_pct_30d if b else None, platform_sold=b.platform_sold if b else None,
                         rating=b.rating if b else None, commission_per_sale_brl=b.commission_per_sale_brl if b else None,
                         breakeven_conversion=b.breakeven_conversion if b else None, delivery_days=b.delivery_days if b else None,
                         ship_from=b.ship_from if b else None, reasons=reasons, created_by=actor[:64])
    session.add(row)
    session.flush()
    return row


def require_paid_ok(session: Session, product_id: int | None, *, now: datetime | None = None) -> None:
    """Trava: anúncio que gasta dinheiro só nasce de produto com parecer `aprovado_pago` recente (ou teste autorizado pelo operador, por 14 dias)."""
    if not GATE_ENABLED or product_id is None:
        return
    if active_test_authorization(session, product_id, now=now) is not None:
        return
    v = latest(session, product_id)
    if v is None:
        raise VettingError(f"produto {product_id} ainda não passou pela triagem de procura e demanda: rode `product_vet` antes de criar anúncio pago.")
    age = (now or datetime.now(UTC)) - _aware(v.created_at)
    if age > timedelta(days=VALID_DAYS):
        raise VettingError(f"a triagem do produto {product_id} tem {age.days} dias (vale {VALID_DAYS}): rode `product_vet` de novo.")
    if v.verdict != PAID_VERDICT:
        why = "; ".join((v.reasons or [])[:2])
        raise VettingError(f"produto {product_id} não tem respaldo para anúncio pago ({v.verdict}): {why}. Use só divulgação orgânica.")


def _candidates(session: Session) -> list[Product]:
    """Produtos que importam: os da vitrine (visíveis) e os que têm anúncio."""
    ids = {r.product_id for r in session.scalars(select(StorefrontItem).where(StorefrontItem.hidden.is_(False)))}
    ids |= {a.product_id for a in session.scalars(select(AdCampaign)) if a.product_id and a.status in ("active", "paused")}
    if not ids:
        return []
    return list(session.scalars(select(Product).where(Product.id.in_(ids), Product.is_active.is_(True))))


def vet_due(session: Session, *, limit: int = 10, max_age_days: int = 7, actor: str = "sistema",
            analyzer: Callable[[list[str]], dict[str, Any]] = _analyze, now: datetime | None = None) -> list[ProductVetting]:
    """Refaz a triagem dos que nunca foram vistos ou estão velhos (os mais antigos primeiro). Em lote: uma consulta ao Google para todos."""
    now = now or datetime.now(UTC)
    due = []
    for p in _candidates(session):
        v = latest(session, p.id)
        if v is None or now - _aware(v.created_at) > timedelta(days=max_age_days):
            due.append((v.created_at.timestamp() if v and v.created_at else 0, p))
    due.sort(key=lambda t: t[0])
    chosen = [p for _, p in due[:limit]]
    if not chosen:
        return []
    kws = {p.id: (_last_keyword(session, p.id) or derive_keyword(storefront.clean_title(p.title, 90))) for p in chosen}
    try:
        found = analyzer(list(dict.fromkeys(kws.values())))
    except Exception:  # noqa: BLE001 - Google fora do ar: segue sem dado de busca (o parecer diz isso)
        found = {}
    return [vet(session, p.id, keyword=kws[p.id], actor=actor, metrics=found.get(kws[p.id]), analyzer=analyzer) for p in chosen]


def review(session: Session, period: str = "weekly", *, now: datetime | None = None) -> dict:
    """Balanço semanal, quinzenal ou mensal: o que foi triado, o que mudou de parecer e onde há anúncio sem respaldo."""
    days = {"weekly": 7, "biweekly": 15, "monthly": 30}.get(period)
    if days is None:
        raise VettingError("período deve ser weekly, biweekly ou monthly")
    now = now or datetime.now(UTC)
    since = now - timedelta(days=days)
    rows = [v for v in session.scalars(select(ProductVetting).order_by(ProductVetting.id)) if _aware(v.created_at) >= since]
    last: dict[int, ProductVetting] = {}
    first: dict[int, ProductVetting] = {}
    for v in rows:
        last[v.product_id] = v
        first.setdefault(v.product_id, v)
    counts: dict[str, int] = {}
    for v in last.values():
        counts[v.verdict] = counts.get(v.verdict, 0) + 1
    changed = [{"product_id": pid, "from": first[pid].verdict, "to": last[pid].verdict} for pid in last if first[pid].verdict != last[pid].verdict]
    unbacked = []
    for ad in session.scalars(select(AdCampaign).where(AdCampaign.status.in_(("active", "paused")))):
        v = latest(session, ad.product_id) if ad.product_id else None
        if (v is None or v.verdict != PAID_VERDICT) and active_test_authorization(session, ad.product_id, now=now) is None:
            unbacked.append({"ad_id": ad.id, "product_id": ad.product_id, "platform": ad.platform, "status": ad.status, "spent_brl": ad.spent_brl,
                             "verdict": v.verdict if v else "sem triagem"})
    tests = [{"product_id": v.product_id, "at": v.created_at.isoformat() if v.created_at else None} for v in session.scalars(
        select(ProductVetting).where(ProductVetting.verdict == TEST_VERDICT).order_by(ProductVetting.id.desc())) if _aware(v.created_at) >= now - timedelta(days=TEST_DAYS)]
    return {"period": period, "days": days, "vetted": len(last), "by_verdict": counts, "changed": changed, "ads_without_backing": unbacked,
            "paid_tests_authorized": tests,
            "paid_ok": [out(v) for v in last.values() if v.verdict == PAID_VERDICT][:15]}
