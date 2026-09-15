"""Add ai_interpretations table.

Revision ID: 0002_ai_interpretations
Revises: 0001_initial
Create Date: 2026-01-02 00:00:00+00:00

Registro auditável das saídas de IA. Existe porque o briefing seção 5 exige que
nenhuma pontuação crítica seja opinião opaca de um modelo: se a IA influencia uma
decisão, a interpretação precisa ficar rastreável junto com os insumos que a
produziram.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_ai_interpretations"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AI_KIND = [
    "TREND_READING",
    "PRODUCT_EVALUATION",
    "SATURATION_READING",
    "PERFORMANCE_DIAGNOSIS",
    "CREATIVE_BRIEF",
    "CATALOG_HEALTH_READING",
]

# Chave de 64 bits no PostgreSQL, INTEGER no SQLite (ver 0001_initial_schema).
BIGINT = sa.BigInteger().with_variant(sa.Integer, "sqlite")


def upgrade() -> None:
    op.create_table(
        "ai_interpretations",
        sa.Column("id", BIGINT, primary_key=True),
        sa.Column("agent", sa.String(64), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(*AI_KIND, name="ai_interpretation_kind", native_enum=False, length=48),
            nullable=False,
        ),
        sa.Column("prompt_key", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(16), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("inputs", sa.JSON()),
        sa.Column("inputs_hash", sa.String(64)),
        sa.Column("raw_text", sa.Text()),
        sa.Column("output", sa.JSON()),
        sa.Column("parse_ok", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("error_message", sa.Text()),
        sa.Column("prompt_tokens", sa.Integer()),
        sa.Column("completion_tokens", sa.Integer()),
        sa.Column("latency_seconds", sa.Float()),
        sa.Column("target_type", sa.String(32)),
        sa.Column("target_id", BIGINT),
        sa.Column("job_id", BIGINT, sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ai_interpretations_agent", "ai_interpretations", ["agent"])
    op.create_index("ix_ai_interpretations_kind", "ai_interpretations", ["kind"])
    op.create_index("ix_ai_interpretations_inputs_hash", "ai_interpretations", ["inputs_hash"])
    op.create_index("ix_ai_interpretations_job_id", "ai_interpretations", ["job_id"])
    op.create_index("ix_ai_interpretations_agent_created", "ai_interpretations", ["agent", "created_at"])
    op.create_index(
        "ix_ai_interpretations_target", "ai_interpretations", ["target_type", "target_id"]
    )


def downgrade() -> None:
    op.drop_table("ai_interpretations")
