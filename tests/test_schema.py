"""Coerência do schema: modelos ORM versus migration Alembic.

Foi exatamente a divergência entre fontes de schema que produziu três definições
incompatíveis de `trend_alerts`, `payments` e `groups` no projeto SQLite. Estes
testes falham se as duas fontes deixarem de concordar, e verificam que as
garantias estruturais exigidas pelo briefing continuam no lugar.

São testes de *estrutura* (metadata), portanto não precisam de PostgreSQL.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import core.db  # noqa: F401 - importar o pacote registra todos os modelos
from core.db.base import Base, CreativeAssetType, PortfolioState

VERSIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"
INITIAL_MIGRATION = VERSIONS_DIR / "0001_initial_schema.py"


def _migration_files() -> list[Path]:
    return sorted(VERSIONS_DIR.glob("[0-9]*.py"))


def _load_migration(path: Path | None = None):
    path = path or INITIAL_MIGRATION
    spec = importlib.util.spec_from_file_location(f"migration_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _migration_source() -> str:
    """Concatena todas as migrations.

    O schema evolui por migrations incrementais, então a verificação de cobertura
    precisa olhar o conjunto — não apenas a inicial. É o que permite adicionar uma
    tabela depois sem reescrever a migration já aplicada em produção.
    """
    return "\n".join(path.read_text(encoding="utf-8") for path in _migration_files())


# --- Estrutura da migration ---------------------------------------------------


def test_every_migration_is_loadable_and_reversible() -> None:
    files = _migration_files()
    assert files, "nenhuma migration encontrada"
    for path in files:
        migration = _load_migration(path)
        assert callable(migration.upgrade), f"{path.name} sem upgrade"
        assert callable(migration.downgrade), f"{path.name} sem downgrade"
        assert migration.revision, f"{path.name} sem revision"


def test_migrations_form_a_single_chain() -> None:
    """Duas migrations com o mesmo `down_revision` criariam branches divergentes."""
    revisions = {}
    for path in _migration_files():
        migration = _load_migration(path)
        assert migration.revision not in revisions, f"revision duplicada: {migration.revision}"
        revisions[migration.revision] = migration.down_revision

    roots = [rev for rev, down in revisions.items() if down is None]
    assert len(roots) == 1, f"esperado exatamente um ponto de partida, encontrados {roots}"

    for revision, down in revisions.items():
        if down is not None:
            assert down in revisions, f"{revision} aponta para down_revision inexistente: {down}"


def test_migration_covers_every_model_table() -> None:
    """Se alguém adicionar um modelo e esquecer a migration, este teste falha."""
    source = _migration_source()
    missing = [table for table in sorted(Base.metadata.tables) if f'"{table}"' not in source]
    assert not missing, f"tabelas do ORM ausentes nas migrations: {missing}"


def test_downgrade_drops_every_table_created() -> None:
    """Cada `create_table` precisa aparecer em algum `downgrade()`.

    A verificação usa o bloco de downgrade inteiro, não só chamadas literais de
    `drop_table`: a migration inicial derruba as tabelas em um laço sobre uma
    tupla, e uma regex de `op.drop_table("x")` não enxergaria isso.
    """
    downgrade_blocks = "\n".join(
        path.read_text(encoding="utf-8").split("def downgrade()")[-1]
        for path in _migration_files()
    )

    created: set[str] = set()
    for path in _migration_files():
        text = path.read_text(encoding="utf-8")
        created.update(re.findall(r'op\.create_table\(\s*"([^"]+)"', text))

    assert created, "nenhuma tabela criada"
    not_dropped = sorted(name for name in created if f'"{name}"' not in downgrade_blocks)
    assert not not_dropped, f"tabelas criadas sem drop no downgrade: {not_dropped}"


def test_downgrade_covers_every_model_table() -> None:
    source = _migration_source()
    downgrade_blocks = source.split("def downgrade()")[1:]
    combined = "\n".join(downgrade_blocks)
    not_dropped = [t for t in sorted(Base.metadata.tables) if f'"{t}"' not in combined]
    assert not not_dropped, f"tabelas não removidas em nenhum downgrade: {not_dropped}"


def test_migration_declares_every_index_of_the_models() -> None:
    """Índices também são schema: divergência aqui degrada consulta em silêncio."""
    source = _migration_source()
    declared = {
        index.name
        for table in Base.metadata.tables.values()
        for index in table.indexes
        if index.name
    }
    missing = sorted(name for name in declared if f'"{name}"' not in source)
    assert not missing, f"índices do ORM ausentes nas migrations: {missing}"


def test_migration_declares_every_unique_constraint() -> None:
    source = _migration_source()
    declared = {
        constraint.name
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint" and constraint.name
    }
    missing = sorted(name for name in declared if f'"{name}"' not in source)
    assert not missing, f"constraints únicas ausentes nas migrations: {missing}"


# --- Guarantias exigidas pelo briefing ----------------------------------------


def test_provenance_is_mandatory() -> None:
    """Seção 4: não existe produto (nem métrica) sem procedência registrada."""
    for table_name in ("products", "product_metrics", "price_history", "sellers"):
        column = Base.metadata.tables[table_name].columns["source_record_id"]
        assert not column.nullable, f"{table_name}.source_record_id deve ser NOT NULL"
        assert column.foreign_keys, f"{table_name}.source_record_id deve referenciar source_records"


def test_market_fields_are_nullable() -> None:
    """Seção 2: ausência de dado é NULL, nunca 0 fabricado ou estimado."""
    products = Base.metadata.tables["products"]
    for column in (
        "price",
        "original_price",
        "discount_pct",
        "affiliate_commission_pct",
        "available_quantity",
        "sold_quantity",
        "rating",
        "review_count",
        "ranking_position",
        "popularity_score",
    ):
        assert products.columns[column].nullable, f"products.{column} deve ser anulável"


def test_score_run_stores_the_whole_calculation() -> None:
    """Seção 5: inputs, pesos, fórmula, versão, resultado e timestamp."""
    runs = Base.metadata.tables["score_runs"]
    for column in ("inputs", "weights", "formula", "algorithm_version", "score", "computed_at"):
        assert column in runs.columns, f"score_runs.{column} ausente"
    for column in ("inputs", "weights", "score", "computed_at"):
        assert not runs.columns[column].nullable, f"score_runs.{column} deve ser NOT NULL"


def test_contribution_is_the_explanation() -> None:
    """Seção 6: cada fator precisa ser registrado com seu impacto no score."""
    contributions = Base.metadata.tables["score_contributions"]
    for column in ("run_id", "factor", "label", "impact", "normalized_value", "weight"):
        assert column in contributions.columns, f"score_contributions.{column} ausente"
    for column in ("impact", "factor", "label"):
        assert not contributions.columns[column].nullable


def test_portfolio_states_cover_the_briefing_list() -> None:
    """Seção 7: os 15 estados."""
    expected = {
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
    }
    assert {state.value for state in PortfolioState} == expected


def test_creative_pipeline_covers_every_asset_type() -> None:
    """Seção 8: estados independentes por tipo de material."""
    expected = {"COPY", "IMAGE", "VIDEO", "VOICE", "EDIT", "APPROVAL", "PUBLICATION"}
    assert {asset.value for asset in CreativeAssetType} == expected


def test_commissions_separate_estimated_from_confirmed() -> None:
    """Comissão estimada não pode se passar por receita realizada."""
    commissions = Base.metadata.tables["commissions"]
    assert commissions.columns["estimated_amount"].nullable
    assert commissions.columns["confirmed_amount"].nullable


def test_sales_are_idempotent_per_marketplace() -> None:
    """Reingerir o mesmo pedido não pode duplicar a venda."""
    sales = Base.metadata.tables["sales"]
    names = {c.name for c in sales.constraints if c.__class__.__name__ == "UniqueConstraint"}
    assert "uq_sales_marketplace_order" in names


def test_learning_loop_tables_exist() -> None:
    """Seção 11: previsão → decisão → execução → resultado real."""
    outcomes = Base.metadata.tables["prediction_outcomes"]
    for column in ("predicted_score", "actual_revenue", "score_error", "window_days"):
        assert column in outcomes.columns
    calibrations = Base.metadata.tables["score_calibrations"]
    for column in ("weights_before", "weights_after", "sample_size", "is_applied"):
        assert column in calibrations.columns


def test_job_observability_tables_exist() -> None:
    """Seção 15: jobs precisam de histórico de execução."""
    jobs = Base.metadata.tables["jobs"]
    for column in ("status", "started_at", "finished_at", "duration_seconds", "error_message"):
        assert column in jobs.columns
    assert "job_events" in Base.metadata.tables


def test_primary_keys_are_portable_to_sqlite() -> None:
    """PKs de 64 bits precisam compilar para INTEGER no SQLite.

    O SQLite só auto-incrementa quando o tipo é exatamente `INTEGER PRIMARY KEY`.
    Com BIGINT puro a coluna vira NOT NULL sem default e todo INSERT falha — foi
    o que impediu os testes de exercitarem o schema real. Em PostgreSQL o tipo
    permanece BIGINT.
    """
    from sqlalchemy.dialects import postgresql, sqlite

    for table in Base.metadata.sorted_tables:
        for column in table.primary_key.columns:
            sqlite_ddl = column.type.compile(dialect=sqlite.dialect())
            assert sqlite_ddl == "INTEGER", (
                f"{table.name}.{column.name} compila para {sqlite_ddl} no SQLite "
                "e não vai auto-incrementar"
            )

    # E continua sendo BIGINT no banco de produção.
    samples = [
        Base.metadata.tables["score_runs"].columns["id"],
        Base.metadata.tables["click_events"].columns["id"],
        Base.metadata.tables["portfolio_transitions"].columns["id"],
    ]
    for column in samples:
        assert column.type.compile(dialect=postgresql.dialect()) == "BIGINT"
