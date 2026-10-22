"""Google Trends via trendspy -> série normalizada.

Antes usava `pytrends`, projeto arquivado: toda chamada devolvia HTTP 400 (o
mesmo erro que o docstring de `core/db/trends.py` já registrava gravado como se
fosse dado). `trendspy` é mantido e responde — verificado ao vivo (série diária
real de 90 dias para "creatina", geo=BR). Mesma interface pública de antes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pandas as pd
from trendspy import Trends


@dataclass(frozen=True)
class TrendSeries:
    keyword: str
    geo: str
    window_days: int
    frame: pd.DataFrame  # columns: date, interest


def _timeframe(window_days: int) -> str:
    # `today N-m` devolve série diária até ~3 meses; acima disso o Google passa a
    # agregar por semana, o que muda a leitura de "último mês" — então limita.
    if window_days <= 7:
        return "now 7-d"
    if window_days <= 30:
        return "today 1-m"
    return "today 3-m"


def fetch_keyword_interest(
    keyword: str,
    *,
    geo: str = "BR",
    window_days: int = 90,
    language: str = "pt-BR",
) -> TrendSeries:
    df = Trends().interest_over_time([keyword], geo=geo, timeframe=_timeframe(window_days))
    if df is None or df.empty or keyword not in df.columns:
        return TrendSeries(keyword, geo, window_days, pd.DataFrame(columns=["date", "interest"]))
    out = df[[keyword]].rename(columns={keyword: "interest"}).reset_index()
    out = out.rename(columns={out.columns[0]: "date"})
    out["date"] = pd.to_datetime(out["date"]).dt.tz_localize(None)
    out = out[["date", "interest"]].sort_values("date").reset_index(drop=True)
    return TrendSeries(keyword=keyword, geo=geo, window_days=window_days, frame=out)


def fetch_compare_interest(
    keywords: Sequence[str],
    *,
    geo: str = "BR",
    window_days: int = 90,
    language: str = "pt-BR",
) -> pd.DataFrame:
    if not keywords:
        return pd.DataFrame()
    kw = list(keywords)[:5]
    df = Trends().interest_over_time(kw, geo=geo, timeframe=_timeframe(window_days))
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", *kw, "geo", "window_days"])
    out = df[[c for c in kw if c in df.columns]].copy().reset_index()
    out = out.rename(columns={out.columns[0]: "date"})
    out["date"] = pd.to_datetime(out["date"]).dt.tz_localize(None)
    out["geo"] = geo
    out["window_days"] = window_days
    return out
