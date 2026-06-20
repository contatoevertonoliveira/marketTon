"""Central settings for marketplaces and agent behavior."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from pydantic import BaseModel


class MarketplaceSettings(BaseModel):
    enabled: bool = True
    mode: str = "affiliate"  # affiliate | dropshipping | both
    scope: str = "national,international"
    api_url: str = ""
    client_id: str = ""
    client_secret: str = ""
    partner_id: str = ""
    partner_key: str = ""
    access_token: str = ""
    access_key: str = ""
    secret_key: str = ""


class AppSettings(BaseModel):
    scan_interval_minutes: int = 60
    min_commission_pct: float = 3.0
    target_ticket_min: float = 30.0
    target_ticket_max: float = 120.0
    min_orders: int = 10
    score_weights: dict = {"commission": 0.4, "orders": 0.3, "ticket": 0.2, "competition": 0.1}
    preferred_supplier_scope: str = "national,international"
    allow_dropshipping: bool = True
    allow_affiliate: bool = True

    marketplaces: dict[str, MarketplaceSettings] = field(
        default_factory=lambda: {
            "mercado_livre": MarketplaceSettings(enabled=True, mode="affiliate", scope="national,international", api_url="https://api.mercadolibre.com"),
            "shopee": MarketplaceSettings(enabled=True, mode="affiliate", scope="national,international", api_url="https://partner.shopeemobile.com"),
            "amazon": MarketplaceSettings(enabled=True, mode="affiliate", scope="international", api_url="https://webservices.amazon.com"),
        }
    )


_SETTINGS_PATH = Path(__file__).resolve().parent.parent / "config" / "settings.json"


def load_settings() -> AppSettings:
    if _SETTINGS_PATH.exists():
        try:
            data = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
            return AppSettings(**data)
        except Exception:
            pass
    return AppSettings()


def save_settings(settings: AppSettings) -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(settings.json(indent=2, ensure_ascii=False), encoding="utf-8")


def apply_env_overrides(settings: AppSettings) -> AppSettings:
    data = settings.dict()
    for key, val in os.environ.items():
        if not key.startswith("MARKETPLACE_"):
            continue
        # MARKETPLACE_MERCADOLIVRE_ENABLED -> ['mercado_livre']['enabled']
        parts = key[len("MARKETPLACE_"):].lower().split("_", 1)
        if len(parts) != 2:
            continue
        mp, field = parts
        mp_map = {"mercadolivre": "mercado_livre", "shopee": "shopee", "amazon": "amazon"}
        mp_name = mp_map.get(mp)
        if not mp_name:
            continue
        if mp_name not in data["marketplaces"]:
            data["marketplaces"][mp_name] = {}
        mp_obj = data["marketplaces"][mp_name]
        # boolean/numbers
        if field in {"enabled", "allow_dropshipping", "allow_affiliate"}:
            mp_obj[field] = val.lower() in {"1", "true", "yes", "y"}
        elif field in {"scan_interval_minutes", "min_orders"} or field.startswith("target_ticket") or field.startswith("min_commission"):
            try:
                mp_obj[field] = float(val) if "." in val else int(val)
            except Exception:
                mp_obj[field] = val
        else:
            if field == "scope":
                mp_obj[field] = val
            else:
                mp_obj[field] = val
    return AppSettings(**data)
