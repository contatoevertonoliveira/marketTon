from django.test import TestCase
from django.utils import timezone

from apps.catalog.models import Marketplace, Product
from apps.portfolio.models import PortfolioItem

from .models import CreativeAsset
from .services import InvalidCreativeStatus, ensure_stages, set_status


def make_portfolio_item() -> PortfolioItem:
    marketplace, _ = Marketplace.objects.get_or_create(
        slug="mercado_livre", defaults={"name": "Mercado Livre", "integration_status": "live"}
    )
    product = Product.objects.create(
        marketplace=marketplace,
        external_id="MLB1",
        title="Produto",
        source="mercado_livre_search",
        collected_at=timezone.now(),
    )
    return PortfolioItem.objects.create(product=product)


class CreativePipelineTests(TestCase):
    def test_ensure_stages_creates_all_seven(self):
        item = make_portfolio_item()
        ensure_stages(item)
        self.assertEqual(item.creative_assets.count(), 7)
        self.assertTrue(all(a.status == "PENDING" or a.status == "BLOCKED" for a in item.creative_assets.all()))

    def test_publication_blocked_until_required_stages_ready(self):
        item = make_portfolio_item()
        ensure_stages(item)
        publication = item.creative_assets.get(asset_type="publication")
        self.assertEqual(publication.status, "BLOCKED")

    def test_matches_briefing_worked_example(self):
        """Copy: READY, Images: READY, Video: PENDING, Edit: PENDING -> Publication: BLOCKED."""
        item = make_portfolio_item()
        ensure_stages(item)
        set_status(item.creative_assets.get(asset_type="copy"), "READY")
        set_status(item.creative_assets.get(asset_type="image"), "READY")
        publication = item.creative_assets.get(asset_type="publication")
        self.assertEqual(publication.status, "BLOCKED")

    def test_publication_unblocks_once_all_required_stages_ready(self):
        item = make_portfolio_item()
        ensure_stages(item)
        for asset_type in ["copy", "image", "video", "edit", "approval"]:
            set_status(item.creative_assets.get(asset_type=asset_type), "READY")
        publication = item.creative_assets.get(asset_type="publication")
        publication.refresh_from_db()
        self.assertEqual(publication.status, "PENDING")

    def test_publication_status_cannot_be_set_directly(self):
        item = make_portfolio_item()
        ensure_stages(item)
        publication = item.creative_assets.get(asset_type="publication")
        with self.assertRaises(InvalidCreativeStatus):
            set_status(publication, "READY")

    def test_regressing_a_stage_re_blocks_publication(self):
        item = make_portfolio_item()
        ensure_stages(item)
        for asset_type in ["copy", "image", "video", "edit", "approval"]:
            set_status(item.creative_assets.get(asset_type=asset_type), "READY")
        set_status(item.creative_assets.get(asset_type="video"), "PENDING")
        publication = item.creative_assets.get(asset_type="publication")
        publication.refresh_from_db()
        self.assertEqual(publication.status, "BLOCKED")
