from django.contrib import admin

from .models import Marketplace, MarketplaceCredential, Product


@admin.register(Marketplace)
class MarketplaceAdmin(admin.ModelAdmin):
    list_display = ["slug", "name", "enabled", "integration_status", "updated_at"]


@admin.register(MarketplaceCredential)
class MarketplaceCredentialAdmin(admin.ModelAdmin):
    list_display = ["marketplace", "enabled", "mode", "scope", "updated_at"]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["title", "marketplace", "price", "commission_pct", "source", "reliability", "collected_at"]
    list_filter = ["marketplace", "reliability", "source"]
    search_fields = ["title", "external_id"]
