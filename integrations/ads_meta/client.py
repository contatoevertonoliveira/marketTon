"""Cliente da Meta Marketing API / Ads Library.

O cliente anterior (`collectors/meta_ads/client.py`) tinha um defeito silencioso:
`_get` fazia `params.pop("access_token")` mas **nenhum chamador definia esse
parâmetro**, e `META_ACCESS_TOKEN` não aparecia em nenhum arquivo `.py`. Toda
chamada saía não autenticada e voltava 401 — sem que o motivo ficasse claro.

Aqui o token vem da configuração validada e a ausência dele falha de imediato,
com mensagem acionável, em vez de produzir erro de autenticação da Graph API.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from config.settings import get_settings

GRAPH_URL = "https://graph.facebook.com/v19.0"

INSIGHTS_FIELDS = (
    "campaign_name,adset_name,ad_name,impressions,clicks,spend,cpc,cpm,ctr,actions"
)
ADS_LIBRARY_FIELDS = "id,ad_creation_time,ad_creative_bodies,page_name,spend,impressions"


class MetaAdsError(RuntimeError):
    """Falha ao falar com a Meta. Inclui o motivo devolvido pela API."""


class MetaCredentialsMissing(MetaAdsError):
    """Token ausente. Erro de configuração, não de rede."""


@dataclass(frozen=True)
class MetaCredentials:
    access_token: str
    ad_account_id: str = ""

    @property
    def is_configured(self) -> bool:
        return bool(self.access_token)


def get_credentials() -> MetaCredentials:
    settings = get_settings()
    return MetaCredentials(
        access_token=settings.meta_access_token,
        ad_account_id=settings.meta_ad_account_id,
    )


def require_credentials() -> MetaCredentials:
    credentials = get_credentials()
    if not credentials.is_configured:
        raise MetaCredentialsMissing(
            "META_ACCESS_TOKEN não configurado. Defina a variável no .env para usar "
            "a Meta Ads Library. Sem o token a API responde 401."
        )
    return credentials


def _get(path: str, params: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
    credentials = require_credentials()
    settings = get_settings()
    query = {**params, "access_token": credentials.access_token}
    response = requests.get(
        f"{GRAPH_URL}/{path}",
        params=query,
        timeout=timeout or settings.connector_timeout_seconds,
    )
    if response.status_code != 200:
        raise MetaAdsError(f"HTTP {response.status_code} em /{path}: {response.text[:400]}")
    return response.json()


def get_status() -> dict[str, Any]:
    """Estado da integração, sem levantar exceção. Usado por páginas de diagnóstico."""
    credentials = get_credentials()
    if not credentials.is_configured:
        return {"status": "missing_credentials", "error": "META_ACCESS_TOKEN não configurado"}
    return {"status": "ready", "ad_account_id": credentials.ad_account_id or None}


def ad_account_insights(
    ad_account_id: str | None = None,
    *,
    fields: str = INSIGHTS_FIELDS,
    date_preset: str = "last_30d",
    level: str = "ad",
) -> list[dict[str, Any]]:
    """Insights de campanha/conjunto/anúncio."""
    credentials = get_credentials()
    account = ad_account_id or credentials.ad_account_id
    if not account:
        raise MetaAdsError("ad_account_id não informado e META_AD_ACCOUNT não configurado.")
    act = account if str(account).startswith("act_") else f"act_{account}"
    data = _get(f"{act}/insights", {"fields": fields, "date_preset": date_preset, "level": level, "limit": 200})
    return data.get("data", [])


def ads_library_adsearch(
    search_terms: str,
    *,
    country: str = "BR",
    limit: int = 25,
    fields: str = ADS_LIBRARY_FIELDS,
) -> list[dict[str, Any]]:
    """Busca de anúncios na biblioteca pública (Ads Library).

    Retorna dados agregados de anúncios ativos. É insumo do Creative Saturation
    Score: volume de anúncios, anunciantes distintos e idade dos criativos.
    """
    data = _get(
        "ads_archive",
        {
            "search_terms": search_terms,
            "ad_reached_countries": f'["{country}"]',
            "fields": fields,
            "limit": limit,
        },
    )
    return data.get("data", [])


def count_active_ads(search_terms: str, *, country: str = "BR", limit: int = 100) -> dict[str, Any]:
    """Resumo agregado para alimentar o Creative Saturation Score.

    Devolve contagens reais. Campos que a API não expõe permanecem ausentes, para
    que o score seja marcado INSUFFICIENT_DATA em vez de estimado.
    """
    ads = ads_library_adsearch(search_terms, country=country, limit=limit, fields="id,page_name,ad_creation_time")
    pages = {ad.get("page_name") for ad in ads if ad.get("page_name")}
    return {
        "active_ads_count": len(ads),
        "distinct_advertisers": len(pages),
        "sampled": len(ads) >= limit,
    }


__all__ = [
    "MetaAdsError",
    "MetaCredentials",
    "MetaCredentialsMissing",
    "ad_account_insights",
    "ads_library_adsearch",
    "count_active_ads",
    "get_credentials",
    "get_status",
    "require_credentials",
]
