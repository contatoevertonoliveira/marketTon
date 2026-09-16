"""Serializadores: ORM → schema de resposta.

Ficam separados dos routers porque a conversão carrega regras próprias — enum para
valor, cálculo de transições permitidas, montagem de explicações — e porque assim
podem ser testados sem HTTP.

Ponto deliberado: **nada aqui inventa valor**. Campo ausente vira `None`. É a
aplicação da regra do briefing seção 2 na fronteira da API.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.schemas import (
    CreativeAssetOut,
    JobEventOut,
    JobOut,
    KpiOut,
    MetricPoint,
    PortfolioItemOut,
    PortfolioTransitionOut,
    PricePoint,
    ProductDetail,
    ProductSummary,
    RecommendationOut,
    ScoreContributionOut,
    ScoreExplanation,
    ScoreRunOut,
    SellerOut,
    SourceRecordOut,
)
from core.db.ai import AIInterpretation
from core.db.catalog import PriceHistory, Product, ProductMetric, SourceRecord
from core.db.creative import CreativeAsset
from core.db.jobs import Job, JobEvent
from core.db.portfolio import PortfolioItem, PortfolioTransition, Recommendation
from core.db.scoring import ScoreContribution, ScoreRun
from core.services.portfolio import allowed_targets, missing_assets_for_publish
from core.services.scoring.engine import get_spec


def enum_value(value: Any) -> Any:
    """Enum → valor string. Passa `None` adiante sem inventar."""
    if value is None:
        return None
    return value.value if hasattr(value, "value") else value


# --- Procedência --------------------------------------------------------------


def source_record_out(record: SourceRecord | None) -> SourceRecordOut | None:
    if record is None:
        return None
    return SourceRecordOut(
        id=record.id,
        marketplace=enum_value(record.marketplace),
        connector=record.connector,
        connector_kind=enum_value(record.connector_kind),
        endpoint=record.endpoint,
        external_id=record.external_id,
        collected_at=record.collected_at,
        reliability=record.reliability,
        warnings=record.warnings,
    )


def seller_out(seller) -> SellerOut | None:
    if seller is None:
        return None
    return SellerOut(
        id=seller.id,
        marketplace=enum_value(seller.marketplace),
        external_id=seller.external_id,
        nickname=seller.nickname,
        reputation_level=seller.reputation_level,
        reputation_score=seller.reputation_score,
        total_sales=seller.total_sales,
        positive_rating_pct=seller.positive_rating_pct,
        feedback_count=seller.feedback_count,
        is_official_store=seller.is_official_store,
        power_seller_status=seller.power_seller_status,
        last_seen_at=seller.last_seen_at,
    )


# --- Scoring ------------------------------------------------------------------


def contribution_out(contribution: ScoreContribution) -> ScoreContributionOut:
    return ScoreContributionOut(
        position=contribution.position,
        factor=contribution.factor,
        label=contribution.label,
        raw_value=contribution.raw_value,
        raw_unit=contribution.raw_unit,
        normalized_value=contribution.normalized_value,
        weight=contribution.weight,
        impact=float(contribution.impact),
        is_positive=contribution.is_positive,
        available=contribution.available,
        explanation=contribution.explanation,
    )


def _higher_score_is_better(dimension: str, version: str) -> bool:
    """Orientação do score, lida do algoritmo registrado em código.

    Necessário porque nem toda dimensão é "maior é melhor": o índice de saturação
    sobe quando o mercado piora. Sem esta informação a UI pintaria saturação alta
    de verde.
    """
    try:
        return get_spec(dimension, version).higher_score_is_better
    except KeyError:
        # Algoritmo não registrado nesta instalação: assume o caso comum.
        return True


def score_run_out(run: ScoreRun) -> ScoreRunOut:
    return ScoreRunOut(
        id=run.id,
        dimension=enum_value(run.dimension),
        algorithm_version=run.algorithm_version,
        formula=run.formula,
        score=float(run.score),
        confidence=run.confidence,
        is_complete=run.is_complete,
        status=enum_value(run.status),
        insufficient_reasons=run.insufficient_reasons,
        computed_at=run.computed_at,
        target_type=run.target_type,
        target_id=run.target_id,
        marketplace=enum_value(run.marketplace),
        higher_score_is_better=_higher_score_is_better(
            enum_value(run.dimension), run.algorithm_version
        ),
    )


def score_explanation(run: ScoreRun) -> ScoreExplanation:
    """Score com suas contribuições e a lista `+ motivo` / `- motivo`.

    A lista é derivada das contribuições ordenadas por impacto absoluto. É a
    resposta a "por que este produto foi recomendado?" (briefing seção 6).
    """
    base = score_run_out(run)
    contributions = sorted(run.contributions, key=lambda item: item.position)

    reasons: list[str] = []
    for contribution in sorted(contributions, key=lambda item: abs(float(item.impact)), reverse=True):
        if not contribution.available:
            continue
        sign = "+" if contribution.is_positive is not False else "-"
        text = contribution.explanation or contribution.label
        reasons.append(f"{sign} {text}")

    return ScoreExplanation(
        **base.model_dump(),
        weights=run.weights,
        contributions=[contribution_out(item) for item in contributions],
        reasons=reasons,
    )


def latest_scores_by_dimension(session: Session, product_ids: list[int]) -> dict[int, dict[str, float]]:
    """Score mais recente por (produto, dimensão).

    Feito em consulta única para não disparar N+1 na listagem.
    """
    if not product_ids:
        return {}

    rows = session.scalars(
        select(ScoreRun)
        .where(ScoreRun.target_type == "product", ScoreRun.target_id.in_(product_ids))
        .order_by(ScoreRun.target_id, ScoreRun.dimension, desc(ScoreRun.computed_at))
    ).all()

    result: dict[int, dict[str, float]] = {}
    seen: set[tuple[int, str]] = set()
    for run in rows:
        key = (run.target_id, enum_value(run.dimension))
        if key in seen:
            continue
        seen.add(key)
        result.setdefault(run.target_id, {})[key[1]] = float(run.score)
    return result


# --- Produto ------------------------------------------------------------------


def product_summary(product: Product, scores: dict[str, float] | None = None) -> ProductSummary:
    return ProductSummary(
        id=product.id,
        marketplace=enum_value(product.marketplace),
        external_id=product.external_id,
        title=product.title,
        brand=product.brand,
        category_id=product.category_id,
        currency=product.currency,
        price=product.price,
        original_price=product.original_price,
        discount_pct=product.discount_pct,
        affiliate_commission_pct=product.affiliate_commission_pct,
        rating=product.rating,
        review_count=product.review_count,
        available_quantity=product.available_quantity,
        sold_quantity=product.sold_quantity,
        is_active=product.is_active,
        first_seen_at=product.first_seen_at,
        last_seen_at=product.last_seen_at,
        scores=scores or {},
    )


def price_point(history: PriceHistory) -> PricePoint:
    return PricePoint(
        observed_at=history.observed_at,
        price=history.price,
        original_price=history.original_price,
        discount_pct=history.discount_pct,
        currency=history.currency,
        available_quantity=history.available_quantity,
        is_available=history.is_available,
    )


def metric_point(metric: ProductMetric) -> MetricPoint:
    return MetricPoint(
        observed_at=metric.observed_at,
        sold_last_period=metric.sold_last_period,
        visits=metric.visits,
        views=metric.views,
        wishlist_count=metric.wishlist_count,
        review_count=metric.review_count,
        rating=metric.rating,
        sales_rank=metric.sales_rank,
    )


def product_detail(
    session: Session,
    product: Product,
    *,
    price_limit: int = 90,
    metric_limit: int = 90,
) -> ProductDetail:
    runs = session.scalars(
        select(ScoreRun)
        .where(ScoreRun.target_type == "product", ScoreRun.target_id == product.id)
        .order_by(desc(ScoreRun.computed_at))
    ).all()

    # Só a execução mais recente por dimensão, para não repetir histórico inteiro.
    seen: set[str] = set()
    explanations: list[ScoreExplanation] = []
    scores: dict[str, float] = {}
    for run in runs:
        dimension = enum_value(run.dimension)
        if dimension in seen:
            continue
        seen.add(dimension)
        scores[dimension] = float(run.score)
        explanations.append(score_explanation(run))

    history = session.scalars(
        select(PriceHistory)
        .where(PriceHistory.product_id == product.id)
        .order_by(desc(PriceHistory.observed_at))
        .limit(price_limit)
    ).all()

    metrics = session.scalars(
        select(ProductMetric)
        .where(ProductMetric.product_id == product.id)
        .order_by(desc(ProductMetric.observed_at))
        .limit(metric_limit)
    ).all()

    summary = product_summary(product, scores)
    return ProductDetail(
        **summary.model_dump(),
        seller=seller_out(product.seller),
        source_record=source_record_out(product.source_record),
        model=product.model,
        condition=product.condition,
        category_path=product.category_path,
        affiliate_commission_fixed=product.affiliate_commission_fixed,
        is_available=product.is_available,
        ranking_position=product.ranking_position,
        popularity_score=product.popularity_score,
        has_promotion=product.has_promotion,
        coupons=product.coupons,
        product_url=product.product_url,
        affiliate_url=product.affiliate_url,
        images=product.images,
        attributes=product.attributes,
        identity_key=product.identity_key,
        # Ordem cronológica para o gráfico: mais antigo primeiro.
        price_history=[price_point(item) for item in reversed(history)],
        metrics_history=[metric_point(item) for item in reversed(metrics)],
        score_explanations=explanations,
    )


# --- Criativos ----------------------------------------------------------------


def creative_asset_out(asset: CreativeAsset) -> CreativeAssetOut:
    return CreativeAssetOut(
        id=asset.id,
        portfolio_item_id=asset.portfolio_item_id,
        product_id=asset.product_id,
        asset_type=enum_value(asset.asset_type),
        status=enum_value(asset.status),
        version=asset.version,
        status_changed_at=asset.status_changed_at,
        title=asset.title,
        content_text=asset.content_text,
        content_url=asset.content_url,
        external_system=asset.external_system,
        external_ref=asset.external_ref,
        approved_by=asset.approved_by,
        approved_at=asset.approved_at,
        blocked_reason=asset.blocked_reason,
        rejection_reason=asset.rejection_reason,
    )


# --- Portfólio ----------------------------------------------------------------


def recommendation_out(recommendation: Recommendation) -> RecommendationOut:
    return RecommendationOut(
        id=recommendation.id,
        kind=enum_value(recommendation.kind),
        dimension=enum_value(recommendation.dimension),
        title=recommendation.title,
        rationale=recommendation.rationale,
        positive_factors=recommendation.positive_factors,
        negative_factors=recommendation.negative_factors,
        priority=recommendation.priority,
        confidence=recommendation.confidence,
        is_actioned=recommendation.is_actioned,
        actioned_at=recommendation.actioned_at,
        outcome=recommendation.outcome,
    )


def transition_out(transition: PortfolioTransition) -> PortfolioTransitionOut:
    return PortfolioTransitionOut(
        id=transition.id,
        from_state=enum_value(transition.from_state),
        to_state=enum_value(transition.to_state),
        occurred_at=transition.occurred_at,
        actor=transition.actor,
        reason=transition.reason,
        triggered_by_recommendation_id=transition.triggered_by_recommendation_id,
    )


def portfolio_item_out(session: Session, item: PortfolioItem) -> PortfolioItemOut:
    """Serializa o item, incluindo o que o operador pode fazer a seguir.

    `allowed_transitions` e `missing_assets_for_publish` vêm do backend para que o
    frontend nunca precise conhecer a máquina de estados (briefing seção 13).
    """
    return PortfolioItemOut(
        id=item.id,
        product_id=item.product_id,
        marketplace=enum_value(item.marketplace),
        label=item.label,
        state=enum_value(item.state),
        state_changed_at=item.state_changed_at,
        entry_score=float(item.entry_score) if item.entry_score is not None else None,
        added_by=item.added_by,
        notes=item.notes,
        revenue_total=item.revenue_total,
        commission_total=item.commission_total,
        clicks_total=item.clicks_total,
        conversions_total=item.conversions_total,
        last_metrics_at=item.last_metrics_at,
        paused_reason=item.paused_reason,
        removed_reason=item.removed_reason,
        removed_at=item.removed_at,
        allowed_transitions=allowed_targets(item.state),
        missing_assets_for_publish=missing_assets_for_publish(session, item),
    )


# --- Jobs ---------------------------------------------------------------------


def job_out(job: Job) -> JobOut:
    return JobOut(
        id=job.id,
        job_type=job.job_type,
        agent=job.agent,
        status=enum_value(job.status),
        started_at=job.started_at,
        finished_at=job.finished_at,
        duration_seconds=job.duration_seconds,
        progress_pct=job.progress_pct,
        result_summary=job.result_summary,
        error_type=job.error_type,
        error_message=job.error_message,
        attempt=job.attempt,
        triggered_by=job.triggered_by,
    )


def job_event_out(event: JobEvent) -> JobEventOut:
    return JobEventOut(
        id=event.id,
        occurred_at=event.occurred_at,
        level=event.level,
        message=event.message,
        payload=event.payload,
    )


# --- IA -----------------------------------------------------------------------


def ai_interpretation_summary(record: AIInterpretation) -> dict[str, Any]:
    """Resumo de uma interpretação de IA, para inspeção no painel."""
    return {
        "id": record.id,
        "agent": record.agent,
        "kind": enum_value(record.kind),
        "prompt": f"{record.prompt_key}:{record.prompt_version}",
        "model": record.model,
        "parse_ok": record.parse_ok,
        "error_message": record.error_message,
        "output": record.output,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


# --- KPIs ---------------------------------------------------------------------


def kpi_out(snapshot) -> KpiOut:
    """`KpiSnapshot` → schema. `None` permanece `None`."""
    return KpiOut(**snapshot.to_dict())


__all__ = [
    "ai_interpretation_summary",
    "contribution_out",
    "creative_asset_out",
    "enum_value",
    "job_event_out",
    "job_out",
    "kpi_out",
    "latest_scores_by_dimension",
    "portfolio_item_out",
    "price_point",
    "product_detail",
    "product_summary",
    "recommendation_out",
    "score_explanation",
    "score_run_out",
    "seller_out",
    "source_record_out",
    "transition_out",
]
