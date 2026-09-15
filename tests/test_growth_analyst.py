"""Testes do Growth Analyst (briefing seções 10 e 11).

Separação que os testes verificam:

* **KPIs são determinísticos e auditáveis.** Calculados das tabelas de vendas,
  cliques e comissões. Nenhum LLM participa.
* **Comissão estimada não é receita realizada.** Plataformas de afiliado atrasam a
  confirmação; somar as duas produziria receita fabricada.
* **Dado ausente é `None`, não `0`.** "Não medimos cliques" e "zero cliques" levam a
  decisões opostas.
* **A IA interpreta, não calcula.** Recebe os KPIs prontos.
"""
from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from agents.growth_analyst.agent import KpiSnapshot, compute_kpis, diagnose, run
from core.db.ai import AIInterpretation, AIInterpretationKind
from core.db.base import Marketplace
from core.db.catalog import Product
from core.db.portfolio import PortfolioItem
from core.db.tracking import AffiliateLink, ClickEvent, Commission, Sale
from core.services.ai.client import AIClient, AIResponse

NOW = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)

# Contador de pedidos: garante `external_order_id` único entre vendas de teste.
_ORDER_COUNTER = itertools.count(1)


def _portfolio_item(session, source_record, external_id="MLB1", title="Fone") -> PortfolioItem:
    product = Product(
        marketplace=Marketplace.MERCADO_LIVRE,
        external_id=external_id,
        title=title,
        price=100.0,
        source_record_id=source_record.id,
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    session.add(product)
    session.flush()

    item = PortfolioItem(
        product_id=product.id,
        marketplace=Marketplace.MERCADO_LIVRE,
        label=title,
        state_changed_at=NOW,
    )
    session.add(item)
    session.flush()
    return item


def _sale(session, item, *, when, gross, currency="BRL", order_id=None) -> Sale:
    """Cria uma venda. O `external_order_id` precisa ser único por marketplace.

    A constraint `uq_sales_marketplace_order` existe para dar idempotência à
    ingestão: reingerir o mesmo pedido não pode duplicar a venda. Nos testes o id
    é sequencial para que duas vendas distintas não colidam.
    """
    sale = Sale(
        portfolio_item_id=item.id,
        marketplace=Marketplace.MERCADO_LIVRE,
        external_order_id=order_id or f"ORD-{next(_ORDER_COUNTER)}",
        occurred_at=when,
        quantity=1,
        currency=currency,
        gross_amount=gross,
    )
    session.add(sale)
    session.flush()
    return sale


def _commission(session, sale, *, estimated=None, confirmed=None, when=NOW) -> Commission:
    commission = Commission(
        sale_id=sale.id,
        portfolio_item_id=sale.portfolio_item_id,
        marketplace=Marketplace.MERCADO_LIVRE,
        estimated_amount=estimated,
        confirmed_amount=confirmed,
        currency="BRL",
        created_at=when,
    )
    session.add(commission)
    session.flush()
    return commission


def _click(session, item, *, when, cost=None, link=None) -> ClickEvent:
    event = ClickEvent(
        affiliate_link_id=link.id,
        portfolio_item_id=item.id,
        occurred_at=when,
        cost=cost,
    )
    session.add(event)
    session.flush()
    return event


@pytest.fixture
def portfolio_item(session, product):
    """Item de portfólio sobre o produto compartilhado.

    Reutiliza o produto do conftest: criar outro com o mesmo `external_id`
    violaria `UNIQUE(marketplace, external_id)`, e criar dois itens para o mesmo
    produto violaria `UNIQUE(portfolio_items.product_id)`. As duas constraints
    existem para impedir duplicação acidental no catálogo.
    """
    item = PortfolioItem(
        product_id=product.id,
        marketplace=Marketplace.MERCADO_LIVRE,
        label=product.title,
        state_changed_at=NOW,
    )
    session.add(item)
    session.flush()
    return item


@pytest.fixture
def link(session, portfolio_item):
    """Link de afiliado do item de portfólio, necessário para registrar cliques."""
    affiliate = AffiliateLink(
        product_id=portfolio_item.product_id,
        portfolio_item_id=portfolio_item.id,
        marketplace=Marketplace.MERCADO_LIVRE,
        destination_url="https://produto.mercadolivre.com.br/MLB-1",
        affiliate_url="https://mercadolivre.com/aff/abc",
        short_code="abc123",
    )
    session.add(affiliate)
    session.flush()
    return affiliate


class TestComputeKpis:
    def test_empty_period_reports_none_not_zero(self, session) -> None:
        """Sem venda, receita é `None`. `0` afirmaria que não vendemos nada."""
        snapshot = compute_kpis(session, days=7, now=NOW)

        assert snapshot.sales_count == 0
        assert snapshot.gross_revenue is None
        assert snapshot.commission_estimated is None
        assert snapshot.commission_confirmed is None
        assert snapshot.clicks_total is None
        assert snapshot.roas is None
        assert any("custo de tráfego pago não registrado" in note for note in snapshot.notes)

    def test_revenue_and_ticket(self, session, source_record) -> None:
        item = _portfolio_item(session, source_record)
        _sale(session, item, when=NOW - timedelta(days=1), gross=100.0)
        _sale(session, item, when=NOW - timedelta(days=2), gross=200.0)

        snapshot = compute_kpis(session, days=7, now=NOW)

        assert snapshot.sales_count == 2
        assert snapshot.gross_revenue == 300.0
        assert snapshot.average_ticket == 150.0
        assert snapshot.currency == "BRL"

    def test_sales_outside_the_window_are_excluded(self, session, source_record) -> None:
        item = _portfolio_item(session, source_record)
        _sale(session, item, when=NOW - timedelta(days=1), gross=100.0)
        _sale(session, item, when=NOW - timedelta(days=30), gross=999.0)

        snapshot = compute_kpis(session, days=7, now=NOW)
        assert snapshot.gross_revenue == 100.0

    def test_estimated_commission_is_not_presented_as_revenue(self, session, source_record) -> None:
        """Ponto central: estimado e confirmado não se somam nem se confundem."""
        item = _portfolio_item(session, source_record)
        sale = _sale(session, item, when=NOW - timedelta(days=1), gross=100.0)
        _commission(session, sale, estimated=12.0, confirmed=None)

        snapshot = compute_kpis(session, days=7, now=NOW)

        assert snapshot.commission_estimated == 12.0
        assert snapshot.commission_confirmed is None
        assert any("não é receita realizada" in note for note in snapshot.notes)

    def test_ctr_and_conversion_need_a_denominator(self, session, portfolio_item, link) -> None:
        for _ in range(10):
            _click(session, portfolio_item, when=NOW - timedelta(days=1), link=link)
        for _ in range(2):
            _sale(session, portfolio_item, when=NOW - timedelta(days=1), gross=100.0)

        snapshot = compute_kpis(session, days=7, now=NOW)

        assert snapshot.clicks_total == 10
        assert snapshot.conversion_rate == pytest.approx(0.2)
        assert snapshot.revenue_per_click == pytest.approx(20.0)

    def test_roas_requires_ad_cost(self, session, portfolio_item, link) -> None:
        _click(session, portfolio_item, when=NOW - timedelta(days=1), cost=50.0, link=link)
        _sale(session, portfolio_item, when=NOW - timedelta(days=1), gross=200.0)

        snapshot = compute_kpis(session, days=7, now=NOW)

        assert snapshot.ad_cost_total == 50.0
        assert snapshot.roas == pytest.approx(4.0)

    def test_products_with_and_without_sales(self, session, source_record) -> None:
        item_a = _portfolio_item(session, source_record, "MLB1", "Fone")
        _portfolio_item(session, source_record, "MLB2", "Caixa")
        _sale(session, item_a, when=NOW - timedelta(days=1), gross=100.0)

        snapshot = compute_kpis(session, days=7, now=NOW)

        assert snapshot.active_products == 2
        assert snapshot.products_with_sales == 1
        assert snapshot.products_without_sales == 1

    def test_marketplace_breakdown(self, session, source_record) -> None:
        item = _portfolio_item(session, source_record)
        _sale(session, item, when=NOW - timedelta(days=1), gross=100.0)

        snapshot = compute_kpis(session, days=7, now=NOW)

        assert len(snapshot.marketplace_breakdown) == 1
        entry = snapshot.marketplace_breakdown[0]
        assert entry["marketplace"] == "mercado_livre"
        assert entry["sales"] == 1
        assert entry["revenue"] == 100.0

    def test_mixed_currencies_are_flagged(self, session, source_record) -> None:
        """Somar BRL com USD produziria um número sem significado."""
        item = _portfolio_item(session, source_record)
        _sale(session, item, when=NOW - timedelta(days=1), gross=100.0, currency="BRL")
        _sale(session, item, when=NOW - timedelta(days=1), gross=50.0, currency="USD")

        snapshot = compute_kpis(session, days=7, now=NOW)

        assert snapshot.currency is None
        assert any("múltiplas moedas" in note for note in snapshot.notes)


class TestSnapshotSerialization:
    def test_to_dict_is_json_serializable(self) -> None:
        snapshot = KpiSnapshot(period_start=NOW, period_end=NOW, days=7)
        payload = json.dumps(snapshot.to_dict())
        assert '"days": 7' in payload


class _FakeProvider:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list = []

    def complete(self, messages, *, temperature: float = 0.2) -> AIResponse:
        self.calls.append(messages)
        return AIResponse(text=json.dumps(self.payload), model="fake")


class TestDiagnosis:
    def test_diagnosis_receives_the_computed_kpis(self, session, portfolio_item, link) -> None:
        """A IA interpreta números prontos; não os recalcula."""
        _sale(session, portfolio_item, when=NOW - timedelta(days=1), gross=100.0)
        _click(session, portfolio_item, when=NOW - timedelta(days=1), cost=25.0, link=link)

        snapshot = compute_kpis(session, days=7, now=NOW)
        provider = _FakeProvider({"what_is_working": ["ROAS 4.0"], "priority_actions": []})
        output = diagnose(session, snapshot, ai=AIClient(provider=provider))

        assert output == {"what_is_working": ["ROAS 4.0"], "priority_actions": []}

        record = session.scalar(select(AIInterpretation))
        assert record.kind == AIInterpretationKind.PERFORMANCE_DIAGNOSIS
        assert record.agent == "growth_analyst"
        # Os KPIs exatos foram entregues ao modelo.
        assert record.inputs["gross_revenue"] == 100.0
        assert record.inputs["roas"] == pytest.approx(4.0)

    def test_diagnosis_returns_none_when_ai_is_disabled(self, session) -> None:
        snapshot = compute_kpis(session, days=7, now=NOW)
        assert diagnose(session, snapshot, ai=AIClient(provider=None)) is None
        assert session.scalars(select(AIInterpretation)).all() == []


class TestRun:
    def test_without_session_says_kpis_were_not_computed(self) -> None:
        """Sem banco, o agente declara a limitação em vez de fingir que calculou."""
        result = run({})

        assert result.ok is True
        assert "não calculados" in result.summary
        assert result.artifacts["kpis"] is None

    def test_with_session_reports_real_numbers(self, session, source_record) -> None:
        item = _portfolio_item(session, source_record)
        _sale(session, item, when=datetime.now(UTC) - timedelta(days=1), gross=250.0)

        result = run({"growth_window_days": 7}, session=session, ai=AIClient(provider=None))

        assert result.ok is True
        assert "1 vendas em 7d" in result.summary
        assert "250.00" in result.summary
        assert result.artifacts["kpis"]["gross_revenue"] == 250.0
        assert result.artifacts["diagnosis"] is None
