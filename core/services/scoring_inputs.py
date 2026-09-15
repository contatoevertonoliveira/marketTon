"""Montagem dos insumos de cada score a partir do banco.

Separação deliberada: o **motor** (`engine.py`) é puro e não toca no banco; **este
módulo** sabe onde cada insumo mora. Isso mantém o cálculo testável sem infra e
deixa explícito de onde vem cada número.

Regra de honestidade aplicada em cada função: se o dado não existe, o insumo fica
`None`. O motor então marca o fator como indisponível, reduz a `confidence` e, se
faltar o bastante, devolve `INSUFFICIENT_DATA`. Nunca preenchemos com zero nem com
estimativa — é a diferença entre "não sabemos" e "é ruim".
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from core.db.catalog import Product, ProductMetric, Seller
from core.db.portfolio import PortfolioItem
from core.db.scoring import ScoreRun, ScoreRunStatus

# Janela usada para comparar dois períodos consecutivos de métricas.
DEFAULT_WINDOW_DAYS = 7


class UnsupportedTargetError(NotImplementedError):
    """Alvo sem montagem de insumos implementada."""


def _latest_metrics(session: Session, product_id: int, limit: int = 2) -> list[ProductMetric]:
    """Observações mais recentes, da mais nova para a mais antiga."""
    return list(
        session.scalars(
            select(ProductMetric)
            .where(ProductMetric.product_id == product_id)
            .order_by(desc(ProductMetric.observed_at))
            .limit(limit)
        )
    )


def _previous_period_metric(
    session: Session, product_id: int, *, now: datetime, window_days: int
) -> ProductMetric | None:
    """Observação mais próxima de uma janela atrás, para medir variação."""
    cutoff = now - timedelta(days=window_days)
    return session.scalar(
        select(ProductMetric)
        .where(ProductMetric.product_id == product_id, ProductMetric.observed_at <= cutoff)
        .order_by(desc(ProductMetric.observed_at))
        .limit(1)
    )


def _latest_score(session: Session, *, dimension: str, product_id: int) -> float | None:
    """Score mais recente **completo** de uma dimensão, para uso como insumo.

    Filtra por `SUCCEEDED` de propósito: um score calculado com dado faltante não
    deve virar insumo de outro score. Propagar um número de confiança parcial para
    dentro do Opportunity Score faria a baixa confiança desaparecer no caminho — o
    Opportunity pareceria bem fundamentado quando na verdade herdou uma lacuna.
    Ausência é propagada como ausência, e o Opportunity reduz a própria confiança.
    """
    run = session.scalar(
        select(ScoreRun)
        .where(
            ScoreRun.target_type == "product",
            ScoreRun.target_id == product_id,
            ScoreRun.dimension == dimension,
            ScoreRun.status == ScoreRunStatus.SUCCEEDED,
        )
        .order_by(desc(ScoreRun.computed_at))
        .limit(1)
    )
    return float(run.score) if run is not None else None


def heat_inputs(session: Session, product: Product, *, now: datetime | None = None) -> dict[str, Any]:
    """Insumos do Heat Score: velocidade e aceleração de vendas, avaliações, nota, estoque."""
    now = now or datetime.now(UTC)
    observations = _latest_metrics(session, product.id, limit=2)

    current = observations[0] if observations else None
    previous = _previous_period_metric(session, product.id, now=now, window_days=DEFAULT_WINDOW_DAYS)

    # `new_reviews_period` exige duas medições: sem a anterior, é desconhecido.
    new_reviews = None
    if current is not None and previous is not None:
        if current.review_count is not None and previous.review_count is not None:
            new_reviews = max(0, current.review_count - previous.review_count)

    sold_last = current.sold_last_period if current else None
    sold_previous = previous.sold_last_period if previous else None

    return {
        "sold_last_period": sold_last,
        "sold_previous_period": sold_previous,
        "new_reviews_period": new_reviews,
        "rating": current.rating if current and current.rating is not None else product.rating,
        "available_quantity": product.available_quantity,
        "_raw": {
            "sales_velocity": sold_last,
            "sales_momentum": (
                (sold_last - sold_previous) / sold_previous
                if sold_last is not None and sold_previous not in (None, 0)
                else None
            ),
            "review_velocity": new_reviews,
            "rating": current.rating if current and current.rating is not None else product.rating,
            "stock_health": product.available_quantity,
        },
    }


def creative_saturation_inputs(session: Session, product: Product) -> dict[str, Any]:
    """Insumos do Creative Saturation Score.

    Estes dados vêm de bibliotecas de anúncios (Meta Ads Library), não do
    marketplace. Sem eles o score sai como `INSUFFICIENT_DATA` — que é o
    comportamento correto, e o briefing seção 5 condiciona esta dimensão a
    "quando houver dados suficientes".

    Os valores podem ser gravados em `Product.attributes["ad_signals"]` por um
    coletor de anúncios. Enquanto isso não existe, devolvemos `None`.
    """
    signals = (product.attributes or {}).get("ad_signals") if product.attributes else None
    if not isinstance(signals, dict):
        return {
            "active_ads_count": None,
            "distinct_advertisers": None,
            "median_ad_age_days": None,
            "homogeneous_offer_pct": None,
            "_raw": {},
        }

    return {
        "active_ads_count": signals.get("active_ads_count"),
        "distinct_advertisers": signals.get("distinct_advertisers"),
        "median_ad_age_days": signals.get("median_ad_age_days"),
        "homogeneous_offer_pct": signals.get("homogeneous_offer_pct"),
        "_raw": {
            "ad_volume": signals.get("active_ads_count"),
            "advertiser_density": signals.get("distinct_advertisers"),
            "creative_age": signals.get("median_ad_age_days"),
            "offer_homogeneity": signals.get("homogeneous_offer_pct"),
        },
    }


def producer_momentum_inputs(session: Session, product: Product, *, now: datetime | None = None) -> dict[str, Any]:
    """Insumos do Producer Momentum Score, a partir do vendedor do produto."""
    now = now or datetime.now(UTC)
    seller: Seller | None = product.seller
    if seller is None:
        return {
            "seller_total_sales": None,
            "seller_active_listings": None,
            "seller_active_listings_previous": None,
            "seller_reputation_level": None,
            "seller_positive_rating_pct": None,
            "seller_active_promotions": None,
            "seller_response_rate_pct": None,
            "_raw": {},
        }

    return {
        "seller_total_sales": seller.total_sales,
        "seller_active_listings": None,
        "seller_active_listings_previous": None,
        "seller_reputation_level": seller.reputation_level,
        "seller_positive_rating_pct": seller.positive_rating_pct,
        "seller_active_promotions": None,
        "seller_response_rate_pct": None,
        "_raw": {
            "sales_track_record": seller.total_sales,
            "listing_growth": None,
            "reputation": seller.positive_rating_pct,
            "promotional_activity": None,
            "responsiveness": None,
        },
    }


def opportunity_inputs(
    session: Session,
    product: Product,
    *,
    heat_score: float | None = None,
    producer_momentum_score: float | None = None,
    creative_saturation_score: float | None = None,
    competing_ads_count: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Insumos do Opportunity Score.

    Reutiliza os outros três scores quando já calculados. Scores ausentes entram
    como `None`: o Opportunity reduz a própria confiança em vez de assumir um
    valor intermediário para os fatores que dependem deles.
    """
    now = now or datetime.now(UTC)

    if heat_score is None:
        heat_score = _latest_score(session, dimension="HEAT", product_id=product.id)
    if producer_momentum_score is None:
        producer_momentum_score = _latest_score(
            session, dimension="PRODUCER_MOMENTUM", product_id=product.id
        )
    if creative_saturation_score is None:
        creative_saturation_score = _latest_score(
            session, dimension="CREATIVE_SATURATION", product_id=product.id
        )

    price = product.price
    return {
        "affiliate_commission_pct": product.affiliate_commission_pct,
        "price": price,
        "heat_score": heat_score,
        "producer_momentum_score": producer_momentum_score,
        "creative_saturation_score": creative_saturation_score,
        "competing_ads_count": competing_ads_count,
        # Limites da faixa alvo vêm do spec quando ausentes; aqui só passamos nada.
        "_raw": {
            "commission": product.affiliate_commission_pct,
            "ticket_fit": price,
            "heat": heat_score,
            "producer_momentum": producer_momentum_score,
            "saturation_headroom": creative_saturation_score,
            "affiliate_pressure": competing_ads_count,
        },
    }


