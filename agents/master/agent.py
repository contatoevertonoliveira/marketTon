"""Master agent runtime — MCP consolidation + approval flow for weekly launch."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from core.orchestrator import Memory
from core.tasks import TaskResult
from agents.core.mcp_state import MCPState

DATA = Path(__file__).resolve().parent.parent.parent / "data"
REPORTS = DATA / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)


def run(memory: Memory) -> TaskResult:
    mcp = MCPState()
    plan = mcp.plan
    last_launch = plan.get("last_launch_date")
    next_launch = plan.get("next_launch_date")
    alerts_path = DATA / "trend_alerts.csv"
    products_path = DATA / "products" / "product_hunter_latest.csv"
    copy_path = DATA / "copy_variants.csv"

    artifacts: dict = {}
    summary_parts: list[str] = []

    for p in [alerts_path, products_path, copy_path]:
        if p.exists():
            artifacts[p.name + "_exists"] = True
            artifacts[p.name + "_rows"] = int(len(pd.read_csv(p))) if p.name.endswith(".csv") else True
        else:
            artifacts[p.name + "_exists"] = False

    approved_for_launch = artifacts.get("copy_variants.csv_exists") and artifacts.get("products" + "_product_hunter_latest.csv_exists") and artifacts.get("alerts" + "_trend_alerts.csv_exists")
    if approved_for_launch:
        summary_parts.append("weekly_launch_ready=APPROVED")
        mcp.update_plan(next_launch_date=datetime.now().isoformat())
    else:
        summary_parts.append("weekly_launch_ready=WAITING")

    if last_launch:
        mcp.update_ctx(last_launch_date=last_launch)
    summary_parts.append(f'alerts_rows={artifacts.get("trend_alerts.csv_rows", 0)}')
    summary_parts.append(f'products_rows={artifacts.get("products_product_hunter_latest.csv_rows", 0)}')
    summary_parts.append(f'copy_rows={artifacts.get("copy_variants.csv_rows", 0)}')

    report_path = REPORTS / f"master_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    pd.DataFrame([{"summary": " | ".join(summary_parts), "ts": datetime.now().isoformat()}]).to_csv(report_path, index=False)

    return TaskResult(task_id="master", ok=True, summary=" | ".join(summary_parts), artifacts={"report_path": str(report_path), **artifacts})
