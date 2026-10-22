"""Add affiliate_count_period and manual_stock to products.

Revision ID: 0011_product_manual_signals
Revises: 0010_product_affiliate_count
Create Date: 2026-09-23 00:00:00+00:00

Nem a Affiliate Open API nem os feeds da Shopee expõem estoque ou número de
afiliados; o operador lê no app de afiliados e digita. O período diz a que
janela o número de afiliados se refere (total, semana ou mês).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_product_manual_signals"
down_revision: str | None = "0010_product_affiliate_count"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("affiliate_count_period", sa.String(8)))
    op.add_column("products", sa.Column("manual_stock", sa.Integer()))


def downgrade() -> None:
    op.drop_column("products", "manual_stock")
    op.drop_column("products", "affiliate_count_period")
