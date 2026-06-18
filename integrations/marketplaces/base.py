"""Base para integração de marketplaces."""
from __future__ import annotations

from abc import ABC, abstractmethod

from pandas import DataFrame


class MarketplaceAdapter(ABC):
    name: str = "base"

    @abstractmethod
    def fetch_products(self) -> DataFrame:  # pragma: no cover - interface
        ...

    @abstractmethod
    def fetch_sales(self) -> DataFrame:  # pragma: no cover - interface
        ...

    @abstractmethod
    def search_competitor(self, query: str) -> list[dict]:  # pragma: no cover - interface
        ...
