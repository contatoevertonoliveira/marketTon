"""Marketplace adapter registry and stubs."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from integrations.marketplaces.base import MarketplaceAdapter

if TYPE_CHECKING:
    pass

_REGISTRY: dict[str, MarketplaceAdapter] = {}


def register(adapter: MarketplaceAdapter) -> None:
    _REGISTRY[adapter.name] = adapter


def resolve(name: str) -> MarketplaceAdapter | None:
    return _REGISTRY.get(name)


def list_adapter_names() -> list[str]:
    return list(_REGISTRY.keys())


class FakeMarketplaceAdapter(MarketplaceAdapter):
    name = "fake_local"

    def fetch_products(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"id": "F1", "title": "Camiseta Dry Fit Premium", "price": 79.9, "stock": 120, "category": "Moda"},
                {"id": "F2", "title": "Garrafa Térmica 1L", "price": 59.9, "stock": 5, "category": "Casa"},
                {"id": "F3", "title": "Luminária Mesa Touch RGB", "price": 129.9, "stock": 0, "category": "Casa"},
            ]
        )

    def fetch_sales(self) -> pd.DataFrame:
        return pd.DataFrame()

    def search_competitor(self, query: str) -> list[dict]:
        return [{"platform": "fake", "query": query, "notes": "competitor stub"}]


class ShopifyStubAdapter(MarketplaceAdapter):
    name = "shopify_stub"

    def fetch_products(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"id": "S1", "title": "Tênis Runner Pro", "price": 299.9, "stock": 40, "category": "Calçados"},
                {"id": "S2", "title": "Fone ANC Lite 2025", "price": 189.9, "stock": 80, "category": "Eletrônicos"},
            ]
        )

    def fetch_sales(self) -> pd.DataFrame:
        return pd.DataFrame()

    def search_competitor(self, query: str) -> list[dict]:
        return [{"platform": "shopify_stub", "query": query, "notes": "competitor stub"}]


class DummyAdapter:
    name = "dummy"

    def fetch_products(self):
        return pd.DataFrame(
            [
                {"title": "Lanterna Tática Pro LED", "price": 39.9, "orders": 1243, "commission_pct": 12.0, "url": "https://example.com/lanterna", "collected_at": "2026-06-18"},
                {"title": "Fone Bluetooth Mini", "price": 59.9, "orders": 980, "commission_pct": 9.5, "url": "https://example.com/fone", "collected_at": "2026-06-18"},
                {"title": "Garrafa Térmica 1L", "price": 49.9, "orders": 756, "commission_pct": 14.0, "url": "https://example.com/garrafa", "collected_at": "2026-06-18"},
            ]
        )

    def fetch_sales(self):
        return pd.DataFrame()

    def search_competitor(self, query: str) -> list[dict]:
        return [{"platform": "dummy", "query": query, "results": 0}]


register(FakeMarketplaceAdapter())
register(ShopifyStubAdapter())
register(DummyAdapter())
