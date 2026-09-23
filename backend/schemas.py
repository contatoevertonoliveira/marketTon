"""Schemas de resposta da API.

Regra que atravessa todos eles: campo sem dado é `None`, nunca `0`. O briefing
seção 2 proíbe estimativa silenciosa, e a API é onde essa regra fica visível para
quem consome — um `null` em `affiliate_commission_pct` diz "a fonte não informa",
enquanto `0` diria "a comissão é zero", que é uma afirmação diferente e falsa.

Por isso os campos numéricos de mercado são `float | None` e não têm default.

Os modelos estão declarados na ordem de dependência, sem referências para frente,
para que nenhum precise de `model_rebuild`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# --- Procedência --------------------------------------------------------------


class SourceRecordOut(BaseModel):
    """Origem de um dado. Sem isto, um produto é um número sem procedência."""

    id: int
    marketplace: str
    connector: str
    connector_kind: str
    endpoint: str | None = None
    external_id: str | None = None
    collected_at: datetime
    reliability: float
    warnings: list[Any] | None = None


# --- Vendedor -----------------------------------------------------------------


class SellerOut(BaseModel):
    id: int
    marketplace: str
    external_id: str
    nickname: str | None = None
    reputation_level: str | None = None
    reputation_score: float | None = None
    total_sales: int | None = None
    positive_rating_pct: float | None = None
    feedback_count: int | None = None
    is_official_store: bool | None = None
    power_seller_status: str | None = None
    last_seen_at: datetime | None = None


# --- Scoring ------------------------------------------------------------------


class ScoreContributionOut(BaseModel):
    """Um fator do cálculo. É a explicação propriamente dita."""

    position: int
    factor: str
    label: str
    raw_value: float | None = None
    raw_unit: str | None = None
    normalized_value: float | None = None
    weight: float | None = None
    impact: float
    is_positive: bool | None = None
    available: bool
    explanation: str | None = None


class ScoreRunOut(BaseModel):
    """Um cálculo de score, com tudo que o torna auditável."""

    id: int
    dimension: str
    algorithm_version: str
    formula: str | None = None
    score: float
    confidence: float | None = None
    is_complete: bool
    status: str
    insufficient_reasons: list[str] | None = None
    computed_at: datetime
    target_type: str
    target_id: int
    marketplace: str | None = None
    # Orientação do score. Falso quando maior significa pior (índice de saturação).
    higher_score_is_better: bool = True


class ScoreExplanation(ScoreRunOut):
    """Score + os motivos. Responde "por que este produto foi recomendado?".

    `reasons` é a forma pronta para exibição, no formato do briefing seção 6
    (`+ motivo` / `- motivo`), derivada das contribuições ordenadas por impacto —
    não é texto gerado à parte, é a própria aritmética do score apresentada.
    """

    weights: dict[str, Any] | None = None
    contributions: list[ScoreContributionOut] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class ScoreAlgorithmOut(BaseModel):
    id: int
    dimension: str
    version: str
    name: str
    description: str | None = None
    algorithm_key: str
    weights: dict[str, Any]
    parameters: dict[str, Any] | None = None
    formula: str | None = None
    is_active: bool
    effective_from: datetime


# --- Séries temporais ---------------------------------------------------------


class PricePoint(BaseModel):
    observed_at: datetime
    price: float | None = None
    original_price: float | None = None
    discount_pct: float | None = None
    currency: str | None = None
    available_quantity: int | None = None
    is_available: bool | None = None


class MetricPoint(BaseModel):
    observed_at: datetime
    sold_last_period: int | None = None
    visits: int | None = None
    views: int | None = None
    wishlist_count: int | None = None
    review_count: int | None = None
    rating: float | None = None
    sales_rank: int | None = None


# --- Produto ------------------------------------------------------------------


class ProductSummary(BaseModel):
    """Versão de lista: o suficiente para decidir se vale abrir o detalhe."""

    id: int
    marketplace: str
    external_id: str
    title: str
    brand: str | None = None
    category_id: str | None = None

    currency: str | None = None
    price: float | None = None
    original_price: float | None = None
    discount_pct: float | None = None
    affiliate_commission_pct: float | None = None

    rating: float | None = None
    review_count: int | None = None
    available_quantity: int | None = None
    sold_quantity: int | None = None

    is_active: bool
    first_seen_at: datetime
    last_seen_at: datetime

    # Campos de exibição (cards): já no Product, sem join extra — por isso
    # entram na listagem, não só no detalhe.
    is_available: bool | None = None
    has_promotion: bool | None = None
    product_url: str | None = None
    affiliate_url: str | None = None
    images: list[Any] | None = None
    attributes: dict[str, Any] | None = None

    # Confiabilidade do vendedor (quando o marketplace expõe): sinal real de
    # "fonte confiável" para priorizar no card, não decoração.
    seller_nickname: str | None = None
    seller_reputation_level: str | None = None
    seller_is_official_store: bool | None = None
    # Posição no ranking de mais vendidos (Mercado Livre) — sinal de demanda
    # de fallback quando o marketplace não expõe `sold_quantity` por item.
    ranking_position: int | None = None
    affiliate_count: int | None = None
    affiliate_count_period: str | None = None
    manual_stock: int | None = None

    # Scores vigentes por dimensão. Ausente = não calculado.
    scores: dict[str, float] = Field(default_factory=dict)


class ProductDetail(ProductSummary):
    """Versão de detalhe: inclui procedência, séries temporais e explicações."""

    seller: SellerOut | None = None
    source_record: SourceRecordOut | None = None

    model: str | None = None
    condition: str | None = None
    category_path: list[Any] | None = None
    affiliate_commission_fixed: float | None = None
    popularity_score: float | None = None
    coupons: list[Any] | None = None
    identity_key: str | None = None

    price_history: list[PricePoint] = Field(default_factory=list)
    metrics_history: list[MetricPoint] = Field(default_factory=list)
    score_explanations: list[ScoreExplanation] = Field(default_factory=list)


# --- Criativos ----------------------------------------------------------------


class CreativeAssetOut(BaseModel):
    id: int
    portfolio_item_id: int | None = None
    product_id: int | None = None
    asset_type: str
    status: str
    version: int
    status_changed_at: datetime
    title: str | None = None
    content_text: str | None = None
    content_url: str | None = None
    external_system: str | None = None
    external_ref: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    blocked_reason: str | None = None
    rejection_reason: str | None = None


# --- Portfólio ----------------------------------------------------------------


class RecommendationOut(BaseModel):
    id: int
    kind: str
    dimension: str | None = None
    title: str
    rationale: str | None = None
    positive_factors: list[Any] | None = None
    negative_factors: list[Any] | None = None
    priority: int
    confidence: float | None = None
    is_actioned: bool
    actioned_at: datetime | None = None
    outcome: str | None = None


class PortfolioTransitionOut(BaseModel):
    id: int
    from_state: str | None = None
    to_state: str
    occurred_at: datetime
    actor: str
    reason: str | None = None
    triggered_by_recommendation_id: int | None = None


class PortfolioItemOut(BaseModel):
    id: int
    product_id: int
    marketplace: str
    label: str | None = None
    state: str
    state_changed_at: datetime
    entry_score: float | None = None
    added_by: str | None = None
    notes: str | None = None

    revenue_total: float | None = None
    commission_total: float | None = None
    clicks_total: int | None = None
    conversions_total: int | None = None
    last_metrics_at: datetime | None = None

    paused_reason: str | None = None
    removed_reason: str | None = None
    removed_at: datetime | None = None

    # O que o operador pode fazer a seguir, calculado pelo backend. O frontend
    # nunca decide estado — apenas oferece o que a API declarou como permitido.
    allowed_transitions: list[str] = Field(default_factory=list)
    # Materiais obrigatórios que faltam para publicar.
    missing_assets_for_publish: list[str] = Field(default_factory=list)


class PortfolioItemDetail(PortfolioItemOut):
    transitions: list[PortfolioTransitionOut] = Field(default_factory=list)
    recommendations: list[RecommendationOut] = Field(default_factory=list)
    creatives: list[CreativeAssetOut] = Field(default_factory=list)


# --- Requisições --------------------------------------------------------------


class TransitionRequest(BaseModel):
    """Pedido de mudança de estado. O backend valida; o cliente só propõe."""

    to_state: str
    actor: str = "operator"
    reason: str | None = None
    recommendation_id: int | None = None


class AddToPortfolioRequest(BaseModel):
    product_id: int
    label: str | None = None
    added_by: str = "operator"
    notes: str | None = None


class CreativeStatusUpdate(BaseModel):
    status: str
    actor: str = "operator"
    note: str | None = None


class CreativeAssetCreate(BaseModel):
    asset_type: str
    # Ao menos um dos dois deveria ser informado na prática — sem isso o
    # material fica órfão e nunca aparece em `GET /creatives/assets?portfolio_item_id=`
    # nem no portão de publicação (briefing §8).
    portfolio_item_id: int | None = None
    product_id: int | None = None
    title: str | None = None
    content_text: str | None = None
    content_url: str | None = None
    external_system: str | None = None
    external_ref: str | None = None


# --- Jobs ---------------------------------------------------------------------


class JobOut(BaseModel):
    id: int
    job_type: str
    agent: str | None = None
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    progress_pct: float | None = None
    result_summary: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    attempt: int
    triggered_by: str | None = None


class JobEventOut(BaseModel):
    id: int
    occurred_at: datetime
    level: str
    message: str
    payload: dict[str, Any] | None = None


# --- Agregados operacionais ---------------------------------------------------


class KpiOut(BaseModel):
    period_start: datetime
    period_end: datetime
    days: int

    sales_count: int
    currency: str | None = None
    gross_revenue: float | None = None
    commission_estimated: float | None = None
    commission_confirmed: float | None = None

    clicks_total: int | None = None
    ad_cost_total: float | None = None

    active_products: int
    products_with_sales: int
    products_without_sales: int

    ctr: float | None = None
    conversion_rate: float | None = None
    average_ticket: float | None = None
    revenue_per_click: float | None = None
    roas: float | None = None

    marketplace_breakdown: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ConnectorStatusOut(BaseModel):
    connector: str
    configured: bool
    reliability: float
    detail: dict[str, Any] = Field(default_factory=dict)


class DailyOperationsOut(BaseModel):
    """O painel de decisão do briefing seção 9.

    Cada bloco responde uma pergunta operacional e traz contagem + itens. Bloco
    vazio é diferente de bloco ausente: o ausente seria indistinguível de
    "nada aconteceu".
    """

    generated_at: datetime
    kpis: KpiOut

    opportunities_today: list[ProductSummary] = Field(default_factory=list)
    recommended: list[ProductSummary] = Field(default_factory=list)
    awaiting_decision: list[PortfolioItemOut] = Field(default_factory=list)
    affiliation_pending: list[PortfolioItemOut] = Field(default_factory=list)
    creatives_pending: list[CreativeAssetOut] = Field(default_factory=list)
    creatives_ready: list[CreativeAssetOut] = Field(default_factory=list)
    ready_to_publish: list[PortfolioItemOut] = Field(default_factory=list)
    published: list[PortfolioItemOut] = Field(default_factory=list)
    optimization_required: list[PortfolioItemOut] = Field(default_factory=list)
    alerts: list[str] = Field(default_factory=list)


# --- Tendências internacionais (Mercado Livre) ---------------------------------


class TrendingAbroadProduct(BaseModel):
    """Mais vendido de outro país da ML — não persistido, é dado ao vivo.

    `already_in_brazil_catalog` é uma checagem honesta e exata (mesmo título
    normalizado + marca do catálogo brasileiro), não uma tradução automática:
    um título em espanhol quase nunca bate com o mesmo produto em português,
    então `False` aqui não significa "produto inédito", só "não achamos uma
    correspondência exata".
    """

    site_id: str
    country: str
    external_id: str
    title: str
    category_id: str | None = None
    price: float | None = None
    currency: str | None = None
    ranking_position: int | None = None
    product_url: str | None = None
    images: list[Any] | None = None
    already_in_brazil_catalog: bool
