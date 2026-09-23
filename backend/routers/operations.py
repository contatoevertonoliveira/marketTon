"""Endpoints operacionais: painel diário e revisão semanal.

Briefing seção 9 — o dashboard é uma central de decisões, e o operador deve
compreender o estado da operação em ~30 segundos. Seção 10 — a revisão semanal
compara períodos e aponta candidatos a escala, pausa e remoção.

Os números vêm de `growth_analyst.compute_kpis`, que é determinístico. Nenhum LLM
participa desta camada: aqui o que importa é o dado, não a interpretação.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from agents.growth_analyst.agent import compute_kpis
from backend.deps import get_adapters, get_session
from backend.security import require
from backend.serializers import (
    creative_asset_out,
    kpi_out,
    latest_scores_by_dimension,
    portfolio_item_out,
    product_summary,
)
from backend.schemas import (
    ConnectorStatusOut,
    CreativeAssetOut,
    DailyOperationsOut,
    PortfolioItemOut,
    ProductSummary,
)
from core.db.base import CreativeStatus, Marketplace, PortfolioState
from core.db.catalog import Product
from core.db.creative import CreativeAsset
from core.db.portfolio import PortfolioItem
from core.db.scoring import ScoreRun

router = APIRouter(
    prefix="/operations",
    tags=["operação"],
    dependencies=[Depends(require("operations.view"))],
)


def _portfolio_in_states(
    session: Session, states: list[PortfolioState], limit: int = 20, marketplace: Marketplace | None = None
) -> list[PortfolioItemOut]:
    filters = [PortfolioItem.state.in_(states)]
    if marketplace is not None:
        filters.append(PortfolioItem.marketplace == marketplace)
    items = session.scalars(
        select(PortfolioItem).where(*filters).order_by(PortfolioItem.state_changed_at.desc()).limit(limit)
    )
    return [portfolio_item_out(session, item) for item in items]


def _creatives_in_status(
    session: Session, statuses: list[CreativeStatus], limit: int = 20, marketplace: Marketplace | None = None
) -> list[CreativeAssetOut]:
    query = select(CreativeAsset).where(CreativeAsset.status.in_(statuses))
    if marketplace is not None:
        # `product_id` é opcional no modelo; um criativo sem produto vinculado não
        # tem como ser atribuído a um marketplace, então o join já os exclui.
        query = query.join(Product, Product.id == CreativeAsset.product_id).where(
            Product.marketplace == marketplace
        )
    assets = session.scalars(query.order_by(CreativeAsset.status_changed_at.asc()).limit(limit))
    return [creative_asset_out(asset) for asset in assets]


@router.get("/daily", response_model=DailyOperationsOut)
def daily_operations(
    session: Session = Depends(get_session),
    days: int = Query(1, ge=1, le=30, description="Janela dos KPIs, em dias"),
    limit: int = Query(20, ge=1, le=100),
    marketplace: Marketplace | None = Query(None, description="Restringe o painel a um marketplace"),
) -> DailyOperationsOut:
    """O painel de decisão do briefing seção 9.

    Cada bloco responde uma pergunta operacional. `alerts` reúne o que exige ação
    agora, derivado de dados — não é uma lista decorativa. Com `marketplace`,
    cada bloco é restrito àquele marketplace (a Visão Geral usa isso para
    montar uma aba por marketplace ativado).
    """
    now = datetime.now(UTC)
    snapshot = compute_kpis(session, days=days, now=now, marketplace=marketplace)
    alerts: list[str] = []

    # --- Oportunidades de hoje -------------------------------------------------
    cutoff = now - timedelta(days=1)
    product_filters = [Product.is_active.is_(True), Product.first_seen_at >= cutoff]
    if marketplace is not None:
        product_filters.append(Product.marketplace == marketplace)
    recent_products = list(
        session.scalars(
            select(Product).where(*product_filters).order_by(desc(Product.first_seen_at)).limit(limit)
        )
    )
    scores = latest_scores_by_dimension(session, [product.id for product in recent_products])
    opportunities = [product_summary(product, scores.get(product.id)) for product in recent_products]

    # --- Recomendados: maior Opportunity Score ---------------------------------
    # Sobra de margem no limite bruto: produtos de outros marketplaces são
    # descartados no laço abaixo antes de bater o `limit` de saída.
    top_runs = session.scalars(
        select(ScoreRun)
        .where(ScoreRun.target_type == "product", ScoreRun.dimension == "OPPORTUNITY")
        .order_by(desc(ScoreRun.score))
        .limit(limit * (8 if marketplace is not None else 3))
    ).all()

    recommended: list[ProductSummary] = []
    seen_products: set[int] = set()
    for run in top_runs:
        if run.target_id in seen_products:
            continue
        product = session.get(Product, run.target_id)
        if product is None:
            continue
        if marketplace is not None and product.marketplace != marketplace:
            continue
        seen_products.add(run.target_id)
        recommended.append(product_summary(product, {run.dimension.value: float(run.score)}))
        if len(recommended) >= limit:
            break

    if not top_runs:
        alerts.append(
            "nenhum Opportunity Score calculado ainda; rode POST /scoring/compute para "
            "priorizar produtos"
        )

    # --- Blocos por estado do portfólio ---------------------------------------
    awaiting = _portfolio_in_states(
        session, [PortfolioState.RECOMMENDED, PortfolioState.WATCHLIST, PortfolioState.DISCOVERED], limit, marketplace
    )
    affiliation = _portfolio_in_states(session, [PortfolioState.AFFILIATION_PENDING], limit, marketplace)
    ready = _portfolio_in_states(session, [PortfolioState.READY_TO_PUBLISH], limit, marketplace)
    published = _portfolio_in_states(
        session, [PortfolioState.PUBLISHED, PortfolioState.MONITORING, PortfolioState.SCALING], limit, marketplace
    )
    optimization = _portfolio_in_states(session, [PortfolioState.OPTIMIZATION_REQUIRED], limit, marketplace)

    # --- Criativos -------------------------------------------------------------
    creatives_pending = _creatives_in_status(
        session, [CreativeStatus.PENDING, CreativeStatus.IN_PROGRESS, CreativeStatus.BLOCKED], limit, marketplace
    )
    creatives_ready = _creatives_in_status(
        session, [CreativeStatus.READY, CreativeStatus.APPROVED], limit, marketplace
    )

    # --- Alertas derivados de dado --------------------------------------------
    if snapshot.commission_confirmed is None and snapshot.commission_estimated is not None:
        alerts.append(
            f"comissão de {snapshot.commission_estimated:.2f} está apenas estimada; "
            "nenhuma confirmada no período"
        )
    if snapshot.roas is None and snapshot.ad_cost_total is None:
        alerts.append("custo de tráfego pago não registrado; ROAS indisponível")
    if snapshot.clicks_total is None:
        alerts.append("nenhum clique registrado; CTR e conversão indisponíveis")

    blocked_query = select(func.count()).select_from(CreativeAsset).where(CreativeAsset.status == CreativeStatus.BLOCKED)
    if marketplace is not None:
        blocked_query = blocked_query.join(Product, Product.id == CreativeAsset.product_id).where(
            Product.marketplace == marketplace
        )
    blocked = session.scalar(blocked_query)
    if blocked:
        alerts.append(f"{int(blocked)} material(is) criativo(s) bloqueado(s)")

    stalled_query = select(func.count()).select_from(PortfolioItem).where(
        PortfolioItem.state == PortfolioState.OPTIMIZATION_REQUIRED
    )
    if marketplace is not None:
        stalled_query = stalled_query.where(PortfolioItem.marketplace == marketplace)
    stalled = session.scalar(stalled_query)
    if stalled:
        alerts.append(f"{int(stalled)} produto(s) exigindo otimização")

    return DailyOperationsOut(
        generated_at=now,
        kpis=kpi_out(snapshot),
        opportunities_today=opportunities,
        recommended=recommended,
        awaiting_decision=awaiting,
        affiliation_pending=affiliation,
        creatives_pending=creatives_pending,
        creatives_ready=creatives_ready,
        ready_to_publish=ready,
        published=published,
        optimization_required=optimization,
        alerts=alerts,
    )


@router.get("/weekly")
def weekly_review(
    session: Session = Depends(get_session),
    weeks_back: int = Query(1, ge=1, le=12, description="Deslocamento: 1 = semana passada"),
    marketplace: Marketplace | None = None,
) -> dict:
    """Revisão semanal do briefing seção 10, com comparação de período.

    Compara a semana pedida com a anterior. A comparação só aparece quando os dois
    períodos têm base — sem isso, uma variação percentual seria ruído apresentado
    como tendência.
    """
    now = datetime.now(UTC)
    period_end = now - timedelta(weeks=weeks_back - 1)
    period_start = period_end - timedelta(days=7)
    previous_end = period_start
    previous_start = previous_end - timedelta(days=7)

    current = compute_kpis(session, days=7, now=period_end, marketplace=marketplace)
    previous = compute_kpis(session, days=7, now=previous_end, marketplace=marketplace)

    # --- Melhores e piores produtos do período --------------------------------
    best_worst = _product_performance(session, period_start, period_end)

    candidates = _scale_pause_candidates(session, current)

    return {
        "period": {
            "start": period_start.isoformat(),
            "end": period_end.isoformat(),
            "weeks_back": weeks_back,
        },
        "current": current.to_dict(),
        "previous": previous.to_dict(),
        "delta": _delta(current, previous),
        "best_products": best_worst["best"],
        "worst_products": best_worst["worst"],
        "products_without_sales": best_worst["without_sales"],
        "scale_candidates": candidates["scale"],
        "pause_candidates": candidates["pause"],
        "removal_candidates": candidates["removal"],
        "notes": [
            "a comparação usa receita e comissão confirmada; valores estimados não entram no delta"
        ],
    }


def _product_performance(session: Session, period_start: datetime, period_end: datetime) -> dict:
    """Receita por produto no período, ordenada nos dois sentidos."""
    from core.db.tracking import Sale

    rows = session.execute(
        select(
            PortfolioItem.id,
            PortfolioItem.label,
            PortfolioItem.state,
            func.count(Sale.id),
            func.sum(Sale.gross_amount),
        )
        .join(Sale, Sale.portfolio_item_id == PortfolioItem.id)
        .where(Sale.occurred_at >= period_start, Sale.occurred_at <= period_end)
        .group_by(PortfolioItem.id, PortfolioItem.label, PortfolioItem.state)
    ).all()

    entries = [
        {
            "portfolio_item_id": item_id,
            "label": label,
            "state": state.value,
            "sales": int(count or 0),
            "revenue": round(float(revenue), 2) if revenue is not None else None,
        }
        for item_id, label, state, count, revenue in rows
    ]
    entries.sort(key=lambda entry: entry["revenue"] or 0, reverse=True)

    active_states = {
        PortfolioState.PUBLISHED,
        PortfolioState.MONITORING,
        PortfolioState.SCALING,
        PortfolioState.OPTIMIZATION_REQUIRED,
    }
    selling_ids = {entry["portfolio_item_id"] for entry in entries}

    all_active = session.scalars(
        select(PortfolioItem).where(PortfolioItem.state.in_(active_states))
    )
    without_sales = [
        {"portfolio_item_id": item.id, "label": item.label, "state": item.state.value}
        for item in all_active
        if item.id not in selling_ids
    ]

    return {
        "best": entries[:5],
        "worst": sorted(entries, key=lambda entry: entry["revenue"] or 0)[:5],
        "without_sales": without_sales,
    }


def _scale_pause_candidates(session: Session, snapshot) -> dict:
    """Candidatos a escala, pausa e remoção, a partir de dado real.

    Critérios declarados em vez de escondidos: escala exige receita registrada;
    pausa e remoção exigem produto ativo sem receita nenhuma. Sem os dois lados não
    há candidato — não inventamos sugestão a partir de ausência de dado.
    """
    from core.db.tracking import Commission

    state_rows = session.execute(
        select(PortfolioItem.id, PortfolioItem.label, PortfolioItem.state, func.sum(Commission.confirmed_amount))
        .outerjoin(Commission, Commission.portfolio_item_id == PortfolioItem.id)
        .group_by(PortfolioItem.id, PortfolioItem.label, PortfolioItem.state)
    ).all()

    scale, pause, removal = [], [], []
    for item_id, label, state, confirmed in state_rows:
        confirmed_value = float(confirmed) if confirmed is not None else None
        entry = {
            "portfolio_item_id": item_id,
            "label": label,
            "state": state.value,
            "confirmed_commission": round(confirmed_value, 2) if confirmed_value is not None else None,
        }
        if state in (PortfolioState.PUBLISHED, PortfolioState.MONITORING) and confirmed_value:
            scale.append(entry)
        elif state in (PortfolioState.PUBLISHED, PortfolioState.MONITORING) and not confirmed_value:
            pause.append(entry)
        elif state == PortfolioState.OPTIMIZATION_REQUIRED and not confirmed_value:
            removal.append(entry)

    return {"scale": scale, "pause": pause, "removal": removal}


def _delta(current, previous) -> dict:
    """Variação entre períodos, apenas onde os dois lados existem."""
    result = {}
    for field in ("gross_revenue", "commission_confirmed", "sales_count", "clicks_total"):
        now_value = getattr(current, field, None)
        before_value = getattr(previous, field, None)
        if now_value is None or before_value is None:
            result[field] = {
                "current": now_value,
                "previous": before_value,
                "absolute": None,
                "percent": None,
                "note": "sem base de comparação no período anterior",
            }
            continue
        absolute = now_value - before_value
        percent = (absolute / before_value) if before_value else None
        result[field] = {
            "current": now_value,
            "previous": before_value,
            "absolute": round(absolute, 4),
            "percent": round(percent, 4) if percent is not None else None,
            "note": None,
        }
    return result


@router.get("/connectors", response_model=list[ConnectorStatusOut])
def connector_status() -> list[ConnectorStatusOut]:
    """Estado de cada conector: configurado, confiabilidade e observações.

    Serve para o operador saber o que está coletando de verdade. Um conector não
    configurado não coleta nada, e isso precisa ser visível.
    """
    adapters = get_adapters()
    result = []
    for name, adapter in sorted(adapters.items()):
        if adapter is None:
            continue
        detail = {}
        if hasattr(adapter, "get_status"):
            try:
                detail = adapter.get_status()
            except Exception as exc:  # noqa: BLE001 - diagnóstico nunca deve falhar
                detail = {"error": str(exc)}
        result.append(
            ConnectorStatusOut(
                connector=name,
                configured=adapter.is_configured(),
                reliability=adapter.reliability,
                detail=detail,
            )
        )
    return result
