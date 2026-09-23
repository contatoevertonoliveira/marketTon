"""Add last_check_* to marketplace_credentials (connection test / traffic light).

Revision ID: 0009_credential_last_check
Revises: 0008_commission_rates
Create Date: 2026-09-23 00:00:00+00:00

A tela de Integrações vai ganhar um "semáforo" por marketplace (verde/amarelo/
vermelho). "Configurado" (tem credencial preenchida) não é o mesmo que
"testado e funcionando" — a Shopee, por exemplo, só se provou funcionando
depois de eu corrigir o formato da query contra uma chamada real. Estas
colunas guardam o resultado da última chamada de teste de verdade.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_credential_last_check"
down_revision: str | None = "0008_commission_rates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("marketplace_credentials", sa.Column("last_check_status", sa.String(16)))
    op.add_column("marketplace_credentials", sa.Column("last_check_message", sa.String(500)))
    op.add_column("marketplace_credentials", sa.Column("last_check_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("marketplace_credentials", "last_check_at")
    op.drop_column("marketplace_credentials", "last_check_message")
    op.drop_column("marketplace_credentials", "last_check_status")
