"""Initial PostgreSQL schema: catalog provenance, versioned scoring, portfolio,
creative pipeline, tracking, jobs and the learning loop.

Revision ID: 0001_initial
Revises:
Create Date: 2026-01-01 00:00:00+00:00

Criado manualmente (não por autogenerate) para que o schema inicial seja
explícito, revisável e reversível. A Fase 1 substitui integralmente os três
schemas SQLite divergentes por uma única fonte versionada.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# --- Definições de enum -------------------------------------------------------
# Persistidos como VARCHAR + CHECK (native_enum=False): renomear ou acrescentar
# um valor não exige um tipo nativo do Postgres nem um ALTER TYPE delicado.

MARKETPLACE = ["mercado_livre", "shopee", "amazon", "tiktok_shop", "other"]
CONNECTOR_KIND = ["official_api", "affiliate_api", "ads_library", "public_dataset", "manual"]
PORTFOLIO_STATE = [
    "DISCOVERED",
    "ANALYZING",
    "WATCHLIST",
    "RECOMMENDED",
    "AFFILIATION_PENDING",
    "AFFILIATED",
    "PORTFOLIO_ACTIVE",
    "CREATIVE_PENDING",
    "READY_TO_PUBLISH",
    "PUBLISHED",
    "MONITORING",
    "OPTIMIZATION_REQUIRED",
    "SCALING",
    "PAUSED",
    "REMOVED",
]
SCORE_DIMENSION = [
    "HEAT",
    "OPPORTUNITY",
    "PRODUCER_MOMENTUM",
    "CREATIVE_SATURATION",
    "PORTFOLIO",
    "CREATIVE",
]
SCORE_RUN_STATUS = ["SUCCEEDED", "INSUFFICIENT_DATA", "FAILED"]
RECOMMENDATION_KIND = [
    "ANALYZE",
    "AFFILIATE",
    "PRODUCE_CREATIVE",
    "PUBLISH",
    "OPTIMIZE",
    "SCALE",
    "PAUSE",
    "REMOVE",
]
CREATIVE_ASSET_TYPE = ["COPY", "IMAGE", "VIDEO", "VOICE", "EDIT", "APPROVAL", "PUBLICATION"]
CREATIVE_STATUS = ["PENDING", "IN_PROGRESS", "READY", "APPROVED", "REJECTED", "BLOCKED"]
JOB_STATUS = ["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]
PUBLICATION_STATUS = ["DRAFT", "SCHEDULED", "PUBLISHED", "FAILED", "REMOVED"]

# Chave de 64 bits no PostgreSQL, INTEGER no SQLite (o SQLite so auto-incrementa
# quando o tipo e exatamente INTEGER PRIMARY KEY - com BIGINT todo INSERT falha).
# Permite que os testes exercitem o schema real sem Docker.
BIGINT = sa.BigInteger().with_variant(sa.Integer, "sqlite")

MONEY = sa.Numeric(14, 2)
SCORE = sa.Numeric(6, 3)


def _enum(name: str, values: list[str]) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, length=48, validate_strings=True)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    # --- Procedência ----------------------------------------------------------
    op.create_table(
        "source_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("marketplace", _enum("marketplace", MARKETPLACE), nullable=False),
        sa.Column("connector", sa.String(64), nullable=False),
        sa.Column("connector_kind", _enum("connector_kind", CONNECTOR_KIND), nullable=False),
        sa.Column("endpoint", sa.String(1024)),
        sa.Column("external_id", sa.String(128)),
        sa.Column("external_parent_id", sa.String(128)),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reliability", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("field_source", sa.String(128)),
        sa.Column("notes", sa.Text()),
        sa.Column("warnings", sa.JSON()),
        sa.Column("raw", sa.JSON()),
        *_timestamps(),
    )
    op.create_index("ix_source_records_marketplace", "source_records", ["marketplace"])
    op.create_index("ix_source_records_external_id", "source_records", ["external_id"])
    op.create_index("ix_source_records_collected_at", "source_records", ["collected_at"])
    op.create_index("ix_source_records_marketplace_collected", "source_records", ["marketplace", "collected_at"])

    # --- Vendedores -----------------------------------------------------------
    op.create_table(
        "sellers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("marketplace", _enum("marketplace", MARKETPLACE), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("nickname", sa.String(255)),
        sa.Column("display_name", sa.String(255)),
        sa.Column("reputation_level", sa.String(64)),
        sa.Column("reputation_score", sa.Float()),
        sa.Column("total_sales", sa.Integer()),
        sa.Column("positive_rating_pct", sa.Float()),
        sa.Column("feedback_count", sa.Integer()),
        sa.Column("is_official_store", sa.Boolean()),
        sa.Column("power_seller_status", sa.String(64)),
        sa.Column("registration_date", sa.DateTime(timezone=True)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("source_record_id", sa.Integer(), sa.ForeignKey("source_records.id", ondelete="RESTRICT"), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("marketplace", "external_id", name="uq_sellers_marketplace_external_id"),
    )
    op.create_index("ix_sellers_marketplace", "sellers", ["marketplace"])
    op.create_index("ix_sellers_source_record_id", "sellers", ["source_record_id"])

    # --- Produtos -------------------------------------------------------------
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("marketplace", _enum("marketplace", MARKETPLACE), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("identity_key", sa.String(320)),
        sa.Column("category_id", sa.String(128)),
        sa.Column("category_path", sa.JSON()),
        sa.Column("brand", sa.String(255)),
        sa.Column("model", sa.String(255)),
        sa.Column("condition", sa.String(64)),
        sa.Column("seller_id", sa.Integer(), sa.ForeignKey("sellers.id", ondelete="SET NULL")),
        sa.Column("currency", sa.String(8)),
        sa.Column("price", sa.Float()),
        sa.Column("original_price", sa.Float()),
        sa.Column("discount_pct", sa.Float()),
        sa.Column("affiliate_commission_pct", sa.Float()),
        sa.Column("affiliate_commission_fixed", sa.Float()),
        sa.Column("available_quantity", sa.Integer()),
        sa.Column("sold_quantity", sa.Integer()),
        sa.Column("is_available", sa.Boolean()),
        sa.Column("rating", sa.Float()),
        sa.Column("review_count", sa.Integer()),
        sa.Column("ranking_position", sa.Integer()),
        sa.Column("popularity_score", sa.Float()),
        sa.Column("has_promotion", sa.Boolean()),
        sa.Column("coupons", sa.JSON()),
        sa.Column("product_url", sa.String(1024)),
        sa.Column("affiliate_url", sa.String(1024)),
        sa.Column("images", sa.JSON()),
        sa.Column("attributes", sa.JSON()),
        sa.Column("source_record_id", sa.Integer(), sa.ForeignKey("source_records.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.UniqueConstraint("marketplace", "external_id", name="uq_products_marketplace_external_id"),
    )
    op.create_index("ix_products_marketplace", "products", ["marketplace"])
    op.create_index("ix_products_identity_key", "products", ["identity_key"])
    op.create_index("ix_products_seller_id", "products", ["seller_id"])
    op.create_index("ix_products_source_record_id", "products", ["source_record_id"])
    op.create_index("ix_products_last_seen_at", "products", ["last_seen_at"])
    op.create_index("ix_products_marketplace_category", "products", ["marketplace", "category_id"])
    op.create_index("ix_products_active_last_seen", "products", ["is_active", "last_seen_at"])

    # --- Séries temporais -----------------------------------------------------
    op.create_table(
        "product_metrics",
        sa.Column("id", BIGINT, primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sales_rank", sa.Integer()),
        sa.Column("sold_last_period", sa.Integer()),
        sa.Column("visits", sa.Integer()),
        sa.Column("views", sa.Integer()),
        sa.Column("wishlist_count", sa.Integer()),
        sa.Column("search_interest", sa.Float()),
        sa.Column("review_count", sa.Integer()),
        sa.Column("rating", sa.Float()),
        sa.Column("source_record_id", sa.Integer(), sa.ForeignKey("source_records.id", ondelete="RESTRICT"), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("product_id", "observed_at", name="uq_product_metrics_product_observed"),
    )
    op.create_index("ix_product_metrics_product_id", "product_metrics", ["product_id"])
    op.create_index("ix_product_metrics_observed_at", "product_metrics", ["observed_at"])
    op.create_index("ix_product_metrics_source_record_id", "product_metrics", ["source_record_id"])
    op.create_index("ix_product_metrics_product_observed", "product_metrics", ["product_id", "observed_at"])

    op.create_table(
        "price_history",
        sa.Column("id", BIGINT, primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Float()),
        sa.Column("original_price", sa.Float()),
        sa.Column("discount_pct", sa.Float()),
        sa.Column("currency", sa.String(8)),
        sa.Column("available_quantity", sa.Integer()),
        sa.Column("is_available", sa.Boolean()),
        sa.Column("source_record_id", sa.Integer(), sa.ForeignKey("source_records.id", ondelete="RESTRICT"), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("product_id", "observed_at", name="uq_price_history_product_observed"),
    )
    op.create_index("ix_price_history_product_id", "price_history", ["product_id"])
    op.create_index("ix_price_history_observed_at", "price_history", ["observed_at"])
    op.create_index("ix_price_history_source_record_id", "price_history", ["source_record_id"])
    op.create_index("ix_price_history_product_observed", "price_history", ["product_id", "observed_at"])

    # --- Scoring versionado ---------------------------------------------------
    op.create_table(
        "score_algorithms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dimension", _enum("score_dimension", SCORE_DIMENSION), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("algorithm_key", sa.String(64), nullable=False),
        sa.Column("weights", sa.JSON(), nullable=False),
        sa.Column("parameters", sa.JSON()),
        sa.Column("formula", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint("dimension", "version", name="uq_score_algorithms_dimension_version"),
    )
    op.create_index("ix_score_algorithms_dimension", "score_algorithms", ["dimension"])

    op.create_table(
        "score_runs",
        sa.Column("id", BIGINT, primary_key=True),
        sa.Column("algorithm_id", sa.Integer(), sa.ForeignKey("score_algorithms.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("dimension", _enum("score_dimension", SCORE_DIMENSION), nullable=False),
        sa.Column("algorithm_version", sa.String(32), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", BIGINT, nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("weights", sa.JSON(), nullable=False),
        sa.Column("formula", sa.Text()),
        sa.Column("inputs_hash", sa.String(64)),
        sa.Column("score", SCORE, nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("is_complete", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", _enum("score_run_status", SCORE_RUN_STATUS), nullable=False, server_default="SUCCEEDED"),
        sa.Column("insufficient_reasons", sa.JSON()),
        sa.Column("marketplace", _enum("marketplace", MARKETPLACE)),
        sa.Column("source_record_id", sa.Integer(), sa.ForeignKey("source_records.id", ondelete="SET NULL")),
        *_timestamps(),
    )
    op.create_index("ix_score_runs_algorithm_id", "score_runs", ["algorithm_id"])
    op.create_index("ix_score_runs_dimension", "score_runs", ["dimension"])
    op.create_index("ix_score_runs_computed_at", "score_runs", ["computed_at"])
    op.create_index("ix_score_runs_inputs_hash", "score_runs", ["inputs_hash"])
    op.create_index("ix_score_runs_source_record_id", "score_runs", ["source_record_id"])
    op.create_index("ix_score_runs_target", "score_runs", ["target_type", "target_id", "dimension", "computed_at"])

    op.create_table(
        "score_contributions",
        sa.Column("id", BIGINT, primary_key=True),
        sa.Column("run_id", BIGINT, sa.ForeignKey("score_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("factor", sa.String(64), nullable=False),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("raw_value", sa.Float()),
        sa.Column("raw_unit", sa.String(32)),
        sa.Column("normalized_value", sa.Float()),
        sa.Column("weight", sa.Float()),
        sa.Column("impact", sa.Numeric(8, 3), nullable=False, server_default="0"),
        sa.Column("is_positive", sa.Boolean()),
        sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("explanation", sa.Text()),
        sa.UniqueConstraint("run_id", "factor", name="uq_score_contributions_run_factor"),
    )
    op.create_index("ix_score_contributions_run_id", "score_contributions", ["run_id"])

    # --- Portfólio ------------------------------------------------------------
    op.create_table(
        "recommendations",
        sa.Column("id", BIGINT, primary_key=True),
        sa.Column("portfolio_item_id", sa.Integer(), sa.ForeignKey("portfolio_items.id", ondelete="CASCADE")),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE")),
        sa.Column("kind", _enum("recommendation_kind", RECOMMENDATION_KIND), nullable=False),
        sa.Column("dimension", _enum("score_dimension", SCORE_DIMENSION)),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("rationale", sa.Text()),
        sa.Column("positive_factors", sa.JSON()),
        sa.Column("negative_factors", sa.JSON()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float()),
        sa.Column("score_run_id", BIGINT, sa.ForeignKey("score_runs.id", ondelete="SET NULL")),
        sa.Column("is_actioned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("actioned_at", sa.DateTime(timezone=True)),
        sa.Column("actioned_by", sa.String(128)),
        sa.Column("outcome", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index("ix_recommendations_portfolio_item_id", "recommendations", ["portfolio_item_id"])
    op.create_index("ix_recommendations_product_id", "recommendations", ["product_id"])
    op.create_index("ix_recommendations_kind", "recommendations", ["kind"])
    op.create_index("ix_recommendations_score_run_id", "recommendations", ["score_run_id"])
    op.create_index("ix_recommendations_open", "recommendations", ["is_actioned", "priority"])
    op.create_index("ix_recommendations_kind_created", "recommendations", ["kind", "created_at"])

    op.create_table(
        "portfolio_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("marketplace", _enum("marketplace", MARKETPLACE), nullable=False),
        sa.Column("label", sa.String(255)),
        sa.Column("state", _enum("portfolio_state", PORTFOLIO_STATE), nullable=False, server_default="DISCOVERED"),
        sa.Column("state_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_score_run_id", BIGINT, sa.ForeignKey("score_runs.id", ondelete="SET NULL")),
        sa.Column("entry_score", SCORE),
        sa.Column("added_by", sa.String(128)),
        sa.Column("notes", sa.Text()),
        sa.Column("revenue_total", sa.Float()),
        sa.Column("commission_total", sa.Float()),
        sa.Column("clicks_total", sa.Integer()),
        sa.Column("conversions_total", sa.Integer()),
        sa.Column("last_metrics_at", sa.DateTime(timezone=True)),
        sa.Column("paused_reason", sa.Text()),
        sa.Column("removed_reason", sa.Text()),
        sa.Column("removed_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint("product_id", name="uq_portfolio_items_product_id"),
    )
    op.create_index("ix_portfolio_items_product_id", "portfolio_items", ["product_id"])
    op.create_index("ix_portfolio_items_marketplace", "portfolio_items", ["marketplace"])
    op.create_index("ix_portfolio_items_state", "portfolio_items", ["state"])
    op.create_index("ix_portfolio_items_entry_score_run_id", "portfolio_items", ["entry_score_run_id"])
    op.create_index("ix_portfolio_items_state_changed", "portfolio_items", ["state", "state_changed_at"])

    op.create_table(
        "portfolio_transitions",
        sa.Column("id", BIGINT, primary_key=True),
        sa.Column("portfolio_item_id", sa.Integer(), sa.ForeignKey("portfolio_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_state", _enum("portfolio_state", PORTFOLIO_STATE)),
        sa.Column("to_state", _enum("portfolio_state", PORTFOLIO_STATE), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("triggered_by_recommendation_id", BIGINT, sa.ForeignKey("recommendations.id", ondelete="SET NULL")),
        *_timestamps(),
    )
    op.create_index("ix_portfolio_transitions_portfolio_item_id", "portfolio_transitions", ["portfolio_item_id"])
    op.create_index("ix_portfolio_transitions_occurred_at", "portfolio_transitions", ["occurred_at"])

    # --- Pipeline criativo ----------------------------------------------------
    op.create_table(
        "creative_assets",
        sa.Column("id", BIGINT, primary_key=True),
        sa.Column("portfolio_item_id", sa.Integer(), sa.ForeignKey("portfolio_items.id", ondelete="CASCADE")),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE")),
        sa.Column("asset_type", _enum("creative_asset_type", CREATIVE_ASSET_TYPE), nullable=False),
        sa.Column("status", _enum("creative_status", CREATIVE_STATUS), nullable=False, server_default="PENDING"),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("title", sa.String(255)),
        sa.Column("content_text", sa.Text()),
        sa.Column("content_url", sa.String(1024)),
        sa.Column("content_metadata", sa.JSON()),
        sa.Column("external_system", sa.String(64)),
        sa.Column("external_ref", sa.String(255)),
        sa.Column("approved_by", sa.String(128)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column("blocked_reason", sa.Text()),
        sa.Column("score_run_id", BIGINT, sa.ForeignKey("score_runs.id", ondelete="SET NULL")),
        sa.Column("performance_metrics", sa.JSON()),
        *_timestamps(),
        sa.UniqueConstraint("portfolio_item_id", "asset_type", "version", name="uq_creative_assets_item_type_version"),
    )
    op.create_index("ix_creative_assets_portfolio_item_id", "creative_assets", ["portfolio_item_id"])
    op.create_index("ix_creative_assets_product_id", "creative_assets", ["product_id"])
    op.create_index("ix_creative_assets_asset_type", "creative_assets", ["asset_type"])
    op.create_index("ix_creative_assets_status", "creative_assets", ["status"])
    op.create_index("ix_creative_assets_external_ref", "creative_assets", ["external_ref"])
    op.create_index("ix_creative_assets_score_run_id", "creative_assets", ["score_run_id"])
    op.create_index("ix_creative_assets_type_status", "creative_assets", ["asset_type", "status"])

    op.create_table(
        "creative_asset_events",
        sa.Column("id", BIGINT, primary_key=True),
        sa.Column("asset_id", BIGINT, sa.ForeignKey("creative_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_status", _enum("creative_status", CREATIVE_STATUS)),
        sa.Column("to_status", _enum("creative_status", CREATIVE_STATUS), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("note", sa.Text()),
        *_timestamps(),
    )
    op.create_index("ix_creative_asset_events_asset_id", "creative_asset_events", ["asset_id"])
    op.create_index("ix_creative_asset_events_occurred_at", "creative_asset_events", ["occurred_at"])

    op.create_table(
        "publications",
        sa.Column("id", BIGINT, primary_key=True),
        sa.Column("creative_asset_id", BIGINT, sa.ForeignKey("creative_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("portfolio_item_id", sa.Integer(), sa.ForeignKey("portfolio_items.id", ondelete="SET NULL")),
        sa.Column("channel", sa.String(64), nullable=False),
        sa.Column("account_ref", sa.String(255)),
        sa.Column("external_post_id", sa.String(255)),
        sa.Column("status", _enum("publication_status", PUBLICATION_STATUS), nullable=False, server_default="DRAFT"),
        sa.Column("scheduled_for", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("removed_at", sa.DateTime(timezone=True)),
        sa.Column("marketplace", _enum("marketplace", MARKETPLACE)),
        sa.Column("url", sa.String(1024)),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("impressions", sa.Integer()),
        sa.Column("clicks", sa.Integer()),
        sa.Column("ctr", sa.Float()),
        sa.Column("metrics_collected_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index("ix_publications_creative_asset_id", "publications", ["creative_asset_id"])
    op.create_index("ix_publications_portfolio_item_id", "publications", ["portfolio_item_id"])
    op.create_index("ix_publications_channel", "publications", ["channel"])
    op.create_index("ix_publications_external_post_id", "publications", ["external_post_id"])
    op.create_index("ix_publications_status", "publications", ["status"])
    op.create_index("ix_publications_published_at", "publications", ["published_at"])
    op.create_index("ix_publications_status_published", "publications", ["status", "published_at"])
    op.create_index("ix_publications_channel_published", "publications", ["channel", "published_at"])

    # --- Tracking -------------------------------------------------------------
    op.create_table(
        "affiliate_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE")),
        sa.Column("portfolio_item_id", sa.Integer(), sa.ForeignKey("portfolio_items.id", ondelete="CASCADE")),
        sa.Column("marketplace", _enum("marketplace", MARKETPLACE), nullable=False),
        sa.Column("channel", sa.String(64)),
        sa.Column("destination_url", sa.String(1024), nullable=False),
        sa.Column("affiliate_url", sa.String(1024), nullable=False),
        sa.Column("short_code", sa.String(32), nullable=False),
        sa.Column("campaign", sa.String(128)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("clicks_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sales_total", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.UniqueConstraint("short_code", name="uq_affiliate_links_short_code"),
    )
    op.create_index("ix_affiliate_links_product_id", "affiliate_links", ["product_id"])
    op.create_index("ix_affiliate_links_portfolio_item_id", "affiliate_links", ["portfolio_item_id"])
    op.create_index("ix_affiliate_links_marketplace", "affiliate_links", ["marketplace"])
    op.create_index("ix_affiliate_links_channel", "affiliate_links", ["channel"])
    op.create_index("ix_affiliate_links_marketplace_active", "affiliate_links", ["marketplace", "is_active"])

    op.create_table(
        "click_events",
        sa.Column("id", BIGINT, primary_key=True),
        sa.Column("affiliate_link_id", sa.Integer(), sa.ForeignKey("affiliate_links.id", ondelete="CASCADE"), nullable=False),
        sa.Column("portfolio_item_id", sa.Integer(), sa.ForeignKey("portfolio_items.id", ondelete="SET NULL")),
        sa.Column("publication_id", BIGINT, sa.ForeignKey("publications.id", ondelete="SET NULL")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("external_click_id", sa.String(128)),
        sa.Column("channel", sa.String(64)),
        sa.Column("referrer", sa.String(1024)),
        sa.Column("country", sa.String(8)),
        sa.Column("device", sa.String(32)),
        sa.Column("cost", MONEY),
        *_timestamps(),
        sa.UniqueConstraint("external_click_id", name="uq_click_events_external_click_id"),
    )
    op.create_index("ix_click_events_affiliate_link_id", "click_events", ["affiliate_link_id"])
    op.create_index("ix_click_events_portfolio_item_id", "click_events", ["portfolio_item_id"])
    op.create_index("ix_click_events_publication_id", "click_events", ["publication_id"])
    op.create_index("ix_click_events_occurred_at", "click_events", ["occurred_at"])
    op.create_index("ix_click_events_external_click_id", "click_events", ["external_click_id"])
    op.create_index("ix_click_events_channel", "click_events", ["channel"])
    op.create_index("ix_click_events_link_occurred", "click_events", ["affiliate_link_id", "occurred_at"])

    op.create_table(
        "publication_links",
        sa.Column("publication_id", BIGINT, sa.ForeignKey("publications.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("affiliate_link_id", sa.Integer(), sa.ForeignKey("affiliate_links.id", ondelete="CASCADE"), primary_key=True),
    )

    op.create_table(
        "sales",
        sa.Column("id", BIGINT, primary_key=True),
        sa.Column("portfolio_item_id", sa.Integer(), sa.ForeignKey("portfolio_items.id", ondelete="SET NULL")),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL")),
        sa.Column("affiliate_link_id", sa.Integer(), sa.ForeignKey("affiliate_links.id", ondelete="SET NULL")),
        sa.Column("publication_id", BIGINT, sa.ForeignKey("publications.id", ondelete="SET NULL")),
        sa.Column("marketplace", _enum("marketplace", MARKETPLACE), nullable=False),
        sa.Column("external_order_id", sa.String(128)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("currency", sa.String(8)),
        sa.Column("gross_amount", MONEY),
        sa.Column("net_amount", MONEY),
        sa.Column("channel", sa.String(64)),
        sa.Column("status", sa.String(32)),
        sa.Column("source_record_id", sa.Integer(), sa.ForeignKey("source_records.id", ondelete="SET NULL")),
        *_timestamps(),
        sa.UniqueConstraint("marketplace", "external_order_id", name="uq_sales_marketplace_order"),
    )
    op.create_index("ix_sales_portfolio_item_id", "sales", ["portfolio_item_id"])
    op.create_index("ix_sales_product_id", "sales", ["product_id"])
    op.create_index("ix_sales_affiliate_link_id", "sales", ["affiliate_link_id"])
    op.create_index("ix_sales_publication_id", "sales", ["publication_id"])
    op.create_index("ix_sales_marketplace", "sales", ["marketplace"])
    op.create_index("ix_sales_external_order_id", "sales", ["external_order_id"])
    op.create_index("ix_sales_occurred_at", "sales", ["occurred_at"])
    op.create_index("ix_sales_channel", "sales", ["channel"])
    op.create_index("ix_sales_status", "sales", ["status"])
    op.create_index("ix_sales_source_record_id", "sales", ["source_record_id"])
    op.create_index("ix_sales_marketplace_occurred", "sales", ["marketplace", "occurred_at"])

    op.create_table(
        "commissions",
        sa.Column("id", BIGINT, primary_key=True),
        sa.Column("sale_id", BIGINT, sa.ForeignKey("sales.id", ondelete="CASCADE")),
        sa.Column("portfolio_item_id", sa.Integer(), sa.ForeignKey("portfolio_items.id", ondelete="SET NULL")),
        sa.Column("marketplace", _enum("marketplace", MARKETPLACE), nullable=False),
        sa.Column("estimated_amount", MONEY),
        sa.Column("confirmed_amount", MONEY),
        sa.Column("currency", sa.String(8)),
        sa.Column("rate_basis_points", sa.Integer()),
        sa.Column("status", sa.String(32)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("external_commission_id", sa.String(128)),
        sa.Column("source_record_id", sa.Integer(), sa.ForeignKey("source_records.id", ondelete="SET NULL")),
        *_timestamps(),
    )
    op.create_index("ix_commissions_sale_id", "commissions", ["sale_id"])
    op.create_index("ix_commissions_portfolio_item_id", "commissions", ["portfolio_item_id"])
    op.create_index("ix_commissions_marketplace", "commissions", ["marketplace"])
    op.create_index("ix_commissions_status", "commissions", ["status"])
    op.create_index("ix_commissions_confirmed_at", "commissions", ["confirmed_at"])
    op.create_index("ix_commissions_external_commission_id", "commissions", ["external_commission_id"])
    op.create_index("ix_commissions_source_record_id", "commissions", ["source_record_id"])
    op.create_index("ix_commissions_status_confirmed", "commissions", ["status", "confirmed_at"])
    op.create_index("ix_commissions_marketplace_confirmed", "commissions", ["marketplace", "confirmed_at"])

    # --- Jobs / observabilidade ----------------------------------------------
    op.create_table(
        "jobs",
        sa.Column("id", BIGINT, primary_key=True),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("agent", sa.String(64)),
        sa.Column("status", _enum("job_status", JOB_STATUS), nullable=False, server_default="PENDING"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("duration_seconds", sa.Float()),
        sa.Column("progress_pct", sa.Float()),
        sa.Column("params", sa.JSON()),
        sa.Column("result_summary", sa.Text()),
        sa.Column("result", sa.JSON()),
        sa.Column("error_type", sa.String(128)),
        sa.Column("error_message", sa.Text()),
        sa.Column("error_traceback", sa.Text()),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("parent_job_id", BIGINT, sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("idempotency_key", sa.String(128)),
        sa.Column("triggered_by", sa.String(128)),
        *_timestamps(),
        sa.UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
    )
    op.create_index("ix_jobs_job_type", "jobs", ["job_type"])
    op.create_index("ix_jobs_agent", "jobs", ["agent"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_started_at", "jobs", ["started_at"])
    op.create_index("ix_jobs_type_status_started", "jobs", ["job_type", "status", "started_at"])
    op.create_index("ix_jobs_status_started", "jobs", ["status", "started_at"])

    op.create_table(
        "job_events",
        sa.Column("id", BIGINT, primary_key=True),
        sa.Column("job_id", BIGINT, sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("level", sa.String(16), nullable=False, server_default="INFO"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON()),
    )
    op.create_index("ix_job_events_job_id", "job_events", ["job_id"])
    op.create_index("ix_job_events_occurred_at", "job_events", ["occurred_at"])
    op.create_index("ix_job_events_job_occurred", "job_events", ["job_id", "occurred_at"])

    # --- Aprendizado ----------------------------------------------------------
    op.create_table(
        "score_calibrations",
        sa.Column("id", BIGINT, primary_key=True),
        sa.Column("dimension", _enum("score_dimension", SCORE_DIMENSION), nullable=False),
        sa.Column("algorithm_version", sa.String(32), nullable=False),
        sa.Column("proposed_version", sa.String(32)),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("mean_absolute_error", sa.Float()),
        sa.Column("correlation", sa.Float()),
        sa.Column("hit_rate", sa.Float()),
        sa.Column("weights_before", sa.JSON()),
        sa.Column("weights_after", sa.JSON()),
        sa.Column("proposal_rationale", sa.Text()),
        sa.Column("is_applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("applied_by", sa.String(128)),
        sa.Column("rejected_reason", sa.Text()),
        *_timestamps(),
    )
    op.create_index("ix_score_calibrations_dimension", "score_calibrations", ["dimension"])
    op.create_index("ix_score_calibrations_dimension_period", "score_calibrations", ["dimension", "period_end"])

    op.create_table(
        "prediction_outcomes",
        sa.Column("id", BIGINT, primary_key=True),
        sa.Column("score_run_id", BIGINT, sa.ForeignKey("score_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("portfolio_item_id", sa.Integer(), sa.ForeignKey("portfolio_items.id", ondelete="SET NULL")),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL")),
        sa.Column("recommendation_id", BIGINT, sa.ForeignKey("recommendations.id", ondelete="SET NULL")),
        sa.Column("dimension", _enum("score_dimension", SCORE_DIMENSION), nullable=False),
        sa.Column("algorithm_version", sa.String(32), nullable=False),
        sa.Column("marketplace", _enum("marketplace", MARKETPLACE)),
        sa.Column("predicted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("predicted_score", SCORE, nullable=False),
        sa.Column("predicted_confidence", sa.Float()),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("actual_revenue", sa.Numeric(14, 2)),
        sa.Column("actual_commission", sa.Numeric(14, 2)),
        sa.Column("actual_clicks", sa.Integer()),
        sa.Column("actual_conversions", sa.Integer()),
        sa.Column("actual_ctr", sa.Float()),
        sa.Column("actual_conversion_rate", sa.Float()),
        sa.Column("score_error", sa.Float()),
        sa.Column("was_profitable", sa.Boolean()),
        sa.Column("outcome_summary", sa.Text()),
        sa.Column("observed_payload", sa.JSON()),
        sa.Column("calibration_id", BIGINT, sa.ForeignKey("score_calibrations.id", ondelete="SET NULL")),
        *_timestamps(),
        sa.UniqueConstraint("score_run_id", "window_days", name="uq_prediction_outcomes_run_window"),
    )
    op.create_index("ix_prediction_outcomes_score_run_id", "prediction_outcomes", ["score_run_id"])
    op.create_index("ix_prediction_outcomes_portfolio_item_id", "prediction_outcomes", ["portfolio_item_id"])
    op.create_index("ix_prediction_outcomes_product_id", "prediction_outcomes", ["product_id"])
    op.create_index("ix_prediction_outcomes_recommendation_id", "prediction_outcomes", ["recommendation_id"])
    op.create_index("ix_prediction_outcomes_dimension", "prediction_outcomes", ["dimension"])
    op.create_index("ix_prediction_outcomes_algorithm_version", "prediction_outcomes", ["algorithm_version"])
    op.create_index("ix_prediction_outcomes_predicted_at", "prediction_outcomes", ["predicted_at"])
    op.create_index("ix_prediction_outcomes_evaluated_at", "prediction_outcomes", ["evaluated_at"])
    op.create_index("ix_prediction_outcomes_calibration_id", "prediction_outcomes", ["calibration_id"])
    op.create_index(
        "ix_prediction_outcomes_version_evaluated", "prediction_outcomes", ["algorithm_version", "evaluated_at"]
    )


def downgrade() -> None:
    # Ordem inversa das dependências de FK.
    for table in (
        "prediction_outcomes",
        "score_calibrations",
        "job_events",
        "jobs",
        "commissions",
        "sales",
        "publication_links",
        "click_events",
        "affiliate_links",
        "publications",
        "creative_asset_events",
        "creative_assets",
        "portfolio_transitions",
        "portfolio_items",
        "recommendations",
        "score_contributions",
        "score_runs",
        "score_algorithms",
        "price_history",
        "product_metrics",
        "products",
        "sellers",
        "source_records",
    ):
        op.drop_table(table)
