"""Travas de gasto em anúncios. Valores definidos pelo operador em Integrações > Orçamento de anúncios.

O agente **não consegue** alterá-los: só quem tem `connectors.manage` mexe nos cartões (o papel do agente não tem). Toda ferramenta de
anúncios deve consultar `load()` e recusar o que passar do teto.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.service_credentials import ServiceCredential

SERVICE = "ads_budget"


class BudgetError(ValueError):
    """Orçamento inválido; a mensagem é segura para exibir."""


@dataclass
class AdsBudget:
    weekly_brl: float
    daily_cap_brl: float
    max_products: int
    creatives_per_product: int
    approval_required: bool = True  # sempre: campanha nova nasce pausada e só liga com a aprovação do operador


def _num(value, name: str, *, integer: bool = False, minimum: float = 0.01, maximum: float = 1_000_000) -> float:
    text = str(value or "").strip().replace("R$", "").replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        number = float(text)
    except ValueError as exc:
        raise BudgetError(f"{name}: informe um número") from exc
    if number < minimum or number > maximum:
        raise BudgetError(f"{name}: informe um valor entre {minimum:g} e {maximum:g}")
    if integer and number != int(number):
        raise BudgetError(f"{name}: informe um número inteiro")
    return int(number) if integer else round(number, 2)


def parse(values: dict) -> AdsBudget:
    weekly = _num(values.get("weekly_brl"), "valor por semana")
    daily = _num(values.get("daily_cap_brl"), "teto por dia")
    if daily > weekly:
        raise BudgetError("o teto por dia não pode passar do valor da semana")
    if daily * 7 < weekly:
        raise BudgetError("o teto por dia é baixo demais para gastar o valor da semana (teto × 7 < semana)")
    products = _num(values.get("max_products") or 3, "produtos por semana", integer=True, minimum=1, maximum=20)
    creatives = _num(values.get("creatives_per_product") or 2, "criativos por produto", integer=True, minimum=1, maximum=6)
    return AdsBudget(weekly, daily, products, creatives)


def load(session: Session) -> AdsBudget | None:
    row = session.scalar(select(ServiceCredential).where(ServiceCredential.service == SERVICE))
    if row is None or not row.enabled:
        return None
    try:
        return parse(row.values or {})
    except BudgetError:
        return None


def check(values: dict) -> str:
    b = parse(values)
    per_slot = b.weekly_brl / (b.max_products * b.creatives_per_product)
    return (f"R$ {b.weekly_brl:,.2f} por semana (teto R$ {b.daily_cap_brl:,.2f}/dia), {b.max_products} produto(s) × "
            f"{b.creatives_per_product} criativo(s): cerca de R$ {per_slot:,.2f} por criativo na semana. Campanha nova sempre pausada até você aprovar.")
