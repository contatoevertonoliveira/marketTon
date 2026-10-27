"""Pareceres do agente sobre criativos e slideshows (porta de qualidade da publicação automática).

Revision ID: 0028_creative_reviews
Revises: 0027_social_posts
Create Date: 2026-10-28 00:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028_creative_reviews"
down_revision: str | None = "0027_social_posts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creative_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("creative_campaign_id", sa.Integer(), sa.ForeignKey("creative_campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("verdict", sa.String(10), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("reviewer", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_creative_reviews_creative_campaign_id", "creative_reviews", ["creative_campaign_id"])


def downgrade() -> None:
    op.drop_table("creative_reviews")
