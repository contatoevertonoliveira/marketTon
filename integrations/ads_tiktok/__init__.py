"""Biblioteca de anúncios do TikTok.

Não implementada de propósito — ver `client.py` para o motivo e as alternativas.
"""
from __future__ import annotations

from integrations.ads_tiktok.client import (
    TikTokAdsUnavailable,
    get_status,
    search_ads,
)

__all__ = ["TikTokAdsUnavailable", "get_status", "search_ads"]
