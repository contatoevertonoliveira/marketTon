"""Add trend tables.

Revision ID: 0005_trend_tables
Revises: 0004_auth_tables
Create Date: 2026-01-05 00:00:00+00:00

Por que tabela e não o CSV anterior: `data/trend_alerts.csv` tinha cabeçalho de 5
colunas e linhas de 3, porque o agente fazia append com `header=not exists()`. Pior,
gravava erro de upstream na coluna `source`, transformando falha de coleta em dado:

    marketing digital cristão,The request failed: Google returned a response with code 400,...

Isso é exatamente o que o briefing seção 2 proíbe. Com tabela, a falha vai para
`source_records.warnings`, onde é auditável, e nenhum valor de tendência é inventado.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_trend_tables"
down_revision: str | None = "0004_auth_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BIGINT = sa.BigInteger().with_variant(sa.Integer, "sqlite")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "trend_keywords",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("keyword", sa.String(255), nullable=False),
        sa.Column("geo", sa.String(16), nullable=False, server_default="BR"),
        sa.Column("display_name", sa.String(255)),
        sa.Column("niche", sa.String(64)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("series_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint("keyword", "geo", name="uq_trend_keywords_keyword_geo"),
    )
    op.create_index("ix_trend_keywords_niche", "trend_keywords", ["niche"])
    op.create_index("ix_trend_keywords_last_seen_at", "trend_keywords", ["last_seen_at"])

    op.create_table(
        "trend_observations",
        sa.Column("id", BIGINT, primary_key=True),
        sa.Column(
            "trend_keyword_id",
            sa.Integer(),
            sa.ForeignKey("trend_keywords.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("interest_last", sa.Float()),
        sa.Column("interest_mean", sa.Float()),
        sa.Column("interest_peak", sa.Float()),
        sa.Column("change_absolute", sa.Float()),
        sa.Column("change_pct", sa.Float()),
        sa.Column("trend_direction", sa.String(16)),
        sa.Column("interpretation", sa.JSON()),
        sa.Column(
            "interpretation_id",
            BIGINT,
            sa.ForeignKey("ai_interpretations.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "source_record_id",
            sa.Integer(),
            sa.ForeignKey("source_records.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text()),
        *_timestamps(),
        sa.UniqueConstraint(
            "trend_keyword_id", "observed_at", name="uq_trend_observations_keyword_observed"
        ),
    )
    op.create_index("ix_trend_observations_trend_keyword_id", "trend_observations", ["trend_keyword_id"])
    op.create_index("ix_trend_observations_observed_at", "trend_observations", ["observed_at"])
    op.create_index("ix_trend_observations_trend_direction", "trend_observations", ["trend_direction"])
    op.create_index("ix_trend_observations_interpretation_id", "trend_observations", ["interpretation_id"])
    op.create_index("ix_trend_observations_source_record_id", "trend_observations", ["source_record_id"])
    op.create_index(
        "ix_trend_observations_direction_observed",
        "trend_observations",
        ["trend_direction", "observed_at"],
    )


def downgrade() -> None:
    for table in ("trend_observations", "trend_keywords"):
        op.drop_table(table)
