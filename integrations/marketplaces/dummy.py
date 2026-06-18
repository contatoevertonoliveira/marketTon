from __future__ import annotations

import pandas as pd

COLUMNS = [
    "title",
    "price",
    "orders",
    "rating",
    "marketplace",
    "url",
    "collected_at",
]


class DummyAdapter:
    name = "dummy"

    def fetch_products(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "title": "Lanterna Tática Pro LED",
                    "price": 39.9,
                    "orders": 1243,
                    "rating": 4.6,
                    "marketplace": self.name,
                    "url": "https://example.com/lanterna",
                    "collected_at": "2026-06-18",
                },
                {
                    "title": "Fone Bluetooth Mini",
                    "price": 59.9,
                    "orders": 980,
                    "rating": 4.4,
                    "marketplace": self.name,
                    "url": "https://example.com/fone",
                    "collected_at": "2026-06-18",
                },
                {
                    "title": "Garrafa Térmica 1L",
                    "price": 49.9,
                    "orders": 756,
                    "rating": 4.7,
                    "marketplace": self.name,
                    "url": "https://example.com/garrafa",
                    "collected_at": "2026-06-18",
                },
            ],
            columns=COLUMNS,
        )

    def fetch_sales(self) -> pd.DataFrame:
        return pd.DataFrame(columns=["product", "sold_last"])


def register() -> None:
    from integrations.marketplaces.registry import register_adapter
    register_adapter(DummyAdapter())


try:
    register()
except Exception:
    pass
