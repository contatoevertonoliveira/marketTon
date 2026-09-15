"""Endpoints de catálogo: produtos coletados, procedência e séries temporais.

Leitura apenas. A entrada de dados acontece pela ingestão
(`core/services/ingestion.py`), não por HTTP — aceitar produto por POST criaria um
caminho sem proveniência, e o briefing seção 4 exige origem para todo dado.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from backend.deps import get_adapters, get_session
from backend.security import require
from backend.serializers import (
    latest_scores_by_dimension,
    product_detail,
    product_summary,
    source_record_out,
)
from backend.schemas import ProductDetail, ProductSummary, SourceRecordOut
from core.db.base import Marketplace
from core.db.catalog import Product, SourceRecord

# Todas as rotas exigem `catalog.view`. O portão é declarado no router em vez de
# repetido em cada endpoint: esquecer um seria um buraco silencioso.
router = APIRouter(
    prefix="/catalog",
    tags=["catálogo"],
    dependencies=[Depends(require("catalog.view"))],
)


@router.get("/products", response_model=list[ProductSummary])
def list_products(
    session: Session = Depends(get_session),
    marketplace: Marketplace | None = None,
    category_id: str | None = None,
    brand: str | None = None,
    search: str | None = Query(None, description="Busca textual no título"),
    min_price: float | None = Query(None, ge=0),
    max_price: float | None = Query(None, ge=0),
    min_commission_pct: float | None = Query(None, ge=0),
    min_rating: float | None = Query(None, ge=0, le=5),
    only_active: bool = True,
    seen_within_days: int | None = Query(None, ge=1, description="Visto nos últimos N dias"),
    order_by: str = Query("last_seen_at", pattern="^(last_seen_at|price|rating|sold_quantity|discount_pct)$"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[ProductSummary]:
    """Lista o catálogo com filtros.

    Campos sem dado na fonte não aparecem em filtro numérico — filtrar por
    `min_commission_pct` exclui produtos cuja comissão é desconhecida, o que é
    diferente de excluir produtos com comissão baixa.
    """
    statement = select(Product)

    if marketplace is not None:
        statement = statement.where(Product.marketplace == marketplace)
    if category_id:
        statement = statement.where(Product.category_id == category_id)
    if brand:
        statement = statement.where(Product.brand == brand)
    if search:
        statement = statement.where(Product.title.ilike(f"%{search}%"))
    if min_price is not None:
        statement = statement.where(Product.price >= min_price)
    if max_price is not None:
        statement = statement.where(Product.price <= max_price)
    if min_commission_pct is not None:
        statement = statement.where(Product.affiliate_commission_pct >= min_commission_pct)
    if min_rating is not None:
        statement = statement.where(Product.rating >= min_rating)
    if only_active:
        statement = statement.where(Product.is_active.is_(True))
    if seen_within_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=seen_within_days)
        statement = statement.where(Product.last_seen_at >= cutoff)

    order_column = getattr(Product, order_by)
    statement = statement.order_by(order_column.desc().nullslast()).limit(limit).offset(offset)

    products = list(session.scalars(statement))
    scores = latest_scores_by_dimension(session, [product.id for product in products])
    return [product_summary(product, scores.get(product.id)) for product in products]


@router.get("/products/{product_id}", response_model=ProductDetail)
def get_product(product_id: int, session: Session = Depends(get_session)) -> ProductDetail:
    """Detalhe do produto: procedência, histórico de preço, métricas e explicações.

    `score_explanations` responde "por que este produto foi recomendado?" — é a
    lista `+ motivo` / `- motivo` derivada da aritmética do score.
    """
    product = session.scalar(
        select(Product)
        .where(Product.id == product_id)
        .options(
            selectinload(Product.seller),
            selectinload(Product.source_record),
        )
    )
    if product is None:
        raise HTTPException(status_code=404, detail=f"produto {product_id} não encontrado")
    return product_detail(session, product)


@router.get("/products/{product_id}/source", response_model=list[SourceRecordOut])
def product_provenance(
    product_id: int, session: Session = Depends(get_session)
) -> list[SourceRecordOut]:
    """Trilha de procedência: todas as coletas que tocaram este produto.

    Usa o `external_id` e o marketplace do produto para reunir o histórico de
    coletas, não apenas a última — é isso que permite auditar de onde veio cada
    valor ao longo do tempo.
    """
    product = session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail=f"produto {product_id} não encontrado")

    statement = (
        select(SourceRecord)
        .where(
            SourceRecord.marketplace == product.marketplace,
            SourceRecord.external_id == product.external_id,
        )
        .order_by(SourceRecord.collected_at.desc())
    )
    records = list(session.scalars(statement))

    # A coleta mais recente pode ter vindo de um lote sem `external_id` por item;
    # nesse caso incluímos o registro atual do produto para não devolver vazio.
    if not records and product.source_record is not None:
        records = [product.source_record]

    return [out for out in (source_record_out(record) for record in records) if out is not None]


@router.get("/stats")
def catalog_stats(session: Session = Depends(get_session)) -> dict:
    """Panorama do catálogo. Serve de contexto para filtros e para o painel."""
    total = session.scalar(select(func.count()).select_from(Product)) or 0
    active = session.scalar(select(func.count()).select_from(Product).where(Product.is_active.is_(True))) or 0

    by_marketplace = session.execute(
        select(Product.marketplace, func.count(Product.id)).group_by(Product.marketplace)
    ).all()

    # Quantos produtos têm cada campo preenchido. É a medida de completude real da
    # coleta, e o que explica por que um score pode sair com confiança baixa.
    field_coverage = {
        field: int(session.scalar(select(func.count()).select_from(Product).where(column.is_not(None))) or 0)
        for field, column in (
            ("price", Product.price),
            ("affiliate_commission_pct", Product.affiliate_commission_pct),
            ("rating", Product.rating),
            ("review_count", Product.review_count),
            ("available_quantity", Product.available_quantity),
            ("sold_quantity", Product.sold_quantity),
            ("seller_id", Product.seller_id),
        )
    }

    last_collection = session.scalar(select(func.max(Product.last_seen_at)))

    return {
        "total_products": total,
        "active_products": active,
        "inactive_products": total - active,
        "by_marketplace": [
            {"marketplace": marketplace.value, "products": int(count)}
            for marketplace, count in by_marketplace
        ],
        "field_coverage": field_coverage,
        "last_collection_at": last_collection.isoformat() if last_collection else None,
    }


@router.get("/marketplaces")
def available_marketplaces() -> dict:
    """Marketplaces suportados pelo domínio e o estado de cada conector."""
    adapters = get_adapters()
    return {
        "supported": [marketplace.value for marketplace in Marketplace],
        "connectors": [
            {
                "connector": name,
                "configured": adapter.is_configured(),
                "reliability": adapter.reliability,
            }
            for name, adapter in sorted(adapters.items())
            if adapter is not None
        ],
    }
