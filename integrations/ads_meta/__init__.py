"""Integração com a Meta Marketing API / Ads Library."""
from __future__ import annotations

from integrations.ads_meta.client import (
    MetaAdsError,
    MetaCredentials,
    MetaCredentialsMissing,
    ad_account_insights,
    ads_library_adsearch,
    count_active_ads,
    get_status,
)

__all__ = [
    "MetaAdsError",
    "MetaCredentials",
    "MetaCredentialsMissing",
    "ad_account_insights",
    "ads_library_adsearch",
    "count_active_ads",
    "get_status",
]
