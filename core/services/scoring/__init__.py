"""Motor de scoring: dimensões versionadas e explicáveis (briefing seções 5 e 6)."""
from __future__ import annotations

from core.services.scoring.engine import (
    AlgorithmSpec,
    ContributionResult,
    ScoreResult,
    active_spec,
    all_specs,
    compute,
    ensure_algorithm,
    get_spec,
    load_specs,
    persist_run,
    register,
)

__all__ = [
    "AlgorithmSpec",
    "ContributionResult",
    "ScoreResult",
    "active_spec",
    "all_specs",
    "compute",
    "ensure_algorithm",
    "get_spec",
    "load_specs",
    "persist_run",
    "register",
]
