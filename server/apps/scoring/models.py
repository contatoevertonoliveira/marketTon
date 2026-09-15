from django.db import models

SCORE_TYPES = [
    ("heat", "Heat Score"),
    ("opportunity", "Opportunity Score"),
    ("producer_momentum", "Producer Momentum Score"),
    ("creative_saturation", "Creative Saturation Score"),
    ("portfolio", "Portfolio Score"),
    ("creative", "Creative Score"),
]


class ScoreRecord(models.Model):
    """A single, versioned, auditable score computation (briefing §5).

    Every calculation stores its inputs, weights, formula version and result
    so no score exists as an opaque opinion — the same computation can always
    be reproduced or inspected later.
    """

    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="scores")
    score_type = models.CharField(max_length=30, choices=SCORE_TYPES)
    version = models.CharField(max_length=20, help_text="Formula version, e.g. 'v1'")

    inputs = models.JSONField(default=dict)
    weights = models.JSONField(default=dict)
    result = models.FloatField()
    reliability = models.CharField(
        max_length=10,
        choices=[("high", "High"), ("medium", "Medium"), ("low", "Low")],
        default="medium",
        help_text="Downgraded when required inputs were missing.",
    )

    computed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["product", "score_type", "-computed_at"])]
        ordering = ["-computed_at"]

    def __str__(self) -> str:
        return f"{self.score_type} v{self.version} = {self.result:.1f} ({self.product_id})"


class Explanation(models.Model):
    """Human-readable reasons behind a ScoreRecord (briefing §6)."""

    score_record = models.ForeignKey(ScoreRecord, on_delete=models.CASCADE, related_name="reasons")
    polarity = models.CharField(max_length=1, choices=[("+", "Positive"), ("-", "Negative")])
    text = models.CharField(max_length=300)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.polarity} {self.text}"
