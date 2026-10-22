"""Add product_external_id / product_title to sales.

Revision ID: 0012_sale_product_ref
Revises: 0011_product_manual_signals
Create Date: 2026-10-21 00:00:00+00:00

Quem afiliou um produto direto no app da Shopee costuma não ter esse produto no
catálogo local — a venda chegava sem nenhuma pista de qual produto era. Guardar
o id e o nome do item na própria venda permite a página "Produtos" mostrar o que
realmente vendeu, estando ou não no catálogo.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_sale_product_ref"
down_revision: str | None = "0011_product_manual_signals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sales", sa.Column("product_external_id", sa.String(128)))
    op.add_column("sales", sa.Column("product_title", sa.String(512)))
    op.create_index("ix_sales_product_external_id", "sales", ["product_external_id"])


def downgrade() -> None:
    op.drop_index("ix_sales_product_external_id", table_name="sales")
    op.drop_column("sales", "product_title")
    op.drop_column("sales", "product_external_id")
