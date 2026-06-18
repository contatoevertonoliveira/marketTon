"""MCP state handlers + methodology config for marketTon agents."""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

STATE_PATH = Path(__file__).resolve().parent.parent.parent / "memory" / "mcp_state.json"
STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

DEFAULT_METHODOLOGY = {
    "mode": "hybrid_canali_lobos",
    "active_influencer": "hybrid",
    "badge": "Canali x Lobos",
    "niche_focus": "marketing_digital_cristao",
    "supplier_mode": "national_pronta_entrega",
    "launch_frequency_days": 7,
    "min_product_ticket": 97.00,
    "max_product_ticket": 297.00,
    "copy_style": "direct_simple_obvious",
    "require_ready_offer": True,
    "must_have_case": True,
    "yt_funnel": True,
    "multi_renda": True,
    "price_strategy": "differentiate_not_compete",
    "daily_sales_target": 1,
    "affiliate_goal": "R$100k_4_ciclos",
}


def _default_state() -> Dict[str, Any]:
    return {
        "methodology": DEFAULT_METHODOLOGY,
        "plan": {},
        "context": {
            "last_trend_alert": None,
            "last_approved_product": None,
            "last_copy_batch": None,
            "last_metric_snapshot": None,
            "actors": ["thiago_lobos", "cassio_canali"],
            "governance": "master_only_decides",
        },
        "queue": {
            "trends_pending": [],
            "products_pending": [],
            "copy_pending": [],
            "reports": [],
        },
        "badges": [
            {"id": "lobos", "label": "Lobos", "used": True, "last_used": None},
            {"id": "canali", "label": "Canali", "used": True, "last_used": None},
        ],
        "updated_at": datetime.now().isoformat(),
    }


class MCPState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if STATE_PATH.exists():
            try:
                return json.loads(STATE_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return _default_state()

    def save(self) -> None:
        with self._lock:
            self._data["updated_at"] = datetime.now().isoformat()
            STATE_PATH.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    @property
    def methodology(self) -> Dict[str, Any]:
        return self._data.get("methodology", DEFAULT_METHODOLOGY)

    @property
    def plan(self) -> Dict[str, Any]:
        return self._data.get("plan", {})

    @property
    def ctx(self) -> Dict[str, Any]:
        return self._data.get("context", {})

    @property
    def queue(self) -> Dict[str, Any]:
        return self._data.get("queue", {})

    def set_active_badge(self, badge_id: str) -> None:
        with self._lock:
            badges = {b["id"]: b for b in self._data.get("badges", [])}
            if badge_id not in badges:
                badges[badge_id] = {"id": badge_id, "label": badge_id.title(), "used": True, "last_used": datetime.now().isoformat()}
            else:
                badges[badge_id]["used"] = True
                badges[badge_id]["last_used"] = datetime.now().isoformat()
            self._data["badges"] = list(badges.values())
            self._data["methodology"]["active_influencer"] = badge_id
            self._data["methodology"]["badge"] = badges[badge_id]["label"]
            self.save()

    def next_badge(self) -> str:
        with self._lock:
            badges = self._data.get("badges", [])
            if not badges:
                return "hybrid"
            used = [b for b in badges if b.get("used")]
            unused = [b for b in badges if not b.get("used")]
            if unused:
                b = unused[0]
                b["used"] = True
                b["last_used"] = datetime.now().isoformat()
                self._data["methodology"]["active_influencer"] = b["id"]
                self._data["methodology"]["badge"] = b["label"]
                self.save()
                return b["id"]
            # reset cycle
            for b in badges:
                b["used"] = False
            b0 = badges[0]
            b0["used"] = True
            b0["last_used"] = datetime.now().isoformat()
            self._data["methodology"]["active_influencer"] = b0["id"]
            self._data["methodology"]["badge"] = b0["label"]
            self.save()
            return b0["id"]

    def enqueue(self, bucket: str, item: Any) -> None:
        with self._lock:
            self._data.setdefault("queue", {}).setdefault(bucket, []).append(item)
            self.save()

    def update_ctx(self, **kwargs) -> None:
        with self._lock:
            self._data.setdefault("context", {}).update(kwargs)
            self.save()

    def update_plan(self, **kwargs) -> None:
        with self._lock:
            self._data.setdefault("plan", {}).update(kwargs)
            self.save()

    def update_methodology(self, **kwargs) -> None:
        with self._lock:
            base = self._data.setdefault("methodology", DEFAULT_METHODOLOGY)
            base.update(kwargs)
            self.save()

    def snapshot(self) -> Dict[str, Any]:
        return json.loads(json.dumps(self._data, ensure_ascii=False))

