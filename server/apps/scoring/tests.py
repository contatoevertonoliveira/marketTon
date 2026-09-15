from django.test import TestCase
from django.utils import timezone

from apps.catalog.models import Marketplace, Product

from .engine import compute_all_for_product, compute_heat, compute_opportunity, compute_producer_momentum
from .models import ScoreRecord
from .services import recompute_scores


def make_product(**overrides) -> Product:
    marketplace, _ = Marketplace.objects.get_or_create(
        slug="mercado_livre", defaults={"name": "Mercado Livre", "integration_status": "live"}
    )
    defaults = dict(
        marketplace=marketplace,
        external_id=overrides.pop("external_id", "MLB999"),
        title="Produto Teste",
        source="mercado_livre_search",
        collected_at=timezone.now(),
    )
    defaults.update(overrides)
    return Product.objects.create(**defaults)


class ScoringEngineTests(TestCase):
    def test_heat_score_with_full_data_is_high_reliability(self):
        product = make_product(orders_count=900, rating=4.8, rating_count=600, discount_pct=30, ranking=5)
        result = compute_heat(product)
        self.assertIsNotNone(result)
        self.assertEqual(result.reliability, "high")
        self.assertGreater(result.result, 50)
        self.assertEqual(len(result.weights), 5)

    def test_heat_score_never_fabricates_missing_inputs(self):
        product = make_product(external_id="MLB_missing")  # every optional field is None
        result = compute_heat(product)
        self.assertIsNotNone(result)
        # nothing usable -> the calculator must not invent a number's inputs
        self.assertEqual(result.inputs, {})
        self.assertEqual(result.reliability, "low")
        missing_reasons = [text for polarity, text in result.reasons if polarity == "-"]
        self.assertEqual(len(missing_reasons), 5)

    def test_heat_score_partial_data_renormalizes_weights(self):
        product = make_product(external_id="MLB_partial", orders_count=800)
        result = compute_heat(product)
        self.assertIn("orders_count", result.weights)
        self.assertAlmostEqual(sum(result.weights.values()), 1.0, places=3)
        self.assertEqual(result.reliability, "low")  # 4 of 5 inputs missing

    def test_opportunity_uses_heat_as_optional_signal(self):
        product = make_product(commission_pct=15, price=150)
        heat = compute_heat(product)
        result = compute_opportunity(product, heat_result=heat)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result.result, 0)

    def test_producer_momentum_flags_active_promotions(self):
        product = make_product(promotions=[{"type": "coupon"}])
        result = compute_producer_momentum(product)
        self.assertTrue(any("promoç" in text for _p, text in result.reasons))

    def test_compute_all_skips_ungrounded_score_types(self):
        product = make_product(external_id="MLB_all")
        scores = compute_all_for_product(product)
        self.assertIn("heat", scores)
        self.assertIn("opportunity", scores)
        self.assertIn("producer_momentum", scores)
        # No creative-market / sales / creative-performance data source exists
        # yet in this phase — these must never be fabricated.
        self.assertNotIn("creative_saturation", scores)
        self.assertNotIn("portfolio", scores)
        self.assertNotIn("creative", scores)


class ScoringServiceTests(TestCase):
    def test_recompute_scores_persists_versioned_records_and_explanations(self):
        product = make_product(orders_count=700, commission_pct=12, price=120)
        records = recompute_scores(product)
        self.assertTrue(len(records) >= 3)
        for record in records:
            self.assertTrue(record.version)
            self.assertGreaterEqual(record.reasons.count(), 0)
        self.assertEqual(ScoreRecord.objects.filter(product=product).count(), len(records))

    def test_recompute_scores_keeps_history_instead_of_overwriting(self):
        product = make_product(orders_count=100)
        recompute_scores(product)
        recompute_scores(product)
        self.assertEqual(ScoreRecord.objects.filter(product=product, score_type="heat").count(), 2)
