"""Add commission_rates (operator-supplied affiliate commission per category).

Revision ID: 0008_commission_rates
Revises: 0007_marketplace_credential_pkce
Create Date: 2026-09-21 00:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_commission_rates"
down_revision: str | None = "0007_marketplace_credential_pkce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MARKETPLACE = ["mercado_livre", "shopee", "amazon", "tiktok_shop", "other"]
BIGINT = sa.BigInteger().with_variant(sa.Integer, "sqlite")


def upgrade() -> None:
    op.create_table(
        "commission_rates",
        sa.Column("id", BIGINT, primary_key=True),
        sa.Column("marketplace", sa.Enum(*MARKETPLACE, name="marketplace", native_enum=False, length=48), nullable=False),
        sa.Column("category_id", sa.String(64), nullable=False),
        sa.Column("rate_pct", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint("marketplace", "category_id", name="uq_commission_rates_marketplace_category"),
    )


def downgrade() -> None:
    op.drop_table("commission_rates")
