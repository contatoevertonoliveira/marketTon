"""Add authentication tables.

Revision ID: 0004_auth_tables
Revises: 0003_support_tables
Create Date: 2026-01-04 00:00:00+00:00

Substitui a tabela `users` que existia em código morto (`core/db.py`) com
`password TEXT NOT NULL` — senha em texto puro, sem nenhuma dependência de hashing
no projeto.

Três tabelas:

* `users` — credencial hasheada (Argon2), papel e controle de bloqueio.
* `refresh_tokens` — guardados **como hash**, para permitir logout real e para que
  um vazamento do banco permita revogar tokens em vez de usá-los.
* `audit_log` — trilha de ações sensíveis, com ator e resultado.

A API estava com 49 rotas sem autenticação: `PUT /support/preferences/{user_id}`
permitia sobrescrever preferências de qualquer usuário e `GET /support/feedback`
expunha ids e nomes. Esta migration é a base para fechar isso.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_auth_tables"
down_revision: str | None = "0003_support_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES = ["admin", "manager", "operator", "viewer", "bot"]


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("email", sa.String(255)),
        # Argon2. Não existe coluna de senha em texto: a versão anterior tinha.
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column(
            "role",
            sa.Enum(*ROLES, name="role", native_enum=False, length=48, validate_strings=True),
            nullable=False,
            server_default="viewer",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("password_changed_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(64)),
        *_timestamps(),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_role", "users", ["role"])

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("user_agent", sa.String(255)),
        sa.Column("client_ip", sa.String(64)),
        *_timestamps(),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"])
    op.create_index("ix_refresh_tokens_user_active", "refresh_tokens", ["user_id", "revoked_at"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor", sa.String(64)),
        sa.Column("actor_role", sa.String(32)),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64)),
        sa.Column("resource_id", sa.String(64)),
        sa.Column("outcome", sa.String(16), nullable=False, server_default="success"),
        sa.Column("detail", sa.Text()),
        sa.Column("client_ip", sa.String(64)),
        sa.Column("user_agent", sa.String(255)),
        *_timestamps(),
    )
    op.create_index("ix_audit_log_actor", "audit_log", ["actor"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_action_created", "audit_log", ["action", "created_at"])
    op.create_index("ix_audit_log_resource", "audit_log", ["resource_type", "resource_id"])


def downgrade() -> None:
    for table in ("audit_log", "refresh_tokens", "users"):
        op.drop_table(table)
