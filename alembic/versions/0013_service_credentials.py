"""Add service_credentials (Google Ads e outros serviços de dados).

Revision ID: 0013_service_credentials
Revises: 0012_sale_product_ref
Create Date: 2026-10-21 00:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_service_credentials"
down_revision: str | None = "0012_sale_product_ref"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "service_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("service", sa.String(48), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("last_check_status", sa.String(16)),
        sa.Column("last_check_message", sa.String(500)),
        sa.Column("last_check_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("service", name="uq_service_credentials_service"),
    )


def downgrade() -> None:
    op.drop_table("service_credentials")
