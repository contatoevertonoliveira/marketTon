from rest_framework import serializers

from .models import CreativeAsset


class CreativeAssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreativeAsset
        fields = ["id", "portfolio_item", "asset_type", "status", "external_ref", "updated_by", "updated_at"]
        read_only_fields = ["portfolio_item", "asset_type", "external_ref"]


class CreativeStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["PENDING", "READY"])
