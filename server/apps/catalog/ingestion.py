"""Ingestion adapters (briefing §2/§4, Fase 2).

Discovery adapters turn a marketplace's real API into `Product` rows.
Credentials come from `MarketplaceCredential` (edited via the Integrações
screen) — never from `.env` or hardcoded values. An adapter raises
`CredentialsMissing` when its marketplace has code but nothing configured
yet, and `NotImplementedIngestion` when there is no real integration at all
(e.g. TikTok Shop). Neither path ever returns fabricated products.
"""
from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from pathlib import Path

from django.utils import timezone

from .models import Marketplace, MarketplaceCredential, Product

# Reuse the existing, working Mercado Livre OAuth client instead of
# re-implementing it.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class NotImplementedIngestion(Exception):
    """No adapter code exists yet for this marketplace."""


class CredentialsMissing(Exception):
    """Adapter code exists but nothing is configured in Integrações yet."""


def get_credential(slug: str) -> MarketplaceCredential | None:
    return MarketplaceCredential.objects.filter(marketplace_id=slug, enabled=True).first()


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_commission_pct(value) -> float | None:
    """Shopee returns commissionRate as a fraction (e.g. 0.05); be defensive
    in case it ever comes back already as a percentage."""
    f = _to_float(value)
    if f is None:
        return None
    return round(f * 100, 2) if f <= 1 else round(f, 2)


class DiscoveryAdapter(ABC):
    slug: str

    @abstractmethod
    def discover(self, *, keywords: list[str], limit: int = 20) -> list[dict]:
        """Returns a list of raw product dicts from the real API."""


class MercadoLivreDiscoveryAdapter(DiscoveryAdapter):
    slug = "mercado_livre"

    def discover(self, *, keywords: list[str], limit: int = 20) -> list[dict]:
        from integrations.marketplaces.mercado_livre import MercadoLivreAdapter, MLConfig

        cred = get_credential(self.slug)
        if cred is None or not cred.values.get("access_token"):
            raise CredentialsMissing(
                "mercado_livre: sem access_token configurado — salve client_id/secret em "
                "Integrações e clique em 'Conectar com Mercado Livre'"
            )
        cfg = MLConfig(
            client_id=cred.values.get("client_id", ""),
            client_secret=cred.values.get("client_secret", ""),
            redirect_uri=cred.values.get("redirect_uri", ""),
            access_token=cred.values.get("access_token", ""),
            refresh_token=cred.values.get("refresh_token", ""),
            country=cred.values.get("country", "BR"),
        )
        client = MercadoLivreAdapter(cfg)
        out: list[dict] = []
        seen_ids: set[str] = set()
        for kw in keywords:
            for item in client.search_competitor(kw)[:limit]:
                item_id = item.get("id")
                if not item_id or item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                out.append(item)

        # The client may have silently refreshed the access token mid-call
        # (see mercado_livre.py::_refresh_access_token) — persist it back so
        # the next run doesn't have to re-authenticate.
        if client.cfg.access_token != cred.values.get("access_token") or client.cfg.refresh_token != cred.values.get(
            "refresh_token"
        ):
            cred.values["access_token"] = client.cfg.access_token
            cred.values["refresh_token"] = client.cfg.refresh_token
            cred.save(update_fields=["values", "updated_at"])
        return out


class ShopeeDiscoveryAdapter(DiscoveryAdapter):
    slug = "shopee"

    def discover(self, *, keywords: list[str], limit: int = 20) -> list[dict]:
        from .shopee_client import search_products

        cred = get_credential(self.slug)
        if cred is None or not cred.values.get("app_id") or not cred.values.get("secret"):
            raise CredentialsMissing("shopee: configure app_id/secret em Integrações")
        out: list[dict] = []
        seen_ids: set[str] = set()
        for kw in keywords:
            for node in search_products(cred.values["app_id"], cred.values["secret"], kw, limit=limit):
                item_id = node.get("itemId")
                if not item_id or item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                out.append(node)
        return out


