"""Testes da ingestão (briefing seção 4).

O que estes testes protegem:

1. **Proveniência obrigatória** — nenhum produto é gravado sem `SourceRecord`.
2. **Idempotência** — o pipeline roda em ciclo; reingerir não pode duplicar produto.
3. **Séries temporais só crescem com mudança real** — do contrário a tabela inflaria
   a cada ciclo sem acrescentar informação.
4. **Ausência não vira zero** — `None` na coleta não apaga o que já sabíamos.
"""
from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from core.db.catalog import PriceHistory, Product, ProductMetric, Seller, SourceRecord
from core.services.ingestion import ingest_products
from integrations.marketplaces.base import ConnectorBatch, ConnectorProduct

# Base fixa + contador: `datetime.now()` com precisão de microssegundo pode
# repetir entre duas chamadas seguidas, e `UNIQUE(product_id, observed_at)`
# rejeitaria a segunda observação. Um relógio incremental torna o teste
# determinístico em vez de flaky.
_CLOCK = itertools.count()
_BASE_TIME = datetime(2026, 3, 20, 10, 0, tzinfo=UTC)


def _next_timestamp() -> datetime:
    return _BASE_TIME + timedelta(minutes=next(_CLOCK))


def _product(**overrides) -> ConnectorProduct:
    base = {
        "external_id": "MLB1",
        "title": "Fone Bluetooth Mini",
        "price": 99.9,
        "currency": "BRL",
        "available_quantity": 10,
        "is_available": True,
        "sold_quantity": 40,
        "rating": 4.5,
        "review_count": 30,
        "product_url": "https://produto.mercadolivre.com.br/MLB-1",
    }
    base.update(overrides)
    return ConnectorProduct(**base)


def _batch(products, *, connector="mercado_livre", collected_at=None, warnings=None, reliability=1.0):
    return ConnectorBatch(
        connector=connector,
        products=list(products),
        collected_at=collected_at or _next_timestamp(),
        endpoint="https://api.mercadolibre.com/items/{id}",
        reliability=reliability,
        warnings=list(warnings or []),
        raw={"user_id": 123},
    )


def _ingest(session, products, marketplace="mercado_livre", *, skip_without_market_signal=True, **batch_kwargs):
    """Helper: monta o lote, ingere e devolve as estatísticas.

    Separa as opções do lote (`connector`, `collected_at`, `warnings`,
    `reliability`) das opções da ingestão (`skip_without_market_signal`).
    """
    return ingest_products(
        session,
        _batch(products, **batch_kwargs),
        marketplace,
        skip_without_market_signal=skip_without_market_signal,
    )


class TestProvenance:
    def test_every_product_gets_a_source_record(self, session) -> None:
        stats = _ingest(session, [_product()])

        assert stats.created == 1
        assert stats.source_record_id is not None

        record = session.get(SourceRecord, stats.source_record_id)
        assert record is not None
        assert record.connector == "mercado_livre"
        assert record.endpoint
        assert record.reliability == 1.0

        product = session.scalar(select(Product))
        assert product.source_record_id == record.id

    def test_warnings_are_persisted_not_swallowed(self, session) -> None:
        """Um aviso de coleta é dado, não ruído: precisa ficar registrado."""
        stats = _ingest(session, [_product()], warnings=["coleta limitada a 50 anúncios"])

        record = session.get(SourceRecord, stats.source_record_id)
        assert record.warnings == ["coleta limitada a 50 anúncios"]
        assert stats.warnings == ["coleta limitada a 50 anúncios"]

    def test_raw_payload_is_kept_for_audit(self, session) -> None:
        stats = _ingest(session, [_product()])
        record = session.get(SourceRecord, stats.source_record_id)
        assert record.raw == {"user_id": 123}

    def test_reliability_reflects_the_source(self, session) -> None:
        """Fonte não oficial entra com confiabilidade menor, não igual."""
        stats = _ingest(session, [_product()], connector="custom_affiliate", reliability=0.6)
        record = session.get(SourceRecord, stats.source_record_id)
        assert record.reliability == 0.6
        assert record.connector_kind.value == "affiliate_api"


class TestIdempotency:
    def test_reingesting_does_not_duplicate_products(self, session) -> None:
        _ingest(session, [_product()])
        stats = _ingest(session, [_product()])

        assert stats.created == 0
        assert stats.unchanged == 1
        assert len(session.scalars(select(Product)).all()) == 1

    def test_reingesting_creates_a_new_source_record(self, session) -> None:
        """Cada coleta é um evento distinto: a trilha de procedência cresce."""
        first = _ingest(session, [_product()])
        second = _ingest(session, [_product()])

        assert first.source_record_id != second.source_record_id
        assert len(session.scalars(select(SourceRecord)).all()) == 2

    def test_price_change_marks_product_updated(self, session) -> None:
        _ingest(session, [_product(price=99.9)])
        stats = _ingest(session, [_product(price=89.9)])

        assert stats.updated == 1
        assert stats.created == 0
        product = session.scalar(select(Product))
        assert float(product.price) == 89.9

    def test_seller_is_not_duplicated(self, session) -> None:
        product = _product(seller_external_id="555", seller_nickname="Loja X")
        _ingest(session, [product])
        stats = _ingest(session, [product])

        assert stats.sellers_created == 0
        assert len(session.scalars(select(Seller)).all()) == 1

    def test_seller_signals_are_updated(self, session) -> None:
        _ingest(session, [_product(seller_external_id="555", seller_total_sales=100)])
        _ingest(session, [_product(seller_external_id="555", seller_total_sales=250)])

        seller = session.scalar(select(Seller))
        assert seller.total_sales == 250


