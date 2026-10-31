"""Campanha do anúncio no clique em oferta (atribuição por anúncio).

Revision ID: 0032_click_campaign
Revises: 0031_product_vettings
Create Date: 2026-10-31 12:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032_click_campaign"
down_revision: str | None = "0031_product_vettings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("click_events", sa.Column("campaign", sa.String(64), nullable=True))
    op.create_index("ix_click_events_campaign", "click_events", ["campaign"])


def downgrade() -> None:
    op.drop_index("ix_click_events_campaign", table_name="click_events")
    op.drop_column("click_events", "campaign")
