"""Relatórios do agente (verificações, achados, ações e ideias).

Revision ID: 0023_agent_reports
Revises: 0022_ad_meta_fields
Create Date: 2026-10-27 00:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_agent_reports"
down_revision: str | None = "0022_ad_meta_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("agent_runs.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("body", sa.Text()),
        sa.Column("author", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_agent_reports_run_id", "agent_reports", ["run_id"])
    op.create_index("ix_agent_reports_kind", "agent_reports", ["kind"])


def downgrade() -> None:
    op.drop_table("agent_reports")
