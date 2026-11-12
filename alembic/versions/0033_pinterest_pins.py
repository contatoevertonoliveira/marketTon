"""Pins do Pinterest (rascunho, aprovação, publicação e métricas).

Revision ID: 0033_pinterest_pins
Revises: 0032_click_campaign
Create Date: 2026-11-12 12:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033_pinterest_pins"
down_revision: str | None = "0032_click_campaign"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pinterest_pins",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("creative_campaign_id", sa.Integer, sa.ForeignKey("creative_campaigns.id", ondelete="SET NULL")),
        sa.Column("board_name", sa.String(120), nullable=False),
        sa.Column("board_id", sa.String(40)),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("alt_text", sa.String(500)),
        sa.Column("keywords", sa.String(300)),
        sa.Column("link_url", sa.String(2048), nullable=False),
        sa.Column("link_mode", sa.String(8), nullable=False, server_default="page"),
        sa.Column("image_ref", sa.String(600), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="draft"),
        sa.Column("scheduled_for", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("pinterest_id", sa.String(64)),
        sa.Column("permalink", sa.String(300)),
        sa.Column("error", sa.String(500)),
        sa.Column("impressions", sa.Integer),
        sa.Column("saves", sa.Integer),
        sa.Column("pin_clicks", sa.Integer),
        sa.Column("outbound_clicks", sa.Integer),
        sa.Column("metrics_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_pinterest_pins_product_id", "pinterest_pins", ["product_id"])
    op.create_index("ix_pinterest_pins_status", "pinterest_pins", ["status"])
    op.create_index("ix_pinterest_pins_scheduled_for", "pinterest_pins", ["scheduled_for"])


def downgrade() -> None:
    op.drop_table("pinterest_pins")
