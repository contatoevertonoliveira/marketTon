"""Add storefront_items (ajustes por produto da vitrine pública).

Revision ID: 0019_storefront
Revises: 0018_agent_run_usage
Create Date: 2026-10-22 00:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_storefront"
down_revision: str | None = "0018_agent_run_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "storefront_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(48)),
        sa.Column("display_title", sa.String(160)),
        sa.Column("blurb", sa.String(280)),
        sa.Column("highlight", sa.Boolean(), nullable=False),
        sa.Column("hidden", sa.Boolean(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("product_id", name="uq_storefront_items_product_id"),
    )


def downgrade() -> None:
    op.drop_table("storefront_items")
