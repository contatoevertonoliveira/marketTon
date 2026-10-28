"""Triagem de produtos (procura, demanda, prazo e custo) antes de gastar com anúncio.

Revision ID: 0031_product_vettings
Revises: 0030_longer_destination_url
Create Date: 2026-10-28 01:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031_product_vettings"
down_revision: str | None = "0030_longer_destination_url"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_vettings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("keyword", sa.String(120), nullable=False),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("monthly_volume", sa.Integer()),
        sa.Column("cpc_brl", sa.Float()),
        sa.Column("trend_direction", sa.String(10)),
        sa.Column("growth_pct_30d", sa.Float()),
        sa.Column("platform_sold", sa.Integer()),
        sa.Column("rating", sa.Float()),
        sa.Column("commission_per_sale_brl", sa.Float()),
        sa.Column("breakeven_conversion", sa.Float()),
        sa.Column("delivery_days", sa.Integer()),
        sa.Column("ship_from", sa.String(32)),
        sa.Column("reasons", sa.JSON()),
        sa.Column("created_by", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_product_vettings_product_id", "product_vettings", ["product_id"])
    op.create_index("ix_product_vettings_verdict", "product_vettings", ["verdict"])


def downgrade() -> None:
    op.drop_index("ix_product_vettings_verdict", table_name="product_vettings")
    op.drop_index("ix_product_vettings_product_id", table_name="product_vettings")
    op.drop_table("product_vettings")
