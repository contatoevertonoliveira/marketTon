"""Radar de tendências: o que está esquentando na busca do Google, medido por código (sem IA) todo dia.

Por palavra da lista de vigilância guarda um retrato diário: crescimento do interesse (Google Trends) nos últimos 7, 15 e 30 dias contra
os períodos anteriores do mesmo tamanho, mais volume mensal, CPC e disputa (Planejador do Google Ads, quando conectado). A comparação
entre retratos mostra o que **começou** a subir; só isso chega ao agente (resumo das verificações), então ele gasta token apenas com novidade.

Honestidade: sem série suficiente do Trends o crescimento fica `None`, nunca zero; volume e CPC ficam `None` sem o Planejador.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.product_hunter.agent import DEFAULT_KEYWORDS
from collectors.google_trends.client import fetch_keyword_interest
from core.db.app_settings import AppSetting
from core.db.trend_radar import TrendSnapshot
from core.services import keyword_metrics

logger = logging.getLogger(__name__)

WATCH_KEY, SCAN_KEY = "trend_watch", "trend_last_scan"
MAX_WATCH = 40
SCAN_EVERY = timedelta(hours=20)
PER_SCAN = 12  # o Google Trends limita pedidos: uma rodada olha no máximo 12 palavras, as mais antigas primeiro
RISING_30D = 25.0  # % de alta no mês
RISING_7D = 40.0  # ou alta forte na semana, desde que a quinzena também suba
MIN_VOLUME = 200  # abaixo disso (quando se sabe o volume) não vale campanha


class RadarError(ValueError):
    """Pedido inválido ao radar; a mensagem é segura para exibir."""


def _aware(dt: datetime | None) -> datetime | None:
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=UTC))


def _clean(keyword: str) -> str:
    return " ".join(str(keyword or "").lower().split())[:120]


def get_watch(session: Session) -> list[str]:
    row = session.scalar(select(AppSetting).where(AppSetting.key == WATCH_KEY))
    saved = (row.value or {}).get("keywords") if row else None
    return list(saved) if isinstance(saved, list) and saved else [_clean(k) for k in DEFAULT_KEYWORDS]


def set_watch(session: Session, *, add: list[str] | None = None, remove: list[str] | None = None, actor: str) -> list[str]:
    words = get_watch(session)
    for k in (_clean(x) for x in (remove or [])):
        if k in words:
            words.remove(k)
    for k in (_clean(x) for x in (add or [])):
        if not k or len(k) < 3:
            raise RadarError("palavra muito curta")
        if k not in words:
            words.append(k)
    if len(words) > MAX_WATCH:
        raise RadarError(f"a lista de vigilância comporta {MAX_WATCH} palavras: remova alguma antes de adicionar")
    row = session.scalar(select(AppSetting).where(AppSetting.key == WATCH_KEY))
    if row is None:
        row = AppSetting(key=WATCH_KEY, value={})
        session.add(row)
    row.value, row.updated_by, row.changed_at = {"keywords": words}, actor[:64], datetime.now(UTC)
    session.flush()
    return words


def _growth(frame, days: int) -> float | None:
    """Interesse médio dos últimos `days` dias sobre o dos `days` anteriores, em %. `None` se faltar série."""
    if frame is None or frame.empty:
        return None
    import pandas as pd

    last = frame["date"].max()
    recent = frame[frame["date"] > last - pd.Timedelta(days=days)]["interest"]
    before = frame[(frame["date"] <= last - pd.Timedelta(days=days)) & (frame["date"] > last - pd.Timedelta(days=2 * days))]["interest"]
    if len(recent) < max(2, days // 4) or len(before) < max(2, days // 4) or before.mean() == 0:
        return None
    return round(float((recent.mean() - before.mean()) / before.mean() * 100), 1)


def is_rising(g7: float | None, g15: float | None, g30: float | None, volume: int | None) -> bool:
    strong = (g30 is not None and g30 >= RISING_30D) or (g7 is not None and g7 >= RISING_7D and (g15 or 0) > 0)
    return bool(strong and (volume is None or volume >= MIN_VOLUME))


def scan(session: Session, *, now: datetime | None = None, force: bool = False, max_keywords: int = PER_SCAN) -> int:
    """Tira o retrato das palavras mais antigas da lista. No máximo uma vez a cada 20 h (o prefetch roda várias vezes ao dia)."""
    now = now or datetime.now(UTC)
    state = session.scalar(select(AppSetting).where(AppSetting.key == SCAN_KEY))
    last = _aware(datetime.fromisoformat(state.value["at"])) if state and (state.value or {}).get("at") else None
    if not force and last is not None and now - last < SCAN_EVERY:
        return 0
    words = get_watch(session)
    taken = {}
    for k, at in session.execute(select(TrendSnapshot.keyword, TrendSnapshot.taken_at).order_by(TrendSnapshot.taken_at)):
        taken[k] = _aware(at)
    pick = sorted(words, key=lambda k: taken.get(k) or datetime.min.replace(tzinfo=UTC))[:max_keywords]
    planner, _source, _error = keyword_metrics._planner_metrics(pick) if keyword_metrics.planner_provider() else ({}, None, None)
    done = 0
    for k in pick:
        try:
            frame = fetch_keyword_interest(k, geo="BR", window_days=90).frame
            error = None if len(frame) >= 14 else "série curta ou vazia no Google Trends"
        except Exception as exc:  # noqa: BLE001 - uma palavra ruim não derruba o lote
            frame, error = None, str(exc)[:160]
        g7, g15, g30 = (_growth(frame, 7), _growth(frame, 15), _growth(frame, 30)) if error is None else (None, None, None)
        item = planner.get(k) or {}
        cpc = item.get("cpc") if item.get("currency") in (None, "BRL") else None
        volume = item.get("search_volume")
        session.add(TrendSnapshot(keyword=k, geo="BR", taken_at=now, interest_last=float(frame["interest"].iloc[-1]) if error is None else None,
                                  growth_7d=g7, growth_15d=g15, growth_30d=g30, monthly_volume=volume, cpc_brl=cpc,
                                  competition=item.get("competition"), rising=is_rising(g7, g15, g30, volume), error=error))
        done += 1
    if state is None:
        state = AppSetting(key=SCAN_KEY, value={})
        session.add(state)
    state.value, state.updated_by, state.changed_at = {"at": now.isoformat()}, "sistema", now
    session.flush()
    return done


def _latest(session: Session) -> dict[str, list[TrendSnapshot]]:
    by_kw: dict[str, list[TrendSnapshot]] = {}
    for s in session.scalars(select(TrendSnapshot).order_by(TrendSnapshot.taken_at, TrendSnapshot.id)):
        by_kw.setdefault(s.keyword, []).append(s)
    return by_kw


def out(s: TrendSnapshot) -> dict:
    return {"keyword": s.keyword, "taken_at": _aware(s.taken_at).isoformat(), "growth_7d": s.growth_7d, "growth_15d": s.growth_15d,
            "growth_30d": s.growth_30d, "monthly_volume": s.monthly_volume, "cpc_brl": s.cpc_brl, "competition": s.competition,
            "rising": s.rising, "error": s.error}


def status(session: Session, *, limit: int = 15, only_rising: bool = False) -> dict:
    """O estado atual de cada palavra vigiada (o retrato mais recente), as que mais sobem primeiro."""
    items = []
    for k, snaps in _latest(session).items():
        if k not in get_watch(session):
            continue
        last = snaps[-1]
        if only_rising and not last.rising:
            continue
        items.append(out(last) | {"snapshots": len(snaps)})
    items.sort(key=lambda i: (not i["rising"], -(i["growth_30d"] if i["growth_30d"] is not None else -999)))
    return {"watching": len(get_watch(session)), "scanned": len(items), "rising": sum(1 for i in items if i["rising"]), "items": items[:max(1, limit)]}


def new_rising(session: Session, since: datetime) -> list[dict]:
    """Palavras que **passaram a subir** desde `since`: o retrato novo está em alta e o anterior (se existia) não estava."""
    since = _aware(since)
    out_list = []
    for k, snaps in _latest(session).items():
        last = snaps[-1]
        if not last.rising or _aware(last.taken_at) < since:
            continue
        before = [s for s in snaps if _aware(s.taken_at) < since]
        if before and before[-1].rising:
            continue
        out_list.append(out(last))
    return sorted(out_list, key=lambda i: -(i["growth_30d"] or 0))
