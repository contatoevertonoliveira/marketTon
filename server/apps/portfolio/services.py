"""State machine enforcement for PortfolioItem (briefing §7: "as transições
deverão ser controladas pelo backend"). Nothing outside this module should
write PortfolioItem.state directly.
"""
from __future__ import annotations

from django.db import transaction

from .models import PortfolioItem, PortfolioStateTransition

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "DISCOVERED": {"ANALYZING", "REMOVED"},
    "ANALYZING": {"WATCHLIST", "REMOVED"},
    "WATCHLIST": {"ANALYZING", "RECOMMENDED", "REMOVED"},
    "RECOMMENDED": {"WATCHLIST", "AFFILIATION_PENDING", "REMOVED"},
    "AFFILIATION_PENDING": {"AFFILIATED", "RECOMMENDED", "REMOVED"},
    "AFFILIATED": {"PORTFOLIO_ACTIVE", "REMOVED"},
    "PORTFOLIO_ACTIVE": {"CREATIVE_PENDING", "PAUSED", "REMOVED"},
    "CREATIVE_PENDING": {"READY_TO_PUBLISH", "PORTFOLIO_ACTIVE", "REMOVED"},
    "READY_TO_PUBLISH": {"PUBLISHED", "CREATIVE_PENDING", "REMOVED"},
    "PUBLISHED": {"MONITORING", "REMOVED"},
    "MONITORING": {"OPTIMIZATION_REQUIRED", "SCALING", "PAUSED", "REMOVED"},
    "OPTIMIZATION_REQUIRED": {"MONITORING", "SCALING", "PAUSED", "REMOVED"},
    "SCALING": {"MONITORING", "PAUSED", "REMOVED"},
    "PAUSED": {"MONITORING", "WATCHLIST", "REMOVED"},
    "REMOVED": set(),
}


class InvalidTransition(Exception):
    pass


@transaction.atomic
def transition(item: PortfolioItem, to_state: str, *, reason: str = "", actor: str = "") -> PortfolioItem:
    allowed = ALLOWED_TRANSITIONS.get(item.state, set())
    if to_state not in allowed:
        raise InvalidTransition(f"{item.state} -> {to_state} is not an allowed transition")
    PortfolioStateTransition.objects.create(
        portfolio_item=item,
        from_state=item.state,
        to_state=to_state,
        reason=reason,
        actor=actor,
    )
    item.state = to_state
    item.save(update_fields=["state", "updated_at"])
    return item
