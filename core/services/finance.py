"""Painel financeiro: vendas e comissão no tempo, comissão por plataforma, gasto com anúncios e saldo das carteiras.

Regras de honestidade, as mesmas do resto do sistema:

* **comissão confirmada x pendente** nunca se misturam: pendente é a estimada enquanto o marketplace não confirmou;
* venda cancelada, reembolsada ou estornada não conta;
* **saldo de carteira** só existe quando alguém informou (ou uma API trouxe): plataforma sem lançamento aparece como "sem saldo
  informado" e fica de fora do total, que diz quantas carteiras entraram. Nada é estimado no ar;
* o gasto com anúncios é o acumulado lido da Meta dos anúncios criados no período (a Meta não dá o gasto por dia aqui).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.ads import AdCampaign
from core.db.finance import WalletBalance
from core.db.tracking import Commission, Sale

CANCELLED = {"CANCELLED", "CANCELED", "REFUNDED", "CHARGEBACK", "EXPIRED", "DUPLICATED"}
WALLETS = ("shopee", "mercado_livre", "amazon", "hotmart", "monetizze", "eduzz")
LABELS = {"shopee": "Shopee", "mercado_livre": "Mercado Livre", "amazon": "Amazon", "hotmart": "Hotmart", "monetizze": "Monetizze",
          "eduzz": "Eduzz", "tiktok_shop": "TikTok Shop", "other": "Outras"}


class FinanceError(ValueError):
    """Dado financeiro inválido; a mensagem é segura para exibir."""


def _aware(dt: datetime | None) -> datetime | None:
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=UTC))


def _mp(value) -> str:
    return getattr(value, "value", str(value))


def set_wallet(session: Session, platform: str, balance_brl: float, *, actor: str, as_of: datetime | None = None,
               note: str | None = None, source: str = "manual") -> WalletBalance:
    if platform not in WALLETS:
        raise FinanceError(f"carteira desconhecida: use {', '.join(WALLETS)}")
    if isinstance(balance_brl, bool) or not isinstance(balance_brl, (int, float)) or not -1_000_000 <= balance_brl <= 100_000_000:
        raise FinanceError("saldo inválido")
    when = _aware(as_of) or datetime.now(UTC)
    if when > datetime.now(UTC) + timedelta(hours=1):
        raise FinanceError("a data do saldo não pode estar no futuro")
    row = WalletBalance(platform=platform, balance_brl=round(float(balance_brl), 2), as_of=when, source=source,
                        note=(note or None) and note[:200], created_by=actor[:64])
    session.add(row)
    session.flush()
    return row


def wallets(session: Session) -> dict:
    """Saldo atual de cada carteira (o lançamento mais recente) e o total das que têm saldo informado."""
    latest: dict[str, WalletBalance] = {}
    for row in sorted(session.scalars(select(WalletBalance)), key=lambda r: (_aware(r.as_of), r.id)):
        latest[row.platform] = row
    items, total, known = [], 0.0, 0
    for key in WALLETS:
        row = latest.get(key)
        if row is not None:
            total += row.balance_brl
            known += 1
        items.append({"platform": key, "label": LABELS[key], "balance_brl": row.balance_brl if row else None,
                      "as_of": _aware(row.as_of).isoformat() if row else None, "source": row.source if row else None,
                      "note": row.note if row else None})
    return {"items": items, "total_brl": round(total, 2), "known": known, "of": len(WALLETS)}


def _wallet_series(session: Session, days: list[datetime]) -> list[dict]:
    """Saldo total ao fim de cada dia: último lançamento de cada carteira até aquela data (só carteiras já lançadas)."""
    rows = sorted(session.scalars(select(WalletBalance)), key=lambda r: (_aware(r.as_of), r.id))
    out = []
    for day in days:
        end = day + timedelta(days=1)
        latest: dict[str, float] = {}
        for r in rows:
            if _aware(r.as_of) < end:
                latest[r.platform] = r.balance_brl
        out.append({"date": f"{day:%Y-%m-%d}", "total_brl": round(sum(latest.values()), 2) if latest else None})
    return out


def overview(session: Session, *, days: int = 30, now: datetime | None = None) -> dict:
    days = max(1, min(int(days), 365))
    local = (now or datetime.now(UTC)).astimezone()
    today = local.replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=days - 1)
    prev_start = start - timedelta(days=days)
    end = today + timedelta(days=1)

    sales = {}
    for s in session.scalars(select(Sale).where(Sale.occurred_at >= prev_start - timedelta(days=1), Sale.occurred_at <= end + timedelta(days=1))):
        at = _aware(s.occurred_at)
        if at is not None and prev_start <= at < end and str(s.status or "").upper() not in CANCELLED:
            sales[s.id] = (s, at.astimezone())
    commission: dict[int, tuple[float, bool]] = {}
    if sales:
        for sale_id, confirmed, estimated in session.execute(
                select(Commission.sale_id, Commission.confirmed_amount, Commission.estimated_amount).where(Commission.sale_id.in_(list(sales)))):
            value, is_confirmed = (float(confirmed), True) if confirmed is not None else (float(estimated or 0), False)
            before = commission.get(sale_id, (0.0, True))
            commission[sale_id] = (before[0] + value, before[1] and is_confirmed)

    day_keys = [start + timedelta(days=i) for i in range(days)]
    series = {f"{d:%Y-%m-%d}": {"date": f"{d:%Y-%m-%d}", "sales": 0, "gross_brl": 0.0, "confirmed_brl": 0.0, "pending_brl": 0.0} for d in day_keys}
    by_platform: dict[str, dict] = {}
    cur = {"sales": 0, "gross": 0.0, "confirmed": 0.0, "pending": 0.0}
    prev_commission = 0.0
    for sale_id, (sale, at) in sales.items():
        value, is_confirmed = commission.get(sale_id, (0.0, False))
        if at < start:
            prev_commission += value
            continue
        point = series[f"{at:%Y-%m-%d}"]
        gross = float(sale.gross_amount or 0)
        point["sales"] += 1
        point["gross_brl"] += gross
        point["confirmed_brl" if is_confirmed else "pending_brl"] += value
        cur["sales"] += 1
        cur["gross"] += gross
        cur["confirmed" if is_confirmed else "pending"] += value
        mp = by_platform.setdefault(_mp(sale.marketplace), {"platform": _mp(sale.marketplace), "sales": 0, "gross_brl": 0.0,
                                                            "confirmed_brl": 0.0, "pending_brl": 0.0})
        mp["sales"] += 1
        mp["gross_brl"] += gross
        mp["confirmed_brl" if is_confirmed else "pending_brl"] += value

    points, running = [], 0.0
    for key, point in series.items():
        running += point["confirmed_brl"] + point["pending_brl"]
        points.append({k: (round(v, 2) if isinstance(v, float) else v) for k, v in point.items()} | {"cumulative_brl": round(running, 2)})

    ads = [a for a in session.scalars(select(AdCampaign)) if a.created_at is not None and _aware(a.created_at) >= start]
    spent = round(sum(a.spent_brl or 0 for a in ads), 2)
    commission_total = round(cur["confirmed"] + cur["pending"], 2)
    prev_total = round(prev_commission, 2)
    return {
        "days": days, "from": f"{start:%Y-%m-%d}", "to": f"{today:%Y-%m-%d}",
        "kpis": {"sales": cur["sales"], "gross_brl": round(cur["gross"], 2), "confirmed_brl": round(cur["confirmed"], 2),
                 "pending_brl": round(cur["pending"], 2), "commission_brl": commission_total, "ads_spent_brl": spent,
                 "result_brl": round(commission_total - spent, 2), "previous_commission_brl": prev_total,
                 "commission_change_pct": round((commission_total - prev_total) / prev_total * 100, 1) if prev_total else None},
        "series": points,
        "by_platform": sorted(({**v, "label": LABELS.get(v["platform"], v["platform"]), "gross_brl": round(v["gross_brl"], 2),
                                "confirmed_brl": round(v["confirmed_brl"], 2), "pending_brl": round(v["pending_brl"], 2)}
                               for v in by_platform.values()), key=lambda v: -(v["confirmed_brl"] + v["pending_brl"])),
        "wallets": wallets(session),
        "wallet_series": _wallet_series(session, day_keys),
        "notes": ["Comissão pendente é estimada até o marketplace confirmar.",
                  "O gasto com anúncios é o acumulado lido da Meta dos anúncios criados no período.",
                  "O saldo das carteiras é o que foi informado; carteira sem lançamento fica fora do total."],
    }
