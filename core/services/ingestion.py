"""Ingestão: transforma uma coleta em registros de domínio com procedência.

Este é o ponto onde a regra do briefing seção 4 deixa de ser documentação e passa a
ser constraint: nenhum produto é gravado sem um `SourceRecord` correspondente, e o
`source_record_id` é `NOT NULL` com `ON DELETE RESTRICT`.

Duas garantias de idempotência, porque o pipeline vai rodar em ciclo:

1. `products` tem `UNIQUE(marketplace, external_id)`. Reingerir o mesmo anúncio
   atualiza em vez de duplicar.
2. `price_history` e `product_metrics` têm `UNIQUE(product_id, observed_at)`.
   Séries temporais só ganham linha nova quando há mudança real de valor — do
   contrário a tabela cresceria a cada ciclo sem acrescentar informação.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.base import ConnectorKind, Marketplace
from core.db.catalog import PriceHistory, Product, ProductMetric, Seller, SourceRecord
from integrations.marketplaces.base import ConnectorBatch, ConnectorProduct

# Campos de `ConnectorProduct` que pertencem a `Product`.
_PRODUCT_FIELDS = (
    "title",
    "category_id",
    "category_path",
    "brand",
    "model",
    "condition",
    "currency",
    "price",
    "original_price",
    "discount_pct",
    "affiliate_commission_pct",
    "affiliate_commission_fixed",
    "available_quantity",
    "sold_quantity",
    "is_available",
    "rating",
    "review_count",
    "ranking_position",
    "popularity_score",
    "has_promotion",
    "coupons",
    "product_url",
    "affiliate_url",
    "images",
    "attributes",
)

# Campos que descrevem demanda num instante e portanto viram série temporal.
_METRIC_FIELDS = (
    "sold_last_period",
    "visits",
    "views",
    "wishlist_count",
    "review_count",
    "rating",
    "ranking_position",
)

# Campos que mudam de preço/disponibilidade e viram histórico.
_PRICE_FIELDS = ("price", "original_price", "discount_pct", "currency", "available_quantity", "is_available")


@dataclass
class IngestStats:
    """Resumo da ingestão. Devolvido para virar `jobs.result`, não log solto."""

    marketplace: str
    source_record_id: int | None = None
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    sellers_created: int = 0
    price_points: int = 0
    metric_points: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.created + self.updated + self.unchanged

    def summary(self) -> str:
        return (
            f"{self.marketplace}: {self.created} novos, {self.updated} atualizados, "
            f"{self.unchanged} sem mudança, {self.skipped} ignorados"
        )


def _as_enum(value: Marketplace | str) -> Marketplace:
    return value if isinstance(value, Marketplace) else Marketplace(value)


def _connector_kind_for(connector: str) -> ConnectorKind:
    """Classifica a fonte para auditoria de legitimidade (briefing seção 2)."""
    lowered = connector.lower()
    if "affiliate" in lowered:
        return ConnectorKind.AFFILIATE_API
    return ConnectorKind.OFFICIAL_API


def record_source(
    session: Session,
    batch: ConnectorBatch,
    marketplace: Marketplace | str,
    *,
    external_id: str | None = None,
    external_parent_id: str | None = None,
) -> SourceRecord:
    """Grava a procedência de uma coleta. Chamado uma vez por lote."""
    record = SourceRecord(
        marketplace=_as_enum(marketplace),
        connector=batch.connector,
        connector_kind=_connector_kind_for(batch.connector),
        endpoint=batch.endpoint,
        external_id=external_id,
        external_parent_id=external_parent_id,
        collected_at=batch.collected_at or datetime.now(UTC),
        reliability=batch.reliability,
        warnings=list(batch.warnings) or None,
        raw=batch.raw,
    )
    session.add(record)
    session.flush()
    return record


def upsert_seller(
    session: Session,
    product: ConnectorProduct,
    marketplace: Marketplace | str,
    source_record_id: int,
    *,
    seen_at: datetime,
) -> tuple[Seller | None, bool]:
    """Cria ou atualiza o vendedor. Devolve `(seller, criado)`."""
    if not product.seller_external_id:
        return None, False

    seller = session.scalar(
        select(Seller).where(
            Seller.marketplace == _as_enum(marketplace),
            Seller.external_id == product.seller_external_id,
        )
    )
    created = seller is None
    if seller is None:
        seller = Seller(
            marketplace=_as_enum(marketplace),
            external_id=product.seller_external_id,
            source_record_id=source_record_id,
        )
        session.add(seller)

    # Só sobrescreve com dado presente: um `None` nesta coleta não apaga o que já
    # sabíamos sobre o vendedor.
    for attr, value in (
        ("nickname", product.seller_nickname),
        ("reputation_level", product.seller_reputation_level),
        ("reputation_score", product.seller_reputation_score),
        ("total_sales", product.seller_total_sales),
        ("positive_rating_pct", product.seller_positive_rating_pct),
        ("feedback_count", product.seller_feedback_count),
        ("is_official_store", product.seller_is_official_store),
        ("power_seller_status", product.seller_power_seller_status),
    ):
        if value is not None:
            setattr(seller, attr, value)

    seller.last_seen_at = seen_at
    session.flush()
    return seller, created


def ingest_products(
    session: Session,
    batch: ConnectorBatch,
    marketplace: Marketplace | str,
    *,
    observed_at: datetime | None = None,
    skip_without_market_signal: bool = True,
) -> IngestStats:
    """Persiste um lote coletado, preservando a procedência.

    `skip_without_market_signal` descarta anúncios sem preço nem sinal de demanda:
    eles não são analisáveis e só poluiriam o catálogo.
    """
    stats = IngestStats(marketplace=_as_enum(marketplace).value, warnings=list(batch.warnings))
    observed_at = observed_at or batch.collected_at or datetime.now(UTC)

    source = record_source(session, batch, marketplace)
    stats.source_record_id = source.id

    for item in batch.products:
        if not item.external_id or not item.title:
            stats.skipped += 1
            stats.warnings.append("item sem external_id ou título")
            continue

        if skip_without_market_signal and not item.has_any_market_signal():
            stats.skipped += 1
            continue

        seller, seller_created = upsert_seller(
            session, item, marketplace, source.id, seen_at=observed_at
        )
        if seller_created:
            stats.sellers_created += 1

        product = session.scalar(
            select(Product).where(
                Product.marketplace == _as_enum(marketplace),
                Product.external_id == item.external_id,
            )
        )

        if product is None:
            product = Product(
                marketplace=_as_enum(marketplace),
                external_id=item.external_id,
                title=item.title,
                source_record_id=source.id,
                first_seen_at=observed_at,
                last_seen_at=observed_at,
            )
            # Copiar os campos do item também na criação. Antes, a criação só
            # definia a identidade: o primeiro produto gravado ficava sem preço,
            # sem estoque e sem vendedor, e só era preenchido na coleta seguinte.
            _apply_product_fields(product, item)
            session.add(product)
            session.flush()
            stats.created += 1
            previous_price: object = None
        else:
            previous_price = product.price
            _apply_product_fields(product, item)
            product.last_seen_at = observed_at
            product.is_active = True
            product.source_record_id = source.id
            # Detecta mudança real para não inflar o histórico.
            if _changed(previous_price, item.price):
                stats.updated += 1
            else:
                stats.unchanged += 1

        if seller is not None:
            product.seller_id = seller.id
        product.identity_key = item.identity_key()

        if _record_price_point(session, product, item, source.id, observed_at, previous_price):
            stats.price_points += 1
        if _record_metric_point(session, product, item, source.id, observed_at):
            stats.metric_points += 1

    session.flush()
    return stats


def _apply_product_fields(product: Product, item: ConnectorProduct) -> None:
    """Copia para o produto apenas os campos presentes na coleta.

    Um `None` nesta coleta não apaga o que já sabíamos: a plataforma pode não
    expor um campo em uma chamada e expô-lo na seguinte, e sobrescrever com nulo
    destruiria informação boa.
    """
    for attr in _PRODUCT_FIELDS:
        value = getattr(item, attr)
        if value is not None:
            setattr(product, attr, value)


def _changed(previous: object, current: object) -> bool:
    if previous is None and current is None:
        return False
    if previous is None or current is None:
        return True
    try:
        return float(previous) != float(current)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return previous != current


def _record_price_point(
    session: Session,
    product: Product,
    item: ConnectorProduct,
    source_record_id: int,
    observed_at: datetime,
    previous_price: object,
) -> bool:
    """Grava histórico de preço quando há valor e ele mudou (ou é o primeiro)."""
    if item.price is None:
        return False
    if not _changed(previous_price, item.price):
        return False

    session.add(
        PriceHistory(
            product_id=product.id,
            observed_at=observed_at,
            price=item.price,
            original_price=item.original_price,
            discount_pct=item.discount_pct,
            currency=item.currency,
            available_quantity=item.available_quantity,
            is_available=item.is_available,
            source_record_id=source_record_id,
        )
    )
    return True


def _record_metric_point(
    session: Session,
    product: Product,
    item: ConnectorProduct,
    source_record_id: int,
    observed_at: datetime,
) -> bool:
    """Grava ponto de série temporal quando há algum sinal de demanda."""
    values: dict[str, Any] = {field: getattr(item, field) for field in _METRIC_FIELDS}
    if all(value is None for value in values.values()):
        return False

    session.add(
        ProductMetric(
            product_id=product.id,
            observed_at=observed_at,
            source_record_id=source_record_id,
            sold_last_period=item.sold_last_period,
            visits=item.visits,
            views=item.views,
            wishlist_count=item.wishlist_count,
            search_interest=None,
            review_count=item.review_count,
            rating=item.rating,
            sales_rank=item.ranking_position,
        )
    )
    return True


__all__ = [
    "IngestStats",
    "ingest_products",
    "record_source",
    "upsert_seller",
]
