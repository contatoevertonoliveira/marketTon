from django.contrib import admin

from .models import Explanation, ScoreRecord


class ExplanationInline(admin.TabularInline):
    model = Explanation
    extra = 0


@admin.register(ScoreRecord)
class ScoreRecordAdmin(admin.ModelAdmin):
    list_display = ["product", "score_type", "version", "result", "reliability", "computed_at"]
    list_filter = ["score_type", "reliability", "version"]
    inlines = [ExplanationInline]
