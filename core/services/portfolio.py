"""Máquina de estados do portfólio (briefing seção 7).

As transições são controladas pelo backend — o frontend nunca decide estado.
Duas garantias explícitas:

1. `ALLOWED_TRANSITIONS` é a única fonte de verdade sobre o que é permitido.
2. `READY_TO_PUBLISH` só é alcançável quando todos os materiais obrigatórios do
   pipeline criativo estão prontos. Sem isso, o estado seria apenas um rótulo
   digitado pelo operador, e o briefing seção 8 pede que os estados dos
   materiais *bloqueiem* a publicação.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.base import CreativeAssetType, CreativeStatus, PortfolioState
from core.db.creative import CreativeAsset
from core.db.portfolio import PortfolioItem, PortfolioTransition

# Estados que encerram o ciclo de vida do item.
TERMINAL_STATES = frozenset({PortfolioState.REMOVED})

# Grafo de transições permitidas. Toda transição ausente desta tabela é rejeitada.
ALLOWED_TRANSITIONS: dict[PortfolioState, frozenset[PortfolioState]] = {
    PortfolioState.DISCOVERED: frozenset(
        {PortfolioState.ANALYZING, PortfolioState.WATCHLIST, PortfolioState.REMOVED}
    ),
    PortfolioState.ANALYZING: frozenset(
        {
            PortfolioState.WATCHLIST,
            PortfolioState.RECOMMENDED,
            PortfolioState.DISCOVERED,
            PortfolioState.REMOVED,
        }
    ),
    PortfolioState.WATCHLIST: frozenset(
        {PortfolioState.ANALYZING, PortfolioState.RECOMMENDED, PortfolioState.REMOVED}
    ),
    PortfolioState.RECOMMENDED: frozenset(
        {PortfolioState.AFFILIATION_PENDING, PortfolioState.WATCHLIST, PortfolioState.REMOVED}
    ),
    PortfolioState.AFFILIATION_PENDING: frozenset(
        {PortfolioState.AFFILIATED, PortfolioState.RECOMMENDED, PortfolioState.REMOVED}
    ),
    PortfolioState.AFFILIATED: frozenset(
        {PortfolioState.PORTFOLIO_ACTIVE, PortfolioState.CREATIVE_PENDING, PortfolioState.REMOVED}
    ),
    PortfolioState.PORTFOLIO_ACTIVE: frozenset(
        {
            PortfolioState.CREATIVE_PENDING,
            PortfolioState.PAUSED,
            PortfolioState.REMOVED,
        }
    ),
    PortfolioState.CREATIVE_PENDING: frozenset(
        {
            PortfolioState.READY_TO_PUBLISH,
            PortfolioState.PORTFOLIO_ACTIVE,
            PortfolioState.PAUSED,
            PortfolioState.REMOVED,
        }
    ),
    PortfolioState.READY_TO_PUBLISH: frozenset(
        {
            PortfolioState.PUBLISHED,
            PortfolioState.CREATIVE_PENDING,
            PortfolioState.PAUSED,
            PortfolioState.REMOVED,
        }
    ),
    PortfolioState.PUBLISHED: frozenset(
        {
            PortfolioState.MONITORING,
            PortfolioState.OPTIMIZATION_REQUIRED,
            PortfolioState.SCALING,
            PortfolioState.PAUSED,
            PortfolioState.REMOVED,
        }
    ),
    PortfolioState.MONITORING: frozenset(
        {
            PortfolioState.OPTIMIZATION_REQUIRED,
            PortfolioState.SCALING,
            PortfolioState.PAUSED,
            PortfolioState.REMOVED,
        }
    ),
    PortfolioState.OPTIMIZATION_REQUIRED: frozenset(
        {
            PortfolioState.CREATIVE_PENDING,
            PortfolioState.PUBLISHED,
            PortfolioState.MONITORING,
            PortfolioState.SCALING,
            PortfolioState.PAUSED,
            PortfolioState.REMOVED,
        }
    ),
    PortfolioState.SCALING: frozenset(
        {
            PortfolioState.MONITORING,
            PortfolioState.OPTIMIZATION_REQUIRED,
            PortfolioState.PAUSED,
            PortfolioState.REMOVED,
        }
    ),
    PortfolioState.PAUSED: frozenset(
        {
            PortfolioState.PORTFOLIO_ACTIVE,
            PortfolioState.PUBLISHED,
            PortfolioState.MONITORING,
            PortfolioState.REMOVED,
        }
    ),
    # REMOVED é terminal. Reentrada exigiria um novo item de portfólio.
    PortfolioState.REMOVED: frozenset(),
}

# Materiais que precisam estar prontos para publicar. COPY é o mínimo: sem copy
# não há o que publicar; imagem/vídeo variam por canal.
REQUIRED_ASSETS_FOR_PUBLISH = frozenset({CreativeAssetType.COPY, CreativeAssetType.APPROVAL})
# Status que satisfazem "pronto" por tipo de material.
READY_STATUSES_BY_TYPE: dict[CreativeAssetType, frozenset[CreativeStatus]] = {
    CreativeAssetType.COPY: frozenset({CreativeStatus.READY, CreativeStatus.APPROVED}),
    CreativeAssetType.IMAGE: frozenset({CreativeStatus.READY, CreativeStatus.APPROVED}),
    CreativeAssetType.VIDEO: frozenset({CreativeStatus.READY, CreativeStatus.APPROVED}),
    CreativeAssetType.VOICE: frozenset({CreativeStatus.READY, CreativeStatus.APPROVED}),
    CreativeAssetType.EDIT: frozenset({CreativeStatus.READY, CreativeStatus.APPROVED}),
    CreativeAssetType.APPROVAL: frozenset({CreativeStatus.APPROVED}),
    CreativeAssetType.PUBLICATION: frozenset({CreativeStatus.READY, CreativeStatus.APPROVED}),
}


class TransitionError(ValueError):
    """Transição de estado inválida. Rejeitada pelo backend, não pelo frontend."""


@dataclass(frozen=True)
class TransitionCheck:
    allowed: bool
    reason: str | None = None


def is_transition_allowed(current: PortfolioState, target: PortfolioState) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def missing_assets_for_publish(session: Session, item: PortfolioItem) -> list[str]:
    """Materiais obrigatórios que ainda não estão prontos.

    Devolve os nomes legíveis, para que o operador entenda exatamente o que falta
    em vez de receber apenas "transição negada".
    """
    if item.id is None:
        return sorted(asset.value for asset in REQUIRED_ASSETS_FOR_PUBLISH)

    assets = list(
        session.scalars(
            select(CreativeAsset).where(CreativeAsset.portfolio_item_id == item.id)
        )
    )
    by_type: dict[CreativeAssetType, list[CreativeAsset]] = {}
    for asset in assets:
        by_type.setdefault(asset.asset_type, []).append(asset)

    missing: list[str] = []
    for asset_type in sorted(REQUIRED_ASSETS_FOR_PUBLISH, key=lambda a: a.value):
        candidates = by_type.get(asset_type)
        if not candidates:
            missing.append(asset_type.value)
            continue
        # A versão mais recente é a que vale.
        latest = max(candidates, key=lambda asset: asset.version)
        allowed = READY_STATUSES_BY_TYPE.get(asset_type, frozenset({CreativeStatus.READY}))
        if latest.status not in allowed:
            missing.append(f"{asset_type.value} ({latest.status.value})")
    return missing


def check_transition(
    session: Session,
    item: PortfolioItem,
    target: PortfolioState,
) -> TransitionCheck:
    """Valida uma transição sem aplicá-la. Usado pela API e pelos agentes."""
    current = item.state

    if current == target:
        return TransitionCheck(False, f"o item já está em {current.value}")

    if not is_transition_allowed(current, target):
        allowed = ", ".join(sorted(state.value for state in ALLOWED_TRANSITIONS.get(current, frozenset())))
        return TransitionCheck(
            False,
            f"transição de {current.value} para {target.value} não é permitida. "
            f"Permitidas a partir de {current.value}: {allowed or 'nenhuma (estado terminal)'}",
        )

    if target == PortfolioState.READY_TO_PUBLISH:
        missing = missing_assets_for_publish(session, item)
        if missing:
            return TransitionCheck(
                False,
                "materiais obrigatórios pendentes: " + ", ".join(missing),
            )

    return TransitionCheck(True)


def apply_transition(
    session: Session,
    item: PortfolioItem,
    target: PortfolioState,
    *,
    actor: str,
    reason: str | None = None,
    recommendation_id: int | None = None,
    occurred_at: datetime | None = None,
) -> PortfolioTransition:
    """Valida e aplica a transição, registrando a trilha de auditoria.

    Levanta `TransitionError` se a transição não for permitida — o chamador não
    pode contornar a regra.
    """
    check = check_transition(session, item, target)
    if not check.allowed:
        raise TransitionError(check.reason or "transição inválida")

    occurred_at = occurred_at or datetime.now(UTC)
    previous = item.state

    item.state = target
    item.state_changed_at = occurred_at
    if target == PortfolioState.PAUSED and reason:
        item.paused_reason = reason
    if target == PortfolioState.REMOVED:
        item.removed_at = occurred_at
        item.removed_reason = reason

    transition = PortfolioTransition(
        portfolio_item_id=item.id,
        from_state=previous,
        to_state=target,
        occurred_at=occurred_at,
        actor=actor,
        reason=reason,
        triggered_by_recommendation_id=recommendation_id,
    )
    session.add(transition)
    session.flush()
    return transition


def allowed_targets(current: PortfolioState) -> list[str]:
    return sorted(state.value for state in ALLOWED_TRANSITIONS.get(current, frozenset()))


__all__ = [
    "ALLOWED_TRANSITIONS",
    "READY_STATUSES_BY_TYPE",
    "REQUIRED_ASSETS_FOR_PUBLISH",
    "TERMINAL_STATES",
    "TransitionCheck",
    "TransitionError",
    "allowed_targets",
    "apply_transition",
    "check_transition",
    "is_transition_allowed",
    "missing_assets_for_publish",
]
