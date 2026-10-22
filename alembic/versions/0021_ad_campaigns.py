"""Add ad_campaigns (anúncios criados sobre os criativos, com métricas).

Revision ID: 0021_ad_campaigns
Revises: 0020_creatives
Create Date: 2026-10-22 00:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_ad_campaigns"
down_revision: str | None = "0020_creatives"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ad_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("creative_campaign_id", sa.Integer(), sa.ForeignKey("creative_campaigns.id", ondelete="SET NULL")),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL")),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("variant", sa.String(8)),
        sa.Column("external_campaign_id", sa.String(64)),
        sa.Column("external_ad_id", sa.String(64)),
        sa.Column("daily_budget_brl", sa.Float()),
        sa.Column("spent_brl", sa.Float()),
        sa.Column("impressions", sa.Integer()),
        sa.Column("clicks", sa.Integer()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("last_metrics_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text()),
        sa.Column("created_by", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ad_campaigns_creative_campaign_id", "ad_campaigns", ["creative_campaign_id"])
    op.create_index("ix_ad_campaigns_product_id", "ad_campaigns", ["product_id"])
    op.create_index("ix_ad_campaigns_status", "ad_campaigns", ["status"])


def downgrade() -> None:
    op.drop_table("ad_campaigns")
