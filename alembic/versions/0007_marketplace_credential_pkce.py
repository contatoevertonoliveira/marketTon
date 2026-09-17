"""Add oauth_code_verifier to marketplace_credentials (PKCE).

Revision ID: 0007_marketplace_credential_pkce
Revises: 0006_marketplace_credentials
Create Date: 2026-09-16 00:00:00+00:00

Descoberto tentando conectar a Mercado Livre ao vivo: a troca do código por
token falhou com `invalid_request: code_verifier is a required parameter` —
o app tem PKCE (RFC 7636) habilitado. `oauth_code_verifier` guarda o
`code_verifier` gerado junto com `oauth_state` no início do fluxo, para ser
enviado na troca do código por token.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_marketplace_credential_pkce"
down_revision: str | None = "0006_marketplace_credentials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "marketplace_credentials",
        sa.Column("oauth_code_verifier", sa.String(128)),
    )


def downgrade() -> None:
    op.drop_column("marketplace_credentials", "oauth_code_verifier")
