"""Plano de verba e de campanhas: quanto se gasta por semana, como se divide e em quais marketplaces o agente pode fazer campanha.

Uma tela só (Verba e campanhas) escreve aqui; os guardas de anúncio (`ads_budget`, `meta_campaigns._guard`) leem o que este módulo grava no cartão
`ads_budget`. Assim há uma só fonte de verdade e as travas antigas continuam valendo.

* **Verba total por semana** e a divisão em três partes (percentuais): Meta Ads, Google Ads e propaganda DENTRO dos marketplaces (Shopee Ads,
  Mercado Livre Ads...). A terceira parte é planejamento: o agente não cria nem gasta nada dentro do marketplace, o operador executa no painel dele.
* **Lista de marketplaces com campanha**: só produto de marketplace que está na lista recebe anúncio pago. Fora da lista é só orgânico.
* **Teto opcional por marketplace** (semana e dia, somando Meta e Google) e verba de propaganda própria por marketplace.
"""
from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.services import ads_budget
from core.db.service_credentials import ServiceCredential

DAILY_FACTOR = 0.3  # teto por dia = 30% do valor da semana (padrão do plano; o operador pode pedir outro depois)
MAX_TOTAL = 1_000_000


class PlanError(ValueError):
    """Plano inválido; a mensagem é segura para exibir."""


def _money(value, name: str, *, allow_zero: bool = False) -> float:
    text = str(value if value is not None else "").strip().replace("R$", "").replace(" ", "")
    if not text:
        if allow_zero:
            return 0.0
        raise PlanError(f"{name}: informe um valor")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        number = float(text)
    except ValueError as exc:
        raise PlanError(f"{name}: informe um número") from exc
    if number < 0 or number > MAX_TOTAL or (number == 0 and not allow_zero):
        raise PlanError(f"{name}: informe um valor entre {'0' if allow_zero else '0,01'} e {MAX_TOTAL:,.0f}".replace(",", "."))
    return round(number, 2)


def _daily(weekly: float) -> float:
    return float(max(1, math.ceil(weekly * DAILY_FACTOR)))


def _row(session: Session) -> ServiceCredential:
    row = session.scalar(select(ServiceCredential).where(ServiceCredential.service == ads_budget.SERVICE))
    if row is None:
        row = ServiceCredential(service=ads_budget.SERVICE, enabled=True, values={})
        session.add(row)
        session.flush()
    return row


def _f(values: dict, key: str) -> float | None:
    try:
        return float(str(values.get(key)).replace(",", ".")) if str(values.get(key) or "").strip() else None
    except ValueError:
        return None


def read(session: Session) -> dict:
    """O plano atual, no formato que a tela edita."""
    existing = session.scalar(select(ServiceCredential).where(ServiceCredential.service == ads_budget.SERVICE))
    values = (existing.values or {}) if existing is not None else {}
    meta, google = _f(values, "weekly_brl") or 0.0, _f(values, "google_weekly_brl") or 0.0
    own_total = _f(values, "plan_marketplace_ads_weekly_brl") or 0.0
    total = _f(values, "plan_total_weekly_brl")
    if total is None:
        total = round(meta + google + own_total, 2)
    enabled = ads_budget.enabled_marketplaces(values)
    marketplaces = []
    for slug in ads_budget.MARKETPLACES:
        weekly_key, daily_key = ads_budget.mp_keys(slug)
        marketplaces.append({
            "slug": slug, "name": ads_budget.MP_NAMES[slug],
            "enabled": (slug in enabled) if enabled is not None else bool(str(values.get(weekly_key) or "").strip()),
            "weekly_brl": _f(values, weekly_key), "daily_cap_brl": _f(values, daily_key),
            "own_ads_weekly_brl": _f(values, f"mp_{slug}_own_ads_weekly_brl"),
        })
    pct = lambda part: round(part / total * 100, 1) if total else 0.0  # noqa: E731
    return {"total_weekly_brl": total, "meta_brl": meta, "google_brl": google, "marketplace_ads_brl": own_total,
            "meta_pct": pct(meta), "google_pct": pct(google), "marketplace_pct": pct(own_total), "marketplaces": marketplaces}


