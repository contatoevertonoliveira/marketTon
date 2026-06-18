"""Google Trends via pytrends -> série normalizada."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Sequence

import pandas as pd
from pytrends.request import TrendReq


@dataclass(frozen=True)
class TrendSeries:
    keyword: str
    geo: str
    window_days: int
    frame: pd.DataFrame  # columns: date, interest


def fetch_keyword_interest(
    keyword: str,
    *,
    geo: str = "BR",
    window_days: int = 90,
    language: str = "pt-BR",
) -> TrendSeries:
    pytrends = TrendReq(hl=language, tz=-180)
    kw = [keyword]
    tf = f"now {window_days}-d"
    pytrends.build_payload(kw, timeframe=tf, geo=geo, gprop="")
    df = pytrends.interest_over_time()
    if df.empty or keyword not in df.columns:
        return TrendSeries(
            keyword=keyword,
            geo=geo,
            window_days=window_days,
            frame=pd.DataFrame(columns=["date", "interest"]),
        )
    out = df[[keyword]].rename(columns={keyword: "interest"}).reset_index()
    out["date"] = pd.to_datetime(out["date"]).dt.tz_localize(timezone.utc).dt.tz_convert(None)
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
    pytrends = TrendReq(hl=language, tz=-180)
    kw = list(keywords)[:5]
    tf = f"now {window_days}-d"
    pytrends.build_payload(kw, timeframe=tf, geo=geo, gprop="")
    df = pytrends.interest_over_time()
    if df.empty:
        return pd.DataFrame(columns=["date", *kw, "geo", "window_days"])
    out = df[kw].copy().reset_index()
    out["date"] = pd.to_datetime(out["date"]).dt.tz_localize(timezone.utc).dt.tz_convert(None)
    out["geo"] = geo
    out["window_days"] = window_days
    return out

