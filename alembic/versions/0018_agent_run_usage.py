"""Add consumo (modelo, turnos, tokens, custo) em agent_runs.

Revision ID: 0018_agent_run_usage
Revises: 0017_agent_runs
Create Date: 2026-10-22 00:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_agent_run_usage"
down_revision: str | None = "0017_agent_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("model", sa.String(48)))
    op.add_column("agent_runs", sa.Column("num_turns", sa.Integer()))
    op.add_column("agent_runs", sa.Column("tokens_in", sa.Integer()))
    op.add_column("agent_runs", sa.Column("tokens_out", sa.Integer()))
    op.add_column("agent_runs", sa.Column("cost_usd", sa.Float()))


def downgrade() -> None:
    for col in ("cost_usd", "tokens_out", "tokens_in", "num_turns", "model"):
        op.drop_column("agent_runs", col)
