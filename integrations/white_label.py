"""White-label: branding e temas personalizados por tenant/grupo."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parent.parent.parent / "data"
BRAND_PATH = DATA / "white_label" / "brands.jsonl"
BRAND_PATH.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class Brand:
    tenant_id: str
    name: str
    primary_color: str | None = None
    secondary_color: str | None = None
    logo_url: str | None = None
    favicon_url: str | None = None
    custom_css: str | None = None
    extra: dict = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "name": self.name,
            "primary_color": self.primary_color,
            "secondary_color": self.secondary_color,
            "logo_url": self.logo_url,
            "favicon_url": self.favicon_url,
            "custom_css": self.custom_css,
            "extra": self.extra,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Brand":
        return Brand(
            tenant_id=data["tenant_id"],
            name=data["name"],
            primary_color=data.get("primary_color"),
            secondary_color=data.get("secondary_color"),
            logo_url=data.get("logo_url"),
            favicon_url=data.get("favicon_url"),
            custom_css=data.get("custom_css"),
            extra=data.get("extra") or {},
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
        )


class BrandManager:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else BRAND_PATH
        self._cache: dict[str, Brand] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").strip().splitlines():
            try:
                obj = json.loads(line)
                brand = Brand.from_dict(obj)
                self._cache[brand.tenant_id] = brand
            except Exception:
                continue

    def _save(self, brand: Brand) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(brand.to_dict(), ensure_ascii=False) + "\n")
        self._cache[brand.tenant_id] = brand

    def create(self, *, name: str, primary_color: str | None = None, secondary_color: str | None = None,
               logo_url: str | None = None, favicon_url: str | None = None, custom_css: str | None = None,
               extra: dict | None = None) -> Brand:
        brand = Brand(
            tenant_id=uuid.uuid4().hex,
            name=name,
            primary_color=primary_color,
            secondary_color=secondary_color,
            logo_url=logo_url,
            favicon_url=favicon_url,
            custom_css=custom_css,
            extra=extra or {},
        )
        self._save(brand)
        return brand

    def get(self, tenant_id: str) -> Brand | None:
        return self._cache.get(tenant_id)

    def list_brands(self) -> list[Brand]:
        return sorted(self._cache.values(), key=lambda x: x.updated_at, reverse=True)

    def set_by_group(self, group_id: int, tenant_id: str) -> Brand | None:
        mapping_path = self.path.parent / "group_mapping.jsonl"
        with mapping_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"group_id": group_id, "tenant_id": tenant_id}, ensure_ascii=False) + "\n")
        return self.get(tenant_id)
