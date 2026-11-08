import json
from typing import Any

from django import forms
from django.contrib import admin
from django.http import HttpRequest

from apps.ai_assistant import services
from apps.ai_assistant.models import AIRequestLog, AIRun, AISuggestion
from apps.core.admin import ReadOnlyAdmin, ReadOnlyTabularInline
from apps.core.admin_services import ServiceAdmin, platform_context, service_action
from apps.core.tenancy import TenantContext


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


class DecisionForm(forms.Form):
    decision = forms.ChoiceField(
        label="Décision",
        choices=[("accept", "Accepter"), ("reject", "Rejeter"), ("modify", "Modifier")],
    )
    value = forms.CharField(
        label="Valeur retenue (si « Modifier »)",
        required=False,
        help_text="Nombre ou texte ; JSON accepté pour une valeur structurée.",
    )


def _parse(value: str) -> Any:
    if value == "":
        return None
    try:
        return json.loads(value)
    except ValueError:
        return value


@admin.register(AISuggestion)
class AISuggestionAdmin(ServiceAdmin):
    """AI proposals are never applied without a human decision (CLAUDE.md §10)."""

    actions = ["decide"]

    def context_for(self, request: HttpRequest, obj: Any) -> TenantContext:
        version = obj.plan_version
        return platform_context(
            request, organization_id=version.organization_id, farm_id=version.farm_id
        )

    @service_action("Décider (accepter, rejeter ou modifier)", form=DecisionForm)
    def decide(self, ctx: TenantContext, obj: AISuggestion, decision: str, value: str) -> None:
        services.decide_suggestion(
            ctx, suggestion_id=obj.id, decision=decision, value=_parse(value)
        )
