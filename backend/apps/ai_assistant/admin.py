from django.contrib import admin

from apps.ai_assistant.models import AIRequestLog, AIRun, AISuggestion
from apps.core.admin import ReadOnlyAdmin, ReadOnlyTabularInline, register_read_only


class AIRequestLogInline(ReadOnlyTabularInline):
    model = AIRequestLog
    fields = ["provider", "model", "status", "input_tokens", "output_tokens", "estimated_cost"]
    show_change_link = False


@admin.register(AIRun)
class AIRunAdmin(ReadOnlyAdmin):
    list_display = ["kind", "status", "provider", "model", "organization", "created_at"]
    list_filter = ["kind", "status", "provider"]
    inlines = [AIRequestLogInline]


@admin.register(AIRequestLog)
class AIRequestLogAdmin(ReadOnlyAdmin):
    """Usage and cost follow-up per organization (FR-108)."""

    list_display = [
        "created_at",
        "provider",
        "model",
        "status",
        "input_tokens",
        "output_tokens",
        "estimated_cost",
        "cost_currency",
        "organization_id",
    ]
    list_filter = ["provider", "model", "status"]
    search_fields = ["=organization_id", "=request_id", "error_code"]
    date_hierarchy = "created_at"


register_read_only(AISuggestion)
