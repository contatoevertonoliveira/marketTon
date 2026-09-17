"""Product Hunter — coleta, persiste e avalia produtos (briefing seções 4, 5 e 6).

Três mudanças em relação à versão anterior, e todas eram defeitos:

1. **Coletava para CSV e não persistia.** O resultado ia para
   `data/products/product_hunter_latest.csv` e sumia. Agora passa por
   `ingest_products`, que grava `source_records` + `products` com proveniência
   obrigatória e idempotência.

2. **O "score" era `preço + 20`.** Literalmente. Nos dados de exemplo, 79,9 virava
   99,9. Agora o score vem do motor versionado (`HEAT`, `OPPORTUNITY`), que
   persiste inputs, pesos, fórmula e versão.

3. **Filtrava por substring do keyword no título.** O adapter devolvia o catálogo
   inteiro e o agente comparava `"fone bluetooth" in title`, o que descartava
   silenciosamente produtos relevantes. Agora a busca é feita pelo próprio
   marketplace quando ele suporta (`search_competitor`), e o filtro é declarado.

A IA entra no fim: avalia os melhores candidatos e produz leitura qualitativa. Ela
não define score — recebe os scores prontos e interpreta.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from core.db.catalog import Product
from core.db.scoring import ScoreRun
from core.services.ai.client import AIClient
from core.services.ai.interpreter import run_interpretation
from core.services.ai.prompts import get_prompt
from core.services.ingestion import IngestStats, ingest_products
from core.services.jobs import JobHandle, job_run
from core.services.scoring.engine import active_spec, compute, load_specs, persist_run
from core.services.scoring_inputs import build_inputs
from core.tasks import TaskResult
from integrations.marketplaces.base import ConnectorBatch, MarketplaceAdapter

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

# Quantos candidatos passam pela avaliação de IA. Chamada de LLM custa tempo e
# dinheiro, então avaliamos os melhores por score, não o catálogo inteiro.
DEFAULT_AI_CANDIDATES = 5
# Quantos produtos entram no cálculo de score a cada execução.
DEFAULT_SCORE_LIMIT = 25


@dataclass
class HunterOptions:
    keywords: list[str] = field(default_factory=lambda: list(DEFAULT_KEYWORDS))
    adapter_names: list[str] = field(default_factory=list)
    max_items_per_adapter: int = 50
    score_limit: int = DEFAULT_SCORE_LIMIT
    ai_candidates: int = DEFAULT_AI_CANDIDATES
    use_ai: bool = True


def _adapter_fetch_options(name: str, options: HunterOptions) -> Any | None:
    """Monta as opções de coleta específicas do adapter a partir das keywords
    genéricas do agente.

    Cada marketplace tem seu próprio dataclass de opções (`MLAdapterOptions`,
    `AmazonAdapterOptions`, ...) porque cada API expõe uma forma diferente de
    busca. `None` significa "chamar `fetch_products` sem `options`" — o caso
    dos adapters que ainda coletam o catálogo da própria conta (Shopee,
    TikTok Shop), não descoberta por termo.
    """
    if name == "mercado_livre":
        from integrations.marketplaces.mercado_livre import MLAdapterOptions

        return MLAdapterOptions(keywords=list(options.keywords), max_items=options.max_items_per_adapter)
    if name == "amazon":
        from integrations.marketplaces.amazon import AmazonAdapterOptions

        # A PA-API aceita um termo por chamada; usa o primeiro da lista.
        keyword = options.keywords[0] if options.keywords else ""
        return AmazonAdapterOptions(keyword=keyword, max_items=min(options.max_items_per_adapter, 10))
    return None


def _collect_batches(
    adapters: dict[str, MarketplaceAdapter],
    options: HunterOptions,
    handle: JobHandle | None,
) -> tuple[list[ConnectorBatch], list[str]]:
    """Coleta de cada adapter. Falha de um não impede os outros."""
    batches: list[ConnectorBatch] = []
    errors: list[str] = []

    for name in options.adapter_names:
        adapter = adapters.get(name)
        if adapter is None:
            errors.append(f"adapter '{name}' não registrado")
            continue

        if not adapter.is_configured():
            # Não é erro: é ausência de credencial. Declaramos em vez de tratar
            # como catálogo vazio, que seria indistinguível de "sem produtos".
            errors.append(f"adapter '{name}' sem credencial configurada; não coletou")
            if handle:
                handle.add_event(
                    f"adapter '{name}' ignorado: sem credencial",
                    level="WARNING",
                    payload={"connector": name},
                )
            continue

        adapter_options = _adapter_fetch_options(name, options)

        try:
            if adapter_options is not None:
                batch = adapter.fetch_products(limit=options.max_items_per_adapter, options=adapter_options)
            else:
                batch = adapter.fetch_products(limit=options.max_items_per_adapter)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"adapter '{name}' falhou: {exc}")
            if handle:
                handle.add_event(
                    f"coleta em '{name}' falhou", level="ERROR", payload={"error": str(exc)}
                )
            continue

        batches.append(batch)
        if handle:
            handle.add_event(
                f"coletados {len(batch.products)} itens em '{name}'",
                payload={"connector": name, "warnings": batch.warnings[:5]},
            )

    return batches, errors


def _persist(
    session: Session,
    batches: list[ConnectorBatch],
    *,
    handle: JobHandle | None,
) -> dict[str, IngestStats]:
    """Persiste cada lote com proveniência. Isolado para ser testável sem rede.

    O marketplace vem do próprio adapter, não do nome do connector: é ele que
    conhece o domínio a que pertence. Um conector que coleta para outro
    marketplace continua gravando o valor correto.
    """
    from integrations.marketplaces.registry import resolve

    stats: dict[str, IngestStats] = {}

    for batch in batches:
        adapter = resolve(batch.connector)
        marketplace = adapter.name if adapter is not None else batch.connector

        try:
            result = ingest_products(session, batch, marketplace)
        except Exception as exc:  # noqa: BLE001
            logger.exception("ingestão de '%s' falhou", batch.connector)
            if handle:
                handle.add_event(
                    f"ingestão de '{batch.connector}' falhou",
                    level="ERROR",
                    payload={"error": str(exc)},
                )
            continue

        stats[batch.connector] = result
        if handle:
            handle.add_event(
                result.summary(),
                payload={
                    "created": result.created,
                    "updated": result.updated,
                    "unchanged": result.unchanged,
                    "skipped": result.skipped,
                    "warnings": result.warnings[:5],
                },
            )

    return stats


def _score_products(
    session: Session,
    *,
    limit: int,
    handle: JobHandle | None,
) -> list[dict[str, Any]]:
    """Calcula `HEAT` e `OPPORTUNITY` para os produtos ativos mais recentes.

    Devolve a lista ordenada por Opportunity Score. É o que substitui o antigo
    `preço + 20`: agora o número vem de fórmula versionada, com inputs e pesos
    persistidos.
    """
    load_specs()

    products = list(
        session.scalars(
            select(Product)
            .where(Product.is_active.is_(True))
            .order_by(desc(Product.last_seen_at))
            .limit(limit)
        )
    )
    scored: list[dict[str, Any]] = []

    for product in products:
        entry: dict[str, Any] = {
            "product_id": product.id,
            "title": product.title,
            "marketplace": product.marketplace.value,
            "price": product.price,
            "scores": {},
        }

        # HEAT primeiro: OPPORTUNITY o consome como insumo.
        for dimension in ("HEAT", "OPPORTUNITY"):
            try:
                inputs = build_inputs(
                    session, dimension=dimension, target_type="product", target_id=product.id
                )
                spec = active_spec(dimension)
                result = compute(spec, inputs)
                run = persist_run(
                    session,
                    spec=spec,
                    result=result,
                    target_type="product",
                    target_id=product.id,
                    marketplace=product.marketplace,
                )
                entry["scores"][dimension] = {
                    "score": result.score,
                    "status": result.status,
                    "confidence": result.confidence,
                    "run_id": run.id,
                }
            except Exception as exc:  # noqa: BLE001
                logger.warning("score %s do produto %s falhou: %s", dimension, product.id, exc)
                entry["scores"][dimension] = {"error": str(exc)}

        scored.append(entry)

    if handle:
        handle.add_event(f"score calculado para {len(scored)} produtos")

    scored.sort(
        key=lambda item: item["scores"].get("OPPORTUNITY", {}).get("score") or 0,
        reverse=True,
    )
    return scored


def evaluate_with_ai(
    session: Session,
    candidates: list[dict[str, Any]],
    *,
    ai: AIClient | None = None,
    handle: JobHandle | None = None,
) -> list[dict[str, Any]]:
    """Pede à IA uma avaliação qualitativa dos melhores candidatos.

    Os scores vão prontos no insumo e o prompt instrui explicitamente a não
    recalculá-los. Sem IA disponível, devolve lista vazia com o motivo registrado —
    o pipeline segue, porque a IA é enriquecimento, não dependência.
    """
    ai = ai or AIClient()
    evaluations: list[dict[str, Any]] = []

    for candidate in candidates:
        if not candidate.get("scores"):
            continue

        payload = {
            "produto": {
                "titulo": candidate["title"],
                "marketplace": candidate["marketplace"],
                "preco": candidate["price"],
            },
            "scores_calculados": candidate["scores"],
        }

        result = run_interpretation(
            session,
            ai=ai,
            agent="product_hunter",
            kind=_evaluation_kind(),
            prompt=get_prompt("product_evaluator"),
            inputs=payload,
            target_type="product",
            target_id=candidate["product_id"],
        )

        if not result.ok:
            if handle and result.skipped_reason:
                handle.add_event(
                    f"avaliação por IA indisponível: {result.skipped_reason}", level="WARNING"
                )
                # Uma vez registrado o motivo, não repete para cada candidato.
                break
            continue

        evaluations.append(
            {
                "product_id": candidate["product_id"],
                "title": candidate["title"],
                "verdict": (result.output or {}).get("verdict"),
                "reasons_for": (result.output or {}).get("reasons_for"),
                "reasons_against": (result.output or {}).get("reasons_against"),
                "angle_suggestion": (result.output or {}).get("angle_suggestion"),
                "interpretation_id": result.interpretation_id,
            }
        )

    return evaluations


def _evaluation_kind():
    from core.db.ai import AIInterpretationKind

    return AIInterpretationKind.PRODUCT_EVALUATION


def run(
    memory: dict,
    *,
    session: Session | None = None,
    adapters: dict[str, MarketplaceAdapter] | None = None,
    ai: AIClient | None = None,
    options: HunterOptions | None = None,
) -> TaskResult:
    """Execução como task do pipeline.

    Sem sessão de banco, declara a limitação em vez de escrever CSV e fingir que
    coletou: o CSV anterior era um beco sem saída que ninguém consumia.
    """
    options = options or HunterOptions()
    if not options.adapter_names:
        from integrations.marketplaces.registry import list_adapter_names

        options.adapter_names = list(memory.get("adapter_names") or list_adapter_names())
    if memory.get("keywords_product"):
        options.keywords = list(memory["keywords_product"])

    if session is None:
        return TaskResult(
            task_id="product_hunter",
            ok=True,
            summary=(
                "sem sessão de banco: nenhum produto persistido. "
                "O CSV anterior era beco sem saída; forneça uma sessão para gravar com proveniência."
            ),
            artifacts={"persisted": False, "adapter_names": options.adapter_names},
        )

    if adapters is None:
        from integrations.marketplaces.registry import load_adapters, resolve

        load_adapters()
        adapters = {name: resolve(name) for name in options.adapter_names}
        adapters = {name: adapter for name, adapter in adapters.items() if adapter is not None}

    with job_run(
        session,
        job_type="product_hunter.collect",
        agent="product_hunter",
        params={"adapters": options.adapter_names, "keywords": options.keywords[:5]},
    ) as handle:
        batches, errors = _collect_batches(adapters, options, handle)

        if not batches:
            # Sem coleta e sem erro seria indistinguível de "nada a fazer".
            if not errors:
                errors.append("nenhum adapter disponível para coleta")
            handle.add_event("nenhum lote coletado", level="WARNING", payload={"errors": errors})

        stats = _persist(session, batches, handle=handle)
        scored = _score_products(session, limit=options.score_limit, handle=handle)

        evaluations: list[dict[str, Any]] = []
        if options.use_ai and scored:
            evaluations = evaluate_with_ai(
                session, scored[: options.ai_candidates], ai=ai, handle=handle
            )

        total_created = sum(item.created for item in stats.values())
        total_updated = sum(item.updated for item in stats.values())
        summary = (
            f"{total_created} produtos novos, {total_updated} atualizados, "
            f"{len(scored)} pontuados, {len(evaluations)} avaliados por IA"
        )
        if errors:
            summary += f" | {len(errors)} adapter(s) sem coleta"

        handle.add_event(summary)

        return TaskResult(
            task_id="product_hunter",
            ok=True,
            summary=summary,
            artifacts={
                "job_id": handle.id,
                "persisted": True,
                "created": total_created,
                "updated": total_updated,
                "scored": scored[: options.score_limit],
                "evaluations": evaluations,
                "collect_errors": errors,
                # Avisos por lote (paginação interrompida, item ignorado, etc.) —
                # antes só apareciam nos eventos do job, invisíveis para quem só olha
                # o resultado da chamada (ex.: scripts/ingest.py).
                "collect_warnings": [warning for batch in batches for warning in batch.warnings],
            },
        )


__all__ = [
    "DEFAULT_AI_CANDIDATES",
    "DEFAULT_KEYWORDS",
    "HunterOptions",
    "evaluate_with_ai",
    "run",
]
