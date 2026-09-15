from django.db import models


class Marketplace(models.Model):
    """Registry of marketplaces the platform can ingest from.

    Briefing §2: the architecture must not depend structurally on a specific
    marketplace — new ones are added as data (a row here) plus an adapter,
    never by hardcoding names through the codebase.
    """

    slug = models.SlugField(primary_key=True)
    name = models.CharField(max_length=100)
    enabled = models.BooleanField(default=True)
    integration_status = models.CharField(
        max_length=20,
        choices=[
            ("live", "Live"),
            ("not_implemented", "Not implemented"),
        ],
        default="not_implemented",
    )
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["slug"]

    def __str__(self) -> str:
        return self.name


class MarketplaceCredential(models.Model):
    """Per-marketplace integration config, editable from the Integrações screen.

    Replaces the old `.env`-based approach (nothing loaded `.env` anyway —
    see Fase 2 plan notes). `values` holds whatever fields that marketplace's
    auth scheme needs (see `apps.catalog.credentials.CREDENTIAL_SCHEMAS`);
    secrets are stored in plain text here, consistent with the rest of this
    project's current security posture (e.g. `core/db.py`'s legacy plaintext
    user passwords) — not a hardening measure, a follow-up for later.
    """

    marketplace = models.OneToOneField(Marketplace, on_delete=models.CASCADE, related_name="credential")
    enabled = models.BooleanField(default=True)
    mode = models.CharField(max_length=20, default="affiliate")
    scope = models.CharField(max_length=100, default="national,international")
    values = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"credentials for {self.marketplace_id}"


class Product(models.Model):
    """A product observed in a marketplace.

    Fields mirror briefing §4. Any field the source doesn't actually provide
    is left null — the platform must never fabricate or silently estimate
    missing data (briefing §2 principle).
    """

    marketplace = models.ForeignKey(Marketplace, on_delete=models.CASCADE, related_name="products")
    external_id = models.CharField(max_length=200)
    title = models.CharField(max_length=500)
    category = models.CharField(max_length=200, blank=True, default="")
    seller_name = models.CharField(max_length=200, blank=True, default="")

    price = models.FloatField(null=True, blank=True)
    previous_price = models.FloatField(null=True, blank=True)
    discount_pct = models.FloatField(null=True, blank=True)
    commission_pct = models.FloatField(null=True, blank=True)

    available = models.BooleanField(null=True, blank=True)
    stock = models.IntegerField(null=True, blank=True)

    rating = models.FloatField(null=True, blank=True)
    rating_count = models.IntegerField(null=True, blank=True)
    ranking = models.IntegerField(null=True, blank=True)
    orders_count = models.IntegerField(null=True, blank=True)

    promotions = models.JSONField(default=list, blank=True)
    coupons = models.JSONField(default=list, blank=True)
    affiliate_program_info = models.JSONField(default=dict, blank=True)

    original_url = models.URLField(max_length=1000, blank=True, default="")
    affiliate_url = models.URLField(max_length=1000, blank=True, default="")
    images = models.JSONField(default=list, blank=True)

    # Provenance — briefing §4: every record must carry origin, timestamp,
    # marketplace and a reliability level.
    source = models.CharField(max_length=100, help_text="Where this row came from, e.g. 'mercado_livre_search'")
    reliability = models.CharField(
        max_length=10,
        choices=[("high", "High"), ("medium", "Medium"), ("low", "Low")],
        default="medium",
    )
    collected_at = models.DateTimeField()

    raw = models.JSONField(default=dict, blank=True, help_text="Raw payload from the source, for audit/debug.")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["marketplace", "external_id"], name="unique_product_per_marketplace"),
        ]
        indexes = [
            models.Index(fields=["marketplace", "category"]),
            models.Index(fields=["collected_at"]),
        ]
        ordering = ["-collected_at"]

    def __str__(self) -> str:
        return f"{self.title} ({self.marketplace_id})"
