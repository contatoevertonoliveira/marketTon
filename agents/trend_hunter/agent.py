"""Trend Hunter agent runtime — Lobos/Canali MCP guided."""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from core.orchestrator import Memory
from core.tasks import TaskResult
from agents.core.mcp_state import MCPState

DATA = Path(__file__).resolve().parent.parent.parent / "data"
ALERTS = DATA / "trend_alerts.csv"
ALERTS.parent.mkdir(parents=True, exist_ok=True)


def run(memory: Memory) -> TaskResult:
    method = MCPState().methodology
    # niche-first filtering, Lobos: do not chase generic noise
    keywords = memory.get("keywords_trend") or [
        "marketing digital cristão",
        "renda extra cristã",
        "empreendedorismo cristão",
        "vendas pelo instagram",
        "dropshipping nacional",
        "produto digital",
        "loja virtual",
        "ganhar dinheiro na internet",
    ]
    geo = memory.get("geo", "BR")
    window = int(memory.get("trend_window_days", 30))
    keywords = keywords[:10]

    rows: list[dict] = []
    for kw in keywords:
        try:
            s = _fetch(kw, geo=geo, window_days=window)
            if s.empty:
                continue
            interest_last = float(s["interest"].iloc[-1])
            interest_mean = float(s["interest"].mean())
            change = float(s["interest"].diff().iloc[-1]) if len(s) > 1 else 0.0
            alert = "UP" if change > 5 else "DOWN" if change < -5 else "STABLE"
            if method.get("niche_focus") == "marketing_digital_cristao":
                # bias: prefer relevance within niche, do not treat generic dropshipping as winning
                if any(x in kw.lower() for x in ["cristão", "crista", "renda extra"]):
                    alert = "UP" if change > -1 else alert
            rows.append(
                {
                    "keyword": kw,
                    "geo": geo,
                    "interest_last": round(interest_last, 2),
                    "interest_mean": round(interest_mean, 2),
                    "interest_change": round(change, 2),
                    "alert": alert,
                    "collected_at": datetime.now().isoformat(),
                }
            )
        except Exception as e:  # noqa: BLE001
            rows.append(
                {
                    "keyword": kw,
                    "error": str(e),
                    "collected_at": datetime.now().isoformat(),
                }
            )

    if rows:
        pd.DataFrame(rows).to_csv(ALERTS, index=False, mode="a", header=not ALERTS.exists())

    mcp = MCPState()
    mcp.update_ctx(last_trend_alert={"count": len(rows), "keywords": [r.get("keyword") for r in rows if "keyword" in r]})
    approved = [r for r in rows if r.get("alert") == "UP"]
    mcp.enqueue("trends_pending", {"count": len(approved), "ts": datetime.now().isoformat()})

    return TaskResult(
        task_id="trend_hunter",
        ok=True,
        summary=f"checked {len(rows)} trends with niche-first gating",
        artifacts={"alerts_path": str(ALERTS), "count": len(rows), "approved_pending": len(approved)},
    )


def _fetch(keyword: str, *, geo: str, window_days: int):
    from collectors.google_trends.client import fetch_keyword_interest

    s = fetch_keyword_interest(keyword, geo=geo, window_days=window_days)
    return s.frame if not s.frame.empty else pd.DataFrame()
