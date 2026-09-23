"""Add manually-entered affiliate_count to products.

Revision ID: 0010_product_affiliate_count
Revises: 0009_credential_last_check
Create Date: 2026-09-23 00:00:00+00:00

A Affiliate Open API da Shopee não expõe quantos afiliados promovem um
produto; o número é lido pelo usuário no Centro de Afiliados e digitado aqui.
Coluna própria (e não `attributes`) porque a ingestão sobrescreve `attributes`
a cada coleta.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_product_affiliate_count"
down_revision: str | None = "0009_credential_last_check"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("affiliate_count", sa.Integer()))
    op.add_column("products", sa.Column("affiliate_count_updated_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("products", "affiliate_count_updated_at")
    op.drop_column("products", "affiliate_count")
