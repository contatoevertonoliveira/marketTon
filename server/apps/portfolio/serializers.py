from rest_framework import serializers

from .models import PortfolioItem, PortfolioStateTransition
from .services import ALLOWED_TRANSITIONS


class PortfolioStateTransitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PortfolioStateTransition
        fields = ["from_state", "to_state", "reason", "actor", "created_at"]


class PortfolioItemSerializer(serializers.ModelSerializer):
    product_title = serializers.CharField(source="product.title", read_only=True)
    marketplace = serializers.CharField(source="product.marketplace_id", read_only=True)
    allowed_next_states = serializers.SerializerMethodField()

    class Meta:
        model = PortfolioItem
        fields = [
            "id",
            "product",
            "product_title",
            "marketplace",
            "state",
            "notes",
            "allowed_next_states",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["state"]

    def get_allowed_next_states(self, obj):
        return sorted(ALLOWED_TRANSITIONS.get(obj.state, set()))


class PortfolioItemDetailSerializer(PortfolioItemSerializer):
    transitions = PortfolioStateTransitionSerializer(many=True, read_only=True)

    class Meta(PortfolioItemSerializer.Meta):
        fields = PortfolioItemSerializer.Meta.fields + ["transitions"]


class TransitionRequestSerializer(serializers.Serializer):
    to_state = serializers.CharField()
    reason = serializers.CharField(required=False, allow_blank=True, default="")
