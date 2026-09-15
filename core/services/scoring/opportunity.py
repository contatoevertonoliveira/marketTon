"""Opportunity Score — potencial daquele produto para a nossa operação (briefing seção 5).

É o score que responde à pergunta do briefing seção 6: "por que este produto foi
recomendado?". Distingue-se do Heat Score porque incorpora o que importa para
*afiliado*: comissão, ticket compatível com nosso público, concorrência entre
afiliados e aderência ao nicho — não apenas volume de vendas.
"""
from __future__ import annotations

from typing import Any

from core.services.scoring.engine import (
    AlgorithmSpec,
    normalize,
    register,
    saturate,
)

DIMENSION = "OPPORTUNITY"
VERSION = "v1"

WEIGHTS: dict[str, float] = {
    "commission": 0.25,
    "ticket_fit": 0.20,
    "heat": 0.20,
    "producer_momentum": 0.15,
    "saturation_headroom": 0.10,
    "affiliate_pressure": 0.10,
}

LABELS: dict[str, str] = {
    "commission": "comissão oferecida",
    "ticket_fit": "faixa de preço adequada ao público",
    "heat": "força atual no mercado",
    "producer_momentum": "momento comercial do produtor",
    "saturation_headroom": "espaço livre de saturação",
    "affiliate_pressure": "concorrência de outros afiliados",
}

UNITS: dict[str, str] = {
    "commission": "%",
    "ticket_fit": "R$",
    "heat": "pts",
    "producer_momentum": "pts",
    "saturation_headroom": "pts",
    "affiliate_pressure": "anúncios",
}

# Faixa de ticket alvo da operação. Definida em parâmetros, não no código, para
# que uma mudança de estratégia gere uma nova versão do algoritmo.
DEFAULT_TICKET_MIN = 30.0
DEFAULT_TICKET_MAX = 300.0
DEFAULT_TICKET_SWEET_MIN = 97.0
DEFAULT_TICKET_SWEET_MAX = 297.0
# Acima disto consideramos a comissão excelente para afiliação.
COMMISSION_CEILING = 30.0
# Número de anúncios ativos a partir do qual a concorrência é considerada máxima.
AFFILIATE_PRESSURE_CEILING = 50.0


def _commission(inputs: dict[str, Any]) -> float | None:
    return saturate(inputs.get("affiliate_commission_pct"), ceiling=COMMISSION_CEILING)


def _ticket_fit(inputs: dict[str, Any]) -> float | None:
    """Preço dentro da faixa alvo. Zona preferencial recebe normalizado 1,0.

    Os limites vêm de `parameters` (e portanto da versão do algoritmo) e podem
    ser sobrescritos por chamada — mudar a faixa alvo exige publicar uma versão
    nova, o que mantém o histórico comparável.
    """
    price = inputs.get("price")
    if price is None:
        return None
    sweet_min = float(inputs.get("ticket_sweet_min", DEFAULT_TICKET_SWEET_MIN))
    sweet_max = float(inputs.get("ticket_sweet_max", DEFAULT_TICKET_SWEET_MAX))
    outer_min = float(inputs.get("ticket_min", DEFAULT_TICKET_MIN))
    outer_max = float(inputs.get("ticket_max", DEFAULT_TICKET_MAX))

    if sweet_min <= price <= sweet_max:
        return 1.0
    if price < outer_min or price > outer_max:
        # Fora da faixa operacional: não é "ruim", é inaplicável.
        return 0.0
    if price < sweet_min:
        return normalize(price, best=sweet_min, worst=outer_min)
    return normalize(price, best=sweet_max, worst=outer_max)


def _heat(inputs: dict[str, Any]) -> float | None:
    """Heat Score já calculado, reutilizado como insumo (0..100 -> 0..1)."""
    heat_score = inputs.get("heat_score")
    if heat_score is None:
        return None
    return float(heat_score) / 100.0


def _producer_momentum(inputs: dict[str, Any]) -> float | None:
    momentum = inputs.get("producer_momentum_score")
    if momentum is None:
        return None
    return float(momentum) / 100.0


def _saturation_headroom(inputs: dict[str, Any]) -> float | None:
    """Saturação de criativos (0..100) na direção "maior = mais saturado".

    A inversão para "espaço livre" é feita pelo motor via `higher_is_better=False`.
    """
    saturation = inputs.get("creative_saturation_score")
    if saturation is None:
        return None
    return float(saturation) / 100.0


def _affiliate_pressure(inputs: dict[str, Any]) -> float | None:
    """Concorrência de afiliados na direção "maior = pior".

    Muitos anúncios ativos significam menos espaço; a inversão é do motor.
    """
    ads = inputs.get("competing_ads_count")
    if ads is None:
        return None
    return normalize(float(ads), best=AFFILIATE_PRESSURE_CEILING, worst=0.0)


SPEC = register(
    AlgorithmSpec(
        dimension=DIMENSION,
        version=VERSION,
        name="Opportunity Score",
        algorithm_key="opportunity.v1",
        description=(
            "Potencial do produto especificamente para a nossa operação de afiliados: comissão, "
            "aderência de preço, força de mercado, momento do produtor, espaço livre de saturação "
            "e pressão de concorrência entre afiliados."
        ),
        weights=WEIGHTS,
        functions={
            "commission": _commission,
            "ticket_fit": _ticket_fit,
            "heat": _heat,
            "producer_momentum": _producer_momentum,
            "saturation_headroom": _saturation_headroom,
            "affiliate_pressure": _affiliate_pressure,
        },
        labels=LABELS,
        units=UNITS,
        parameters={
            "gamma": 0.6,
            "min_confidence": 0.5,
            "ticket_min": DEFAULT_TICKET_MIN,
            "ticket_max": DEFAULT_TICKET_MAX,
            "ticket_sweet_min": DEFAULT_TICKET_SWEET_MIN,
            "ticket_sweet_max": DEFAULT_TICKET_SWEET_MAX,
            "commission_ceiling": COMMISSION_CEILING,
            "affiliate_pressure_ceiling": AFFILIATE_PRESSURE_CEILING,
        },
        input_keys={
            "commission": "affiliate_commission_pct",
            "ticket_fit": "price",
            "heat": "heat_score",
            "producer_momentum": "producer_momentum_score",
            "saturation_headroom": "creative_saturation_score",
            "affiliate_pressure": "competing_ads_count",
        },
        formatters={
            "commission": lambda v: f"comissão de {v:g}%",
            "ticket_fit": lambda v: f"preço R$ {v:,.2f} dentro da faixa alvo",
            "heat": lambda v: f"heat score {v:.0f}/100",
            "producer_momentum": lambda v: f"produtor com momentum {v:.0f}/100",
            "saturation_headroom": lambda v: (
                f"saturação baixa (score {v:.0f}/100)" if v >= 50 else f"saturação alta (score {v:.0f}/100)"
            ),
            "affiliate_pressure": lambda v: f"{v:.0f} anúncios concorrentes ativos",
        },
        # Fatores em que o valor bruto alto é desfavorável. A inversão é feita pelo
        # motor; aqui apenas declaramos a direção para que a normalização e o sinal
        # exibido permaneçam consistentes.
        higher_is_better={
            "commission": True,
            "ticket_fit": True,
            "heat": True,
            "producer_momentum": True,
            "saturation_headroom": False,
            "affiliate_pressure": False,
        },
    )
)
