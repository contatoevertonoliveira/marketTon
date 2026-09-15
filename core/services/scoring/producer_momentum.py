"""Producer Momentum Score — força comercial/promocional do vendedor ou produtor
(briefing seção 5).

Mede o momento do produtor, não do produto: um produtor em plena atividade
promocional tende a sustentar o desempenho de um lançamento, enquanto um produtor
estagnado faz um bom produto esfriar. É insumo do Opportunity Score.
"""
from __future__ import annotations

from typing import Any

from core.services.scoring.engine import (
    AlgorithmSpec,
    growth,
    normalize,
    register,
    saturate,
)

DIMENSION = "PRODUCER_MOMENTUM"
VERSION = "v1"

WEIGHTS: dict[str, float] = {
    "sales_track_record": 0.25,
    "listing_growth": 0.20,
    "reputation": 0.20,
    "promotional_activity": 0.20,
    "responsiveness": 0.15,
}

LABELS: dict[str, str] = {
    "sales_track_record": "histórico de vendas do produtor",
    "listing_growth": "expansão do catálogo",
    "reputation": "reputação no marketplace",
    "promotional_activity": "atividade promocional recente",
    "responsiveness": "qualidade do atendimento",
}

UNITS: dict[str, str] = {
    "sales_track_record": "vendas",
    "listing_growth": "%",
    "reputation": "pts",
    "promotional_activity": "ações",
    "responsiveness": "%",
}

SALES_CEILING = 100_000.0
PROMO_CEILING = 20.0

REPUTATION_BY_LEVEL: dict[str, float] = {
    # Mercado Livre usa estes rótulos. Outros marketplaces caem no fallback.
    "5_green": 1.0,
    "4_light_green": 0.8,
    "3_yellow": 0.5,
    "2_orange": 0.25,
    "1_red": 0.0,
    "leader": 1.0,
    "platinum": 0.9,
    "gold": 0.75,
    "silver": 0.5,
    "bronze": 0.2,
    "new": 0.3,
}


def _sales_track_record(inputs: dict[str, Any]) -> float | None:
    return saturate(inputs.get("seller_total_sales"), ceiling=SALES_CEILING)


def _listing_growth(inputs: dict[str, Any]) -> float | None:
    return growth(inputs.get("seller_active_listings"), inputs.get("seller_active_listings_previous"))


def _reputation(inputs: dict[str, Any]) -> float | None:
    """Combina reputação declarada e percentual de avaliações positivas."""
    level_value = None
    level = inputs.get("seller_reputation_level")
    if isinstance(level, str):
        level_value = REPUTATION_BY_LEVEL.get(level.lower())

    positive = inputs.get("seller_positive_rating_pct")
    positive_value = normalize(positive, best=100.0, worst=80.0) if positive is not None else None

    if level_value is None and positive_value is None:
        return None
    if level_value is None:
        return positive_value
    if positive_value is None:
        return level_value
    # Média simples: reputação formal e avaliação real dos compradores.
    return (level_value + positive_value) / 2.0


def _promotional_activity(inputs: dict[str, Any]) -> float | None:
    """Promoções e cupons ativos: sinal direto de esforço comercial."""
    return saturate(inputs.get("seller_active_promotions"), ceiling=PROMO_CEILING)


def _responsiveness(inputs: dict[str, Any]) -> float | None:
    """Percentual de mensagens respondidas em prazo, quando o marketplace expõe."""
    return normalize(inputs.get("seller_response_rate_pct"), best=100.0, worst=50.0)


SPEC = register(
    AlgorithmSpec(
        dimension=DIMENSION,
        version=VERSION,
        name="Producer Momentum Score",
        algorithm_key="producer_momentum.v1",
        description=(
            "Sinais de força comercial e promocional do produtor: histórico de vendas, expansão de "
            "catálogo, reputação, promoções ativas e qualidade de atendimento."
        ),
        weights=WEIGHTS,
        functions={
            "sales_track_record": _sales_track_record,
            "listing_growth": _listing_growth,
            "reputation": _reputation,
            "promotional_activity": _promotional_activity,
            "responsiveness": _responsiveness,
        },
        labels=LABELS,
        units=UNITS,
        parameters={"gamma": 0.6, "min_confidence": 0.4},
        input_keys={
            "sales_track_record": "seller_total_sales",
            "listing_growth": "seller_active_listings",
            "reputation": "seller_reputation_level",
            "promotional_activity": "seller_active_promotions",
            "responsiveness": "seller_response_rate_pct",
        },
        formatters={
            "sales_track_record": lambda v: f"{v:,.0f} vendas acumuladas do produtor".replace(",", "."),
            "listing_growth": lambda v: (
                f"catálogo crescendo {v:.0%}" if v > 0 else f"catálogo encolhendo {abs(v):.0%}"
            ),
            "reputation": lambda v: f"reputação {v * 100:.0f}/100",
            "promotional_activity": lambda v: f"{v:,.0f} promoções ativas".replace(",", "."),
            "responsiveness": lambda v: f"atendimento responde {v:.0f}% em prazo",
        },
    )
)
