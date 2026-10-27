"""Saldo das carteiras por plataforma (painel Financeiro).

Revision ID: 0024_wallet_balances
Revises: 0023_agent_reports
Create Date: 2026-10-27 00:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_wallet_balances"
down_revision: str | None = "0023_agent_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wallet_balances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform", sa.String(24), nullable=False),
        sa.Column("balance_brl", sa.Float(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(12), nullable=False),
        sa.Column("note", sa.String(200)),
        sa.Column("created_by", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_wallet_balances_platform", "wallet_balances", ["platform"])
    op.create_index("ix_wallet_balances_as_of", "wallet_balances", ["as_of"])


def downgrade() -> None:
    op.drop_table("wallet_balances")
