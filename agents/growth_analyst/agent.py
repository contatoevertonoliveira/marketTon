"""Growth Analyst agent runtime."""
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
    insights_path = DATA / "meta_ads_insights.csv"
    trends_path = DATA / "trends_interest.csv"
    report_path = REPORTS / f"growth_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    frames = []
    summary = []
    try:
        insights = pd.read_csv(insights_path)
        if not insights.empty and "error" not in insights.columns:
            frames.append(insights.assign(source="meta_insights"))
            summary.append(f"meta_insights={len(insights)}")
        else:
            summary.append("meta_insights=error_or_empty")
    except Exception as e:  # noqa: BLE001
        summary.append(f"meta_insights=read_error:{e}")
    try:
        trends = pd.read_csv(trends_path)
        if not trends.empty and "error" not in trends.columns:
            frames.append(trends.assign(source="trends"))
            summary.append(f"trends={len(trends)}")
        else:
            summary.append("trends=error_or_empty")
    except Exception as e:  # noqa: BLE001
        summary.append(f"trends=read_error:{e}")
    if frames:
        combined = pd.concat(frames, ignore_index=True)
        combined.to_csv(report_path, index=False)
    else:
        combined = pd.DataFrame()
        pd.DataFrame().to_csv(report_path, index=False)
    return TaskResult(
        task_id="growth_analyst",
        ok=True,
        summary=" | ".join(summary),
        artifacts={"report_path": str(report_path), "frames": len(frames)},
    )
