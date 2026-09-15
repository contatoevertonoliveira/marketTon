"""Trend Hunter — coleta de tendências e leitura por IA (briefing seções 4 e 6).

Mudanças em relação à versão anterior:

1. **O `alert` era um limiar fixo** (`change > 5`). Um produto com +6 de variação
   recebia "UP" igual a um com +400. Agora a série é interpretada por IA, que
   distingue movimento real de ruído — e declara quando o dado é insuficiente.

2. **Erros de coleta eram gravados como se fossem tendência.** O CSV
   `data/trend_alerts.csv` tinha linhas como
   `marketing digital cristão,The request failed: Google returned a response with code 400,...`
   — uma falha de upstream virou dado. Agora a falha entra em `warnings` do
   `SourceRecord` e em `trend_observations`, nunca como valor de tendência.

3. **Persistia em CSV com schema corrompido.** O arquivo tinha cabeçalho de 5
   colunas e linhas de 3, porque o agente fazia append com
   `header=not ALERTS.exists()`. Agora vai para tabela, com proveniência.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from statistics import fmean
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from core.db.base import ConnectorKind, Marketplace
from core.db.catalog import SourceRecord
from core.db.trends import TrendKeyword, TrendObservation
from core.services.ai.client import AIClient
from core.services.ai.interpreter import run_interpretation
from core.services.ai.prompts import get_prompt
from core.services.jobs import JobHandle, job_run
from core.tasks import TaskResult

logger = logging.getLogger(__name__)

DEFAULT_KEYWORDS = [
    "fone bluetooth",
    "luminária led",
    "calça legging",
    "garrafa térmica",
    "tênis running",
    "lanterna tática",
    "fonte carregador rápido",
]

DEFAULT_GEO = "BR"
DEFAULT_WINDOW_DAYS = 30
# Quantas keywords passam pela leitura de IA. É uma chamada por keyword.
DEFAULT_AI_KEYWORDS = 6


@dataclass
class TrendOptions:
    keywords: list[str] = field(default_factory=lambda: list(DEFAULT_KEYWORDS))
    geo: str = DEFAULT_GEO
    window_days: int = DEFAULT_WINDOW_DAYS
    ai_keywords: int = DEFAULT_AI_KEYWORDS
    use_ai: bool = True


def _fetch_series(keyword: str, *, geo: str, window_days: int):
    """Busca a série de interesse. Importado dentro da função para não exigir
    `pytrends` em ambiente onde só se testa a persistência."""
    from collectors.google_trends.client import fetch_keyword_interest

    return fetch_keyword_interest(keyword, geo=geo, window_days=window_days)


def _summarize(frame) -> dict[str, Any]:
    """Resume a série em números interpretáveis.

    Devolve `None` nos campos que a série não permite calcular, em vez de zero:
    uma série vazia não tem "interesse médio zero", ela não tem interesse médio.
    """
    if frame is None or frame.empty:
        return {
            "points": 0,
            "interest_last": None,
            "interest_mean": None,
            "interest_peak": None,
            "change_absolute": None,
            "change_pct": None,
            "trend_direction": None,
        }

    interests = [float(value) for value in frame["interest"].tolist()]
    last = interests[-1]
    mean = round(fmean(interests), 2)
    peak = max(interests)

    # Compara a média da metade recente com a da metade anterior. Isso é mais
    # estável que comparar dois pontos isolados, que oscilam por ruído diário.
    half = len(interests) // 2
    change_absolute = change_pct = direction = None
    if half >= 2:
        recent = fmean(interests[half:])
        earlier = fmean(interests[:half])
        change_absolute = round(recent - earlier, 2)
        if earlier > 0:
            change_pct = round((recent - earlier) / earlier * 100, 2)
        # Faixa morta de 5%: variação menor que isso é ruído de medição.
        if change_pct is None:
            direction = None
        elif change_pct > 5:
            direction = "rising"
        elif change_pct < -5:
            direction = "falling"
        else:
            direction = "stable"

    return {
        "points": len(interests),
        "interest_last": last,
        "interest_mean": mean,
        "interest_peak": peak,
        "change_absolute": change_absolute,
        "change_pct": change_pct,
        "trend_direction": direction,
    }


def record_observation(
    session: Session,
    *,
    keyword: str,
    geo: str,
    window_days: int,
    summary: dict[str, Any],
    source_record_id: int,
    observed_at: datetime | None = None,
) -> TrendObservation:
    """Grava uma leitura de tendência, criando a keyword se necessário."""
    normalized = keyword.strip().lower()
    trend = session.scalar(
        select(TrendKeyword).where(TrendKeyword.keyword == normalized, TrendKeyword.geo == geo)
    )
    if trend is None:
        trend = TrendKeyword(keyword=normalized, geo=geo, display_name=keyword.strip())
        session.add(trend)
        session.flush()

    observation = TrendObservation(
        trend_keyword_id=trend.id,
        observed_at=observed_at or datetime.now(UTC),
        window_days=window_days,
        points=int(summary.get("points") or 0),
        interest_last=summary.get("interest_last"),
        interest_mean=summary.get("interest_mean"),
        interest_peak=summary.get("interest_peak"),
        change_absolute=summary.get("change_absolute"),
        change_pct=summary.get("change_pct"),
        trend_direction=summary.get("trend_direction"),
        source_record_id=source_record_id,
    )
    session.add(observation)
    session.flush()

    trend.last_seen_at = observation.observed_at
    trend.series_count = (trend.series_count or 0) + 1
    session.flush()
    return observation


def interpret_with_ai(
    session: Session,
    observations: list[dict[str, Any]],
    *,
    ai: AIClient | None = None,
    handle: JobHandle | None = None,
) -> dict[str, Any] | None:
    """Pede à IA uma leitura do conjunto de movimentos.

    Uma chamada para o conjunto, não uma por keyword: o valor da IA aqui é comparar
    movimentos entre si ("qual merece atenção"), e isso exige ver todos juntos.
    """
    if not observations:
        return None

    ai = ai or AIClient()

    result = run_interpretation(
        session,
        ai=ai,
        agent="trend_hunter",
        kind=_trend_kind(),
        prompt=get_prompt("trend_interpreter"),
        inputs={"geo": observations[0].get("geo"), "movimentos": observations},
        target_type="trend_batch",
    )

    if not result.ok:
        if handle:
            handle.add_event(
                f"leitura de tendências por IA indisponível: {result.skipped_reason or result.error}",
                level="WARNING",
            )
        return None

    return result.output


def _trend_kind():
    from core.db.ai import AIInterpretationKind

    return AIInterpretationKind.TREND_READING


def run(
    memory: dict,
    *,
    session: Session | None = None,
    ai: AIClient | None = None,
    options: TrendOptions | None = None,
    fetcher=None,
) -> TaskResult:
    """Execução como task do pipeline.

    `fetcher` permite injetar a coleta em teste, sem rede e sem `pytrends`.
    """
    options = options or TrendOptions()
    if memory.get("keywords_trend"):
        options.keywords = list(memory["keywords_trend"])
    options.geo = memory.get("geo", options.geo)
    options.window_days = int(memory.get("trend_window_days", options.window_days))

    fetch = fetcher or _fetch_series

    if session is None:
        return TaskResult(
            task_id="trend_hunter",
            ok=True,
            summary="sem sessão de banco: nenhuma tendência persistida",
            artifacts={"persisted": False},
        )

    collected_at = datetime.now(UTC)

    with job_run(
        session,
        job_type="trend_hunter.collect",
        agent="trend_hunter",
        params={"geo": options.geo, "window_days": options.window_days, "keywords": options.keywords[:10]},
    ) as handle:
        # Procedência do lote inteiro: a coleta é uma chamada, um registro.
        source = SourceRecord(
            marketplace=Marketplace.OTHER,
            connector="google_trends",
            connector_kind=ConnectorKind.PUBLIC_DATASET,
            endpoint="pytrends.interest_over_time",
            external_id=options.geo,
            collected_at=collected_at,
            # Fonte não oficial e sem contrato de estabilidade: não vale 1.0.
            reliability=0.6,
        )
        session.add(source)
        session.flush()

        observations: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []

        for keyword in options.keywords[:10]:
            try:
                series = fetch(keyword, geo=options.geo, window_days=options.window_days)
                frame = getattr(series, "frame", None)
            except Exception as exc:  # noqa: BLE001
                # Falha de coleta NÃO vira dado. Antes, o erro era gravado no CSV
                # como se fosse uma fonte de tendência.
                failures.append({"keyword": keyword, "error": str(exc)})
                handle.add_event(
                    f"coleta de '{keyword}' falhou", level="WARNING", payload={"error": str(exc)}
                )
                continue

            summary = _summarize(frame)
            if summary["points"] == 0:
                failures.append({"keyword": keyword, "error": "série vazia retornada pela fonte"})
                continue

            record_observation(
                session,
                keyword=keyword,
                geo=options.geo,
                window_days=options.window_days,
                summary=summary,
                source_record_id=source.id,
                observed_at=collected_at,
            )
            observations.append({"keyword": keyword, "geo": options.geo, **summary})

        if failures:
            # Os avisos ficam no registro de procedência, onde são auditáveis.
            source.warnings = failures
            session.flush()

        # A leitura por IA recebe só os movimentos que têm série.
        interpretable = [item for item in observations if item.get("trend_direction")]
        interpretation = None
        if options.use_ai and interpretable:
            interpretation = interpret_with_ai(
                session, interpretable[: options.ai_keywords], ai=ai, handle=handle
            )

        rising = [item for item in observations if item.get("trend_direction") == "rising"]

        summary_text = (
            f"{len(observations)} keywords coletadas, {len(rising)} em alta, "
            f"{len(failures)} falhas de coleta"
        )
        if interpretation:
            summary_text += " | com leitura por IA"

        handle.add_event(summary_text)

        return TaskResult(
            task_id="trend_hunter",
            ok=True,
            summary=summary_text,
            artifacts={
                "job_id": handle.id,
                "persisted": True,
                "source_record_id": source.id,
                "observations": observations,
                "rising": [item["keyword"] for item in rising],
                "collect_failures": failures,
                "interpretation": interpretation,
            },
        )


def recent_observations(
    session: Session, *, hours: int = 48, limit: int = 200
) -> list[TrendObservation]:
    """Observações recentes, para o painel e para o agente de produto."""
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    return list(
        session.scalars(
            select(TrendObservation)
            .where(TrendObservation.observed_at >= cutoff)
            .order_by(desc(TrendObservation.observed_at))
            .limit(limit)
        )
    )


__all__ = [
    "DEFAULT_GEO",
    "DEFAULT_KEYWORDS",
    "DEFAULT_WINDOW_DAYS",
    "TrendOptions",
    "interpret_with_ai",
    "recent_observations",
    "record_observation",
    "run",
]
