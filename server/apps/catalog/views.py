from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.scoring.models import ScoreRecord
from apps.scoring.serializers import ScoreRecordSerializer
from apps.scoring.services import recompute_scores

from .models import Marketplace, MarketplaceCredential, Product
from .serializers import (
    MarketplaceCredentialUpdateSerializer,
    MarketplaceSerializer,
    ProductDetailSerializer,
    ProductListSerializer,
)


class MarketplaceViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Marketplace.objects.select_related("credential").all()
    serializer_class = MarketplaceSerializer

    @action(detail=True, methods=["put"])
    def credentials(self, request, pk=None):
        """Upserts this marketplace's MarketplaceCredential. Never returns the
        submitted secret values back — the response is the regular
        MarketplaceSerializer, which only exposes configured/not booleans."""
        marketplace = self.get_object()
        req = MarketplaceCredentialUpdateSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        cred, _created = MarketplaceCredential.objects.get_or_create(marketplace=marketplace)
        cred.enabled = req.validated_data.get("enabled", True)
        cred.mode = req.validated_data.get("mode", "affiliate")
        cred.scope = req.validated_data.get("scope", "national,international")
        incoming_values = req.validated_data.get("values") or {}
        # A blank string means "leave whatever secret is already saved
        # untouched" — the frontend never has the real value to redisplay.
        merged = dict(cred.values)
        merged.update({k: v for k, v in incoming_values.items() if v not in (None, "")})
        cred.values = merged
        cred.save()
        return Response(MarketplaceSerializer(marketplace).data)


class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Product.objects.select_related("marketplace").prefetch_related("scores").all()
    serializer_class = ProductListSerializer

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ProductDetailSerializer
        return ProductListSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        marketplace = self.request.query_params.get("marketplace")
        if marketplace:
            qs = qs.filter(marketplace_id=marketplace)
        category = self.request.query_params.get("category")
        if category:
            qs = qs.filter(category__icontains=category)
        state = self.request.query_params.get("state")
        if state:
            qs = qs.filter(portfolio_item__state=state)
        return qs

    @action(detail=True, methods=["get"])
    def scores(self, request, pk=None):
        """Latest score per type by default; pass ?history=true for full history."""
        product = self.get_object()
        qs = ScoreRecord.objects.filter(product=product).order_by("score_type", "-computed_at")
        if request.query_params.get("history") == "true":
            return Response(ScoreRecordSerializer(qs, many=True).data)
        latest_by_type: dict[str, ScoreRecord] = {}
        for record in qs:
            latest_by_type.setdefault(record.score_type, record)
        return Response(ScoreRecordSerializer(latest_by_type.values(), many=True).data)

    @action(detail=True, methods=["get"])
    def explain(self, request, pk=None):
        """Explanation for the latest score of a given type (default: opportunity)."""
        product = self.get_object()
        score_type = request.query_params.get("type", "opportunity")
        record = (
            ScoreRecord.objects.filter(product=product, score_type=score_type).order_by("-computed_at").first()
        )
        if record is None:
            return Response(
                {"score_type": score_type, "available": False, "reason": "no score computed yet for this product"}
            )
        return Response(ScoreRecordSerializer(record).data)

    @action(detail=True, methods=["post"], url_path="recompute-scores")
    def recompute(self, request, pk=None):
        product = self.get_object()
        records = recompute_scores(product)
        return Response(ScoreRecordSerializer(records, many=True).data)
