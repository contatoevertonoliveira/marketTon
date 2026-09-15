from django.contrib import admin

from .models import CreativeAsset


@admin.register(CreativeAsset)
class CreativeAssetAdmin(admin.ModelAdmin):
    list_display = ["portfolio_item", "asset_type", "status", "updated_at"]
    list_filter = ["asset_type", "status"]
