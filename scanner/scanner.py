"""Marketplace scanner utilities."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from integrations.marketplaces.registry import resolve, list_adapter_names


@dataclass
class MarketRules:
    min_commission_pct: float = 5.0
    target_ticket_min: float = 97.0
    target_ticket_max: float = 297.0
    min_orders: int = 50
    score_weights: dict[str, float] = field(
        default_factory=lambda: {
            "commission": 0.4,
            "orders": 0.3,
            "ticket": 0.2,
            "competition": 0.1,
        }
    )


_RULES_PATH = Path(__file__).resolve().parent.parent / "memory" / "market_rules.json"


def load_rules() -> MarketRules:
    if _RULES_PATH.exists():
        try:
            data = json.loads(_RULES_PATH.read_text(encoding="utf-8"))
            return MarketRules(**data)
        except Exception:
            pass
    return MarketRules()


def save_rules(rules: MarketRules) -> None:
    _RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RULES_PATH.write_text(json.dumps(rules.__dict__, indent=2), encoding="utf-8")


def _series(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce").fillna(default)
    return pd.Series(default, index=df.index)


def _fetch_marketplace_products(name: str) -> pd.DataFrame:
    adapter = resolve(name)
    if adapter is None:
        return pd.DataFrame()
    try:
        df = adapter.fetch_products()
        if df is None:
            return pd.DataFrame()
        return df
    except Exception:
        return pd.DataFrame()


def _apply_scoring(df: pd.DataFrame, rules: MarketRules) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    orders = _series(out, "orders")
    commission = _series(out, "commission_pct")
    if commission.max() == 0:
        commission = _series(out, "score")
    ticket = _series(out, "price")
    max_orders = max(float(orders.max() or 1), 1.0)
    max_commission = max(float(commission.max() or 1), 1.0)
    out["score_orders"] = (orders / max_orders).clip(0, 1).values
    out["score_commission"] = (commission / max_commission).clip(0, 1).values
    ticket_center = (rules.target_ticket_min + rules.target_ticket_max) / 2
    ticket_spread = max(rules.target_ticket_max - rules.target_ticket_min, 1.0)
    out["score_ticket"] = (1 - (ticket - ticket_center).abs() / ticket_spread).clip(0, 1).values
    out["score_competition"] = 0.5
    w = rules.score_weights
    out["score"] = (
        w.get("commission", 0.0) * out["score_commission"]
        + w.get("orders", 0.0) * out["score_orders"]
        + w.get("ticket", 0.0) * out["score_ticket"]
        + w.get("competition", 0.0) * out["score_competition"]
    )
    mask = (
        (commission >= rules.min_commission_pct)
        & (orders >= rules.min_orders)
        & (ticket >= rules.target_ticket_min)
        & (ticket <= rules.target_ticket_max)
    )
    return out.loc[mask].sort_values("score", ascending=False)


def scan_all(rules: MarketRules | None = None) -> pd.DataFrame:
    rules = rules or load_rules()
    frames = []
    for name in list_adapter_names():
        df = _fetch_marketplace_products(name)
        if not df.empty:
            df["marketplace"] = name
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    merged = pd.concat(frames, ignore_index=True)
    return _apply_scoring(merged, rules)
