from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from integrations.marketplaces.registry import list_adapter_names, resolve
from integrations.marketplaces.base import MarketplaceAdapter


@dataclass(frozen=True)
class ServiceInfo:
    name: str
    description: str
    tags: tuple[str, ...]
    invocation: str = ""

    def to_public(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "tags": self.tags, "invocation": self.invocation}


@dataclass(frozen=True)
class InputInfo:
    name: str
    mode: str
    location: str
    required: bool

    def to_public(self) -> dict[str, Any]:
        return {"name": self.name, "mode": self.mode, "location": self.location, "required": self.required}


@dataclass(frozen=True)
class OutputInfo:
    name: str
    format: str
    path: str
    description: str

    def to_public(self) -> dict[str, Any]:
        return {"name": self.name, "format": self.format, "path": self.path, "description": self.description}


@dataclass(frozen=True)
class InventoryDoc:
    updated_at: str
    services: list[ServiceInfo] = field(default_factory=list)
    inputs: list[InputInfo] = field(default_factory=list)
    outputs: list[OutputInfo] = field(default_factory=list)

    def to_public(self) -> dict[str, Any]:
        return {
            "updated_at": self.updated_at,
            "services": [s.to_public() for s in self.services],
            "inputs": [i.to_public() for i in self.inputs],
            "outputs": [o.to_public() for o in self.outputs],
        }


def services() -> list[ServiceInfo]:
    items: list[ServiceInfo] = []
    items.append(
        ServiceInfo(
            "google_trends",
            "Interest over time and compare by keyword",
            ("trends", "interest"),
            "fetch_keyword_interest(keyword)",
        )
    )
    items.append(
        ServiceInfo(
            "google_trends_comp",
            "Interest compare across keywords",
            ("trends", "interest"),
            "fetch_compare_interest(keywords)",
        )
    )
    items.extend(_adapters())
    items.extend(_ads())
    return items


def inputs() -> list[InputInfo]:
    return [
        InputInfo("keywords", ".env", "dashboard/config/config.example.env", False),
        InputInfo("marketplace credentials", "env", "integrations/*/.env", True),
        InputInfo("seller_mode", "env", "theme/.env.example", False),
    ]


def outputs(base_path: Path | None = None) -> list[OutputInfo]:
    data = (base_path or Path(__file__).resolve().parent.parent) / "data"
    return [
        OutputInfo("trend_alerts.csv", "csv", str(data / "trend_alerts.csv"), "Daily trend signals by keyword"),
        OutputInfo(
            "products/product_hunter_latest.csv",
            "csv",
            str(data / "products" / "product_hunter_latest.csv"),
            "Top candidate products across marketplaces",
        ),
        OutputInfo("copy_variants.csv", "csv", str(data / "copy_variants.csv"), "Generated copy variants"),
        OutputInfo("reports/growth_report_*.csv", "csv", str(data / "reports"), "Consolidated growth report"),
        OutputInfo("reports/marketplace_health_*.csv", "csv", str(data / "reports"), "Catalog health signals"),
    ]


def inventory_doc(base_path: Path | None = None) -> InventoryDoc:
    code_path = base_path or Path(__file__).resolve().parent.parent
    return InventoryDoc(
        updated_at=__import__("datetime").datetime.now().isoformat(),
        services=services(),
        inputs=inputs(),
        outputs=outputs(code_path),
    )


def save_inventory(path: Path | None = None) -> Path:
    path = path or Path(__file__).resolve().parent.parent / "inventory" / "services.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = inventory_doc()
    path.write_text(json.dumps(doc.to_public(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


if __name__ == "__main__":
    print(save_inventory())


def _ads() -> list[ServiceInfo]:
    items: list[ServiceInfo] = []
    try:
        meta_get_status()
        items.append(
            ServiceInfo(
                "meta_ads",
                "Meta Marketing API",
                ("ads", "facebook", "meta"),
                "get_campaigns(account_id) / get_insights(account_id)",
            )
        )
    except Exception as e:  # noqa: BLE001
        items.append(ServiceInfo("meta_ads", f"Meta offline ({e})", ("ads", "facebook")))
    try:
        search_ads("headphones", country="US", limit=3)
        items.append(
            ServiceInfo(
                "tiktok_ads",
                "TikTok Ads Library",
                ("ads", "tiktok"),
                "search_ads(query, country, limit)",
            )
        )
    except Exception as e:  # noqa: BLE001
        items.append(ServiceInfo("tiktok_ads", f"TikTok offline ({e})", ("ads", "tiktok")))
    return items


def _adapters() -> list[ServiceInfo]:
    out: list[ServiceInfo] = []
    for name in list_adapter_names():
        adapter: MarketplaceAdapter | None = resolve(name)
        if adapter is None:
            out.append(ServiceInfo(name, "adapter missing", ("marketplace", name), ""))
            continue
        out.append(
            ServiceInfo(
                name,
                "Marketplace adapter",
                ("marketplace", "products", "catalog"),
                "adapter.fetch_products()",
            )
        )
    return out
