"""Registry de adapters de marketplace.

Importar este pacote registra os adapters reais disponíveis.
"""
from __future__ import annotations

from integrations.marketplaces.registry import (  # noqa: F401
    list_adapter_names,
    load_adapters,
    register,
    registered_adapters,
    resolve,
)

__all__ = [
    "list_adapter_names",
    "load_adapters",
    "register",
    "registered_adapters",
    "resolve",
]