def save(session: Session, payload: dict) -> dict:
    """Valida e grava o plano. Campos: `total_weekly_brl`, `meta_pct`, `google_pct`, `marketplace_pct` (somam 100), `marketplaces`
    (lista de {slug, enabled, weekly_brl?, daily_cap_brl?, own_ads_weekly_brl?})."""
    total = _money(payload.get("total_weekly_brl"), "Verba total por semana")
    pcts = {k: _money(payload.get(f"{k}_pct"), f"Parte do {label}", allow_zero=True)
            for k, label in (("meta", "Meta Ads"), ("google", "Google Ads"), ("marketplace", "propaganda nos marketplaces"))}
    if abs(sum(pcts.values()) - 100) > 0.05:
        raise PlanError(f"a divisão precisa somar 100% (hoje soma {sum(pcts.values()):g}%)")
    meta, google, own_total = (round(total * pcts[k] / 100, 2) for k in ("meta", "google", "marketplace"))

    seen: dict[str, dict] = {}
    for item in payload.get("marketplaces") or []:
        slug = str(item.get("slug") or "")
        if slug not in ads_budget.MARKETPLACES:
            raise PlanError(f"marketplace desconhecido: {slug}")
        seen[slug] = item
    values: dict[str, str] = {}
    paid_cap = meta + google
    own_sum = 0.0
    enabled: list[str] = []
    for slug in ads_budget.MARKETPLACES:
        item = seen.get(slug, {})
        name = ads_budget.MP_NAMES[slug]
        weekly_key, daily_key = ads_budget.mp_keys(slug)
        on = bool(item.get("enabled"))
        if on:
            enabled.append(slug)
        w_raw, d_raw, o_raw = item.get("weekly_brl"), item.get("daily_cap_brl"), item.get("own_ads_weekly_brl")
        if on and str(w_raw or "").strip():
            weekly = _money(w_raw, f"{name}: teto por semana")
            daily = _money(d_raw, f"{name}: teto por dia") if str(d_raw or "").strip() else min(_daily(weekly), weekly)
            if weekly > paid_cap + 1e-9:
                raise PlanError(f"{name}: o teto por semana (R$ {weekly:g}) passa da verba de Meta + Google (R$ {paid_cap:g})")
            if daily > weekly:
                raise PlanError(f"{name}: o teto por dia não pode passar do teto da semana")
            values[weekly_key], values[daily_key] = f"{weekly:g}", f"{daily:g}"
        else:
            values[weekly_key] = values[daily_key] = ""
        own = _money(o_raw, f"{name}: propaganda no marketplace", allow_zero=True) if on and str(o_raw or "").strip() else 0.0
        own_sum += own
        values[f"mp_{slug}_own_ads_weekly_brl"] = f"{own:g}" if own else ""
    if own_sum > own_total + 0.005:
        raise PlanError(f"a propaganda dentro dos marketplaces (R$ {own_sum:g}) passa da parte reservada a ela (R$ {own_total:g})")

    values.update({"plan_total_weekly_brl": f"{total:g}", "plan_marketplace_ads_weekly_brl": f"{own_total:g}" if own_total else "",
                   "mp_enabled": ",".join(enabled), "weekly_brl": f"{meta:g}" if meta else "", "daily_cap_brl": f"{min(_daily(meta), meta):g}" if meta else "",
                   "google_weekly_brl": f"{google:g}" if google else "", "google_daily_cap_brl": f"{min(_daily(google), google):g}" if google else ""})
    row = _row(session)
    row.values = {**(row.values or {}), **values}
    row.enabled = True
    session.flush()
    return read(session)
