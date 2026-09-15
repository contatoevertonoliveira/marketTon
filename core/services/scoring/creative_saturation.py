"""Creative Saturation Score — saturação competitiva de criativos/ofertas
(briefing seção 5).

O briefing condiciona este score: "quando houver dados suficientes". Por isso a
ausência de dados de anúncios produz INSUFFICIENT_DATA em vez de estimativa — e o
Opportunity Score simplesmente ignora o fator, reduzindo a própria confiança.

Interpretação para o operador: score ALTO = mercado SATURADO = pior para nós.
As funções abaixo devolvem o valor na direção "maior = mais saturado" e o motor
inverte, conforme `higher_is_better=False`. O texto da explicação fala sempre em
saturação, que é como o operador pensa — nunca em "normalizado".
"""
from __future__ import annotations

from typing import Any

from core.services.scoring.engine import (
    AlgorithmSpec,
    normalize,
    register,
    saturate,
)

DIMENSION = "CREATIVE_SATURATION"
VERSION = "v1"

WEIGHTS: dict[str, float] = {
    "ad_volume": 0.35,
    "advertiser_density": 0.25,
    "creative_age": 0.20,
    "offer_homogeneity": 0.20,
}

LABELS: dict[str, str] = {
    "ad_volume": "volume de anúncios ativos",
    "advertiser_density": "quantidade de anunciantes distintos",
    "creative_age": "tempo médio dos anúncios no ar",
    "offer_homogeneity": "semelhança entre as ofertas",
}

UNITS: dict[str, str] = {
    "ad_volume": "anúncios",
    "advertiser_density": "anunciantes",
    "creative_age": "dias",
    "offer_homogeneity": "%",
}

AD_VOLUME_CEILING = 200.0
ADVERTISER_CEILING = 50.0
# Anúncios antigos rodando = oferta já validada e muito explorada.
CREATIVE_AGE_CEILING = 180.0


def _ad_volume(inputs: dict[str, Any]) -> float | None:
    """Muitos anúncios do mesmo produto = saturação alta."""
    return saturate(inputs.get("active_ads_count"), ceiling=AD_VOLUME_CEILING)


def _advertiser_density(inputs: dict[str, Any]) -> float | None:
    return saturate(inputs.get("distinct_advertisers"), ceiling=ADVERTISER_CEILING)


def _creative_age(inputs: dict[str, Any]) -> float | None:
    """Quanto mais antigo o anúncio médio, mais explorada está a oferta."""
    return normalize(inputs.get("median_ad_age_days"), best=CREATIVE_AGE_CEILING, worst=0.0)


def _offer_homogeneity(inputs: dict[str, Any]) -> float | None:
    """Percentual de anúncios com a mesma oferta/ângulo: alto = pouca diferenciação."""
    homogeneity = inputs.get("homogeneous_offer_pct")
    if homogeneity is None:
        return None
    return normalize(float(homogeneity), best=100.0, worst=0.0)


SPEC = register(
    AlgorithmSpec(
        dimension=DIMENSION,
        version=VERSION,
        name="Creative Saturation Score",
        algorithm_key="creative_saturation.v1",
        description=(
            "Grau de saturação competitiva de criativos e ofertas para o produto ou segmento. "
            "Score alto significa mercado saturado e pouco espaço para um novo criativo. "
            "Requer dados de bibliotecas de anúncios; sem eles o resultado é INSUFFICIENT_DATA."
        ),
        weights=WEIGHTS,
        functions={
            "ad_volume": _ad_volume,
            "advertiser_density": _advertiser_density,
            "creative_age": _creative_age,
            "offer_homogeneity": _offer_homogeneity,
        },
        labels=LABELS,
        units=UNITS,
        parameters={"gamma": 0.6, "min_confidence": 0.5},
        input_keys={
            "ad_volume": "active_ads_count",
            "advertiser_density": "distinct_advertisers",
            "creative_age": "median_ad_age_days",
            "offer_homogeneity": "homogeneous_offer_pct",
        },
        # Esta dimensão é um ÍNDICE, não uma nota: maior significa mercado mais
        # saturado, ou seja, pior para nós. A UI precisa saber disso para não
        # pintar um score alto de verde.
        higher_score_is_better=False,
        higher_is_better={
            "ad_volume": False,
            "advertiser_density": False,
            "creative_age": False,
            "offer_homogeneity": False,
        },
        formatters={
            "ad_volume": lambda v: f"{v:,.0f} anúncios ativos para este produto".replace(",", "."),
            "advertiser_density": lambda v: f"{v:,.0f} anunciantes distintos disputando".replace(",", "."),
            "creative_age": lambda v: f"anúncios no ar há {v:.0f} dias em média",
            "offer_homogeneity": lambda v: f"{v:.0f}% das ofertas usam o mesmo ângulo",
        },
    )
)
