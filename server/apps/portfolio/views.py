from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.catalog.models import Product

from .models import PortfolioItem
from .serializers import (
    PortfolioItemDetailSerializer,
    PortfolioItemSerializer,
    TransitionRequestSerializer,
)
from .services import InvalidTransition, transition


class PortfolioItemViewSet(viewsets.ModelViewSet):
    queryset = PortfolioItem.objects.select_related("product", "product__marketplace").all()
    http_method_names = ["get", "post", "head", "options"]  # no raw PUT/PATCH/DELETE — state changes go through /transition

    def get_serializer_class(self):
        if self.action == "retrieve":
            return PortfolioItemDetailSerializer
        return PortfolioItemSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        state = self.request.query_params.get("state")
        if state:
            qs = qs.filter(state=state)
        return qs

    def create(self, request, *args, **kwargs):
        product_id = request.data.get("product")
        if not product_id:
            return Response({"detail": "product is required"}, status=status.HTTP_400_BAD_REQUEST)
        product = Product.objects.filter(pk=product_id).first()
        if product is None:
            return Response({"detail": "product not found"}, status=status.HTTP_404_NOT_FOUND)
        item, created = PortfolioItem.objects.get_or_create(product=product)
        serializer = self.get_serializer(item)
        return Response(serializer.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        item = self.get_object()
        req = TransitionRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        try:
            transition(
                item,
                req.validated_data["to_state"],
                reason=req.validated_data.get("reason", ""),
                actor=getattr(request.user, "username", "") or "api",
            )
        except InvalidTransition as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(PortfolioItemDetailSerializer(item).data)
