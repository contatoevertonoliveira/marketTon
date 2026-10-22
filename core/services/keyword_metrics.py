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
  do Google Ads, que não tem API gratuita. Vêm do DataForSEO *se* houver
  credencial; sem ela ficam `None`. O CPC vem em dólar e só é convertido para
  R$ se o operador informar a cotação — nenhum câmbio é embutido aqui.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from collectors.google_trends.client import fetch_keyword_interest
from config.settings import get_settings

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


def _planner_metrics(keywords: list[str]) -> dict[str, dict[str, Any]]:
    """Volume/CPC/concorrência via DataForSEO (Google Ads search_volume).

    Sem credencial devolve `{}`. Formato da resposta montado a partir da
    documentação pública do provedor e **ainda não validado com conta real** —
    ajustar na primeira chamada de verdade, como foi feito com a Shopee.
    """
    settings = get_settings()
    if not (settings.dataforseo_login and settings.dataforseo_password):
        return {}
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
    except Exception as exc:  # noqa: BLE001 - falha do provedor não derruba a tela
        logger.warning("DataForSEO falhou: %s", exc)
        return {}
    return {str(item.get("keyword", "")).lower(): item for item in items}


def analyze_keywords(keywords: list[str], *, geo: str = "BR") -> list[KeywordMetrics]:
    now = time.time()
    results: dict[str, KeywordMetrics] = {}
    pending: list[str] = []

    for keyword in keywords:
        cached = _cache.get((keyword.lower(), geo))
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            results[keyword] = cached[1]
        else:
            pending.append(keyword)

    planner = _planner_metrics(pending) if pending else {}
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

        item = planner.get(keyword.lower())
        if item:
            metrics.planner_source = "dataforseo"
            metrics.monthly_volume = item.get("search_volume")
            metrics.competition = item.get("competition")
            metrics.competition_index = item.get("competition_index")
            cpc = item.get("cpc")
            if cpc is not None:
                metrics.cpc_usd = float(cpc)
                if settings.usd_brl_rate:
                    metrics.cpc_brl = round(float(cpc) * settings.usd_brl_rate, 2)
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


__all__ = ["KeywordMetrics", "analyze_keywords", "infer_audience", "rank_opportunities"]
