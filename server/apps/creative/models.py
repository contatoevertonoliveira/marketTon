from django.db import models

ASSET_TYPES = [
    ("copy", "Copy"),
    ("image", "Image"),
    ("video", "Video"),
    ("voice", "Voice / narration"),
    ("edit", "Edit"),
    ("approval", "Approval"),
    ("publication", "Publication"),
]

STATUSES = [
    ("PENDING", "Pending"),
    ("READY", "Ready"),
    ("BLOCKED", "Blocked"),
]


class CreativeAsset(models.Model):
    """One creative pipeline stage for a portfolio item (briefing §8).

    The Affiliate Intelligence System does not produce the creative itself —
    a separate AI Studio does that. This model tracks demand/status only, and
    is updated manually via checkbox for now (`status` flips PENDING->READY).
    The `external_ref` field exists so a future AI Studio API integration can
    attach without remodeling this table.
    """

    portfolio_item = models.ForeignKey(
        "portfolio.PortfolioItem", on_delete=models.CASCADE, related_name="creative_assets"
    )
    asset_type = models.CharField(max_length=20, choices=ASSET_TYPES)
    status = models.CharField(max_length=10, choices=STATUSES, default="PENDING")
    external_ref = models.CharField(max_length=200, blank=True, default="", help_text="Future AI Studio asset id")
    updated_by = models.CharField(max_length=100, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["portfolio_item", "asset_type"], name="unique_asset_per_stage"),
        ]
        ordering = ["portfolio_item_id", "asset_type"]

    def __str__(self) -> str:
        return f"{self.portfolio_item_id}: {self.asset_type} = {self.status}"
