"""Versioned, explainable scoring formulas (briefing §5 and §6).

Design rules this module must keep:
  * every formula is a pure function of a `Product` (plus, optionally, other
    already-computed scores) — no hidden state, no opaque model call;
  * a formula never invents a value for a missing field. Missing inputs are
    dropped and the remaining weights are renormalized; the result's
    `reliability` is downgraded accordingly and an explicit "dado
    indisponível" reason is recorded;
  * when a score type has no usable signal at all for a product yet
    (creative_saturation / portfolio / creative in this phase — there is no
    creative-market, sales or creative-performance data source wired up
    yet), `compute_score` returns None rather than fabricating a number.
    Callers must skip persisting a ScoreRecord in that case.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScoreResult:
    result: float
    inputs: dict
    weights: dict
    reasons: list[tuple[str, str]] = field(default_factory=list)  # (polarity, text)
    reliability: str = "medium"


def _weighted(parts: dict[str, tuple[float | None, float]]) -> tuple[float, dict, dict, list[str]]:
    """parts: name -> (normalized_value_0_1_or_None, weight). Drops missing values
    and renormalizes remaining weights. Returns (score_0_100, used_inputs, used_weights, missing_names)."""
    usable = {k: v for k, (v, _w) in parts.items() if v is not None}
    missing = [k for k, (v, _w) in parts.items() if v is None]
    if not usable:
        return 0.0, {}, {}, list(parts.keys())
    total_w = sum(parts[k][1] for k in usable)
    if total_w <= 0:
        total_w = 1.0
    used_weights = {k: round(parts[k][1] / total_w, 4) for k in usable}
    score = sum(usable[k] * used_weights[k] for k in usable) * 100
    return round(score, 2), usable, used_weights, missing


def _reliability_for(missing_count: int, total_count: int) -> str:
    if missing_count == 0:
        return "high"
    if missing_count < total_count / 2:
        return "medium"
    return "low"


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ---------------------------------------------------------------------------
# Heat Score — briefing §5: "força atual do produto no mercado".
# ---------------------------------------------------------------------------
HEAT_VERSION = "v1"


def compute_heat(product) -> ScoreResult | None:
    orders = product.orders_count
    rating = product.rating
    rating_count = product.rating_count
    discount = product.discount_pct
    ranking = product.ranking

    parts = {
        "orders_count": (_clip01(orders / 1000) if orders is not None else None, 0.4),
        "rating": (_clip01((rating - 3) / 2) if rating is not None else None, 0.2),
        "rating_count": (_clip01(rating_count / 500) if rating_count is not None else None, 0.15),
        "discount_pct": (_clip01((discount or 0) / 50) if discount is not None else None, 0.1),
        "ranking": (_clip01(1 - (ranking / 100)) if ranking is not None else None, 0.15),
    }
    score, used_inputs, used_weights, missing = _weighted(parts)
    reasons: list[tuple[str, str]] = []
    if orders is not None and orders > 500:
        reasons.append(("+", f"volume de pedidos alto ({orders})"))
    if rating is not None and rating >= 4.5:
        reasons.append(("+", f"avaliação muito boa ({rating})"))
    if discount is not None and discount >= 20:
        reasons.append(("+", f"desconto relevante ({discount:.0f}%)"))
    for name in missing:
        reasons.append(("-", f"dado indisponível: {name}"))
    reliability = _reliability_for(len(missing), len(parts))
    return ScoreResult(score, used_inputs, used_weights, reasons, reliability)


# ---------------------------------------------------------------------------
# Opportunity Score — briefing §5: potencial do produto para NOSSA operação
# de afiliados especificamente (não força genérica de mercado).
# ---------------------------------------------------------------------------
OPPORTUNITY_VERSION = "v1"
TICKET_TARGET_MIN = 97.0
TICKET_TARGET_MAX = 297.0


def compute_opportunity(product, heat_result: ScoreResult | None = None) -> ScoreResult | None:
    commission = product.commission_pct
    price = product.price

    ticket_fit = None
    if price is not None:
        center = (TICKET_TARGET_MIN + TICKET_TARGET_MAX) / 2
        spread = max(TICKET_TARGET_MAX - TICKET_TARGET_MIN, 1.0)
        ticket_fit = _clip01(1 - abs(price - center) / spread)

    heat_signal = _clip01(heat_result.result / 100) if heat_result is not None else None

    parts = {
        "commission_pct": (_clip01((commission or 0) / 20) if commission is not None else None, 0.4),
        "ticket_fit": (ticket_fit, 0.35),
        "heat": (heat_signal, 0.25),
    }
    score, used_inputs, used_weights, missing = _weighted(parts)
    reasons: list[tuple[str, str]] = []
    if commission is not None and commission >= 10:
        reasons.append(("+", f"comissão competitiva ({commission:.1f}%)"))
    elif commission is not None:
        reasons.append(("-", f"comissão baixa ({commission:.1f}%)"))
    if ticket_fit is not None and ticket_fit >= 0.7:
        reasons.append(("+", "preço dentro da faixa ideal de ticket"))
    if heat_signal is not None and heat_signal >= 0.6:
        reasons.append(("+", "produto com boa força de mercado (heat score)"))
    for name in missing:
        reasons.append(("-", f"dado indisponível: {name}"))
    reliability = _reliability_for(len(missing), len(parts))
    return ScoreResult(score, used_inputs, used_weights, reasons, reliability)


# ---------------------------------------------------------------------------
# Producer Momentum Score — briefing §5: sinais de força comercial/promocional
# do vendedor/produtor.
# ---------------------------------------------------------------------------
PRODUCER_MOMENTUM_VERSION = "v1"


def compute_producer_momentum(product) -> ScoreResult | None:
    has_promo = bool(product.promotions) if product.promotions is not None else None
    discount = product.discount_pct
    orders = product.orders_count

    parts = {
        "active_promotions": (1.0 if has_promo else (0.0 if has_promo is not None else None), 0.4),
        "discount_pct": (_clip01((discount or 0) / 40) if discount is not None else None, 0.3),
        "orders_count": (_clip01(orders / 1000) if orders is not None else None, 0.3),
    }
    score, used_inputs, used_weights, missing = _weighted(parts)
    reasons: list[tuple[str, str]] = []
    if has_promo:
        reasons.append(("+", "vendedor com promoções ativas"))
    for name in missing:
        reasons.append(("-", f"dado indisponível: {name}"))
    reliability = _reliability_for(len(missing), len(parts))
    return ScoreResult(score, used_inputs, used_weights, reasons, reliability)


CALCULATORS = {
    "heat": (HEAT_VERSION, compute_heat),
    "opportunity": (OPPORTUNITY_VERSION, compute_opportunity),
    "producer_momentum": (PRODUCER_MOMENTUM_VERSION, compute_producer_momentum),
    # "creative_saturation", "portfolio" and "creative" are intentionally
    # absent here: this phase has no creative-market signal, no sales/click
    # tracking and no creative-performance data source to compute them from
    # honestly. They will be added once those data sources exist.
}


def compute_all_for_product(product) -> dict[str, tuple[str, ScoreResult]]:
    """Runs every available calculator for a product. Returns {score_type: (version, ScoreResult)}."""
    heat = compute_heat(product)
    out: dict[str, tuple[str, ScoreResult]] = {}
    if heat is not None:
        out["heat"] = (HEAT_VERSION, heat)
    opportunity = compute_opportunity(product, heat_result=heat)
    if opportunity is not None:
        out["opportunity"] = (OPPORTUNITY_VERSION, opportunity)
    momentum = compute_producer_momentum(product)
    if momentum is not None:
        out["producer_momentum"] = (PRODUCER_MOMENTUM_VERSION, momentum)
    return out
