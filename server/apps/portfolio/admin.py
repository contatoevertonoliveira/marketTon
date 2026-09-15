from django.contrib import admin

from .models import PortfolioItem, PortfolioStateTransition


class TransitionInline(admin.TabularInline):
    model = PortfolioStateTransition
    extra = 0
    readonly_fields = ["from_state", "to_state", "reason", "actor", "created_at"]
    can_delete = False


@admin.register(PortfolioItem)
class PortfolioItemAdmin(admin.ModelAdmin):
    list_display = ["product", "state", "updated_at"]
    list_filter = ["state"]
    inlines = [TransitionInline]
