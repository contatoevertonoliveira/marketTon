"""Add creative_campaigns e creative_events (integração com o AI Studio).

Revision ID: 0020_creatives
Revises: 0019_storefront
Create Date: 2026-10-22 00:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_creatives"
down_revision: str | None = "0019_storefront"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creative_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL")),
        sa.Column("external_ref", sa.String(120), nullable=False),
        sa.Column("campaign_id", sa.String(64)),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("quality", sa.String(12), nullable=False),
        sa.Column("angle", sa.String(32)),
        sa.Column("budget_usd", sa.Float(), nullable=False),
        sa.Column("cost_usd", sa.Float()),
        sa.Column("request", sa.JSON()),
        sa.Column("manifest", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("created_by", sa.String(64)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("external_ref", name="uq_creative_campaigns_external_ref"),
    )
    op.create_index("ix_creative_campaigns_status", "creative_campaigns", ["status"])
    op.create_table(
        "creative_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(80), nullable=False),
        sa.Column("event", sa.String(48), nullable=False),
        sa.Column("campaign_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("event_id", name="uq_creative_events_event_id"),
    )


def downgrade() -> None:
    op.drop_table("creative_events")
    op.drop_table("creative_campaigns")
