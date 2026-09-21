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
    """Adapters registrados, com os reais já carregados.

    Os adapters são singletons no `registry` — construídos uma vez, na primeira
    chamada, com a config de `.env`/`config/settings.py`. Antes de devolvê-los,
    sobrepomos qualquer credencial salva em `marketplace_credentials` (tela de
    Integrações). Como isso roda a cada chamada, editar uma credencial passa a
    valer no próximo request, sem reiniciar o processo — sem essa sobreposição
    o `.env` venceria sempre, e a tela de Integrações não serviria pra nada.
    """
    from integrations.marketplaces.registry import list_adapter_names, load_adapters, resolve

    load_adapters()
    adapters = {name: resolve(name) for name in list_adapter_names()}
    _apply_credential_overrides(adapters)
    _apply_commission_rates(adapters)
    return adapters


def _apply_credential_overrides(adapters: dict) -> None:
    from sqlalchemy import select

    from core.db.marketplace_credentials import MarketplaceCredential
    from core.db.session import session_scope

    try:
        with session_scope() as session:
            rows = session.scalars(
                select(MarketplaceCredential).where(MarketplaceCredential.enabled.is_(True))
            ).all()
            overrides = {row.marketplace.value: dict(row.values or {}) for row in rows}
    except Exception:  # noqa: BLE001 - banco fora do ar não pode derrubar o registro de adapters
        return

    for name, values in overrides.items():
        adapter = adapters.get(name)
        cfg = getattr(adapter, "cfg", None)
        if cfg is None:
            continue
        for key, value in values.items():
            # Só sobrescreve campos que o dataclass de config realmente declara,
            # e só quando um valor foi de fato salvo (string vazia não apaga).
            if value and hasattr(cfg, key):
                setattr(cfg, key, value)


def _apply_commission_rates(adapters: dict) -> None:
    """Entrega a cada adapter a tabela de comissão por categoria do operador."""
    from sqlalchemy import select

    from core.db.commission_rates import CommissionRate
    from core.db.session import session_scope

    try:
        with session_scope() as session:
            rows = session.scalars(select(CommissionRate)).all()
            by_marketplace: dict[str, dict[str, float]] = {}
            for row in rows:
                by_marketplace.setdefault(row.marketplace.value, {})[row.category_id] = row.rate_pct
    except Exception:  # noqa: BLE001 - banco fora do ar não pode derrubar o registro de adapters
        return

    for name, adapter in adapters.items():
        adapter.commission_rates = by_marketplace.get(name, {})


__all__ = ["get_adapters", "get_ai_client", "get_session"]
