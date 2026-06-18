"""Marketplace Manager agent runtime — Canali value/presentation rules + MCP."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from core.orchestrator import Memory
from core.tasks import TaskResult
from integrations.marketplaces.registry import list_adapter_names, resolve
from agents.core.mcp_state import MCPState

DATA = Path(__file__).resolve().parent.parent.parent / "data"
REPORTS = DATA / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)


def run(memory: Memory) -> TaskResult:
    mcp = MCPState()
    method = mcp.methodology
    adapter_names = memory.get("adapter_names") or list_adapter_names()
    rows: list[pd.DataFrame] = []
    summary = []
    for name in adapter_names:
        adapter = resolve(name)
        if adapter is None:
            continue
        try:
            products = adapter.fetch_products()
            sales = adapter.fetch_sales()
            if products is None or products.empty:
                summary.append(f"{name}=no_products")
                continue
            products = products.copy()
            products["marketplace"] = name
            products["sales_collected_at"] = datetime.now().isoformat() if sales is None else sales.to_json()
            compiled, watch = _health(products, sales, method)
            rows.append(compiled)
            rows.append(watch)
            summary.append(f"{name}: ok {len(compiled)} watch {len(watch)}")
        except Exception as e:  # noqa: BLE001
            summary.append(f"{name}=error:{e}")
            rows.append(pd.DataFrame([{"marketplace": name, "error": str(e)}]))
    if rows:
        combined = pd.concat(rows, ignore_index=True)
        out_path = REPORTS / f"marketplace_health_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        combined.to_csv(out_path, index=False)
        artifacts = {"path": str(out_path), "rows": int(len(combined)), "summary": summary}
    else:
        artifacts = {"summary": summary}
    mcp.update_ctx(last_metric_snapshot={"summary": summary, "ts": datetime.now().isoformat()})
    return TaskResult(task_id="marketplace_manager", ok=True, summary=" | ".join(summary), artifacts=artifacts)


def _health(products: pd.DataFrame, sales: pd.DataFrame | None, method) -> tuple[pd.DataFrame, pd.DataFrame]:
    stock_col = None
    for c in products.columns:
        if any(k in str(c).lower() for k in ["estoque", "stock", "quantity"]):
            stock_col = c
            break
    products["_stock"] = pd.to_numeric(products[stock_col], errors="coerce").fillna(0) if stock_col else 0

    # Canali-style presentation gating instead of lowest price winning
    products["_value_presentation_ok"] = True
    products.loc[(products["_stock"] <= 0), "_value_presentation_ok"] = False
    compiled = products.head(20).copy()
    compiled["role"] = "catalog"
    watch = pd.DataFrame()
    if sales is not None and not sales.empty and {"product", "sold_last"}.issubset(sales.columns):
        watch = sales[sales["sold_last"].fillna(0) == 0].head(20).copy()
        watch["role"] = "watch"
    if watch is None or watch.empty:
        watch = pd.DataFrame(columns=list(compiled.columns))
    return compiled, watch
