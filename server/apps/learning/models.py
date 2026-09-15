from django.db import models


class LearningRecord(models.Model):
    """Skeleton for briefing §11: preserves PREVISÃO -> DECISÃO -> EXECUÇÃO ->
    RESULTADO REAL so future calibration has something to learn from.

    Nothing populates `actual_outcome_*` automatically yet in this phase —
    there is no sales/click tracking wired up. The table exists so that once
    that data exists, closing the loop doesn't require a schema change.
    """

    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="learning_records")
    score_record = models.ForeignKey(
        "scoring.ScoreRecord", on_delete=models.SET_NULL, null=True, blank=True, related_name="learning_records"
    )

    predicted_score_type = models.CharField(max_length=30, blank=True, default="")
    predicted_value = models.FloatField(null=True, blank=True)
    decision = models.CharField(max_length=200, blank=True, default="", help_text="e.g. 'added to portfolio'")
    decided_at = models.DateTimeField(null=True, blank=True)

    actual_outcome_summary = models.CharField(max_length=300, blank=True, default="")
    actual_outcome_metrics = models.JSONField(default=dict, blank=True)
    outcome_recorded_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.product_id}: {self.decision or 'pending decision'}"
