from rest_framework import serializers

from .credentials import schema_as_dicts, status_for
from .models import Marketplace, MarketplaceCredential, Product


class MarketplaceSerializer(serializers.ModelSerializer):
    credential_schema = serializers.SerializerMethodField()
    credential_status = serializers.SerializerMethodField()
    credential_enabled = serializers.SerializerMethodField()
    credential_mode = serializers.SerializerMethodField()
    credential_scope = serializers.SerializerMethodField()

    class Meta:
        model = Marketplace
        fields = [
            "slug",
            "name",
            "enabled",
            "integration_status",
            "notes",
            "updated_at",
            "credential_schema",
            "credential_status",
            "credential_enabled",
            "credential_mode",
            "credential_scope",
        ]

    def _credential(self, obj) -> MarketplaceCredential | None:
        return getattr(obj, "credential", None)

    def get_credential_schema(self, obj):
        return schema_as_dicts(obj.slug)

    def get_credential_status(self, obj):
        cred = self._credential(obj)
        return status_for(obj.slug, cred.values if cred else {})

    def get_credential_enabled(self, obj):
        cred = self._credential(obj)
        return cred.enabled if cred else False

    def get_credential_mode(self, obj):
        cred = self._credential(obj)
        return cred.mode if cred else "affiliate"

    def get_credential_scope(self, obj):
        cred = self._credential(obj)
        return cred.scope if cred else "national,international"


class MarketplaceCredentialUpdateSerializer(serializers.Serializer):
    """Write-only: accepts values, never echoes secrets back (the response
    to a PUT is the MarketplaceSerializer above, which only exposes
    credential_status booleans)."""

    enabled = serializers.BooleanField(required=False, default=True)
    mode = serializers.CharField(required=False, default="affiliate")
    scope = serializers.CharField(required=False, default="national,international")
    values = serializers.DictField(required=False, default=dict)


class ProductListSerializer(serializers.ModelSerializer):
    marketplace = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    portfolio_state = serializers.SerializerMethodField()
    latest_opportunity_score = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "marketplace",
            "title",
            "category",
            "price",
            "commission_pct",
            "rating",
            "source",
            "reliability",
            "collected_at",
            "portfolio_state",
            "latest_opportunity_score",
        ]

    def get_portfolio_state(self, obj):
        item = getattr(obj, "portfolio_item", None)
        return item.state if item else None

    def get_latest_opportunity_score(self, obj):
        record = obj.scores.filter(score_type="opportunity").order_by("-computed_at").first()
        return record.result if record else None


class ProductDetailSerializer(serializers.ModelSerializer):
    marketplace = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    portfolio_state = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "marketplace",
            "external_id",
            "title",
            "category",
            "seller_name",
            "price",
            "previous_price",
            "discount_pct",
            "commission_pct",
            "available",
            "stock",
            "rating",
            "rating_count",
            "ranking",
            "orders_count",
            "promotions",
            "coupons",
            "affiliate_program_info",
            "original_url",
            "affiliate_url",
            "images",
            "source",
            "reliability",
            "collected_at",
            "portfolio_state",
        ]

    def get_portfolio_state(self, obj):
        item = getattr(obj, "portfolio_item", None)
        return item.state if item else None
