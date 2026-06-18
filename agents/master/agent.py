"""Master agent runtime — consolida relatórios dos subagentes."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from core.orchestrator import Memory
from core.tasks import TaskResult

DATA = Path(__file__).resolve().parent.parent.parent / "data"
REPORTS = DATA / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)


def run(memory: Memory) -> TaskResult:
    artifacts = _read_latest(DATA / "trend_alerts.csv", "trend_alerts")
    artifacts.update(_read_latest(DATA / "products" / "product_hunter_latest.csv", "product_hunter"))
    artifacts.update(_read_latest(DATA / "copy_variants.csv", "copy_variants"))
    products_rows = 0
    alerts_rows = 0
    try:
        if (DATA / "products" / "product_hunter_latest.csv").exists() and artifacts.get("product_hunter_path"):
            products_rows = int(len(pd.read_csv(artifacts["product_hunter_path"])))
    except Exception:  # noqa: BLE001
        pass
    try:
        if artifacts.get("trend_alerts_path"):
            alerts_rows = int(len(pd.read_csv(artifacts["trend_alerts_path"])))
    except Exception:  # noqa: BLE001
        pass
    summary = {
        "generated_at": datetime.now().isoformat(),
        "top_opportunities_hint": "Check `product_hunter` + `trend_alerts`",
        "top_risks_hint": "Check marketplace health from marketplace_manager report",
        "next_actions_hint": "Run marketing tests from `copy_variants.csv`.",
        "alerts_rows": alerts_rows,
        "products_rows": products_rows,
        "frames": {k: v for k, v in artifacts.items() if k.endswith("_path")},
    }
    return TaskResult(task_id="master", ok=True, summary="consolidated daily briefing", artifacts=summary)


def _read_latest(path: Path, key: str) -> dict:
    if path.exists():
        return {f"{key}_path": str(path)}
    return {}
