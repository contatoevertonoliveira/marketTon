"""Destino do link rastreado mais longo (o link de afiliado do AliExpress passa de 1024 caracteres).

Revision ID: 0030_longer_destination_url
Revises: 0029_longer_urls
Create Date: 2026-10-28 00:10:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030_longer_destination_url"
down_revision: str | None = "0029_longer_urls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("affiliate_links") as batch:
        batch.alter_column("destination_url", existing_type=sa.String(1024), type_=sa.String(4096), existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("affiliate_links") as batch:
        batch.alter_column("destination_url", existing_type=sa.String(4096), type_=sa.String(1024), existing_nullable=False)
