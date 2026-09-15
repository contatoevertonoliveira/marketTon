"""Endpoints do portfólio operacional (briefing seção 7).

O ponto central: **as transições de estado vivem no backend.** O frontend não
decide estado — ele propõe uma transição e a API valida contra o grafo
`ALLOWED_TRANSITIONS`, respeitando o portão de publicação do briefing seção 8.
Uma tentativa inválida devolve 409 com a lista do que *é* permitido, para que a
resposta seja acionável em vez de apenas negativa.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.deps import get_session
from backend.security import require
from backend.serializers import (
    creative_asset_out,
    portfolio_item_out,
    recommendation_out,
    transition_out,
)
from backend.schemas import (
    AddToPortfolioRequest,
    PortfolioItemDetail,
    PortfolioItemOut,
    PortfolioTransitionOut,
    RecommendationOut,
    TransitionRequest,
)
from core.db.base import Marketplace, PortfolioState, ScoreRunStatus
from core.db.catalog import Product
from core.db.creative import CreativeAsset
from core.db.portfolio import PortfolioItem, Recommendation
from core.db.scoring import ScoreRun
from core.services.portfolio import (
    ALLOWED_TRANSITIONS,
    TransitionError,
    allowed_targets,
    apply_transition,
)

router = APIRouter(
    prefix="/portfolio",
    tags=["portfólio"],
    dependencies=[Depends(require("portfolio.view"))],
)


def _load_item(session: Session, item_id: int) -> PortfolioItem:
    item = session.get(PortfolioItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"item de portfólio {item_id} não encontrado")
    return item


@router.get("/transitions", summary="Grafo de estados permitido")
def transition_graph() -> dict:
    """O grafo completo de transições, para o frontend desenhar o fluxo.

    Exposto porque o cliente precisa saber o que existe sem replicar a regra: a
    lista `allowed_transitions` de cada item é derivada daqui.
    """
    return {
        "states": [state.value for state in PortfolioState],
        "transitions": {
            state.value: sorted(target.value for target in targets)
            for state, targets in ALLOWED_TRANSITIONS.items()
        },
    }


@router.get("/items", response_model=list[PortfolioItemOut])
def list_items(
    session: Session = Depends(get_session),
    state: PortfolioState | None = None,
    marketplace: Marketplace | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[PortfolioItemOut]:
    statement = select(PortfolioItem)
    if state is not None:
        statement = statement.where(PortfolioItem.state == state)
    if marketplace is not None:
        statement = statement.where(PortfolioItem.marketplace == marketplace)
    statement = statement.order_by(PortfolioItem.state_changed_at.desc()).limit(limit).offset(offset)

    return [portfolio_item_out(session, item) for item in session.scalars(statement)]


@router.get("/items/{item_id}", response_model=PortfolioItemDetail)
def get_item(item_id: int, session: Session = Depends(get_session)) -> PortfolioItemDetail:
    """Detalhe com a trilha de auditoria, recomendações e materiais criativos."""
    item = _load_item(session, item_id)
    base = portfolio_item_out(session, item)

    return PortfolioItemDetail(
        **base.model_dump(),
        transitions=[transition_out(t) for t in sorted(item.transitions, key=lambda t: t.occurred_at)],
        recommendations=[recommendation_out(r) for r in item.recommendations],
        creatives=[
            creative_asset_out(asset)
            for asset in sorted(
                session.scalars(
                    select(CreativeAsset).where(CreativeAsset.portfolio_item_id == item.id)
                ),
                key=lambda a: (a.asset_type.value, a.version),
            )
        ],
    )


@router.post(
    "/items",
    response_model=PortfolioItemOut,
    status_code=201,
    dependencies=[Depends(require("portfolio.manage"))],
)
def add_item(
    payload: AddToPortfolioRequest, session: Session = Depends(get_session)
) -> PortfolioItemOut:
    """Adiciona um produto ao portfólio no estado inicial.

    O produto precisa existir: entrar no portfólio sem catálogo significaria um item
    sem procedência, e o item aponta para o produto que carrega a origem.
    """
    product = session.get(Product, payload.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail=f"produto {payload.product_id} não encontrado")

    existing = session.scalar(
        select(PortfolioItem).where(PortfolioItem.product_id == product.id)
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"produto {product.id} já está no portfólio (item {existing.id})",
        )

    now = datetime.now(UTC)
    item = PortfolioItem(
        product_id=product.id,
        marketplace=product.marketplace,
        label=payload.label or product.title,
        state=PortfolioState.DISCOVERED,
        state_changed_at=now,
        added_by=payload.added_by,
        notes=payload.notes,
    )

    # Congela o score de oportunidade vigente na entrada. O motor de aprendizado
    # compara esta previsão com o resultado real depois (briefing seção 11).
    entry = session.scalar(
        select(ScoreRun)
        .where(
            ScoreRun.target_type == "product",
            ScoreRun.target_id == product.id,
            ScoreRun.dimension == "OPPORTUNITY",
            ScoreRun.status == ScoreRunStatus.SUCCEEDED,
        )
        .order_by(ScoreRun.computed_at.desc())
    )
    if entry is not None:
        item.entry_score_run_id = entry.id
        item.entry_score = entry.score

    session.add(item)
    session.commit()
    session.refresh(item)
    return portfolio_item_out(session, item)


@router.post(
    "/items/{item_id}/transition",
    response_model=PortfolioTransitionOut,
    dependencies=[Depends(require("portfolio.manage"))],
)
def transition_item(
    item_id: int, payload: TransitionRequest, session: Session = Depends(get_session)
) -> PortfolioTransitionOut:
    """Aplica uma transição de estado, validada pelo backend.

    Devolve 409 quando a transição não é permitida, com o motivo e a lista do que
    é permitido a partir do estado atual.
    """
    item = _load_item(session, item_id)

    try:
        target = PortfolioState(payload.to_state)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=(
                f"estado desconhecido: {payload.to_state}. "
                f"Válidos: {[state.value for state in PortfolioState]}"
            ),
        ) from None

    try:
        transition = apply_transition(
            session,
            item,
            target,
            actor=payload.actor,
            reason=payload.reason,
            recommendation_id=payload.recommendation_id,
        )
    except TransitionError as exc:
        # 409 e não 400: o pedido está bem formado, conflita com o estado atual.
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "current_state": item.state.value,
                "requested_state": target.value,
                "allowed_transitions": allowed_targets(item.state),
            },
        ) from exc

    session.commit()
    session.refresh(transition)
    return transition_out(transition)


@router.get("/items/{item_id}/transitions", response_model=list[PortfolioTransitionOut])
def item_history(item_id: int, session: Session = Depends(get_session)) -> list[PortfolioTransitionOut]:
    """Trilha de auditoria: quem mudou o estado, quando e por quê."""
    item = _load_item(session, item_id)
    return [transition_out(t) for t in sorted(item.transitions, key=lambda t: t.occurred_at)]


@router.get("/recommendations", response_model=list[RecommendationOut])
def list_recommendations(
    session: Session = Depends(get_session),
    kind: str | None = None,
    only_open: bool = Query(True, description="Apenas as ainda não trabalhadas"),
    limit: int = Query(50, ge=1, le=200),
) -> list[RecommendationOut]:
    """Recomendações acionáveis, com a justificativa que as originou."""
    statement = select(Recommendation)
    if kind:
        statement = statement.where(Recommendation.kind == kind)
    if only_open:
        statement = statement.where(Recommendation.is_actioned.is_(False))
    statement = (
        statement.order_by(Recommendation.priority.desc(), Recommendation.created_at.desc()).limit(limit)
    )

    return [recommendation_out(item) for item in session.scalars(statement)]
