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


# Teto por marketplace de ORIGEM do produto (vale para Meta e Google somados). Marketplace sem teto definido não recebe anúncio pago.
MP_NAMES = {"shopee": "Shopee", "aliexpress": "AliExpress", "mercado_livre": "Mercado Livre", "amazon": "Amazon", "tiktok_shop": "TikTok Shop",
            "hotmart": "Hotmart", "monetizze": "Monetizze", "eduzz": "Eduzz"}
MARKETPLACES = tuple(MP_NAMES)  # novo marketplace do sistema: acrescente aqui e ele aparece na tela de Verba e campanhas


def enabled_marketplaces(values: dict) -> set[str] | None:
    """Marketplaces que podem receber campanha paga (a lista da tela Verba e campanhas). `None` = lista nunca definida (vale quem tem teto)."""
    if "mp_enabled" not in values:
        return None
    return {s.strip() for s in str(values.get("mp_enabled") or "").split(",") if s.strip()}


def marketplace_allowed(session: Session, marketplace: str) -> bool:
    row = session.scalar(select(ServiceCredential).where(ServiceCredential.service == SERVICE))
    if row is None or not row.enabled:
        return False
    values = row.values or {}
    enabled = enabled_marketplaces(values)
    if enabled is not None:
        return marketplace in enabled
    return load_marketplace(session, marketplace) is not None


def mp_keys(marketplace: str) -> tuple[str, str]:
    return f"mp_{marketplace}_weekly_brl", f"mp_{marketplace}_daily_cap_brl"


def parse_marketplace(values: dict, marketplace: str) -> tuple[float, float] | None:
    """(valor por semana, teto por dia) do marketplace, ou `None` se não foi definido."""
    weekly_key, daily_key = mp_keys(marketplace)
    if not str(values.get(weekly_key) or "").strip() and not str(values.get(daily_key) or "").strip():
        return None
    who = MP_NAMES[marketplace]
    weekly = _num(values.get(weekly_key), f"{who}: valor por semana")
    daily = _num(values.get(daily_key), f"{who}: teto por dia")
    if daily > weekly:
        raise BudgetError(f"{who}: o teto por dia não pode passar do valor da semana")
    return weekly, daily


def load_marketplace(session: Session, marketplace: str) -> tuple[float, float] | None:
    row = session.scalar(select(ServiceCredential).where(ServiceCredential.service == SERVICE))
    if row is None or not row.enabled or marketplace not in MARKETPLACES:
        return None
    try:
        return parse_marketplace(row.values or {}, marketplace)
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
    caps = {m: parse_marketplace(values, m) for m in MARKETPLACES}
    defined = {m: c for m, c in caps.items() if c}
    if defined:
        parts.append("Por marketplace (Meta e Google somados): " + "; ".join(f"{MP_NAMES[m]} R$ {w:,.2f}/semana (até R$ {d:,.2f}/dia)" for m, (w, d) in defined.items()) + ".")
        total = sum(w for w, _ in defined.values())
        platforms = parse(values, "meta").weekly_brl + (parse(values, "google").weekly_brl if str(values.get("google_weekly_brl") or "").strip() else 0)
        if total > platforms + 1e-9:
            parts.append(f"Atenção: os tetos por marketplace somam R$ {total:,.2f}, mais que as plataformas (R$ {platforms:,.2f}); vale o menor dos dois limites.")
    else:
        parts.append("Marketplaces: sem teto definido (o agente não cria anúncio pago de produto de marketplace sem teto).")
    return " ".join(parts) + " Campanha nova sempre pausada até você aprovar. Os orçamentos são separados: o gasto de uma plataforma não consome o da outra."
