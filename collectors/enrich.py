"""Enriquecimento unificado: salva métricas de Meta Ads e Google Trends."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from collectors.google_trends.client import fetch_compare_interest, fetch_keyword_interest
from collectors.meta_ads.client import MetaError, ads_library_adsearch, ad_account_insights

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)


def save_csv(name: str, df: pd.DataFrame) -> str:
    path = DATA / name
    df.to_csv(path, index=False)
    return str(path)


def run_trends(keywords: list[str], *, geo: str = "BR", days: int = 90) -> dict[str, object]:
    rows = []
    for kw in keywords:
        s = fetch_keyword_interest(kw, geo=geo, window_days=days)
        rows.append(
            {
                "keyword": kw,
                "geo": geo,
                "window_days": days,
                "interest_mean": float(s.frame["interest"].mean()) if not s.frame.empty else 0.0,
                "interest_last": float(s.frame["interest"].iloc[-1]) if not s.frame.empty else 0.0,
                "interest_change": float(s.frame["interest"].diff().iloc[-1] / 100.0)
                if len(s.frame) > 1
                else 0.0,
                "collected_at": datetime.now().isoformat(),
            }
        )
    df = pd.DataFrame(rows)
    path = save_csv("trends_interest.csv", df)
    compare = fetch_compare_interest(keywords, geo=geo, window_days=days)
    if not compare.empty:
        save_csv("trends_compare.csv", compare)
    return {"summary": path, "compare": str(DATA / "trends_compare.csv")}


def run_meta_ads(*, account: str | None = None, query: str = "", country: str = "BR", date_preset: str = "last_30d") -> dict[str, object]:
    insights_path = str(DATA / "meta_ads_insights.csv")
    library_path = str(DATA / "meta_ads_library.csv")
    try:
        data = ad_account_insights(account or "", date_preset=date_preset) if account else []
        out = pd.DataFrame(data)
        out.to_csv(insights_path, index=False)
    except Exception as e:
        pd.DataFrame([{"error": str(e)}]).to_csv(insights_path, index=False)
    try:
        lib_df = pd.DataFrame(ads_library_adsearch(query or "promocao", country=country))
        lib_df.to_csv(library_path, index=False)
        return {"insights": insights_path, "library": library_path, "library_rows": int(len(lib_df))}
    except Exception as e:
        pd.DataFrame([{"error": str(e)}]).to_csv(library_path, index=False)
        return {"insights": insights_path, "library": library_path, "library_rows": 0, "error": str(e)}

