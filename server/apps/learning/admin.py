from django.contrib import admin

from .models import LearningRecord


@admin.register(LearningRecord)
class LearningRecordAdmin(admin.ModelAdmin):
    list_display = ["product", "decision", "predicted_score_type", "predicted_value", "outcome_recorded_at"]
