from django.db import models

STATES = [
    ("DISCOVERED", "Discovered"),
    ("ANALYZING", "Analyzing"),
    ("WATCHLIST", "Watchlist"),
    ("RECOMMENDED", "Recommended"),
    ("AFFILIATION_PENDING", "Affiliation pending"),
    ("AFFILIATED", "Affiliated"),
    ("PORTFOLIO_ACTIVE", "Portfolio active"),
    ("CREATIVE_PENDING", "Creative pending"),
    ("READY_TO_PUBLISH", "Ready to publish"),
    ("PUBLISHED", "Published"),
    ("MONITORING", "Monitoring"),
    ("OPTIMIZATION_REQUIRED", "Optimization required"),
    ("SCALING", "Scaling"),
    ("PAUSED", "Paused"),
    ("REMOVED", "Removed"),
]


class PortfolioItem(models.Model):
    """A product's lifecycle inside our operation (briefing §7).

    State transitions are controlled exclusively by the backend
    (`apps.portfolio.services`) — never set this field directly from a view
    or the frontend.
    """

    product = models.OneToOneField("catalog.Product", on_delete=models.CASCADE, related_name="portfolio_item")
    state = models.CharField(max_length=30, choices=STATES, default="DISCOVERED")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.product_id}: {self.state}"


class PortfolioStateTransition(models.Model):
    """Audit trail of every state change — briefing §7 ("as transições
    deverão ser controladas pelo backend") implies they must also be
    inspectable."""

    portfolio_item = models.ForeignKey(PortfolioItem, on_delete=models.CASCADE, related_name="transitions")
    from_state = models.CharField(max_length=30, choices=STATES, blank=True)
    to_state = models.CharField(max_length=30, choices=STATES)
    reason = models.CharField(max_length=300, blank=True, default="")
    actor = models.CharField(max_length=100, blank=True, default="", help_text="Who/what triggered this transition")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.from_state} -> {self.to_state}"
