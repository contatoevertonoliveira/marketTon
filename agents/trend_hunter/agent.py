"""Trend Hunter agent runtime."""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from core.orchestrator import Memory
from core.tasks import TaskResult
from integrations.marketplaces.registry import list_adapter_names, resolve

DATA = Path(__file__).resolve().parent.parent.parent / "data"
ALERTS = DATA / "trend_alerts.csv"
ALERTS.parent.mkdir(parents=True, exist_ok=True)

DEFAULT_KEYWORDS = ["fone bluetooth", "luminária led", "calça legging", "garrafa térmica", "tênis running"]
DEFAULT_GEO = "BR"
DEFAULT_WINDOW = 30


def run(memory: Memory) -> TaskResult:
    keywords = memory.get("keywords_trend") or DEFAULT_KEYWORDS
    geo = memory.get("geo", DEFAULT_GEO)
    window = int(memory.get("trend_window_days", DEFAULT_WINDOW))
    rows = []
    for kw in keywords[:10]:
        try:
            s = _fetch(kw, geo=geo, window_days=window)
            if not s.empty:
                interest_last = float(s["interest"].iloc[-1])
                interest_mean = float(s["interest"].mean())
                change = float(s["interest"].diff().iloc[-1]) if len(s) > 1 else 0.0
                rows.append(
                    {
                        "keyword": kw,
                        "geo": geo,
                        "interest_last": round(interest_last, 2),
                        "interest_mean": round(interest_mean, 2),
                        "interest_change": round(change, 2),
                        "alert": "UP" if change > 5 else "DOWN" if change < -5 else "STABLE",
                        "collected_at": datetime.now().isoformat(),
                    }
                )
        except Exception as e:  # noqa: BLE001
            rows.append({"keyword": kw, "error": str(e)})
    if rows:
        pd.DataFrame(rows).to_csv(ALERTS, index=False, mode="a", header=not ALERTS.exists())
    return TaskResult(
        task_id="trend_hunter",
        ok=True,
        summary=f"checked {len(rows)} trends",
        artifacts={"alerts_path": str(ALERTS), "count": len(rows)},
    )


def _fetch(keyword: str, *, geo: str, window_days: int):
    from collectors.google_trends.client import fetch_keyword_interest
    s = fetch_keyword_interest(keyword, geo=geo, window_days=window_days)
    return s.frame if not s.frame.empty else pd.DataFrame()
