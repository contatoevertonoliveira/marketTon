"""Metas do agente: o que o operador quer alcançar no mês e quanto já foi feito (com dados reais, nunca estimados no ar).

Cinco números, todos medidos no próprio marketTon:

* `store_products`  — produtos publicados na vitrine (estado atual, não acumulado);
* `posts`           — publicações registradas como PUBLISHED no mês;
* `clicks`          — cliques de pessoas nos links curtos rastreados no mês (robôs não contam);
* `sales`           — vendas do mês que não foram canceladas, reembolsadas ou estornadas;
* `commission_brl`  — comissão dessas vendas (confirmada, ou estimada enquanto não confirmada).

Para cada meta: o realizado, a % da meta, a % **esperada** até hoje (dias decorridos do mês) e a projeção linear para o
fim do mês. O estado compara o ritmo: `adiantada`, `no_ritmo`, `atrasada` ou `sem_meta`. Metas nascem como **sugestões**
(`suggested=True`) e só deixam de ser sugestão quando o operador as salva: o agente persegue o número do operador.
"""
from __future__ import annotations

import calendar
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.app_settings import AppSetting
from core.db.creative import Publication
from core.db.tracking import ClickEvent, Commission, Sale

GOALS_KEY = "agent_goals"
STORE_PUBLISH_KEY = "storefront_last_publish"
CANCELLED = {"CANCELLED", "CANCELED", "REFUNDED", "CHARGEBACK", "EXPIRED", "DUPLICATED"}

METRICS = {
    "store_products": {"label": "Produtos na vitrine", "unit": "produtos", "cumulative": False, "default": 24},
    "posts": {"label": "Publicações nas redes", "unit": "posts", "cumulative": True, "default": 60},
    "clicks": {"label": "Cliques nos links rastreados", "unit": "cliques", "cumulative": True, "default": 500},
    "sales": {"label": "Vendas", "unit": "vendas", "cumulative": True, "default": 10},
    "commission_brl": {"label": "Comissão", "unit": "R$", "cumulative": True, "default": 300},
}


class GoalsError(ValueError):
    """Meta inválida; a mensagem é segura para exibir."""


def get_targets(session: Session) -> dict:
    row = session.scalar(select(AppSetting).where(AppSetting.key == GOALS_KEY))
    saved = (row.value or {}).get("targets", {}) if row else {}
    targets = {}
    for key, meta in METRICS.items():
        value = saved.get(key)
        targets[key] = {"target": value if isinstance(value, (int, float)) and value >= 0 else meta["default"],
                        "suggested": not (isinstance(value, (int, float)) and value >= 0)}
    return targets


def set_targets(session: Session, targets: dict, *, actor: str) -> dict:
    """Grava as metas informadas (as ausentes não mudam). Valor negativo ou não numérico é recusado."""
    row = session.scalar(select(AppSetting).where(AppSetting.key == GOALS_KEY))
    if row is None:
        row = AppSetting(key=GOALS_KEY, value={})
        session.add(row)
    saved = dict((row.value or {}).get("targets", {}))
    for key, value in targets.items():
        if key not in METRICS:
            raise GoalsError(f"meta desconhecida: {key}. Use {', '.join(METRICS)}")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or value > 10_000_000:
            raise GoalsError(f"valor inválido para {key}: informe um número de 0 a 10.000.000")
        saved[key] = float(value) if key == "commission_brl" else int(value)
    row.value, row.updated_by, row.changed_at = {"targets": saved}, actor[:64], datetime.now(UTC)
    session.flush()
    return get_targets(session)


def _aware(dt: datetime | None) -> datetime | None:
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=UTC))


def month_bounds(now: datetime | None = None) -> tuple[datetime, datetime, int, int]:
    """(início, fim, dia do mês, dias do mês) em hora local."""
    local = (now or datetime.now(UTC)).astimezone()
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    days = calendar.monthrange(local.year, local.month)[1]
    return start, start + timedelta(days=days), local.day, days


def _measure(session: Session, start: datetime, end: datetime) -> dict:
    lo, hi = start - timedelta(days=1), end + timedelta(days=1)  # margem: o filtro exato é em Python
    in_period = lambda dt: (a := _aware(dt)) is not None and start <= a < end  # noqa: E731

    clicks = sum(1 for (t,) in session.execute(select(ClickEvent.occurred_at).where(ClickEvent.occurred_at >= lo, ClickEvent.occurred_at <= hi))
                 if in_period(t))
    posts = sum(1 for (t, status) in session.execute(select(Publication.published_at, Publication.status).where(Publication.published_at.is_not(None)))
                if in_period(t) and getattr(status, "value", status) == "PUBLISHED")
    sales_rows = [(sid, st) for sid, st, t in session.execute(select(Sale.id, Sale.status, Sale.occurred_at).where(Sale.occurred_at >= lo, Sale.occurred_at <= hi))
                  if in_period(t) and str(st or "").upper() not in CANCELLED]
    ids = [sid for sid, _ in sales_rows]
    commission = 0.0
    if ids:
        for confirmed, estimated in session.execute(select(Commission.confirmed_amount, Commission.estimated_amount).where(Commission.sale_id.in_(ids))):
            commission += float(confirmed if confirmed is not None else (estimated or 0))
    last = session.scalar(select(AppSetting).where(AppSetting.key == STORE_PUBLISH_KEY))
    return {"store_products": int((last.value or {}).get("count", 0)) if last else 0, "posts": posts, "clicks": clicks,
            "sales": len(sales_rows), "commission_brl": round(commission, 2)}


