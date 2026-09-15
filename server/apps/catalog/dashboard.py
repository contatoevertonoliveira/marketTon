"""Daily Ops aggregation (briefing §9).

Every bucket here is backed by a real query. Where the platform has no data
source yet (sales, commissions, alerts), the bucket says so explicitly via
`available: false` instead of returning a fabricated zero — briefing §2's
"dados inexistentes ou indisponíveis não poderão ser fabricados ou estimados
silenciosamente" applies to the dashboard just as much as to product data.
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.creative.models import CreativeAsset
from apps.portfolio.models import STATES, PortfolioItem
from apps.scoring.models import ScoreRecord

from .models import Product


def _product_ids(qs, limit=20):
    return list(qs.values_list("id", flat=True)[:limit])


class DailyOpsView(APIView):
    def get(self, request):
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        opportunities_today = Product.objects.filter(collected_at__gte=today_start).order_by("-collected_at")

        # sqlite has no DISTINCT ON — dedupe to "latest score per product" in Python.
        seen: set[int] = set()
        latest_heat_by_product = []
        for record in ScoreRecord.objects.filter(score_type="heat").order_by("product_id", "-computed_at"):
            if record.product_id in seen:
                continue
            seen.add(record.product_id)
            latest_heat_by_product.append(record)
        trending_up_ids = [r.product_id for r in latest_heat_by_product if r.result >= 70]
        cooling_down_ids = [r.product_id for r in latest_heat_by_product if r.result < 30]

        by_state = {state: PortfolioItem.objects.filter(state=state).count() for state, _label in STATES}

        creative_pending = (
            CreativeAsset.objects.exclude(asset_type="publication").filter(status="PENDING").values("portfolio_item").distinct().count()
        )
        creative_ready = CreativeAsset.objects.filter(asset_type="publication", status="READY").count()

        return Response(
            {
                "generated_at": now.isoformat(),
                "opportunities_today": {
                    "count": opportunities_today.count(),
                    "product_ids": _product_ids(opportunities_today),
                },
                "trending_up": {"count": len(trending_up_ids), "product_ids": trending_up_ids[:20]},
                "cooling_down": {"count": len(cooling_down_ids), "product_ids": cooling_down_ids[:20]},
                "recommended": {"count": by_state.get("RECOMMENDED", 0)},
                "awaiting_decision": {
                    "count": by_state.get("WATCHLIST", 0) + by_state.get("ANALYZING", 0)
                },
                "affiliation_pending": {"count": by_state.get("AFFILIATION_PENDING", 0)},
                "creative_pending": {"count": creative_pending},
                "creative_ready": {"count": creative_ready},
                "ready_to_publish": {"count": by_state.get("READY_TO_PUBLISH", 0)},
                "published": {"count": by_state.get("PUBLISHED", 0) + by_state.get("MONITORING", 0)},
                "alerts": {"available": False, "reason": "no alert source wired up yet"},
                "sales_and_commissions": {
                    "available": False,
                    "reason": "no sales/commission tracking wired up yet — needs marketplace order/conversion data",
                },
                "portfolio_performance": {"by_state": by_state},
            }
        )
