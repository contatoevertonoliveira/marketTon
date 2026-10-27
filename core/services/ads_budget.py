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


PLATFORMS = ("meta", "google")
NAMES = {"meta": "Meta", "google": "Google"}
# Cada plataforma tem o seu orçamento. Os campos da Meta mantêm os nomes antigos; os do Google levam o prefixo `google_`.
KEYS = {"meta": ("weekly_brl", "daily_cap_brl", "max_products", "creatives_per_product"),
        "google": ("google_weekly_brl", "google_daily_cap_brl", "google_max_products", None)}


def parse(values: dict, platform: str = "meta") -> AdsBudget:
    weekly_key, daily_key, products_key, creatives_key = KEYS[platform]
    who = NAMES[platform]
    weekly = _num(values.get(weekly_key), f"{who}: valor por semana")
    daily = _num(values.get(daily_key), f"{who}: teto por dia")
    if daily > weekly:
        raise BudgetError(f"{who}: o teto por dia não pode passar do valor da semana")
    if daily * 7 < weekly:
        raise BudgetError(f"{who}: o teto por dia é baixo demais para gastar o valor da semana (teto × 7 < semana)")
    products = _num(values.get(products_key) or 3, f"{who}: produtos por semana", integer=True, minimum=1, maximum=20)
    creatives = _num(values.get(creatives_key) or 2, "criativos por produto", integer=True, minimum=1, maximum=6) if creatives_key else 1
    return AdsBudget(weekly, daily, products, creatives)


def load(session: Session, platform: str = "meta") -> AdsBudget | None:
    row = session.scalar(select(ServiceCredential).where(ServiceCredential.service == SERVICE))
    if row is None or not row.enabled:
        return None
    try:
        return parse(row.values or {}, platform)
    except BudgetError:
        return None


def check(values: dict) -> str:
    parts = []
    b = parse(values, "meta")
    per_slot = b.weekly_brl / (b.max_products * b.creatives_per_product)
    parts.append(f"Meta: R$ {b.weekly_brl:,.2f} por semana (teto R$ {b.daily_cap_brl:,.2f}/dia), {b.max_products} produto(s) × "
                 f"{b.creatives_per_product} criativo(s): cerca de R$ {per_slot:,.2f} por criativo.")
    if str(values.get("google_weekly_brl") or "").strip() or str(values.get("google_daily_cap_brl") or "").strip():
        g = parse(values, "google")
        parts.append(f"Google: R$ {g.weekly_brl:,.2f} por semana (teto R$ {g.daily_cap_brl:,.2f}/dia), {g.max_products} produto(s).")
    else:
        parts.append("Google: sem orçamento definido (o agente não cria campanha no Google até você preencher).")
    return " ".join(parts) + " Campanha nova sempre pausada até você aprovar. Os orçamentos são separados: o gasto de uma plataforma não consome o da outra."
