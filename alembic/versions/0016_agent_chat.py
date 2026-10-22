"""Add agent_messages (chat com o agente, pedidos, alertas e tarefas).

Revision ID: 0016_agent_chat
Revises: 0015_app_settings
Create Date: 2026-10-22 00:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_agent_chat"
down_revision: str | None = "0015_app_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("author", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("meta", sa.JSON()),
        sa.Column("status", sa.String(16)),
        sa.Column("read_by_user", sa.Boolean(), nullable=False),
        sa.Column("read_by_agent", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_agent_messages_author", "agent_messages", ["author"])
    op.create_index("ix_agent_messages_kind", "agent_messages", ["kind"])
    op.create_index("ix_agent_messages_status", "agent_messages", ["status"])
    op.create_index("ix_agent_messages_read_by_user", "agent_messages", ["read_by_user"])
    op.create_index("ix_agent_messages_read_by_agent", "agent_messages", ["read_by_agent"])


def downgrade() -> None:
    op.drop_table("agent_messages")
