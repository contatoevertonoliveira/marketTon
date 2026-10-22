"""Métricas de palavra-chave para decidir afiliação: tendência, público, e —
quando há credencial — volume, CPC e concorrência no Google.

Honestidade sobre o que vem de onde:

* **Tendência** (alta/baixa e % de variação) é dado real do Google Trends,
  coletado via `trendspy`. Compara a média dos últimos 30 dias com a dos 30
  anteriores; variação dentro de ±5% é "estável" (faixa morta: ruído de
  medição não é tendência).
* **Público** (feminino/masculino/infantil) é *inferido do texto* da palavra-
  chave por regras simples — está rotulado como inferência na API.
* **Volume, CPC e concorrência** só existem no Planejador de Palavras-chave
  do Google Ads. Vêm da API do Google Ads (credenciais em Integrações) ou, na
  falta dela, do DataForSEO; sem nenhum dos dois ficam `None`. O CPC chega na
  moeda da conta do Google Ads (BRL vira `cpc_brl` direto) ou em dólar pelo
  DataForSEO, que só vira R$ se o operador informar a cotação — nenhum câmbio
  é embutido aqui.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from collectors.google_trends.client import fetch_keyword_interest
from config.settings import get_settings
from integrations.google_ads import GoogleAdsClient, GoogleAdsConfig, GoogleAdsError

logger = logging.getLogger(__name__)

# O Google limita requisições; o resultado de uma palavra-chave não muda de hora
# em hora. Cache em memória do processo: reiniciar a API zera, de propósito.
_CACHE_TTL_SECONDS = 6 * 3600
_cache: dict[tuple[str, str], tuple[float, "KeywordMetrics"]] = {}

DEADBAND_PCT = 5.0

_AUDIENCE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("infantil", ("infantil", "criança", "crianca", "bebê", "bebe", "kids", "menino", "menina")),
    ("feminino", ("feminin", "mulher", "mulheres", "legging", "vestido", "blusa", "saia", "maquiagem",
                  "batom", "sutiã", "sutia", "bolsa", "salto", "gestante", "cintura alta")),
    ("masculino", ("masculin", "homem", "homens", "barba", "cueca", "gravata", "terno")),
]


def infer_audience(text: str) -> str | None:
    """Público provável pelo texto. `None` = sem sinal (não afirma "unissex")."""
    lowered = text.lower()
    for audience, needles in _AUDIENCE_RULES:
        if any(needle in lowered for needle in needles):
            return audience
    return None


@dataclass
class KeywordMetrics:
    keyword: str
    geo: str = "BR"

    # Google Trends (real)
    trend_direction: str | None = None  # "rising" | "falling" | "stable"
    growth_pct_30d: float | None = None
    interest_last: float | None = None
    trend_error: str | None = None

    # Inferido do texto
    audience: str | None = None

    # Planejador do Google Ads (via provedor; None sem credencial)
    monthly_volume: int | None = None
    cpc_usd: float | None = None
    cpc_brl: float | None = None
    competition: str | None = None  # "LOW" | "MEDIUM" | "HIGH"
    competition_index: int | None = None
    planner_source: str | None = None
    planner_error: str | None = None

    notes: list[str] = field(default_factory=list)


def _trend_summary(keyword: str, geo: str) -> dict[str, Any]:
    series = fetch_keyword_interest(keyword, geo=geo, window_days=90)
    frame = series.frame
    if frame.empty or len(frame) < 14:
        return {"error": "série curta ou vazia no Google Trends"}

    last_date = frame["date"].max()
    recent = frame[frame["date"] > last_date - _days(30)]["interest"]
    previous = frame[(frame["date"] <= last_date - _days(30)) & (frame["date"] > last_date - _days(60))]["interest"]
    result: dict[str, Any] = {"interest_last": float(frame["interest"].iloc[-1])}
    if len(recent) < 5 or len(previous) < 5 or previous.mean() == 0:
        result["error"] = "dados insuficientes para comparar os dois últimos meses"
        return result

    growth = (recent.mean() - previous.mean()) / previous.mean() * 100
    result["growth_pct_30d"] = round(float(growth), 1)
    result["trend_direction"] = (
        "rising" if growth > DEADBAND_PCT else "falling" if growth < -DEADBAND_PCT else "stable"
    )
    return result


def _days(n: int):
    import pandas as pd

    return pd.Timedelta(days=n)


def _google_ads_config() -> GoogleAdsConfig | None:
    """Credenciais do Google Ads salvas em Integrações (só se ativas e completas)."""
    try:
        from sqlalchemy import select

        from core.db.service_credentials import ServiceCredential
        from core.db.session import session_scope

        with session_scope() as session:
            row = session.scalar(select(ServiceCredential).where(ServiceCredential.service == "google_ads"))
            if row is None or not row.enabled:
                return None
            config = GoogleAdsConfig.from_values(row.values)
            return config if config.is_complete() else None
    except Exception as exc:  # noqa: BLE001 - banco indisponível não derruba a tela
        logger.warning("não foi possível ler credenciais do Google Ads: %s", exc)
        return None


def _dataforseo_configured() -> bool:
    settings = get_settings()
    return bool(settings.dataforseo_login and settings.dataforseo_password)


def planner_provider() -> str | None:
    """Qual provedor de volume/CPC está configurado: "google_ads", "dataforseo" ou `None`."""
    if _google_ads_config() is not None:
        return "google_ads"
    return "dataforseo" if _dataforseo_configured() else None


def _planner_metrics(keywords: list[str]) -> tuple[dict[str, dict[str, Any]], str | None, str | None]:
    """Volume/CPC/concorrência. Devolve `(métricas, provedor, erro)`.

    Cada métrica vem normalizada: `search_volume`, `competition`,
    `competition_index`, `cpc` e `currency`. Tenta o Google Ads primeiro; se ele
    falhar, o erro volta para a tela (não some em silêncio) e o DataForSEO, se
    configurado, é a alternativa.
    """
    error: str | None = None
    config = _google_ads_config()
    if config is not None:
        try:
            found, _currency = GoogleAdsClient(config).keyword_metrics(keywords)
            return found, "google_ads", None
        except GoogleAdsError as exc:
            logger.warning("Google Ads falhou: %s", exc)
            error = f"Google Ads: {exc}"

    if _dataforseo_configured():
        settings = get_settings()
        try:
            response = requests.post(
                "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live",
                auth=(settings.dataforseo_login, settings.dataforseo_password),
                json=[{"keywords": keywords, "location_code": 2076, "language_code": "pt"}],
                timeout=45,
            )
            response.raise_for_status()
            tasks = response.json().get("tasks") or []
            items = (tasks[0].get("result") or []) if tasks else []
            # Formato montado pela documentação do provedor, ainda não validado
            # com conta real. O CPC do DataForSEO é sempre em dólar.
            return (
                {
                    str(item.get("keyword", "")).lower(): {
                        "search_volume": item.get("search_volume"),
                        "competition": item.get("competition"),
                        "competition_index": item.get("competition_index"),
                        "cpc": item.get("cpc"),
                        "currency": "USD",
                    }
                    for item in items
                },
                "dataforseo",
                error,
            )
        except Exception as exc:  # noqa: BLE001 - falha do provedor não derruba a tela
            logger.warning("DataForSEO falhou: %s", exc)
            error = f"{error + ' · ' if error else ''}DataForSEO: {str(exc)[:160]}"
    return {}, None, error


def planner_volumes(keywords: list[str]) -> dict[str, int | None]:
    """Volume mensal de várias palavras numa só consulta ao provedor (sem Trends).

    Usado para escolher, entre candidatas, a mais buscada. Sem provedor devolve `{}`.
    """
    if not keywords or planner_provider() is None:
        return {}
    found, _source, _error = _planner_metrics(keywords)
    return {k: (found.get(k.lower()) or {}).get("search_volume") for k in keywords}


def analyze_keywords(keywords: list[str], *, geo: str = "BR") -> list[KeywordMetrics]:
    now = time.time()
    results: dict[str, KeywordMetrics] = {}
    pending: list[str] = []

    provider = planner_provider()
    for keyword in keywords:
        cached = _cache.get((keyword.lower(), geo))
        fresh = cached and now - cached[0] < _CACHE_TTL_SECONDS
        # Resultado guardado sem volume/CPC deixa de valer assim que um provedor
        # é configurado — senão o operador salva a credencial e nada muda por 6h.
        if fresh and not (cached[1].planner_source is None and provider is not None):
            results[keyword] = cached[1]
        else:
            pending.append(keyword)

    planner, source, planner_error = _planner_metrics(pending) if pending else ({}, None, None)
    settings = get_settings()

    for keyword in pending:
        metrics = KeywordMetrics(keyword=keyword, geo=geo, audience=infer_audience(keyword))
        try:
            trend = _trend_summary(keyword, geo)
        except Exception as exc:  # noqa: BLE001 - uma palavra-chave ruim não derruba o lote
            trend = {"error": str(exc)[:160]}
        metrics.interest_last = trend.get("interest_last")
        metrics.growth_pct_30d = trend.get("growth_pct_30d")
        metrics.trend_direction = trend.get("trend_direction")
        metrics.trend_error = trend.get("error")

        metrics.planner_error = planner_error
        item = planner.get(keyword.lower())
        if item:
            metrics.planner_source = source
            metrics.monthly_volume = item.get("search_volume")
            metrics.competition = item.get("competition")
            metrics.competition_index = item.get("competition_index")
            cpc, currency = item.get("cpc"), item.get("currency")
            if cpc is not None:
                if currency == "BRL":
                    metrics.cpc_brl = round(float(cpc), 2)
                elif currency == "USD":
                    metrics.cpc_usd = float(cpc)
                    if settings.usd_brl_rate:
                        metrics.cpc_brl = round(float(cpc) * settings.usd_brl_rate, 2)
                else:
                    # Moeda da conta que não conhecemos: não converte no escuro.
                    metrics.notes.append(f"CPC em {currency or 'moeda desconhecida'}, sem conversão para R$")
        _cache[(keyword.lower(), geo)] = (now, metrics)
        results[keyword] = metrics

    return [results[k] for k in keywords]


def rank_opportunities(items: list[KeywordMetrics], limit: int = 5) -> tuple[list[KeywordMetrics], str]:
    """Top N: tráfego crescente e CPC baixo. Devolve também a base do ranking.

    Só entra quem está em alta (acima da faixa morta). Com CPC conhecido, ordena
    por CPC crescente e, no empate, por crescimento; sem CPC em nenhum item,
    ordena só por crescimento e avisa — não finge que olhou o custo.
    """
    rising = [m for m in items if m.trend_direction == "rising"]
    has_cpc = any((m.cpc_brl or m.cpc_usd) is not None for m in rising)
    if has_cpc:
        def key(m: KeywordMetrics):
            cpc = m.cpc_brl if m.cpc_brl is not None else m.cpc_usd
            return (cpc if cpc is not None else float("inf"), -(m.growth_pct_30d or 0))

        return sorted(rising, key=key)[:limit], "cpc_and_growth"
    return sorted(rising, key=lambda m: -(m.growth_pct_30d or 0))[:limit], "growth_only"


__all__ = ["KeywordMetrics", "analyze_keywords", "infer_audience", "planner_provider", "planner_volumes", "rank_opportunities"]
