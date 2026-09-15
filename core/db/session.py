"""Engine, fábrica de sessões e helpers transacionais.

SQLite foi descontinuado: `config.Settings` recusa qualquer URL que não seja
PostgreSQL, porque o domínio depende de tipos (JSONB, constraints, índices
parciais) e de concorrência real entre API e workers.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from config.settings import Settings, get_settings
from core.db.base import Base

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def create_db_engine(settings: Settings | None = None) -> Engine:
    """Cria um engine novo. Use em testes para apontar a outro banco."""
    settings = settings or get_settings()
    settings.validate_database_url()
    return create_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=settings.db_pool_pre_ping,
        future=True,
    )


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_db_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )
    return _session_factory


def reset_engine() -> None:
    """Descarta engine e fábrica. Necessário em testes e após trocar `.env`."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


@contextmanager
def session_scope() -> Iterator[Session]:
    """Sessão transacional: commit no sucesso, rollback na exceção."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """Dependência do FastAPI. Não faz commit: o endpoint decide."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


__all__ = [
    "Base",
    "create_db_engine",
    "get_db",
    "get_engine",
    "get_session_factory",
    "reset_engine",
    "session_scope",
]