PERIODS = (("day", "Hoje"), ("week", "Semana"), ("fortnight", "Quinzena"), ("month", "Mês"))


def period_bounds(key: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Início e fim (hora local) do dia, da semana (segunda a domingo), da quinzena (1–15 / 16–fim) ou do mês."""
    local = (now or datetime.now(UTC)).astimezone()
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if key == "day":
        return midnight, midnight + timedelta(days=1)
    if key == "week":
        start = midnight - timedelta(days=midnight.weekday())
        return start, start + timedelta(days=7)
    month_start, month_end, _, _ = month_bounds(now)
    if key == "fortnight":
        if local.day <= 15:
            return month_start, month_start + timedelta(days=15)
        return month_start + timedelta(days=15), month_end
    return month_start, month_end


def period_progress(session: Session, now: datetime | None = None) -> list[dict]:
    """Ritmo por período: a meta mensal repartida pelos dias (diária, semanal, quinzenal) contra o que foi medido no período.

    Só as metas acumulativas (cliques, vendas, comissão, posts) se repartem; vitrine é um estado e fica só no mensal.
    """
    local = (now or datetime.now(UTC)).astimezone()
    _, _, _, month_days = month_bounds(now)
    targets, out = get_targets(session), []
    for key, label in PERIODS:
        start, end = period_bounds(key, now)
        days = (end - start).days
        expected = min(1.0, max(0.0, (local - start).total_seconds() / (end - start).total_seconds()))
        done, metrics = _measure(session, start, end), []
        for mkey, meta in METRICS.items():
            if not meta["cumulative"]:
                continue
            target = round(targets[mkey]["target"] * days / month_days, 2)
            current = done[mkey]
            if not target:
                status = "sem_meta"
            elif current >= target:
                status = "adiantada"
            else:
                ratio = (current / target) / expected if expected else 1.0
                status = "adiantada" if ratio >= 1 else "no_ritmo" if ratio >= 0.8 else "atrasada"
            metrics.append({"key": mkey, "label": meta["label"], "unit": meta["unit"], "target": target, "current": current,
                            "pct": round(current / target * 100, 1) if target else None, "status": status})
        out.append({"key": key, "label": label, "start": start.isoformat(), "end": end.isoformat(), "days": days, "metrics": metrics})
    return out


def progress(session: Session, now: datetime | None = None) -> dict:
    start, end, day, days = month_bounds(now)
    expected = day / days
    targets, done = get_targets(session), _measure(session, start, end)
    metrics = []
    for key, meta in METRICS.items():
        target, current = targets[key]["target"], done[key]
        pct = (current / target) if target else None
        projection = round(current / expected, 2) if meta["cumulative"] and expected > 0 else None
        if not target:
            status = "sem_meta"
        elif current >= target:
            status = "adiantada"
        else:
            benchmark = expected if meta["cumulative"] else 1.0  # estado atual (vitrine): a meta vale desde já
            ratio = pct / benchmark if benchmark else 0
            status = "adiantada" if ratio >= 1 else "no_ritmo" if ratio >= 0.8 else "atrasada"
        metrics.append({
            "key": key, "label": meta["label"], "unit": meta["unit"], "target": target, "suggested": targets[key]["suggested"],
            "current": current, "pct": round(pct * 100, 1) if pct is not None else None,
            "expected_pct": round(expected * 100, 1) if meta["cumulative"] else 100.0,
            "projection": projection, "missing": max(0, round(target - current, 2)) if target else 0, "status": status,
        })
    behind = [m for m in metrics if m["status"] == "atrasada"]
    return {"period": f"{start:%m/%Y}", "day": day, "days": days, "days_left": days - day, "metrics": metrics,
            "periods": period_progress(session, now),
            "behind": [m["key"] for m in behind],
            "summary": ("Todas as metas estão no ritmo ou adiantadas." if not behind else
                        "Atrasadas: " + "; ".join(f"{m['label']} ({m['current']:g} de {m['target']:g})" for m in behind) + ".")}
