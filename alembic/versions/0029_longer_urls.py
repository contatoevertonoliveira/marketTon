"""Endereços de produto e de afiliado mais longos (links do AliExpress passam de 1024 caracteres).

Revision ID: 0029_longer_urls
Revises: 0028_creative_reviews
Create Date: 2026-10-28 00:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029_longer_urls"
down_revision: str | None = "0028_creative_reviews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = (("products", "product_url", False), ("products", "affiliate_url", False), ("affiliate_links", "affiliate_url", True))


def upgrade() -> None:
    for table, column, required in COLUMNS:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(column, existing_type=sa.String(1024), type_=sa.String(4096), existing_nullable=not required)


def downgrade() -> None:
    for table, column, required in COLUMNS:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(column, existing_type=sa.String(4096), type_=sa.String(1024), existing_nullable=not required)
