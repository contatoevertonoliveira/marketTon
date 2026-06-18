"""Product Hunter agent runtime — national supply focus + weekly mode + MCP."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from core.orchestrator import Memory
from core.tasks import TaskResult
from integrations.marketplaces.registry import list_adapter_names, resolve
from agents.core.mcp_state import MCPState

DATA = Path(__file__).resolve().parent.parent.parent / "data"
PRODUCTS_DIR = DATA / "products"
PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_KEYWORDS = [
    "fone bluetooth",
    "luminária led",
    "calça legging",
    "garrafa térmica",
    "tênis running",
    "lanterna tática",
    "fonte carregador rápido",
]


def run(memory: Memory) -> TaskResult:
    method = MCPState().methodology
    keywords = memory.get("keywords_product") or DEFAULT_KEYWORDS
    adapter_names = memory.get("adapter_names") or list_adapter_names()

    rows: list[dict] = []
    seen_titles: set[str] = set()

    for kw in keywords[:5]:
        for name in adapter_names or []:
            adapter = resolve(name)
            if adapter is None:
                continue
            try:
                df = adapter.fetch_products()
            except Exception as e:  # noqa: BLE001
                rows.append({"keyword": kw, "marketplace": name, "error": str(e), "score": 0.0})
                continue
            if df is None or df.empty:
                continue
            for _, item in df.iterrows():
                title = str(item.get("title") or item.get("name") or "").strip()
                if not title or title in seen_titles:
                    continue
                haystack = f"{title} {kw}".lower()
                if kw.lower() not in haystack:
                    continue
                score = _score(item, method)
                seen_titles.add(title)
                rows.append({
                    "title": title,
                    "keyword": kw,
                    "marketplace": name,
                    "price": item.get("price"),
                    "score": score,
                    "collected_at": datetime.now().isoformat(),
                })

    out = sorted(rows, key=lambda x: x.get("score", 0) or 0, reverse=True)[:20]
    out_path = PRODUCTS_DIR / "product_hunter_latest.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["title", "keyword", "marketplace", "price", "score", "collected_at"])
        writer.writeheader()
        writer.writerows(out)

    mcp = MCPState()
    mcp.update_ctx(last_approved_product={"count": int(len(out)), "ts": datetime.now().isoformat()})
    mcp.enqueue("products_pending", {"count": int(len(out)), "ts": datetime.now().isoformat()})
    return TaskResult(
        task_id="product_hunter",
        ok=True,
        summary=f"evaluated products across {len(adapter_names or [])} adapters",
        artifacts={"path": str(out_path), "rows": int(len(out)), "adapter_names": adapter_names},
    )


def _score(item: dict, method: dict) -> float:
    try:
        base = float(item.get("price") or 0)
        if method.get("price_strategy") == "differentiate_not_compete" and base > 0:
            return base + 20.0
        return base
    except Exception:  # noqa: BLE001
        return 0.0
