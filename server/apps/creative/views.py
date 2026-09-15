from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.portfolio.models import PortfolioItem

from .models import CreativeAsset
from .serializers import CreativeAssetSerializer, CreativeStatusUpdateSerializer
from .services import InvalidCreativeStatus, ensure_stages, set_status


class CreativeAssetViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CreativeAsset.objects.select_related("portfolio_item").all()
    serializer_class = CreativeAssetSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        portfolio_item_id = self.request.query_params.get("portfolio_item")
        if portfolio_item_id:
            item = PortfolioItem.objects.filter(pk=portfolio_item_id).first()
            if item is not None:
                ensure_stages(item)
            qs = qs.filter(portfolio_item_id=portfolio_item_id)
        return qs

    @action(detail=True, methods=["post"], url_path="status")
    def update_status(self, request, pk=None):
        asset = self.get_object()
        req = CreativeStatusUpdateSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        try:
            set_status(asset, req.validated_data["status"], actor=getattr(request.user, "username", "") or "api")
        except InvalidCreativeStatus as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(CreativeAssetSerializer(asset).data)
