from django.test import TestCase
from django.utils import timezone

from apps.catalog.models import Marketplace, Product

from .models import PortfolioItem
from .services import InvalidTransition, transition


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


class PortfolioTransitionTests(TestCase):
    def test_starts_discovered(self):
        item = make_portfolio_item()
        self.assertEqual(item.state, "DISCOVERED")

    def test_valid_transition_is_applied_and_logged(self):
        item = make_portfolio_item()
        transition(item, "ANALYZING", reason="looks promising")
        item.refresh_from_db()
        self.assertEqual(item.state, "ANALYZING")
        self.assertEqual(item.transitions.count(), 1)
        self.assertEqual(item.transitions.first().from_state, "DISCOVERED")

    def test_invalid_transition_is_rejected(self):
        item = make_portfolio_item()
        with self.assertRaises(InvalidTransition):
            transition(item, "PUBLISHED")
        item.refresh_from_db()
        self.assertEqual(item.state, "DISCOVERED")
        self.assertEqual(item.transitions.count(), 0)

    def test_removed_is_terminal(self):
        item = make_portfolio_item()
        transition(item, "ANALYZING")
        transition(item, "WATCHLIST")
        transition(item, "REMOVED")
        item.refresh_from_db()
        with self.assertRaises(InvalidTransition):
            transition(item, "MONITORING")
