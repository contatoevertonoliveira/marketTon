"""Heat Score — força atual do produto no mercado (briefing seção 5).

Responde "quão quente este produto está agora", independentemente de servir ou
não à nossa operação. É deliberadamente separado do Opportunity Score: um
produto pode estar fervendo e ainda assim ser ruim para nós (comissão baixa,
saturado, fora do nosso nicho).
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

DIMENSION = "HEAT"
VERSION = "v1"

WEIGHTS: dict[str, float] = {
    "sales_velocity": 0.30,
    "sales_momentum": 0.25,
    "review_velocity": 0.20,
    "rating": 0.15,
    "stock_health": 0.10,
}

LABELS: dict[str, str] = {
    "sales_velocity": "volume de vendas recentes",
    "sales_momentum": "aceleração das vendas",
    "review_velocity": "fluxo de novas avaliações",
    "rating": "avaliação dos compradores",
    "stock_health": "disponibilidade de estoque",
}

UNITS: dict[str, str] = {
    "sales_velocity": "un.",
    "sales_momentum": "%",
    "review_velocity": "aval.",
    "rating": "estrelas",
    "stock_health": "un.",
}

# Tetos de saturação: valores a partir dos quais o sinal já é "muito forte".
SALES_CEILING = 5000.0
REVIEW_CEILING = 2000.0


def _sales_velocity(inputs: dict[str, Any]) -> float | None:
    return saturate(inputs.get("sold_last_period"), ceiling=SALES_CEILING)


def _sales_momentum(inputs: dict[str, Any]) -> float | None:
    return growth(inputs.get("sold_last_period"), inputs.get("sold_previous_period"))


def _review_velocity(inputs: dict[str, Any]) -> float | None:
    return saturate(inputs.get("new_reviews_period"), ceiling=REVIEW_CEILING)


def _rating(inputs: dict[str, Any]) -> float | None:
    # Escala de 5 estrelas. Abaixo de 3.0 é reprovação para venda por afiliado;
    # 4.8+ é excelência.
    return normalize(inputs.get("rating"), best=5.0, worst=3.0)


def _stock_health(inputs: dict[str, Any]) -> float | None:
    quantity = inputs.get("available_quantity")
    if quantity is None:
        return None
    # Estoque zerado é o pior cenário; a partir de 50 unidades é confortável.
    return normalize(float(quantity), best=50.0, worst=0.0)


SPEC = register(
    AlgorithmSpec(
        dimension=DIMENSION,
        version=VERSION,
        name="Heat Score",
        algorithm_key="heat.v1",
        description=(
            "Força atual do produto no mercado, medida por velocidade e aceleração de vendas, "
            "fluxo de avaliações, nota e disponibilidade. Não considera se o produto serve à nossa operação."
        ),
        weights=WEIGHTS,
        functions={
            "sales_velocity": _sales_velocity,
            "sales_momentum": _sales_momentum,
            "review_velocity": _review_velocity,
            "rating": _rating,
            "stock_health": _stock_health,
        },
        labels=LABELS,
        units=UNITS,
        parameters={"gamma": 0.6, "min_confidence": 0.4},
        input_keys={
            "sales_velocity": "sold_last_period",
            "sales_momentum": "sold_last_period",
            "review_velocity": "new_reviews_period",
            "rating": "rating",
            "stock_health": "available_quantity",
        },
        formatters={
            "sales_velocity": lambda v: f"{v:,.0f} unidades vendidas no período".replace(",", "."),
            "sales_momentum": lambda v: (
                f"vendas em alta de {v:.0%}" if v > 0 else f"vendas em queda de {abs(v):.0%}"
            ),
            "review_velocity": lambda v: f"{v:,.0f} avaliações novas no período".replace(",", "."),
            "rating": lambda v: f"nota {v:.1f} de 5",
            "stock_health": lambda v: f"{v:,.0f} unidades em estoque".replace(",", "."),
        },
    )
)
