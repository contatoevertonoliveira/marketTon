"""Add marketplace_credentials table.

Revision ID: 0006_marketplace_credentials
Revises: 0005_trend_tables
Create Date: 2026-09-15 00:00:00+00:00

A permissão `connectors.manage` já existia em `core/roles.py` ("Configurar
credenciais de marketplace") mas não havia onde persistir a credencial em
tempo de execução — só `.env`, lido uma vez no start do processo. Esta tabela
é a fonte de verdade editável pela tela de Integrações; `config/settings.py`
continua fornecendo os defaults quando a linha não existe ou está desligada.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_marketplace_credentials"
down_revision: str | None = "0005_trend_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MARKETPLACE = ["mercado_livre", "shopee", "amazon", "tiktok_shop", "other"]

# Chave de 64 bits no PostgreSQL, INTEGER no SQLite (ver 0001_initial_schema).
BIGINT = sa.BigInteger().with_variant(sa.Integer, "sqlite")


def upgrade() -> None:
    op.create_table(
        "marketplace_credentials",
        sa.Column("id", BIGINT, primary_key=True),
        sa.Column(
            "marketplace",
            sa.Enum(*MARKETPLACE, name="marketplace", native_enum=False, length=48),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("oauth_state", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("marketplace", name="uq_marketplace_credentials_marketplace"),
    )


def downgrade() -> None:
    op.drop_table("marketplace_credentials")
