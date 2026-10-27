"""Criativo pode ser "excluído" da tela (escondido), sem apagar o histórico.

Revision ID: 0026_creative_hidden
Revises: 0025_trend_snapshots
Create Date: 2026-10-27 00:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_creative_hidden"
down_revision: str | None = "0025_trend_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("creative_campaigns", sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("creative_campaigns", "hidden")
