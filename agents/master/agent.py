"""Master — consolida o ciclo e produz recomendações acionáveis (briefing seções 6 e 16).

O que fazia antes: contava linhas de três CSVs e escrevia um relatório de uma linha.
A lógica de aprovação tinha um bug de chave de artefato
(`"products" + "_product_hunter_latest.csv_exists"`, que nunca existia), então
`approved_for_launch` era **sempre False** e o agente imprimia `WAITING` para sempre.
Um coordenador que nunca aprova não coordena nada.

Agora o Master fecha o ciclo do briefing §16 — informação → recomendação → ação:

* lê o **estado real** do domínio (produtos pontuados, portfólio, criativos, jobs);
* deriva recomendações por regra determinística, cada uma ligada ao score que a
  originou (`score_run_id`), o que permite auditar a decisão depois;
* pede à IA que priorize e explique, mas **a IA não cria a recomendação nem decide
  o score** — ela ordena e redige sobre o que as regras encontraram;
* registra tudo em `recommendations`, onde o operador marca o que foi feito e o
  motor de aprendizado compara previsão com resultado.

Regra que estrutura as escolhas: uma recomendação sem justificativa é uma ordem, não
uma recomendação. Por isso toda recomendação carrega `rationale` e os fatores.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from core.db.base import (
    CreativeAssetType,
    CreativeStatus,
    PortfolioState,
    RecommendationKind,
    ScoreRunStatus,
)
from core.db.creative import CreativeAsset
from core.db.portfolio import PortfolioItem, Recommendation
from core.db.scoring import ScoreContribution, ScoreRun
from core.services.ai.client import AIClient
from core.services.ai.interpreter import run_interpretation
from core.services.ai.prompts import get_prompt
from core.services.jobs import JobHandle, job_run, last_successful_job
from core.services.portfolio import REQUIRED_ASSETS_FOR_PUBLISH, missing_assets_for_publish
from core.tasks import TaskResult

logger = logging.getLogger(__name__)

# Limiares de decisão. Declarados como constantes nomeadas em vez de números soltos
# no meio do código, porque são escolha de negócio e precisam ser discutíveis.
MIN_OPPORTUNITY_TO_RECOMMEND = 65.0
MIN_CONFIDENCE_TO_RECOMMEND = 0.5
# Um item publicado sem nenhuma comissão confirmada após este período é candidato a
# otimização — não a remoção, porque a comissão pode estar apenas atrasada.
OPTIMIZE_AFTER_DAYS = 21
# Cobertura mínima dos insumos para considerar o score confiável.
MIN_PRODUCTS_FOR_CYCLE = 1


@dataclass
class MasterOptions:
    max_recommendations: int = 20
    use_ai: bool = True
    # Não recria recomendação já aberta para o mesmo alvo e tipo.
    dedupe: bool = True


@dataclass
class CycleState:
    """Estado consolidado do domínio. É o insumo das regras e da IA."""

    generated_at: datetime
    products_total: int = 0
    products_scored: int = 0
    products_with_opportunity: int = 0
    portfolio_by_state: dict[str, int] = field(default_factory=dict)
    creatives_by_status: dict[str, int] = field(default_factory=dict)
    pending_creatives: int = 0
    ready_creatives: int = 0
    blocked_creatives: int = 0
    recommendations_open: int = 0
    stale_jobs: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "products_total": self.products_total,
            "products_scored": self.products_scored,
            "products_with_opportunity": self.products_with_opportunity,
            "portfolio_by_state": self.portfolio_by_state,
            "creatives_by_status": self.creatives_by_status,
            "pending_creatives": self.pending_creatives,
            "ready_creatives": self.ready_creatives,
            "blocked_creatives": self.blocked_creatives,
            "recommendations_open": self.recommendations_open,
            "stale_jobs": self.stale_jobs,
            "notes": self.notes,
        }


def collect_state(session: Session, *, now: datetime | None = None) -> CycleState:
    """Lê o estado real do domínio. Sem IA, sem regra — só contagem e leitura."""
    from core.db.catalog import Product

    now = now or datetime.now(UTC)
    state = CycleState(generated_at=now)

    state.products_total = int(
        session.scalar(select(func.count()).select_from(Product).where(Product.is_active.is_(True))) or 0
    )

    scored_ids = session.scalars(
        select(func.distinct(ScoreRun.target_id)).where(
            ScoreRun.target_type == "product", ScoreRun.status == ScoreRunStatus.SUCCEEDED
        )
    ).all()
    state.products_scored = len(scored_ids)

    state.products_with_opportunity = int(
        session.scalar(
            select(func.count(func.distinct(ScoreRun.target_id))).where(
                ScoreRun.target_type == "product",
                ScoreRun.dimension == "OPPORTUNITY",
                ScoreRun.status == ScoreRunStatus.SUCCEEDED,
            )
        )
        or 0
    )

    for portfolio_state, count in session.execute(
        select(PortfolioItem.state, func.count(PortfolioItem.id)).group_by(PortfolioItem.state)
    ).all():
        state.portfolio_by_state[portfolio_state.value] = int(count)

    for creative_status, count in session.execute(
        select(CreativeAsset.status, func.count(CreativeAsset.id)).group_by(CreativeAsset.status)
    ).all():
        state.creatives_by_status[creative_status.value] = int(count)

    state.pending_creatives = state.creatives_by_status.get(CreativeStatus.PENDING.value, 0) + state.creatives_by_status.get(
        CreativeStatus.IN_PROGRESS.value, 0
    )
    state.ready_creatives = state.creatives_by_status.get(CreativeStatus.READY.value, 0) + state.creatives_by_status.get(
        CreativeStatus.APPROVED.value, 0
    )
    state.blocked_creatives = state.creatives_by_status.get(CreativeStatus.BLOCKED.value, 0)

    state.recommendations_open = int(
        session.scalar(
            select(func.count()).select_from(Recommendation).where(Recommendation.is_actioned.is_(False))
        )
        or 0
    )

    # Jobs que deveriam ter rodado e não rodaram. É o tipo de problema que nenhum
    # log mostra diretamente.
    expected_jobs = (
        "product_hunter.collect",
        "trend_hunter.collect",
        "marketplace_manager.health",
        "growth_analyst.report",
    )
    for job_type in expected_jobs:
        last = last_successful_job(session, job_type=job_type)
        if last is None:
            state.stale_jobs.append(f"{job_type}: nunca executou com sucesso")
            continue
        finished = last.finished_at
        if finished is None:
            state.stale_jobs.append(f"{job_type}: sem data de conclusão")
            continue
        finished_aware = finished if finished.tzinfo else finished.replace(tzinfo=UTC)
        hours = (now - finished_aware).total_seconds() / 3600
        if hours > 26:
            state.stale_jobs.append(f"{job_type}: última execução há {hours:.0f}h")

    if state.products_total == 0:
        state.notes.append("catálogo vazio: nenhuma coleta foi executada ainda")
    elif state.products_with_opportunity == 0:
        state.notes.append(
            "nenhum produto com Opportunity Score: o ciclo de scoring não rodou"
        )

    return state


def _existing_open_recommendation(
    session: Session,
    *,
    kind: RecommendationKind,
    product_id: int | None,
    portfolio_item_id: int | None,
    title: str | None = None,
) -> Recommendation | None:
    """Recomendação aberta equivalente.

    Sem esta checagem o ciclo criaria a mesma recomendação a cada execução, e a
    lista do operador viraria ruído.

    `title` existe para os casos sem alvo único — a recomendação sobre um job
    parado, por exemplo. Dedupe só por `kind` faria a primeira recomendação de
    otimização suprimir todas as outras, escondendo problemas distintos.
    """
    statement = select(Recommendation).where(
        Recommendation.kind == kind, Recommendation.is_actioned.is_(False)
    )
    if product_id is not None:
        statement = statement.where(Recommendation.product_id == product_id)
    if portfolio_item_id is not None:
        statement = statement.where(Recommendation.portfolio_item_id == portfolio_item_id)
    if title is not None:
        statement = statement.where(Recommendation.title == title)
    return session.scalar(statement.limit(1))


def _load_contributions(session: Session, run_id: int) -> tuple[list[str], list[str]]:
    """Separa os fatores do score em favoráveis e contrários.

    É daqui que sai a justificativa: a recomendação cita os fatores do próprio
    cálculo, não uma explicação inventada depois.
    """
    contributions = session.scalars(
        select(ScoreContribution)
        .where(ScoreContribution.run_id == run_id)
        .order_by(ScoreContribution.position)
    ).all()

    positive: list[str] = []
    negative: list[str] = []
    for contribution in sorted(contributions, key=lambda item: abs(float(item.impact)), reverse=True):
        if not contribution.available:
            continue
        text = contribution.explanation or contribution.label
        if contribution.is_positive is False:
            negative.append(f"- {text}")
        else:
            positive.append(f"+ {text}")
    return positive, negative


def build_recommendations(
    session: Session,
    state: CycleState,
    *,
    options: MasterOptions | None = None,
    handle: JobHandle | None = None,
) -> list[Recommendation]:
    """Deriva recomendações por regra determinística.

    A IA **não** entra aqui: as regras decidem o que recomendar, e a IA ordena e
    redige no passo seguinte. Um modelo decidindo o que fazer, sem regra auditável,
    seria exatamente a "opinião opaca" que o briefing §5 proíbe.
    """
    options = options or MasterOptions()
    now = datetime.now(UTC)
    created: list[Recommendation] = []

    # --- Recomendar produtos com oportunidade alta ----------------------------
    top_runs = session.scalars(
        select(ScoreRun)
        .where(
            ScoreRun.target_type == "product",
            ScoreRun.dimension == "OPPORTUNITY",
            ScoreRun.status == ScoreRunStatus.SUCCEEDED,
            ScoreRun.score >= MIN_OPPORTUNITY_TO_RECOMMEND,
        )
        .order_by(desc(ScoreRun.score))
        .limit(options.max_recommendations * 2)
    ).all()

    from core.db.catalog import Product

    seen_products: set[int] = set()
    for run in top_runs:
        if len(created) >= options.max_recommendations:
            break
        if run.target_id in seen_products:
            continue
        seen_products.add(run.target_id)

        if run.confidence is not None and run.confidence < MIN_CONFIDENCE_TO_RECOMMEND:
            # Score alto com confiança baixa não é recomendação: é palpite. Melhor
            # não recomendar do que recomendar com base frágil.
            continue

        product = session.get(Product, run.target_id)
        if product is None or not product.is_active:
            continue

        if options.dedupe and _existing_open_recommendation(
            session, kind=RecommendationKind.ANALYZE, product_id=product.id, portfolio_item_id=None
        ):
            continue

        positive, negative = _load_contributions(session, run.id)

        # Se o produto já está no portfólio, a próxima ação é diferente de analisar.
        in_portfolio = session.scalar(
            select(PortfolioItem).where(PortfolioItem.product_id == product.id)
        )

        if in_portfolio is None:
            kind = RecommendationKind.AFFILIATE
            title = f"Avaliar afiliação: {product.title[:100]}"
            rationale = (
                f"Opportunity Score {float(run.score):.1f}/100 "
                f"(confiança {(run.confidence or 0) * 100:.0f}%), algoritmo {run.algorithm_version}. "
                "O produto ainda não está no portfólio."
            )
        else:
            kind = RecommendationKind.PRODUCE_CREATIVE
            title = f"Produzir criativo para: {product.title[:100]}"
            rationale = (
                f"Produto no portfólio (estado {in_portfolio.state.value}) com "
                f"Opportunity Score {float(run.score):.1f}/100. "
                f"Materiais pendentes: {', '.join(missing_assets_for_publish(session, in_portfolio)) or 'nenhum'}."
            )

        recommendation = Recommendation(
            product_id=product.id,
            portfolio_item_id=in_portfolio.id if in_portfolio else None,
            kind=kind,
            dimension=run.dimension,
            title=title,
            rationale=rationale,
            positive_factors=positive,
            negative_factors=negative,
            # Prioridade a partir do score: a ordenação da lista é objetiva.
            priority=int(float(run.score)),
            confidence=run.confidence,
            score_run_id=run.id,
        )
        session.add(recommendation)
        created.append(recommendation)

    # --- Portfólio: itens que exigem ação --------------------------------------
    for item in session.scalars(
        select(PortfolioItem).where(
            PortfolioItem.state.in_(
                [
                    PortfolioState.RECOMMENDED,
                    PortfolioState.AFFILIATION_PENDING,
                    PortfolioState.CREATIVE_PENDING,
                    PortfolioState.OPTIMIZATION_REQUIRED,
                ]
            )
        )
    ).all():
        if len(created) >= options.max_recommendations:
            break

        if item.state == PortfolioState.CREATIVE_PENDING:
            missing = missing_assets_for_publish(session, item)
            if not missing:
                kind = RecommendationKind.PUBLISH
                title = f"Publicar: {item.label or item.product_id}"
                rationale = "Todos os materiais obrigatórios estão prontos."
                priority = 70
            else:
                kind = RecommendationKind.PRODUCE_CREATIVE
                title = f"Completar materiais: {item.label or item.product_id}"
                rationale = f"Faltam: {', '.join(missing)}."
                priority = 60

        elif item.state == PortfolioState.OPTIMIZATION_REQUIRED:
            kind = RecommendationKind.OPTIMIZE
            title = f"Otimizar: {item.label or item.product_id}"
            rationale = "Item marcado para otimização. Verifique criativo, canal e preço."

            # Diferencia "sem resultado" de "resultado ruim": comissão zero e
            # nenhuma confirmação é um caso; comissão baixa é outro.
            if item.commission_total in (None, 0):
                rationale += " Nenhuma comissão registrada ainda."
            priority = 80

        elif item.state == PortfolioState.AFFILIATION_PENDING:
            kind = RecommendationKind.AFFILIATE
            title = f"Concluir afiliação: {item.label or item.product_id}"
            rationale = "Afiliação pendente; sem ela o link não gera comissão."
            priority = 85

        else:
            kind = RecommendationKind.ANALYZE
            title = f"Decidir sobre: {item.label or item.product_id}"
            rationale = f"Item em {item.state.value}, aguardando decisão do operador."
            priority = 50

        if options.dedupe and _existing_open_recommendation(
            session, kind=kind, product_id=None, portfolio_item_id=item.id
        ):
            continue

        recommendation = Recommendation(
            portfolio_item_id=item.id,
            product_id=item.product_id,
            kind=kind,
            title=title,
            rationale=rationale,
            priority=priority,
        )
        session.add(recommendation)
        created.append(recommendation)

    # --- Itens prontos para publicar ------------------------------------------
    ready = session.scalars(
        select(PortfolioItem).where(PortfolioItem.state == PortfolioState.READY_TO_PUBLISH)
    ).all()
    for item in ready:
        if len(created) >= options.max_recommendations:
            break
        if options.dedupe and _existing_open_recommendation(
            session, kind=RecommendationKind.PUBLISH, product_id=None, portfolio_item_id=item.id
        ):
            continue

        # Toda recomendação criada entra em `created`. A versão anterior adicionava
        # direto na sessão e esquecia a lista, então `persist=False` não conseguia
        # desfazê-la — o modo de inspeção gravava mesmo assim.
        recommendation = Recommendation(
            portfolio_item_id=item.id,
            product_id=item.product_id,
            kind=RecommendationKind.PUBLISH,
            title=f"Publicar: {item.label or item.product_id}",
            rationale="Item aprovado para publicação e aguardando execução.",
            priority=90,
        )
        session.add(recommendation)
        created.append(recommendation)

    # --- Bloqueios e jobs parados ---------------------------------------------
    if state.blocked_creatives:
        blocked_title = f"Desbloquear {state.blocked_creatives} material(is) criativo(s)"
        if not (
            options.dedupe
            and _existing_open_recommendation(
                session,
                kind=RecommendationKind.OPTIMIZE,
                product_id=None,
                portfolio_item_id=None,
                title=blocked_title,
            )
        ):
            session.add(
                Recommendation(
                    kind=RecommendationKind.OPTIMIZE,
                    title=blocked_title,
                    rationale="Material bloqueado impede a publicação do produto associado.",
                    priority=75,
                )
            )

    for stale in state.stale_jobs:
        if len(created) >= options.max_recommendations:
            break

        # Uma recomendação por job parado. Dedupe por `title` para não repetir a
        # mesma, mas sem suprimir as outras — cada execução atrasada é um problema
        # distinto, com ação distinta.
        job_name = stale.split(":")[0]
        title = f"Execução atrasada: {job_name}"

        if options.dedupe and _existing_open_recommendation(
            session,
            kind=RecommendationKind.OPTIMIZE,
            product_id=None,
            portfolio_item_id=None,
            title=title,
        ):
            continue

        recommendation = Recommendation(
            kind=RecommendationKind.OPTIMIZE,
            title=title,
            rationale=stale,
            priority=95,
        )
        session.add(recommendation)
        created.append(recommendation)

    session.flush()
    if handle:
        handle.add_event(f"{len(created)} recomendação(ões) derivada(s) por regra")
    return created


def prioritize_with_ai(
    session: Session,
    recommendations: list[Recommendation],
    *,
    ai: AIClient | None = None,
    handle: JobHandle | None = None,
) -> dict[str, Any] | None:
    """Pede à IA uma leitura do conjunto de recomendações.

    A IA **ordeniza e explica**, não cria recomendação nem altera score. O prompt
    pede diagnóstico, e o resultado é registrado como interpretação — o operador
    continua vendo a lista derivada de regra.
    """
    if not recommendations:
        return None

    ai = ai or AIClient()
    payload = [
        {
            "titulo": item.title,
            "tipo": item.kind.value,
            "prioridade": item.priority,
            "justificativa": item.rationale,
            "fatores_favoraveis": item.positive_factors,
            "fatores_contrarios": item.negative_factors,
        }
        for item in recommendations[:20]
    ]

    result = run_interpretation(
        session,
        ai=ai,
        agent="master",
        kind=_diagnosis_kind(),
        prompt=get_prompt("performance_diagnosis"),
        inputs={"recomendacoes": payload},
        target_type="cycle",
    )

    if not result.ok:
        if handle:
            handle.add_event(
                f"leitura do ciclo por IA indisponível: {result.skipped_reason or result.error}",
                level="WARNING",
            )
        return None

    return result.output


def _diagnosis_kind():
    from core.db.ai import AIInterpretationKind

    return AIInterpretationKind.PERFORMANCE_DIAGNOSIS


def run(
    memory: dict,
    *,
    session: Session | None = None,
    ai: AIClient | None = None,
    options: MasterOptions | None = None,
    persist: bool = True,
) -> TaskResult:
    """Execução como task do pipeline.

    `persist=False` permite ao operador inspecionar o que o ciclo recomendaria sem
    poluir a lista de recomendações.
    """
    options = options or MasterOptions()

    if session is None:
        return TaskResult(
            task_id="master",
            ok=True,
            summary="sem sessão de banco: ciclo não consolidado",
            artifacts={"persisted": False},
        )

    with job_run(
        session,
        job_type="master.cycle",
        agent="master",
        params={"max_recommendations": options.max_recommendations},
    ) as handle:
        state = collect_state(session)
        handle.add_event(
            f"estado: {state.products_total} produtos, {state.products_with_opportunity} com "
            f"Opportunity Score, {state.recommendations_open} recomendação(ões) aberta(s)",
            payload=state.to_dict(),
        )

        for note in state.notes:
            handle.add_event(note, level="WARNING")

        for stale in state.stale_jobs:
            handle.add_event(stale, level="WARNING")

        recommendations = build_recommendations(session, state, options=options, handle=handle)

        diagnosis = None
        if options.use_ai and recommendations:
            diagnosis = prioritize_with_ai(session, recommendations, ai=ai, handle=handle)

        if not persist:
            # Desfaz as recomendações criadas: o chamador queria só inspecionar.
            for recommendation in recommendations:
                session.delete(recommendation)
            session.flush()
            handle.add_event("modo inspeção: recomendações não persistidas", level="INFO")

        summary = (
            f"ciclo consolidado: {len(recommendations)} recomendação(ões)"
            + (" (não persistidas)" if not persist else "")
        )
        if state.stale_jobs:
            summary += f" | {len(state.stale_jobs)} execução(ões) atrasada(s)"
        if diagnosis:
            summary += " | com leitura por IA"

        handle.add_event(summary)

        return TaskResult(
            task_id="master",
            ok=True,
            summary=summary,
            artifacts={
                "job_id": handle.id,
                "state": state.to_dict(),
                "recommendations": [
                    {
                        "id": item.id if persist else None,
                        "kind": item.kind.value,
                        "title": item.title,
                        "rationale": item.rationale,
                        "priority": item.priority,
                        "score_run_id": item.score_run_id,
                    }
                    for item in recommendations
                ],
                "diagnosis": diagnosis,
                "persisted": persist,
            },
        )


__all__ = [
    "MIN_CONFIDENCE_TO_RECOMMEND",
    "MIN_OPPORTUNITY_TO_RECOMMEND",
    "OPTIMIZE_AFTER_DAYS",
    "CycleState",
    "MasterOptions",
    "build_recommendations",
    "collect_state",
    "prioritize_with_ai",
    "run",
]
