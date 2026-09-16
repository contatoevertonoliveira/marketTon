"""Endpoints do pipeline criativo (briefing seção 8).

Cada produto tem estados independentes por tipo de material (COPY, IMAGE, VIDEO,
VOICE, EDIT, APPROVAL, PUBLICATION). O operador atualiza o status manualmente —
é o que o briefing chama de controle de demanda enquanto o AI Studio não está
integrado por API.

Duas regras aplicadas aqui:

* **Toda mudança de status vira evento** em `creative_asset_events`, com autor e
  nota. Sem isso o histórico do material se perderia e a aprovação não teria
  responsável.
* **A versão mais recente é a que vale** para o portão de publicação. Uma revisão
  nova em PENDING volta a bloquear `READY_TO_PUBLISH`, mesmo que a versão anterior
  estivesse aprovada — publicar a versão antiga seria publicar o material errado.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.deps import get_session
from backend.security import Principal, get_principal, require
from backend.serializers import creative_asset_out
from backend.schemas import CreativeAssetCreate, CreativeAssetOut, CreativeStatusUpdate
from core.db.base import CreativeAssetType, CreativeStatus
from core.db.creative import CreativeAsset, CreativeAssetEvent
from core.db.portfolio import PortfolioItem

router = APIRouter(
    prefix="/creatives",
    tags=["criativos"],
    dependencies=[Depends(require("creatives.view"))],
)

# Transições de status permitidas. Aprovar é terminal; rejeitar devolve a PENDING.
ALLOWED_STATUS_TRANSITIONS: dict[CreativeStatus, frozenset[CreativeStatus]] = {
    CreativeStatus.PENDING: frozenset(
        {CreativeStatus.IN_PROGRESS, CreativeStatus.READY, CreativeStatus.BLOCKED}
    ),
    CreativeStatus.IN_PROGRESS: frozenset(
        {CreativeStatus.READY, CreativeStatus.BLOCKED, CreativeStatus.PENDING}
    ),
    CreativeStatus.READY: frozenset(
        {CreativeStatus.APPROVED, CreativeStatus.REJECTED, CreativeStatus.BLOCKED, CreativeStatus.IN_PROGRESS}
    ),
    CreativeStatus.APPROVED: frozenset({CreativeStatus.REJECTED, CreativeStatus.BLOCKED}),
    CreativeStatus.REJECTED: frozenset({CreativeStatus.IN_PROGRESS, CreativeStatus.PENDING}),
    CreativeStatus.BLOCKED: frozenset({CreativeStatus.PENDING, CreativeStatus.IN_PROGRESS}),
}


@router.get("/assets", response_model=list[CreativeAssetOut])
def list_assets(
    session: Session = Depends(get_session),
    portfolio_item_id: int | None = None,
    product_id: int | None = None,
    asset_type: CreativeAssetType | None = None,
    status: CreativeStatus | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[CreativeAssetOut]:
    statement = select(CreativeAsset)
    if portfolio_item_id is not None:
        statement = statement.where(CreativeAsset.portfolio_item_id == portfolio_item_id)
    if product_id is not None:
        statement = statement.where(CreativeAsset.product_id == product_id)
    if asset_type is not None:
        statement = statement.where(CreativeAsset.asset_type == asset_type)
    if status is not None:
        statement = statement.where(CreativeAsset.status == status)

    statement = (
        statement.order_by(CreativeAsset.status_changed_at.desc()).limit(limit).offset(offset)
    )
    return [creative_asset_out(asset) for asset in session.scalars(statement)]


@router.get("/pending", response_model=list[CreativeAssetOut])
def pending_assets(
    session: Session = Depends(get_session),
    limit: int = Query(100, ge=1, le=500),
) -> list[CreativeAssetOut]:
    """Materiais que ainda exigem trabalho. Alimenta o painel do briefing §9."""
    statement = (
        select(CreativeAsset)
        .where(
            CreativeAsset.status.in_(
                [CreativeStatus.PENDING, CreativeStatus.IN_PROGRESS, CreativeStatus.BLOCKED]
            )
        )
        .order_by(CreativeAsset.status_changed_at.asc())
        .limit(limit)
    )
    return [creative_asset_out(asset) for asset in session.scalars(statement)]


@router.get("/ready", response_model=list[CreativeAssetOut])
def ready_assets(
    session: Session = Depends(get_session),
    limit: int = Query(100, ge=1, le=500),
) -> list[CreativeAssetOut]:
    """Materiais prontos ou aprovados, aguardando publicação."""
    statement = (
        select(CreativeAsset)
        .where(CreativeAsset.status.in_([CreativeStatus.READY, CreativeStatus.APPROVED]))
        .order_by(CreativeAsset.status_changed_at.desc())
        .limit(limit)
    )
    return [creative_asset_out(asset) for asset in session.scalars(statement)]


@router.get("/assets/{asset_id}", response_model=CreativeAssetOut)
def get_asset(asset_id: int, session: Session = Depends(get_session)) -> CreativeAssetOut:
    asset = session.get(CreativeAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"material {asset_id} não encontrado")
    return creative_asset_out(asset)


@router.post(
    "/assets",
    response_model=CreativeAssetOut,
    status_code=201,
    dependencies=[Depends(require("creatives.edit"))],
)
def create_asset(
    payload: CreativeAssetCreate, session: Session = Depends(get_session)
) -> CreativeAssetOut:
    """Cria um material do pipeline.

    `portfolio_item_id` é opcional para permitir registrar material de produto que
    ainda não entrou no portfólio — mas nesse caso o portão de publicação não se
    aplica, porque não há item para publicar.
    """
    try:
        asset_type = CreativeAssetType(payload.asset_type)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=(
                f"tipo desconhecido: {payload.asset_type}. "
                f"Válidos: {[item.value for item in CreativeAssetType]}"
            ),
        ) from None

    if payload.portfolio_item_id is not None:
        if session.get(PortfolioItem, payload.portfolio_item_id) is None:
            raise HTTPException(
                status_code=404, detail=f"item de portfólio {payload.portfolio_item_id} não encontrado"
            )

    now = datetime.now(UTC)
    asset = CreativeAsset(
        asset_type=asset_type,
        portfolio_item_id=payload.portfolio_item_id,
        product_id=payload.product_id,
        status=CreativeStatus.PENDING,
        status_changed_at=now,
        version=1,
        title=payload.title,
        content_text=payload.content_text,
        content_url=payload.content_url,
        external_system=payload.external_system,
        external_ref=payload.external_ref,
    )
    session.add(asset)
    session.flush()

    session.add(
        CreativeAssetEvent(
            asset_id=asset.id,
            from_status=None,
            to_status=CreativeStatus.PENDING,
            occurred_at=now,
            actor="operator",
            note="material criado",
        )
    )
    session.commit()
    session.refresh(asset)
    return creative_asset_out(asset)


@router.post(
    "/assets/{asset_id}/status",
    response_model=CreativeAssetOut,
    dependencies=[Depends(require("creatives.edit"))],
)
def update_status(
    asset_id: int,
    payload: CreativeStatusUpdate,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
) -> CreativeAssetOut:
    """Atualiza o status do material, validando a transição e registrando o evento.

    Aprovar exige uma permissão adicional (`creatives.approve`), checada aqui e não
    no router: só o alvo APPROVED é uma decisão de liberação, e o portão de
    publicação do briefing seção 8 depende dela. Quem edita material não deve
    necessariamente poder liberá-lo.
    """
    asset = session.get(CreativeAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"material {asset_id} não encontrado")

    try:
        target = CreativeStatus(payload.status)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=(
                f"status desconhecido: {payload.status}. "
                f"Válidos: {[item.value for item in CreativeStatus]}"
            ),
        ) from None

    if target == CreativeStatus.APPROVED and not principal.can("creatives.approve"):
        raise HTTPException(
            status_code=403,
            detail={
                "message": "permissão negada: 'creatives.approve' é exigida para aprovar material",
                "role": principal.role.value,
            },
        )

    allowed = ALLOWED_STATUS_TRANSITIONS.get(asset.status, frozenset())
    if target not in allowed:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"transição de {asset.status.value} para {target.value} não é permitida",
                "current_status": asset.status.value,
                "requested_status": target.value,
                "allowed_transitions": sorted(item.value for item in allowed),
            },
        )

    now = datetime.now(UTC)
    previous = asset.status
    asset.status = target
    asset.status_changed_at = now

    if target == CreativeStatus.APPROVED:
        asset.approved_by = payload.actor
        asset.approved_at = now
    elif target == CreativeStatus.REJECTED:
        asset.rejection_reason = payload.note
    elif target == CreativeStatus.BLOCKED:
        asset.blocked_reason = payload.note

    session.add(
        CreativeAssetEvent(
            asset_id=asset.id,
            from_status=previous,
            to_status=target,
            occurred_at=now,
            actor=payload.actor,
            note=payload.note,
        )
    )
    session.commit()
    session.refresh(asset)
    return creative_asset_out(asset)


@router.get("/assets/{asset_id}/history")
def asset_history(asset_id: int, session: Session = Depends(get_session)) -> list[dict]:
    """Histórico de status do material: quem mudou, quando e com que nota."""
    asset = session.get(CreativeAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"material {asset_id} não encontrado")

    return [
        {
            "occurred_at": event.occurred_at.isoformat(),
            "from_status": event.from_status.value if event.from_status else None,
            "to_status": event.to_status.value,
            "actor": event.actor,
            "note": event.note,
        }
        for event in sorted(asset.events, key=lambda event: event.occurred_at)
    ]


@router.get("/publish-readiness/{portfolio_item_id}")
def publish_readiness(portfolio_item_id: int, session: Session = Depends(get_session)) -> dict:
    """O que falta para poder publicar este item.

    Responde à pergunta do operador sem que ele precise conhecer a regra: o backend
    calcula o que está pendente e o que já está satisfeito.
    """
    from core.services.portfolio import (
        REQUIRED_ASSETS_FOR_PUBLISH,
        READY_STATUSES_BY_TYPE,
        missing_assets_for_publish,
    )

    item = session.get(PortfolioItem, portfolio_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"item {portfolio_item_id} não encontrado")

    missing = missing_assets_for_publish(session, item)
    assets = list(
        session.scalars(
            select(CreativeAsset).where(CreativeAsset.portfolio_item_id == portfolio_item_id)
        )
    )
    by_type: dict[str, dict] = {}
    for asset in assets:
        current = by_type.get(asset.asset_type.value)
        if current is None or asset.version > current["version"]:
            by_type[asset.asset_type.value] = {
                "status": asset.status.value,
                "version": asset.version,
            }

    required = sorted(item.value for item in REQUIRED_ASSETS_FOR_PUBLISH)
    satisfied = []
    for asset_type in REQUIRED_ASSETS_FOR_PUBLISH:
        present = by_type.get(asset_type.value)
        if present is None:
            continue
        if CreativeStatus(present["status"]) in READY_STATUSES_BY_TYPE.get(asset_type, frozenset()):
            satisfied.append(asset_type.value)

    return {
        "portfolio_item_id": portfolio_item_id,
        "state": item.state.value,
        "can_publish": not missing,
        "required_assets": required,
        "satisfied_assets": satisfied,
        "missing_assets": missing,
        "assets": by_type,
    }
