"""Gerar inventário final em inventory/services.json sem depender de pacotes ausentes."""
from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ServiceInfo:
    name: str
    description: str
    tags: tuple[str, ...]
    invocation: str = ""

    def to_public(self) -> dict:
        return {"name": self.name, "description": self.description, "tags": self.tags, "invocation": self.invocation}


@dataclass(frozen=True)
class InputInfo:
    name: str
    mode: str
    location: str
    required: bool

    def to_public(self) -> dict:
        return {"name": self.name, "mode": self.mode, "location": self.location, "required": self.required}


@dataclass(frozen=True)
class OutputInfo:
    name: str
    format: str
    path: str
    description: str

    def to_public(self) -> dict:
        return {"name": self.name, "format": self.format, "path": self.path, "description": self.description}


@dataclass(frozen=True)
class InventoryDoc:
    updated_at: str
    services: list[ServiceInfo] = field(default_factory=list)
    inputs: list[InputInfo] = field(default_factory=list)
    outputs: list[OutputInfo] = field(default_factory=list)

    def to_public(self) -> dict:
        return {
            "updated_at": self.updated_at,
            "services": [s.to_public() for s in self.services],
            "inputs": [i.to_public() for i in self.inputs],
            "outputs": [o.to_public() for o in self.outputs],
        }


def services(base_path: Path) -> list[ServiceInfo]:
    items: list[ServiceInfo] = [
        ServiceInfo("google_trends", "Interest over time and compare by keyword", ("trends", "interest"), "fetch_keyword_interest(keyword)"),
        ServiceInfo("marketplace_stub", "Marketplace adapter (fake + shopify stubs)", ("marketplace", "products", "catalog"), "adapter.fetch_products()"),
    ]
    meta_path = base_path / "collectors" / "meta_ads" / "client.py"
    if meta_path.exists():
        items.append(ServiceInfo("meta_graph", "Meta Marketing API", ("ads", "facebook"), "ad_account_insights / ads_library_adsearch"))
    tiktok_path = base_path / "integrations" / "ads_tiktok" / "client.py"
    if tiktok_path.exists():
        items.append(ServiceInfo("tiktok_ads", "TikTok Ads Library", ("ads", "tiktok"), "search_ads(query, country, limit)"))
    return items


def inputs(base_path: Path) -> list[InputInfo]:
    return [
        InputInfo("keywords", ".env", str(base_path / "dashboard" / "config" / "config.example.env"), False),
        InputInfo("marketplace credentials", "env", str(base_path / "integrations"), True),
        InputInfo("seller_mode", "env", str(base_path / "theme" / ".env.example"), False),
    ]


def outputs(base_path: Path) -> list[OutputInfo]:
    data = base_path / "data"
    return [
        OutputInfo("trend_alerts.csv", "csv", str(data / "trend_alerts.csv"), "Daily trend signals by keyword"),
        OutputInfo("products/product_hunter_latest.csv", "csv", str(data / "products" / "product_hunter_latest.csv"), "Top candidate products across marketplaces"),
        OutputInfo("copy_variants.csv", "csv", str(data / "copy_variants.csv"), "Generated copy variants"),
        OutputInfo("reports/growth_report_*.csv", "csv", str(data / "reports"), "Consolidated growth report"),
        OutputInfo("reports/marketplace_health_*.csv", "csv", str(data / "reports"), "Catalog health signals"),
    ]


def inventory_doc(base_path: Path | None = None) -> InventoryDoc:
    code_path = base_path or Path(__file__).resolve().parent.parent
    return InventoryDoc(
        updated_at=__import__("datetime").datetime.now().isoformat(),
        services=services(code_path),
        inputs=inputs(code_path),
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
