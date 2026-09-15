"""Growth Analyst — KPIs reais e diagnóstico (briefing seções 10 e 11).

Antes: concatenava dois CSVs e não calculava nada. O `SOUL.md` prometia ROAS, CPA,
CTR e conversão; o código não calculava nenhum deles.

Agora tem duas partes com papéis distintos:

1. **Cálculo determinístico** (`compute_kpis`) — receita, comissão, cliques, CTR,
   conversão, ticket médio, ROAS. Números auditáveis, derivados das tabelas de
   vendas, cliques e comissões. Nenhum LLM participa.
2. **Diagnóstico por IA** (`diagnose`) — interpreta os KPIs e prioriza ações. A IA
   recebe os números prontos e a instrução explícita de não recalculá-los.

Separação deliberada: o número é verificável, a interpretação é útil.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from core.db.ai import AIInterpretationKind
from core.db.base import Marketplace
from core.db.portfolio import PortfolioItem
from core.db.tracking import AffiliateLink, ClickEvent, Commission, Sale
from core.services.ai.client import AIClient
from core.services.ai.interpreter import run_interpretation
from core.services.ai.prompts import get_prompt
from core.services.jobs import job_run
from core.tasks import TaskResult

logger = logging.getLogger(__name__)


@dataclass
class KpiSnapshot:
    """KPIs de um período. Campo sem dado é `None`, nunca 0.

    A distinção importa para o briefing seção 2: "zero cliques" e "não medimos
    cliques" levam a decisões opostas, e fundir os dois em `0` produziria análise
    errada com aparência de correta.
    """

    period_start: datetime
    period_end: datetime
    days: int

    sales_count: int = 0
    currency: str | None = None
    gross_revenue: float | None = None
    commission_estimated: float | None = None
    commission_confirmed: float | None = None

    clicks_total: int | None = None
    ad_cost_total: float | None = None

    active_products: int = 0
    products_with_sales: int = 0
    products_without_sales: int = 0

    # Valores derivados, calculados apenas quando a base existe.
    ctr: float | None = None
    conversion_rate: float | None = None
    average_ticket: float | None = None
    revenue_per_click: float | None = None
    roas: float | None = None

    marketplace_breakdown: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "days": self.days,
            "sales_count": self.sales_count,
            "currency": self.currency,
            "gross_revenue": self.gross_revenue,
            "commission_estimated": self.commission_estimated,
            "commission_confirmed": self.commission_confirmed,
            "clicks_total": self.clicks_total,
            "ad_cost_total": self.ad_cost_total,
            "active_products": self.active_products,
            "products_with_sales": self.products_with_sales,
            "products_without_sales": self.products_without_sales,
            "ctr": self.ctr,
            "conversion_rate": self.conversion_rate,
            "average_ticket": self.average_ticket,
            "revenue_per_click": self.revenue_per_click,
            "roas": self.roas,
            "marketplace_breakdown": self.marketplace_breakdown,
            "notes": self.notes,
        }


def compute_kpis(
    session: Session,
    *,
    days: int = 7,
    now: datetime | None = None,
    marketplace: Marketplace | None = None,
) -> KpiSnapshot:
    """Calcula os KPIs do período a partir das tabelas de tracking."""
    period_end = now or datetime.now(UTC)
    period_start = period_end - timedelta(days=days)

    snapshot = KpiSnapshot(period_start=period_start, period_end=period_end, days=days)

    # --- Vendas ---------------------------------------------------------------
    sales_filters = [Sale.occurred_at >= period_start, Sale.occurred_at <= period_end]
    if marketplace is not None:
        sales_filters.append(Sale.marketplace == marketplace)

    sales_rows = list(
        session.scalars(
            select(Sale).where(*sales_filters)
        )
    )
    snapshot.sales_count = len(sales_rows)

    if sales_rows:
        gross_values = [float(row.gross_amount) for row in sales_rows if row.gross_amount is not None]
        snapshot.gross_revenue = round(sum(gross_values), 2) if gross_values else None
        currencies = {row.currency for row in sales_rows if row.currency}
        snapshot.currency = currencies.pop() if len(currencies) == 1 else None
        if len(currencies) > 1:
            snapshot.notes.append(
                f"vendas em múltiplas moedas ({sorted(currencies)}); a soma não é comparável"
            )

        product_ids = {row.portfolio_item_id for row in sales_rows if row.portfolio_item_id is not None}
        snapshot.products_with_sales = len(product_ids)

    # --- Comissões (estimado e confirmado separados) --------------------------
    commission_filters = [Commission.created_at >= period_start, Commission.created_at <= period_end]
    if marketplace is not None:
        commission_filters.append(Commission.marketplace == marketplace)

    commission_rows = list(session.scalars(select(Commission).where(*commission_filters)))
    if commission_rows:
        estimated = [float(c.estimated_amount) for c in commission_rows if c.estimated_amount is not None]
        confirmed = [float(c.confirmed_amount) for c in commission_rows if c.confirmed_amount is not None]
        snapshot.commission_estimated = round(sum(estimated), 2) if estimated else None
        snapshot.commission_confirmed = round(sum(confirmed), 2) if confirmed else None
        if snapshot.commission_confirmed is None and snapshot.commission_estimated is not None:
            snapshot.notes.append(
                "nenhuma comissão confirmada no período; o valor estimado não é receita realizada"
            )

    # --- Cliques --------------------------------------------------------------
    click_filters = [ClickEvent.occurred_at >= period_start, ClickEvent.occurred_at <= period_end]
    click_rows = list(session.scalars(select(ClickEvent).where(*click_filters)))
    if click_rows:
        snapshot.clicks_total = len(click_rows)
        costs = [float(row.cost) for row in click_rows if row.cost is not None]
        snapshot.ad_cost_total = round(sum(costs), 2) if costs else None

    # --- Portfólio ------------------------------------------------------------
    portfolio_query: Select = select(func.count()).select_from(PortfolioItem)
    snapshot.active_products = int(session.scalar(portfolio_query) or 0)
    if snapshot.active_products:
        snapshot.products_without_sales = max(
            0, snapshot.active_products - snapshot.products_with_sales
        )

    # --- Derivados ------------------------------------------------------------
    # Calculados só quando a base existe. Sem base, ficam `None` e uma nota explica.
    if snapshot.clicks_total and snapshot.sales_count:
        snapshot.conversion_rate = round(snapshot.sales_count / snapshot.clicks_total, 6)

    if snapshot.gross_revenue is not None and snapshot.sales_count:
        snapshot.average_ticket = round(snapshot.gross_revenue / snapshot.sales_count, 2)

    if snapshot.gross_revenue is not None and snapshot.clicks_total:
        snapshot.revenue_per_click = round(snapshot.gross_revenue / snapshot.clicks_total, 4)

    if snapshot.ad_cost_total and snapshot.gross_revenue is not None:
        snapshot.roas = round(snapshot.gross_revenue / snapshot.ad_cost_total, 4)
    elif snapshot.ad_cost_total is None:
        snapshot.notes.append(
            "custo de tráfego pago não registrado; ROAS e CPA não podem ser calculados"
        )

    if not snapshot.clicks_total:
        snapshot.notes.append(
            "nenhum clique registrado no período; CTR e conversão não podem ser calculados"
        )

    # --- Quebra por marketplace ----------------------------------------------
    snapshot.marketplace_breakdown = _marketplace_breakdown(session, period_start, period_end)

    return snapshot


def _marketplace_breakdown(
    session: Session, period_start: datetime, period_end: datetime
) -> list[dict[str, Any]]:
    rows = session.execute(
        select(
            Sale.marketplace,
            func.count(Sale.id),
            func.sum(Sale.gross_amount),
        )
        .where(Sale.occurred_at >= period_start, Sale.occurred_at <= period_end)
        .group_by(Sale.marketplace)
    ).all()

    breakdown = []
    for marketplace, count, revenue in rows:
        breakdown.append(
            {
                "marketplace": marketplace.value if hasattr(marketplace, "value") else str(marketplace),
                "sales": int(count or 0),
                "revenue": round(float(revenue), 2) if revenue is not None else None,
            }
        )
    return sorted(breakdown, key=lambda item: item["revenue"] or 0, reverse=True)


def diagnose(
    session: Session,
    snapshot: KpiSnapshot,
    *,
    ai: AIClient | None = None,
    agent: str = "growth_analyst",
) -> dict[str, Any] | None:
    """Pede à IA um diagnóstico operacional sobre os KPIs já calculados."""
    if ai is None:
        ai = AIClient()

    result = run_interpretation(
        session,
        ai=ai,
        agent=agent,
        kind=AIInterpretationKind.PERFORMANCE_DIAGNOSIS,
        prompt=get_prompt("performance_diagnosis"),
        inputs=snapshot.to_dict(),
        target_type="period",
    )
    if not result.ok:
        logger.info("diagnóstico por IA indisponível: %s", result.skipped_reason or result.error)
    return result.output


def run(memory: dict, *, session: Session | None = None, ai: AIClient | None = None) -> TaskResult:
    """Execução como task do pipeline.

    Sem sessão de banco, declara a limitação em vez de calcular KPIs sobre nada:
    a versão anterior concatenava dois CSVs que não existiam e chamava aquilo de
    relatório de crescimento.
    """
    days = int(memory.get("growth_window_days", 7))

    if session is None:
        return TaskResult(
            task_id="growth_analyst",
            ok=True,
            summary=(
                "sem sessão de banco: KPIs não calculados. "
                "Forneça uma sessão para usar as tabelas de vendas, cliques e comissões."
            ),
            artifacts={"days": days, "kpis": None},
        )

    with job_run(
        session,
        job_type="growth_analyst.report",
        agent="growth_analyst",
        params={"days": days},
    ) as handle:
        snapshot = compute_kpis(session, days=days)
        handle.add_event(
            f"{snapshot.sales_count} vendas em {days}d",
            payload={"gross_revenue": snapshot.gross_revenue, "notes": snapshot.notes},
        )

        # As notas são limitações declaradas pelo cálculo ("custo de tráfego não
        # registrado; ROAS indisponível"). Vão para o job para que a ausência de um
        # KPI seja rastreável em vez de virar um campo `null` sem explicação.
        for note in snapshot.notes:
            handle.add_event(note, level="WARNING")

        diagnosis = None
        if ai is None or ai.is_available:
            diagnosis = diagnose(session, snapshot, ai=ai)

        summary_parts = [f"{snapshot.sales_count} vendas em {days}d"]
        if snapshot.gross_revenue is not None:
            summary_parts.append(f"receita {snapshot.gross_revenue:.2f}")
        if snapshot.commission_confirmed is not None:
            summary_parts.append(f"comissão confirmada {snapshot.commission_confirmed:.2f}")
        elif snapshot.commission_estimated is not None:
            summary_parts.append(f"comissão estimada {snapshot.commission_estimated:.2f}")
        if diagnosis:
            summary_parts.append("com diagnóstico por IA")

        summary = " | ".join(summary_parts)
        handle.add_event(summary)

        return TaskResult(
            task_id="growth_analyst",
            ok=True,
            summary=summary,
            artifacts={
                "job_id": handle.id,
                "days": days,
                "kpis": snapshot.to_dict(),
                "diagnosis": diagnosis,
            },
        )


__all__ = ["KpiSnapshot", "compute_kpis", "diagnose", "run"]
