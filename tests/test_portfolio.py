"""Testes da máquina de estados do portfólio (briefing seção 7) e do portão de
publicação (briefing seção 8).

O ponto central: `READY_TO_PUBLISH` não é um rótulo que o operador digita. Ele só
é alcançável quando os materiais obrigatórios estão prontos — caso contrário o
estado mentiria sobre a realidade da operação.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.db.base import CreativeAssetType, CreativeStatus, Marketplace, PortfolioState
from core.db.creative import CreativeAsset
from core.db.portfolio import PortfolioItem, PortfolioTransition
from core.services.portfolio import (
    ALLOWED_TRANSITIONS,
    REQUIRED_ASSETS_FOR_PUBLISH,
    TERMINAL_STATES,
    TransitionError,
    allowed_targets,
    apply_transition,
    check_transition,
    is_transition_allowed,
    missing_assets_for_publish,
)


@pytest.fixture
def item(session, product):
    now = datetime.now(UTC)
    portfolio_item = PortfolioItem(
        product_id=product.id,
        marketplace=Marketplace.MERCADO_LIVRE,
        label="Fone Bluetooth Mini",
        state=PortfolioState.DISCOVERED,
        state_changed_at=now,
        added_by="test",
    )
    session.add(portfolio_item)
    session.flush()
    return portfolio_item


def _add_asset(session, item, asset_type: CreativeAssetType, status: CreativeStatus):
    asset = CreativeAsset(
        portfolio_item_id=item.id,
        asset_type=asset_type,
        status=status,
        status_changed_at=datetime.now(UTC),
        version=1,
    )
    session.add(asset)
    session.flush()
    return asset


class TestTransitionGraph:
    def test_every_state_has_an_entry_in_the_graph(self) -> None:
        """Um estado sem entrada no grafo seria inalcançável ou travado."""
        for state in PortfolioState:
            assert state in ALLOWED_TRANSITIONS, f"{state.value} fora do grafo"

    def test_removed_is_terminal(self) -> None:
        assert ALLOWED_TRANSITIONS[PortfolioState.REMOVED] == frozenset()
        assert PortfolioState.REMOVED in TERMINAL_STATES
        assert allowed_targets(PortfolioState.REMOVED) == []

    def test_every_non_terminal_state_reaches_removal(self) -> None:
        """Nenhum estado pode ser uma armadilha: sempre há saída para REMOVED."""
        for state in PortfolioState:
            if state in TERMINAL_STATES:
                continue
            assert _reaches_removed(state), f"{state.value} não tem caminho até REMOVED"

    def test_recommended_requires_affiliation_path(self) -> None:
        """Briefing seção 7: recomendado passa por afiliação antes de entrar no portfólio."""
        assert is_transition_allowed(PortfolioState.RECOMMENDED, PortfolioState.AFFILIATION_PENDING)
        assert is_transition_allowed(PortfolioState.AFFILIATION_PENDING, PortfolioState.AFFILIATED)
        assert is_transition_allowed(PortfolioState.AFFILIATED, PortfolioState.PORTFOLIO_ACTIVE)

    def test_cannot_skip_from_discovered_to_published(self) -> None:
        assert not is_transition_allowed(PortfolioState.DISCOVERED, PortfolioState.PUBLISHED)


def _reaches_removed(start: PortfolioState, seen: set | None = None) -> bool:
    seen = seen or set()
    if start in seen:
        return False
    seen.add(start)
    for target in ALLOWED_TRANSITIONS.get(start, frozenset()):
        if target == PortfolioState.REMOVED:
            return True
        if _reaches_removed(target, seen):
            return True
    return False


class TestCheckTransition:
    def test_rejects_invalid_transition_with_explanation(self, session, item) -> None:
        check = check_transition(session, item, PortfolioState.PUBLISHED)
        assert not check.allowed
        assert "não é permitida" in (check.reason or "")
        # A mensagem precisa dizer o que É permitido, para ser acionável.
        assert "ANALYZING" in (check.reason or "")

    def test_rejects_no_op_transition(self, session, item) -> None:
        check = check_transition(session, item, PortfolioState.DISCOVERED)
        assert not check.allowed
        assert "já está" in (check.reason or "")

    def test_terminal_state_message_is_explicit(self, session, item) -> None:
        apply_transition(session, item, PortfolioState.ANALYZING, actor="test")
        apply_transition(session, item, PortfolioState.REMOVED, actor="test")
        check = check_transition(session, item, PortfolioState.ANALYZING)
        assert not check.allowed
        assert "estado terminal" in (check.reason or "")


class TestPublishGate:
    def test_missing_assets_block_ready_to_publish(self, session, item) -> None:
        """Sem materiais prontos, o estado é negado com a lista do que falta."""
        _walk_to_creative_pending(session, item)

        check = check_transition(session, item, PortfolioState.READY_TO_PUBLISH)
        assert not check.allowed
        assert "materiais obrigatórios pendentes" in (check.reason or "")
        for asset_type in REQUIRED_ASSETS_FOR_PUBLISH:
            assert asset_type.value in (check.reason or "")

    def test_apply_raises_when_gate_is_closed(self, session, item) -> None:
        _walk_to_creative_pending(session, item)
        with pytest.raises(TransitionError, match="materiais obrigatórios pendentes"):
            apply_transition(session, item, PortfolioState.READY_TO_PUBLISH, actor="test")

    def test_copy_ready_but_approval_pending_still_blocks(self, session, item) -> None:
        """Aprovação é um material de primeira classe, não uma formalidade."""
        _walk_to_creative_pending(session, item)
        _add_asset(session, item, CreativeAssetType.COPY, CreativeStatus.READY)

        missing = missing_assets_for_publish(session, item)
        assert missing == ["APPROVAL"]
        assert not check_transition(session, item, PortfolioState.READY_TO_PUBLISH).allowed

    def test_ready_when_copy_ready_and_approval_approved(self, session, item) -> None:
        _walk_to_creative_pending(session, item)
        _add_asset(session, item, CreativeAssetType.COPY, CreativeStatus.READY)
        _add_asset(session, item, CreativeAssetType.APPROVAL, CreativeStatus.APPROVED)

        assert missing_assets_for_publish(session, item) == []
        check = check_transition(session, item, PortfolioState.READY_TO_PUBLISH)
        assert check.allowed, check.reason

    def test_approved_copy_satisfies_the_copy_requirement(self, session, item) -> None:
        _walk_to_creative_pending(session, item)
        _add_asset(session, item, CreativeAssetType.COPY, CreativeStatus.APPROVED)
        _add_asset(session, item, CreativeAssetType.APPROVAL, CreativeStatus.APPROVED)
        assert check_transition(session, item, PortfolioState.READY_TO_PUBLISH).allowed

    def test_blocked_asset_does_not_satisfy_the_gate(self, session, item) -> None:
        _walk_to_creative_pending(session, item)
        _add_asset(session, item, CreativeAssetType.COPY, CreativeStatus.BLOCKED)
        _add_asset(session, item, CreativeAssetType.APPROVAL, CreativeStatus.APPROVED)

        missing = missing_assets_for_publish(session, item)
        assert missing == ["COPY (BLOCKED)"]

    def test_latest_version_is_the_one_that_counts(self, session, item) -> None:
        """Uma revisão nova não pode ser aprovada pelo status da versão anterior."""
        _walk_to_creative_pending(session, item)
        _add_asset(session, item, CreativeAssetType.COPY, CreativeStatus.READY)
        _add_asset(session, item, CreativeAssetType.APPROVAL, CreativeStatus.APPROVED)

        # v2 do copy volta para PENDING: o material publicado seria o antigo.
        revision = CreativeAsset(
            portfolio_item_id=item.id,
            asset_type=CreativeAssetType.COPY,
            status=CreativeStatus.PENDING,
            status_changed_at=datetime.now(UTC),
            version=2,
        )
        session.add(revision)
        session.flush()

        assert missing_assets_for_publish(session, item) == ["COPY (PENDING)"]
        assert not check_transition(session, item, PortfolioState.READY_TO_PUBLISH).allowed


class TestApplyTransition:
    def test_applies_and_records_audit_trail(self, session, item) -> None:
        transition = apply_transition(
            session,
            item,
            PortfolioState.ANALYZING,
            actor="agent:master",
            reason="score de oportunidade acima do limiar",
        )

        assert item.state == PortfolioState.ANALYZING
        assert item.state_changed_at is not None
        assert transition.from_state == PortfolioState.DISCOVERED
        assert transition.to_state == PortfolioState.ANALYZING
        assert transition.actor == "agent:master"
        assert transition.reason == "score de oportunidade acima do limiar"
        assert session.query(PortfolioTransition).count() == 1

    def test_full_happy_path_to_published(self, session, item) -> None:
        _walk_to_creative_pending(session, item)
        _add_asset(session, item, CreativeAssetType.COPY, CreativeStatus.READY)
        _add_asset(session, item, CreativeAssetType.APPROVAL, CreativeStatus.APPROVED)

        apply_transition(session, item, PortfolioState.READY_TO_PUBLISH, actor="operator:everton")
        apply_transition(session, item, PortfolioState.PUBLISHED, actor="operator:everton")
        apply_transition(session, item, PortfolioState.MONITORING, actor="agent:growth_analyst")
        apply_transition(session, item, PortfolioState.SCALING, actor="operator:everton")

        assert item.state == PortfolioState.SCALING
        # 6 para chegar a CREATIVE_PENDING + READY_TO_PUBLISH + PUBLISHED +
        # MONITORING + SCALING.
        assert session.query(PortfolioTransition).count() == 10

    def test_paused_records_the_reason(self, session, item) -> None:
        _walk_to_published(session, item)
        apply_transition(
            session,
            item,
            PortfolioState.PAUSED,
            actor="operator:everton",
            reason="CTR caiu abaixo de 0,8%",
        )
        assert item.paused_reason == "CTR caiu abaixo de 0,8%"

    def test_removed_records_timestamp_and_reason(self, session, item) -> None:
        apply_transition(session, item, PortfolioState.REMOVED, actor="operator:everton", reason="produto saiu de linha")
        assert item.removed_at is not None
        assert item.removed_reason == "produto saiu de linha"

    def test_transition_links_to_the_recommendation_that_caused_it(self, session, item) -> None:
        """Briefing seção 11: a decisão precisa ficar ligada à previsão que a originou."""
        from core.db.portfolio import Recommendation
        from core.db.base import RecommendationKind

        recommendation = Recommendation(
            portfolio_item_id=item.id,
            kind=RecommendationKind.ANALYZE,
            title="Analisar Fone Bluetooth Mini",
        )
        session.add(recommendation)
        session.flush()

        transition = apply_transition(
            session,
            item,
            PortfolioState.ANALYZING,
            actor="agent:master",
            recommendation_id=recommendation.id,
        )
        assert transition.triggered_by_recommendation_id == recommendation.id


def _walk_to_creative_pending(session, item) -> None:
    for target in (
        PortfolioState.ANALYZING,
        PortfolioState.RECOMMENDED,
        PortfolioState.AFFILIATION_PENDING,
        PortfolioState.AFFILIATED,
        PortfolioState.PORTFOLIO_ACTIVE,
        PortfolioState.CREATIVE_PENDING,
    ):
        apply_transition(session, item, target, actor="test")


def _walk_to_published(session, item) -> None:
    _walk_to_creative_pending(session, item)
    _add_asset(session, item, CreativeAssetType.COPY, CreativeStatus.READY)
    _add_asset(session, item, CreativeAssetType.APPROVAL, CreativeStatus.APPROVED)
    apply_transition(session, item, PortfolioState.READY_TO_PUBLISH, actor="test")
    apply_transition(session, item, PortfolioState.PUBLISHED, actor="test")
