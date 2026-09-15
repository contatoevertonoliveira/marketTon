"""Fixtures compartilhadas dos testes.

Os testes usam SQLite em memória: o objetivo é exercitar as regras de domínio,
não o dialeto do PostgreSQL. `ALLOW_SQLITE=true` existe exatamente para isso — o
sistema em si recusa SQLite (ver `Settings.validate_database_url`).
"""
from __future__ import annotations

import os

import pytest

# Precisa estar definido antes de qualquer import de `config.settings`.
os.environ.setdefault("ALLOW_SQLITE", "true")
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
# Auth desligada por padrão nos testes: os testes de API verificam o domínio, não
# o portão de autenticação. `tests/test_auth.py` e `tests/test_api_auth.py` sobem
# clientes próprios com `AUTH_ENABLED=true` para exercitar o portão de verdade.
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only")
# Custo mínimo de Argon2 nos testes. Em produção o custo é o recomendado da
# RFC 9106; aqui centenas de hashes seriam gerados e o custo alto dominaria o
# tempo de execução sem acrescentar cobertura de teste.
os.environ.setdefault("ARGON2_TIME_COST", "1")
os.environ.setdefault("ARGON2_MEMORY_COST", "8192")
os.environ.setdefault("ARGON2_PARALLELISM", "1")


@pytest.fixture(scope="session", autouse=True)
def _fast_password_hashing():
    """Reduz o custo do Argon2 para a suíte.

    O custo é lido da configuração pelo hasher, que é memoizado. Como o ambiente é
    definido no import deste arquivo, o `lru_cache` de `get_settings` já teria a
    configuração correta; ainda assim descartamos o hasher para garantir que os
    testes usem o custo reduzido mesmo se algum módulo hashear durante a coleta.
    """
    from core.services.security import reset_password_hasher

    reset_password_hasher()
    yield
    reset_password_hasher()


@pytest.fixture
def session():
    """Sessão sobre um banco limpo, com todo o schema criado.

    Importa `core.db` (o pacote), não `core.db.base`. Isso é deliberado:
    `Base.metadata` só contém os modelos que foram **importados**, então quem
    importa apenas `core.db.base` obtém um registry vazio e `create_all` não cria
    tabela nenhuma. O `__init__` do pacote existe justamente para ser o ponto único
    que carrega todos os modelos.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from core.db import Base

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    try:
        yield db
        db.commit()
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def source_record(session):
    """Registro de procedência, pré-requisito obrigatório de qualquer produto."""
    from datetime import UTC, datetime

    from core.db.base import ConnectorKind, Marketplace
    from core.db.catalog import SourceRecord

    record = SourceRecord(
        marketplace=Marketplace.MERCADO_LIVRE,
        connector="mercado_livre",
        connector_kind=ConnectorKind.OFFICIAL_API,
        endpoint="https://api.mercadolibre.com/sites/MLB/search",
        external_id="MLB123",
        collected_at=datetime.now(UTC),
        reliability=1.0,
    )
    session.add(record)
    session.flush()
    return record


@pytest.fixture
def product(session, source_record):
    """Produto mínimo, sempre com procedência."""
    from datetime import UTC, datetime

    from core.db.base import Marketplace
    from core.db.catalog import Product

    now = datetime.now(UTC)
    item = Product(
        marketplace=Marketplace.MERCADO_LIVRE,
        external_id="MLB123",
        title="Fone Bluetooth Mini",
        price=150.0,
        affiliate_commission_pct=12.0,
        source_record_id=source_record.id,
        first_seen_at=now,
        last_seen_at=now,
    )
    session.add(item)
    session.flush()
    return item
