"""Marketplace adapter registry.

Adapters self-register through `register`. A missing adapter must fail loudly
instead of silently falling back to fabricated data (briefing section 2: data
that does not exist may not be invented).
"""
from __future__ import annotations

import logging

from integrations.marketplaces.base import MarketplaceAdapter

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, MarketplaceAdapter] = {}


def register(adapter: MarketplaceAdapter) -> MarketplaceAdapter:
    """Register an adapter instance by its `name`."""
    if not getattr(adapter, "name", None):
        raise ValueError(f"{type(adapter).__name__} must define a non-empty `name`")
    _REGISTRY[adapter.name] = adapter
    logger.debug("registered marketplace adapter: %s", adapter.name)
    return adapter


def resolve(name: str) -> MarketplaceAdapter | None:
    return _REGISTRY.get(name)


def list_adapter_names() -> list[str]:
    return list(_REGISTRY.keys())


def registered_adapters() -> list[MarketplaceAdapter]:
    return list(_REGISTRY.values())


def load_adapters() -> None:
    """Importa os adapters reais para que se registrem.

    Chamado uma vez na inicialização da aplicação. Explícito em vez de depender de
    efeito de importação, para que os testes controlem o registro.
    """
    from integrations.marketplaces.amazon import AmazonAdapter
    from integrations.marketplaces.mercado_livre import MercadoLivreAdapter
    from integrations.marketplaces.shopee import ShopeeAdapter
    from integrations.marketplaces.tiktok_shop import TikTokShopAdapter

    for adapter_cls in (MercadoLivreAdapter, ShopeeAdapter, AmazonAdapter, TikTokShopAdapter):
        if adapter_cls.name in _REGISTRY:
            continue
        try:
            register(adapter_cls())
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not register %s: %s", adapter_cls.name, exc)
