"""Add campos da Meta em ad_campaigns (conjunto de anúncios, duração e destino).

Revision ID: 0022_ad_meta_fields
Revises: 0021_ad_campaigns
Create Date: 2026-10-23 00:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_ad_meta_fields"
down_revision: str | None = "0021_ad_campaigns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ad_campaigns", sa.Column("external_adset_id", sa.String(64)))
    op.add_column("ad_campaigns", sa.Column("duration_days", sa.Integer()))
    op.add_column("ad_campaigns", sa.Column("destination_url", sa.String(1024)))
    op.add_column("ad_campaigns", sa.Column("meta_status", sa.String(32)))


def downgrade() -> None:
    for col in ("meta_status", "destination_url", "duration_days", "external_adset_id"):
        op.drop_column("ad_campaigns", col)
