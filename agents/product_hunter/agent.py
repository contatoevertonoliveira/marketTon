"""Product Hunter agent runtime."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from core.orchestrator import Memory
from core.tasks import TaskResult
from integrations.marketplaces.registry import list_adapter_names, resolve

DATA = Path(__file__).resolve().parent.parent.parent / "data"
PRODUCTS_DIR = DATA / "products"
PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_KEYWORDS = ["fone bluetooth", "luminária led", "calça legging", "garrafa térmica", "tênis running"]


def run(memory: Memory) -> TaskResult:
    keywords = memory.get("keywords_product") or DEFAULT_KEYWORDS
    adapter_names = memory.get("adapter_names") or list_adapter_names()
    rows = []
    for kw in keywords[:5]:
        for name in adapter_names:
            adapter = resolve(name)
            if adapter is None:
                continue
            try:
                df = adapter.fetch_products()
                if df is None or df.empty:
                    continue
                matches = _keyword_match(df, kw)
                if matches.empty:
                    continue
                matches["keyword"] = kw
                matches["marketplace"] = name
                matches["score"] = _score(matches)
                matches["collected_at"] = datetime.now().isoformat()
                rows.append(matches)
            except Exception as e:  # noqa: BLE001
                rows.append(pd.DataFrame([{"keyword": kw, "marketplace": name, "error": str(e)}]))
    if rows:
        combined = pd.concat(rows, ignore_index=True)
        combined["score"] = combined["score"].fillna(0).astype(float)
        out = combined.sort_values("score", ascending=False).head(20)
        (PRODUCTS_DIR / "product_hunter_latest.csv").unlink(missing_ok=True)
        out.to_csv(PRODUCTS_DIR / "product_hunter_latest.csv", index=False)
        return TaskResult(
            task_id="product_hunter",
            ok=True,
            summary=f"evaluated products across {len(adapter_names)} adapters",
            artifacts={
                "path": str(PRODUCTS_DIR / "product_hunter_latest.csv"),
                "rows": int(len(out)),
                "adapter_names": adapter_names,
            },
        )
    return TaskResult(task_id="product_hunter", ok=True, summary="no products found", artifacts={})


def _keyword_match(df: pd.DataFrame, keyword: str) -> pd.DataFrame:
    text_cols = [c for c in df.columns if df[c].dtype == object]
    if not text_cols:
        return pd.DataFrame()
    mask = df[text_cols].astype(str).apply(lambda col: col.str.contains(keyword, case=False, na=False)).any(axis=1)
    return df[mask]


def _score(df: pd.DataFrame) -> float:
    try:
        return float(df[["price", "price"]].mean().mean())
    except Exception:  # noqa: BLE001
        return 0.0