def portfolio_inputs(session: Session, item: PortfolioItem, *, now: datetime | None = None) -> dict[str, Any]:
    """Insumos do Portfolio Score: desempenho real depois de entrar na operação.

    Receita e comissão podem ser `None` enquanto o item não vendeu. O motor trata
    como fator indisponível — o que é diferente de desempenho zero.
    """
    now = now or datetime.now(UTC)
    return {
        "revenue_total": item.revenue_total,
        "commission_total": item.commission_total,
        "clicks_total": item.clicks_total,
        "conversions_total": item.conversions_total,
        "_raw": {
            "revenue": item.revenue_total,
            "commission": item.commission_total,
            "clicks": item.clicks_total,
            "conversions": item.conversions_total,
        },
    }


def build_inputs(
    session: Session,
    *,
    dimension: str,
    target_type: str,
    target_id: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Despacha para o montador de insumos da dimensão pedida."""
    dimension = dimension.upper()

    if target_type == "product":
        product = session.get(Product, target_id)
        if product is None:
            raise LookupError(f"produto {target_id} não encontrado")

        if dimension == "HEAT":
            return heat_inputs(session, product, now=now)
        if dimension == "OPPORTUNITY":
            return opportunity_inputs(session, product, now=now)
        if dimension == "PRODUCER_MOMENTUM":
            return producer_momentum_inputs(session, product, now=now)
        if dimension == "CREATIVE_SATURATION":
            return creative_saturation_inputs(session, product)

    if target_type == "portfolio_item":
        item = session.get(PortfolioItem, target_id)
        if item is None:
            raise LookupError(f"item de portfólio {target_id} não encontrado")
        if dimension == "PORTFOLIO":
            return portfolio_inputs(session, item, now=now)

    raise UnsupportedTargetError(
        f"não há montagem de insumos para dimension={dimension} target_type={target_type}. "
        "Dimensões com insumos implementados: HEAT, OPPORTUNITY, PRODUCER_MOMENTUM e "
        "CREATIVE_SATURATION para produtos; PORTFOLIO para itens de portfólio."
    )


__all__ = [
    "UnsupportedTargetError",
    "build_inputs",
    "creative_saturation_inputs",
    "heat_inputs",
    "opportunity_inputs",
    "portfolio_inputs",
    "producer_momentum_inputs",
]
