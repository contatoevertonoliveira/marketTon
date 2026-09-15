"""Add support tables migrated from the legacy SQLite schema.

Revision ID: 0003_support_tables
Revises: 0002_ai_interpretations
Create Date: 2026-01-03 00:00:00+00:00

As tabelas de suporte operacional (feedback, preferências, agenda, grupos,
pagamentos, alertas de tendência) vêm da versão anterior do projeto e contêm dado
real de operação.

Elas passam a ser criadas por migration em vez de DDL em tempo de execução. Antes,
três arquivos as definiam de forma incompatível
(`core/db.py`, `backend/main.py`, `backend/init_db.py`), todos com
`CREATE TABLE IF NOT EXISTS`: a primeira execução vencia e as demais viravam no-op
silencioso.

Diferenças deliberadas em relação ao legado:

* Prefixo `support_` para não colidir com as tabelas de domínio e deixar claro que
  são suporte, não catálogo.
* `support_groups.updated_by` é `VARCHAR` — no legado era `INTEGER` num arquivo e
  `TEXT` no outro.
* `support_payments` unifica os campos divergentes (`amount`/`amount_cents`,
  `provider`/`gateway`, `tx_id`/`external_id`).
* `support_trend_alerts` unifica as três formas que a tabela já teve.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_support_tables"
down_revision: str | None = "0002_ai_interpretations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "support_feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("channel", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(128)),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("sentiment", sa.String(32)),
        sa.Column("tags", sa.String(255)),
        *_timestamps(),
    )
    op.create_index("ix_support_feedback_channel", "support_feedback", ["channel"])
    op.create_index("ix_support_feedback_user_id", "support_feedback", ["user_id"])

    op.create_table(
        "support_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.Integer()),
        sa.Column("username", sa.String(128)),
        sa.Column("language", sa.String(16), nullable=False, server_default="pt-BR"),
        sa.Column("notify_alerts", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notify_daily_report", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notify_opportunities", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("muted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("extra", sa.JSON()),
        *_timestamps(),
        sa.UniqueConstraint("user_id", name="uq_support_preferences_user_id"),
    )

    op.create_table(
        "support_agenda",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("owner", sa.String(128)),
        sa.Column("channel", sa.String(64)),
        sa.Column("when_date", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index("ix_support_agenda_when_date", "support_agenda", ["when_date"])

    op.create_table(
        "support_groups",
        sa.Column("group_id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(255)),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("reason", sa.Text()),
        # VARCHAR de propósito: no legado era INTEGER num arquivo e TEXT no outro.
        sa.Column("updated_by", sa.String(128)),
        *_timestamps(),
    )

    op.create_table(
        "support_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tx_id", sa.String(128)),
        sa.Column("provider", sa.String(64)),
        sa.Column("gateway", sa.String(64)),
        sa.Column("status", sa.String(32)),
        sa.Column("amount", sa.Float()),
        sa.Column("amount_cents", sa.Integer()),
        sa.Column("currency", sa.String(8), server_default="BRL"),
        sa.Column("external_id", sa.String(128)),
        sa.Column("reference", sa.String(128)),
        sa.Column("user_id", sa.Integer()),
        sa.Column("raw", sa.JSON()),
        *_timestamps(),
        sa.UniqueConstraint("tx_id", name="uq_support_payments_tx_id"),
    )
    op.create_index("ix_support_payments_provider", "support_payments", ["provider"])
    op.create_index("ix_support_payments_status", "support_payments", ["status"])

    op.create_table(
        "support_trend_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("keyword", sa.String(255), nullable=False),
        sa.Column("topic", sa.String(255)),
        sa.Column("source", sa.String(64)),
        sa.Column("geo", sa.String(16)),
        sa.Column("region", sa.String(64)),
        sa.Column("signal", sa.String(32)),
        sa.Column("alert", sa.String(32)),
        sa.Column("score", sa.Float()),
        sa.Column("interest_last", sa.Float()),
        sa.Column("interest_mean", sa.Float()),
        sa.Column("interest_change", sa.Float()),
        sa.Column("collected_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint(
            "keyword", "geo", "collected_at", name="uq_support_trend_alerts_kw_geo_at"
        ),
    )
    op.create_index("ix_support_trend_alerts_collected_at", "support_trend_alerts", ["collected_at"])
    op.create_index("ix_support_trend_alerts_collected", "support_trend_alerts", ["collected_at"])


def downgrade() -> None:
    for table in (
        "support_trend_alerts",
        "support_payments",
        "support_groups",
        "support_agenda",
        "support_preferences",
        "support_feedback",
    ):
        op.drop_table(table)
