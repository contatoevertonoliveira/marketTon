"""Dependências compartilhadas da API.

Centraliza o que cada router precisa: sessão de banco, cliente de IA e acesso aos
adapters de marketplace já registrados.
"""
from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy.orm import Session

from core.db.session import get_db as _get_db
from core.services.ai.client import AIClient


def get_session() -> Iterator[Session]:
    """Sessão de banco por requisição.

    Não faz commit: o endpoint decide quando a transação termina. Escritas passam
    por `session_scope()` ou por `session.commit()` explícito no handler.
    """
    yield from _get_db()


@lru_cache
def get_ai_client() -> AIClient:
    """Cliente de IA como singleton.

    Caro de construir e sem estado por requisição. `is_available` é consultado em
    cada uso, então desligar a IA no `.env` e reiniciar basta.
    """
    return AIClient()


def get_adapters() -> dict:
    """Adapters registrados, com os reais já carregados."""
    from integrations.marketplaces.registry import list_adapter_names, load_adapters, resolve

    load_adapters()
    return {name: resolve(name) for name in list_adapter_names()}


__all__ = ["get_adapters", "get_ai_client", "get_session"]
