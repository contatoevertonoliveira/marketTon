"""Copy Chief — geração de copy com IA (briefing seções 5 e 8).

O que a versão anterior fazia: escolhia um entre 5 templates fixos com
`random.choice`, e o resultado dependia de uma flag de metodologia
(`must_have_case`) que **nunca era False** — então o ramo de templates diretos era
código morto e só saíam 4 variações quase idênticas para um produto fixo
("Negócio de 4 Rend").

Agora:

* a copy é gerada por IA a partir dos **dados reais do produto** (título, preço,
  desconto, comissão) e dos scores já calculados;
* cada geração é registrada em `ai_interpretations` com o prompt e os insumos, então
  a copy é rastreável até o dado que a originou;
* o material vira `CreativeAsset` do tipo `COPY`, em `PENDING`, para o pipeline de
  aprovação do briefing §8;
* sem IA disponível o agente **não inventa** copy com template: devolve vazio com o
  motivo. Template fixo apresentado como copy personalizada seria pior que nada.

A IA não define score. Ela recebe os scores prontos e escreve.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from core.db.base import CreativeAssetType, CreativeStatus
from core.db.catalog import Product
from core.db.creative import CreativeAsset, CreativeAssetEvent
from core.db.scoring import ScoreRun
from core.services.ai.client import AIClient
from core.services.ai.interpreter import run_interpretation
from core.services.ai.prompts import get_prompt
from core.services.jobs import JobHandle, job_run
from core.tasks import TaskResult

logger = logging.getLogger(__name__)

# Quantos produtos recebem copy por execução. Cada um é uma chamada de IA.
DEFAULT_COPY_BUDGET = 5


@dataclass
class CopyOptions:
    max_products: int = DEFAULT_COPY_BUDGET
    # Aproveitar apenas produtos que já têm score: gerar copy sem score seria
    # escrever sobre um produto que não sabemos se vale a pena.
    require_score: bool = True
    min_opportunity_score: float | None = None
    use_ai: bool = True


def _candidate_products(session: Session, options: CopyOptions) -> list[tuple[Product, dict[str, Any]]]:
    """Produtos que já têm Opportunity Score, ordenados do melhor para o pior.

    O score é o critério de priorização: escrever copy para o produto errado é
    desperdício de esforço criativo.
    """
    runs = session.scalars(
        select(ScoreRun)
        .where(
            ScoreRun.target_type == "product",
            ScoreRun.dimension == "OPPORTUNITY",
            ScoreRun.status == "SUCCEEDED",
        )
        .order_by(desc(ScoreRun.score))
        .limit(options.max_products * 4)
    ).all()

    candidates: list[tuple[Product, dict[str, Any]]] = []
    seen: set[int] = set()

    for run in runs:
        if run.target_id in seen:
            continue
        seen.add(run.target_id)

        if options.min_opportunity_score is not None and float(run.score) < options.min_opportunity_score:
            continue

        product = session.get(Product, run.target_id)
        if product is None or not product.is_active:
            continue

        candidates.append(
            (
                product,
                {
                    "opportunity_score": float(run.score),
                    "confidence": run.confidence,
                    "algorithm_version": run.algorithm_version,
                    "score_run_id": run.id,
                },
            )
        )
        if len(candidates) >= options.max_products:
            break

    if candidates or not options.require_score:
        return candidates

    # Sem score não há candidato. Se `require_score` fosse ignorado, geraríamos copy
    # para produtos arbitrários — o comportamento antigo, que escrevia sempre para
    # um produto fixo.
    return []


def _product_payload(product: Product, score: dict[str, Any]) -> dict[str, Any]:
    """Insumos entregues à IA. Só o que existe; o resto fica fora."""
    return {
        "titulo": product.title,
        "marketplace": product.marketplace.value,
        "preco": product.price,
        "preco_original": product.original_price,
        "desconto_pct": product.discount_pct,
        "comissao_afiliado_pct": product.affiliate_commission_pct,
        "nota": product.rating,
        "avaliacoes": product.review_count,
        "vendidos": product.sold_quantity,
        "marca": product.brand,
        "categoria": product.category_id,
        "url": product.product_url,
        "scores_calculados": score,
    }


def generate_brief_with_ai(
    session: Session,
    product: Product,
    score: dict[str, Any],
    *,
    ai: AIClient | None = None,
    handle: JobHandle | None = None,
    portfolio_item_id: int | None = None,
) -> dict[str, Any] | None:
    """Gera o briefing criativo e o registra como material do pipeline."""
    ai = ai or AIClient()
    payload = _product_payload(product, score)

    result = run_interpretation(
        session,
        ai=ai,
        agent="copy_chief",
        kind=_brief_kind(),
        prompt=get_prompt("creative_brief"),
        inputs=payload,
        target_type="product",
        target_id=product.id,
    )

    if not result.ok:
        if handle:
            handle.add_event(
                f"briefing indisponível para '{product.title}': "
                f"{result.skipped_reason or result.error}",
                level="WARNING",
            )
        return None

    output = result.output or {}
    asset = _create_copy_asset(
        session,
        product=product,
        output=output,
        interpretation_id=result.interpretation_id,
        portfolio_item_id=portfolio_item_id,
    )

    return {
        "product_id": product.id,
        "title": product.title,
        "asset_id": asset.id,
        "interpretation_id": result.interpretation_id,
        "hook": output.get("hook"),
        "narrative": output.get("narrative"),
        "cta": output.get("cta"),
        "target_audience": output.get("target_audience"),
        "visual_notes": output.get("visual_notes"),
        "claims_to_avoid": output.get("claims_to_avoid"),
    }


def _create_copy_asset(
    session: Session,
    *,
    product: Product,
    output: dict[str, Any],
    interpretation_id: int | None,
    portfolio_item_id: int | None = None,
) -> CreativeAsset:
    """Registra o briefing como `CreativeAsset` de COPY, em PENDING.

    Fica em PENDING de propósito: a IA escreveu, mas quem aprova é humano. O
    briefing §8 exige que APPROVAL seja um estado de primeira classe no portão de
    publicação.
    """
    now = datetime.now(UTC)

    # Conteúdo legível: o asset precisa ser útil fora do JSON.
    parts = []
    if output.get("hook"):
        parts.append(f"HOOK: {output['hook']}")
    if output.get("narrative"):
        parts.append(f"DESENVOLVIMENTO: {output['narrative']}")
    if output.get("cta"):
        parts.append(f"CTA: {output['cta']}")
    if output.get("target_audience"):
        parts.append(f"PÚBLICO: {output['target_audience']}")
    if output.get("visual_notes"):
        notes = output["visual_notes"]
        parts.append("CENAS: " + "; ".join(str(item) for item in notes))
    if output.get("claims_to_avoid"):
        avoid = output["claims_to_avoid"]
        parts.append("NÃO PROMETER: " + "; ".join(str(item) for item in avoid))

    # Versão nova a cada geração: uma copy nova não deve apagar o histórico da
    # anterior, e o portão de publicação considera sempre a versão mais recente.
    highest_version = session.scalar(
        select(func.max(CreativeAsset.version)).where(
            CreativeAsset.product_id == product.id,
            CreativeAsset.asset_type == CreativeAssetType.COPY,
        )
    )
    version = int(highest_version or 0) + 1

    asset = CreativeAsset(
        product_id=product.id,
        portfolio_item_id=portfolio_item_id,
        asset_type=CreativeAssetType.COPY,
        status=CreativeStatus.PENDING,
        status_changed_at=now,
        version=version,
        title=f"Briefing criativo — {product.title[:120]}",
        content_text="\n".join(parts) or None,
        content_metadata=output,
        # A rastreabilidade: a copy aponta para a interpretação que a produziu.
        external_system="ai:creative_brief" if interpretation_id else None,
        external_ref=str(interpretation_id) if interpretation_id else None,
    )
    session.add(asset)
    session.flush()

    session.add(
        CreativeAssetEvent(
            asset_id=asset.id,
            from_status=None,
            to_status=CreativeStatus.PENDING,
            occurred_at=now,
            actor="agent:copy_chief",
            note=f"briefing gerado por IA (interpretation {interpretation_id})",
        )
    )
    session.flush()
    return asset


def _brief_kind():
    from core.db.ai import AIInterpretationKind

    return AIInterpretationKind.CREATIVE_BRIEF


def run(
    memory: dict,
    *,
    session: Session | None = None,
    ai: AIClient | None = None,
    options: CopyOptions | None = None,
) -> TaskResult:
    """Execução como task do pipeline."""
    options = options or CopyOptions()

    if session is None:
        return TaskResult(
            task_id="copy_chief",
            ok=True,
            summary="sem sessão de banco: nenhuma copy gerada",
            artifacts={"generated": 0},
        )

    with job_run(
        session,
        job_type="copy_chief.generate",
        agent="copy_chief",
        params={"max_products": options.max_products, "require_score": options.require_score},
    ) as handle:
        candidates = _candidate_products(session, options)

        if not candidates:
            reason = (
                "nenhum produto com Opportunity Score calculado. "
                "Rode o product_hunter primeiro, ou use require_score=False para ignorar."
                if options.require_score
                else "nenhum produto ativo no catálogo"
            )
            handle.add_event(reason, level="WARNING")
            return TaskResult(
                task_id="copy_chief",
                ok=True,
                summary=reason,
                artifacts={"job_id": handle.id, "generated": 0, "briefs": []},
            )

        ai = ai or AIClient()
        if options.use_ai and not ai.is_available:
            # Sem IA não geramos template apresentado como copy personalizada.
            message = (
                "IA desligada ou sem credencial: nenhuma copy gerada. "
                "Template fixo não substitui copy baseada nos dados do produto."
            )
            handle.add_event(message, level="WARNING")
            return TaskResult(
                task_id="copy_chief",
                ok=True,
                summary=message,
                artifacts={"job_id": handle.id, "generated": 0, "candidates": len(candidates)},
            )

        briefs: list[dict[str, Any]] = []
        for product, score in candidates:
            brief = generate_brief_with_ai(
                session, product, score, ai=ai, handle=handle
            )
            if brief is not None:
                briefs.append(brief)

        summary = (
            f"{len(briefs)} briefing(s) gerado(s) para {len(candidates)} candidato(s) "
            f"com score"
        )
        handle.add_event(summary)

        return TaskResult(
            task_id="copy_chief",
            ok=True,
            summary=summary,
            artifacts={"job_id": handle.id, "generated": len(briefs), "briefs": briefs},
        )


__all__ = [
    "DEFAULT_COPY_BUDGET",
    "CopyOptions",
    "generate_brief_with_ai",
    "run",
]