class AmazonDiscoveryAdapter(DiscoveryAdapter):
    slug = "amazon"

    def discover(self, *, keywords: list[str], limit: int = 20) -> list[dict]:
        from .amazon_client import search_items

        cred = get_credential(self.slug)
        required = ("access_key", "secret_key", "associate_tag", "host")
        if cred is None or not all(cred.values.get(k) for k in required):
            raise CredentialsMissing(
                "amazon: configure access_key/secret_key/associate_tag/host em Integrações "
                "(precisa de 3 vendas qualificadas nos últimos 180 dias para a API liberar acesso)"
            )
        out: list[dict] = []
        seen_asins: set[str] = set()
        for kw in keywords:
            items = search_items(
                access_key=cred.values["access_key"],
                secret_key=cred.values["secret_key"],
                associate_tag=cred.values["associate_tag"],
                region=cred.values.get("region", "us-east-1"),
                host=cred.values["host"],
                keywords=kw,
                item_count=min(limit, 10),
            )
            for item in items:
                asin = item.get("ASIN")
                if not asin or asin in seen_asins:
                    continue
                seen_asins.add(asin)
                out.append(item)
        return out


class NotImplementedDiscoveryAdapter(DiscoveryAdapter):
    def __init__(self, slug: str):
        self.slug = slug

    def discover(self, *, keywords: list[str], limit: int = 20) -> list[dict]:
        raise NotImplementedIngestion(f"'{self.slug}' has no real discovery integration yet")


ADAPTERS: dict[str, DiscoveryAdapter] = {
    "mercado_livre": MercadoLivreDiscoveryAdapter(),
    "shopee": ShopeeDiscoveryAdapter(),
    "amazon": AmazonDiscoveryAdapter(),
    "tiktok_shop": NotImplementedDiscoveryAdapter("tiktok_shop"),
}


def _upsert_product(marketplace_slug: str, marketplace_name: str, external_id: str, *, defaults: dict) -> Product:
    marketplace, _ = Marketplace.objects.get_or_create(slug=marketplace_slug, defaults={"name": marketplace_name})
    defaults.setdefault("collected_at", timezone.now())
    product, _created = Product.objects.update_or_create(
        marketplace=marketplace, external_id=external_id, defaults=defaults
    )
    return product


def upsert_product_from_ml_item(item: dict) -> Product:
    return _upsert_product(
        "mercado_livre",
        "Mercado Livre",
        str(item.get("id")),
        defaults=dict(
            title=item.get("title") or "",
            price=_to_float(item.get("price")),
            original_url=item.get("permalink") or "",
            seller_name=str(item.get("seller_id") or ""),
            source="mercado_livre_search",
            # Public site search — no commission/affiliate-program data here;
            # that belongs to the separate, undocumented "Mercado Livre
            # Afiliados" program. Never fabricated.
            reliability="medium",
            raw=item,
        ),
    )


def upsert_product_from_shopee_node(node: dict) -> Product:
    return _upsert_product(
        "shopee",
        "Shopee",
        str(node.get("itemId")),
        defaults=dict(
            title=node.get("productName") or "",
            price=_to_float(node.get("price")),
            commission_pct=_normalize_commission_pct(node.get("commissionRate")),
            rating=_to_float(node.get("ratingStar")),
            orders_count=node.get("sales"),
            seller_name=node.get("shopName") or "",
            affiliate_url=node.get("offerLink") or "",
            images=[node.get("imageUrl")] if node.get("imageUrl") else [],
            source="shopee_affiliate_api",
            # Real affiliate-offer data, commission included — higher
            # confidence than a generic public search result.
            reliability="high",
            raw=node,
        ),
    )


def upsert_product_from_amazon_item(item: dict, *, associate_tag: str, marketplace_domain: str) -> Product:
    from .amazon_client import build_affiliate_url

    asin = item.get("ASIN") or ""
    title = (((item.get("ItemInfo") or {}).get("Title") or {}).get("DisplayValue")) or ""
    listings = ((item.get("Offers") or {}).get("Listings")) or []
    price = _to_float((listings[0].get("Price") or {}).get("Amount")) if listings else None
    primary_image = (((item.get("Images") or {}).get("Primary") or {}).get("Medium") or {}).get("URL")
    reviews = item.get("CustomerReviews") or {}
    affiliate_url = build_affiliate_url(asin, associate_tag, marketplace_domain) if asin else ""

    return _upsert_product(
        "amazon",
        "Amazon",
        asin,
        defaults=dict(
            title=title,
            price=price,
            rating=_to_float(reviews.get("StarRating")),
            rating_count=reviews.get("Count"),
            images=[primary_image] if primary_image else [],
            affiliate_url=affiliate_url,
            original_url=affiliate_url,
            source="amazon_paapi_searchitems",
            # PA-API has no per-item commission field (Amazon pays by
            # category, not by item) — commission_pct stays null, never
            # guessed.
            reliability="medium",
            raw=item,
        ),
    )
