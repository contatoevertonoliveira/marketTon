"""Cliente mínimo para Meta Marketing API (Facebook Ads Library / Ads Insights)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

GRAPH = "https://graph.facebook.com/v19.0"


class MetaError(Exception):
    pass


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    token = params.pop("access_token", None) if params else None
    url = f"{GRAPH}/{path}"
    r = requests.get(url, params=params, timeout=30)
    if r.status_code != 200:
        raise MetaError(f"{r.status_code} {r.text}")
    return r.json()


def ad_account_insights(
    ad_account_id: str,
    *,
    fields: str = "campaign_name,adset_name,ad_name,impressions,clicks,spend,cpc,cpm,ctr,actions",
    date_preset: str = "last_30d",
    level: str = "ad",
) -> list[dict[str, Any]]:
    act = ad_account_id if str(ad_account_id).startswith("act_") else f"act_{ad_account_id}"
    params = {"fields": fields, "date_preset": date_preset, "level": level, "limit": 200}
    try:
        data = _get(f"{act}/insights", params=params)
        return data.get("data", [])
    except MetaError as e:
        raise MetaError(f"Falha insights: {e}") from e


def ads_library_adsearch(
    search_terms: str,
    *,
    country: str = "BR",
    limit: int = 25,
    fields: str = "id,ad_creation_time,ad_creative_bodies,page_name,spend,impressions",
) -> list[dict[str, Any]]:
    url = f"{GRAPH}/ads_archive"
    params = {
        "search_terms": search_terms,
        "ad_reached_countries": f'["{country}"]',
        "fields": fields,
        "limit": limit,
    }
    r = requests.get(url, params=params, timeout=30)
    if r.status_code != 200:
        raise MetaError(f"{r.status_code} {r.text}")
    return r.json().get("data", [])

