"""
URL configuration for project project.
"""
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.catalog.dashboard import DailyOpsView
from apps.catalog.oauth_ml import MercadoLivreOAuthCallbackView, MercadoLivreOAuthStartView
from apps.catalog.views import MarketplaceViewSet, ProductViewSet
from apps.creative.views import CreativeAssetViewSet
from apps.portfolio.views import PortfolioItemViewSet

router = DefaultRouter()
router.register("marketplaces", MarketplaceViewSet)
router.register("products", ProductViewSet)
router.register("portfolio", PortfolioItemViewSet)
router.register("creative", CreativeAssetViewSet, basename="creative")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(router.urls)),
    path("api/dashboard/daily-ops", DailyOpsView.as_view(), name="daily-ops"),
    path(
        "api/marketplaces/mercado_livre/oauth/start/",
        MercadoLivreOAuthStartView.as_view(),
        name="ml-oauth-start",
    ),
    path(
        "api/marketplaces/mercado_livre/oauth/callback/",
        MercadoLivreOAuthCallbackView.as_view(),
        name="ml-oauth-callback",
    ),
]