class TestTimeSeries:
    def test_price_history_only_records_real_changes(self, session) -> None:
        """Sem esta regra a tabela cresceria a cada ciclo sem informação nova."""
        base = datetime.now(UTC)

        _ingest(session, [_product(price=99.9)], collected_at=base)
        _ingest(session, [_product(price=99.9)], collected_at=base + timedelta(hours=1))
        assert len(session.scalars(select(PriceHistory)).all()) == 1

        _ingest(session, [_product(price=89.9)], collected_at=base + timedelta(hours=2))
        points = session.scalars(select(PriceHistory).order_by(PriceHistory.observed_at)).all()
        assert [float(p.price) for p in points] == [99.9, 89.9]

    def test_metrics_series_records_each_observation(self, session) -> None:
        base = datetime.now(UTC)
        _ingest(session, [_product()], collected_at=base)
        _ingest(session, [_product()], collected_at=base + timedelta(hours=1))

        points = session.scalars(select(ProductMetric)).all()
        assert len(points) == 2
        assert all(p.rating == 4.5 for p in points)

    def test_no_metric_row_when_there_is_no_demand_signal(self, session) -> None:
        """Preço sem sinal de demanda não vira ponto de série temporal."""
        bare = _product()
        for field in (
            "sold_last_period",
            "visits",
            "views",
            "wishlist_count",
            "review_count",
            "rating",
            "ranking_position",
        ):
            setattr(bare, field, None)

        stats = _ingest(session, [bare])
        assert stats.metric_points == 0
        assert session.scalars(select(ProductMetric)).all() == []

    def test_sold_quantity_does_not_become_a_period_metric(self, session) -> None:
        """`sold_quantity` é acumulado; tratá-lo como período falsearia o Heat Score."""
        stats = _ingest(session, [_product(sold_quantity=500, rating=None, review_count=None)])
        assert stats.metric_points == 0

        product = session.scalar(select(Product))
        assert product.sold_quantity == 500


class TestAbsenceIsNotZero:
    def test_missing_field_does_not_erase_known_value(self, session) -> None:
        """Uma coleta sem nota não pode zerar a nota que já tínhamos."""
        _ingest(session, [_product(rating=4.8, brand="Acme")])
        _ingest(session, [_product(rating=None, brand=None)])

        product = session.scalar(select(Product))
        assert float(product.rating) == 4.8
        assert product.brand == "Acme"

    def test_product_without_any_market_signal_is_skipped(self, session) -> None:
        bare = ConnectorProduct(external_id="MLB2", title="Anúncio sem preço")
        stats = _ingest(session, [bare])

        assert stats.skipped == 1
        assert stats.created == 0
        assert session.scalars(select(Product)).all() == []

    def test_skip_can_be_disabled_explicitly(self, session) -> None:
        bare = ConnectorProduct(external_id="MLB2", title="Anúncio sem preço")
        stats = _ingest(session, [bare], skip_without_market_signal=False)
        assert stats.created == 1

    def test_item_without_id_or_title_is_skipped_with_a_warning(self, session) -> None:
        stats = _ingest(
            session,
            [
                ConnectorProduct(external_id="", title="x"),
                ConnectorProduct(external_id="y", title=""),
            ],
        )
        assert stats.skipped == 2
        assert any("external_id ou título" in w for w in stats.warnings)


class TestIdentity:
    def test_identity_key_is_normalized(self, session) -> None:
        _ingest(session, [_product(title="Fone  Bluetooth   Mini!", brand="Acme")])
        product = session.scalar(select(Product))
        assert product.identity_key == "fone bluetooth mini acme"

    def test_identity_key_groups_the_same_product_across_marketplaces(self, session) -> None:
        """É o que permite comparar o mesmo produto em marketplaces diferentes."""
        _ingest(
            session,
            [_product(external_id="MLB1", title="Fone Bluetooth Mini", brand="Acme")],
            "mercado_livre",
        )
        _ingest(
            session,
            [_product(external_id="SHP1", title="fone bluetooth  mini", brand="acme")],
            "shopee",
            connector="shopee",
        )

        keys = {p.identity_key for p in session.scalars(select(Product)).all()}
        assert len(keys) == 1
        assert len(session.scalars(select(Product)).all()) == 2

    def test_different_products_are_not_grouped(self, session) -> None:
        _ingest(
            session,
            [
                _product(external_id="A", title="Fone Bluetooth"),
                _product(external_id="B", title="Caixa de Som"),
            ],
        )
        keys = {p.identity_key for p in session.scalars(select(Product)).all()}
        assert len(keys) == 2


class TestStats:
    def test_summary_is_human_readable(self, session) -> None:
        stats = _ingest(session, [_product()])
        assert "mercado_livre" in stats.summary()
        assert "1 novos" in stats.summary()

    def test_counts_are_consistent(self, session) -> None:
        products = [_product(external_id=f"MLB{i}", title=f"Produto {i}") for i in range(5)]
        stats = _ingest(session, products)
        assert stats.total == 5
        assert stats.created == 5
