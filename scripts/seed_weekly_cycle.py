#!/usr/bin/env python3
"""Seed rápido do ciclo semanal Lobos/Canali — sem importar agentes."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "memory" / "mcp_state.json"
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

DEFAULT_PLAN = {}

DEFAULT_CONTEXT = {
    "last_trend_alert": None,
    "last_approved_product": None,
    "last_copy_batch": None,
    "last_metric_snapshot": None,
    "actors": ["thiago_lobos", "cassio_canali"],
    "governance": "master_only_decides",
}

DEFAULT_QUEUE = {
    "trends_pending": [],
    "products_pending": [],
    "copy_pending": [],
    "reports": [],
}

DEFAULT_BADGES = [
    {"id": "lobos", "label": "Lobos", "used": True, "last_used": None},
    {"id": "canali", "label": "Canali", "used": True, "last_used": None},
]


def main() -> int:
    data = {
        "methodology": DEFAULT_METHODOLOGY,
        "plan": DEFAULT_PLAN,
        "context": DEFAULT_CONTEXT,
        "queue": DEFAULT_QUEUE,
        "badges": DEFAULT_BADGES,
        "updated_at": datetime.now().isoformat(),
    }

    data["context"].update({
        "selected_trend": {"topic": "perfume importado", "source": "tiktok", "region": "Brasil"},
        "adapter_names": ["dummy"],
        "current_copy": {
            "headline": "Apenas 12x de R$ 12",
            "body": "Case real: mãe de família começou do zero com nosso método.",
            "style": "case_social_proof",
        },
        "publish_playbook": ["yt_short", "ig_reel", "tt_lead"],
        "published": {"status": "scheduled"},
        "metrics": {"visits": 1240, "leads": 178, "sales": 14, "revenue_estimated": 1358.0},
        "master_decision": "go",
    })

    data["methodology"].update({
        "supplier_mode": "national_pronta_entrega",
        "price_strategy": "differentiate_not_compete",
        "weekly_launch": True,
        "must_have_case": True,
        "current_launch_week": 1,
        "target_ticket_min": 97.0,
        "target_ticket_max": 297.0,
        "copy_style": "direct_simple_obvious",
    })

    data["plan"].update({
        "last_launch_date": "2026-06-18",
        "next_launch_date": "2026-06-25",
        "current_ladder": [
            {"name": "Negocio de 4 Rend", "ticket": 97.0, "week": 1}
        ],
        "approved_products": [{"title": "Negocio de 4 Rend", "score": 59.9}],
        "selected_cases": ["case_social_proof"],
        "weekly_calendar": [{"week": 1, "date": "2026-06-18", "action": "launch"}],
    })

    STATE_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Seed salva em {STATE_PATH}")
    print(
        json.dumps(
            {
                "methodology": data["methodology"],
                "plan": data["plan"],
                "ctx_keys": sorted(data["context"].keys()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
