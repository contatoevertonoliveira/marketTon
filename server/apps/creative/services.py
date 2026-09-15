"""Creative pipeline status handling (briefing §8).

Every stage except "publication" is a manual toggle (the operator confirms
via checkbox that a piece was produced, e.g. "[ ] Vídeo criado" flips
VIDEO_PENDING -> VIDEO_READY). "publication" is derived: it is BLOCKED
whenever a required upstream stage isn't READY yet, exactly like the
briefing's worked example (Video: PENDING, Edit: PENDING -> Publication:
BLOCKED).
"""
from __future__ import annotations

from django.db import transaction

from .models import ASSET_TYPES, CreativeAsset

REQUIRED_FOR_PUBLICATION = ["copy", "image", "video", "edit", "approval"]
MANUAL_TYPES = [t for t, _ in ASSET_TYPES if t != "publication"]


class InvalidCreativeStatus(Exception):
    pass


def ensure_stages(portfolio_item) -> list[CreativeAsset]:
    """Creates any missing stage rows for a portfolio item (idempotent)."""
    existing = {a.asset_type for a in portfolio_item.creative_assets.all()}
    created_any = False
    for asset_type, _label in ASSET_TYPES:
        if asset_type not in existing:
            CreativeAsset.objects.create(portfolio_item=portfolio_item, asset_type=asset_type)
            created_any = True
    if created_any:
        _sync_publication(portfolio_item)
    return list(portfolio_item.creative_assets.all())


@transaction.atomic
def set_status(asset: CreativeAsset, status: str, *, actor: str = "") -> CreativeAsset:
    if asset.asset_type == "publication":
        raise InvalidCreativeStatus("publication status is derived automatically, not set directly")
    if status not in {"PENDING", "READY"}:
        raise InvalidCreativeStatus(f"manual stages only accept PENDING/READY, got {status!r}")
    asset.status = status
    asset.updated_by = actor
    asset.save(update_fields=["status", "updated_by", "updated_at"])
    _sync_publication(asset.portfolio_item)
    return asset


def _sync_publication(portfolio_item) -> CreativeAsset:
    pub, _ = CreativeAsset.objects.get_or_create(portfolio_item=portfolio_item, asset_type="publication")
    required = CreativeAsset.objects.filter(
        portfolio_item=portfolio_item, asset_type__in=REQUIRED_FOR_PUBLICATION
    )
    all_ready = required.count() == len(REQUIRED_FOR_PUBLICATION) and all(a.status == "READY" for a in required)
    if not all_ready:
        pub.status = "BLOCKED"
    elif pub.status == "BLOCKED":
        pub.status = "PENDING"
    pub.save(update_fields=["status", "updated_at"])
    return pub
