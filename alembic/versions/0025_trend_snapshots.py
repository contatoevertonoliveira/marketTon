"""Radar de tendências: retrato diário da busca por palavra.

Revision ID: 0025_trend_snapshots
Revises: 0024_wallet_balances
Create Date: 2026-10-27 00:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_trend_snapshots"
down_revision: str | None = "0024_wallet_balances"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trend_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("keyword", sa.String(120), nullable=False),
        sa.Column("geo", sa.String(8), nullable=False),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interest_last", sa.Float()),
        sa.Column("growth_7d", sa.Float()),
        sa.Column("growth_15d", sa.Float()),
        sa.Column("growth_30d", sa.Float()),
        sa.Column("monthly_volume", sa.Integer()),
        sa.Column("cpc_brl", sa.Float()),
        sa.Column("competition", sa.String(12)),
        sa.Column("rising", sa.Boolean(), nullable=False),
        sa.Column("error", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_trend_snapshots_keyword", "trend_snapshots", ["keyword"])
    op.create_index("ix_trend_snapshots_taken_at", "trend_snapshots", ["taken_at"])
    op.create_index("ix_trend_snapshots_rising", "trend_snapshots", ["rising"])


def downgrade() -> None:
    op.drop_table("trend_snapshots")
