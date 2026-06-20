"""Marketplace scanner agent — top offers selection."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from core.orchestrator import Memory
from core.tasks import TaskResult
from scanner.scanner import scan_all, save_rules, MarketRules

DATA = Path(__file__).resolve().parent.parent.parent / "data"
PRODUCTS = DATA / "products"
PRODUCTS.mkdir(parents=True, exist_ok=True)


def run(memory: Memory) -> TaskResult:
    df = scan_all()
    out_path = PRODUCTS / "market_scanner_latest.csv"
    if df.empty:
        pd.DataFrame(columns=["marketplace","title","price","orders","commission_pct","score"]).to_csv(out_path, index=False)
        return TaskResult(task_id="market_scanner", ok=True, summary="no_candidates", artifacts={"path": str(out_path), "rows": 0})
    cols = [c for c in ["marketplace","title","price","orders","commission_pct","score","url"] if c in df.columns]
    df[cols].to_csv(out_path, index=False)
    top = df.iloc[0]
    summary = f"selected={top.get('title')} marketplace={top.get('marketplace')} commission={top.get('commission_pct')} score={top.get('score')}"
    return TaskResult(task_id="market_scanner", ok=True, summary=summary, artifacts={"path": str(out_path), "rows": int(len(df)), "top": top.to_dict()})
