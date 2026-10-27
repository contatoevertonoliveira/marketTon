"""Posts publicados nas redes (Instagram).

Revision ID: 0027_social_posts
Revises: 0026_creative_hidden
Create Date: 2026-10-28 00:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027_social_posts"
down_revision: str | None = "0026_creative_hidden"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "social_posts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("creative_campaign_id", sa.Integer(), sa.ForeignKey("creative_campaigns.id", ondelete="SET NULL")),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL")),
        sa.Column("deliverable_id", sa.String(64)),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("external_id", sa.String(64)),
        sa.Column("permalink", sa.String(300)),
        sa.Column("error", sa.String(500)),
        sa.Column("created_by", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_social_posts_platform", "social_posts", ["platform"])
    op.create_index("ix_social_posts_status", "social_posts", ["status"])
    op.create_index("ix_social_posts_creative_campaign_id", "social_posts", ["creative_campaign_id"])
    op.create_index("ix_social_posts_product_id", "social_posts", ["product_id"])


def downgrade() -> None:
    op.drop_table("social_posts")
