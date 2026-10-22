"""Add profile fields (full_name, phone, company) to users.

Revision ID: 0014_user_profile
Revises: 0013_service_credentials
Create Date: 2026-10-22 00:00:00+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_user_profile"
down_revision: str | None = "0013_service_credentials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("full_name", sa.String(128)))
    op.add_column("users", sa.Column("phone", sa.String(32)))
    op.add_column("users", sa.Column("company", sa.String(128)))


def downgrade() -> None:
    op.drop_column("users", "company")
    op.drop_column("users", "phone")
    op.drop_column("users", "full_name")
