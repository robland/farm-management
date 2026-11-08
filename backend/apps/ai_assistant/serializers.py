from typing import Any

from rest_framework import serializers

from apps.ai_assistant.models import AIRequestLog, AIRun, AISuggestion
from apps.core.serializers import FarmScopedPrimaryKeyRelatedField
from apps.fields.models import Parcel
from apps.inventory.serializers import OrgScopedRelatedField
from apps.production_plans.models import Campaign
from apps.varieties.models import Variety


class AISuggestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AISuggestion
        fields = [
            "id",
            "plan_version",
            "field_path",
            "value",
            "rationale",
            "status",
            "decided_by",
            "decided_at",
        ]
        read_only_fields = fields


class AIRunSerializer(serializers.ModelSerializer):
    suggestions = AISuggestionSerializer(many=True, read_only=True)
    usage = serializers.SerializerMethodField()

    class Meta:
        model = AIRun
        fields = [
            "id",
            "kind",
            "status",
            "provider",
            "model",
            "prompt_version",
            "schema_version",
            "document",
            "data_set",
            "plan_version",
            "missing_info",
            "rejected_items",
            "error_code",
            "error_message",
            "suggestions",
            "usage",
            "requested_by",
            "created_at",
            "finished_at",
        ]
        read_only_fields = fields

    def get_usage(self, run: AIRun) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in AIRequestLog.objects.filter(run=run).values(
                "model",
                "input_tokens",
                "output_tokens",
                "estimated_cost",
                "cost_currency",
                "latency_ms",
                "status",
                "error_code",
            )
        ]


class ExtractionRequestSerializer(serializers.Serializer):
    document = serializers.UUIDField()


class PlanDraftRequestSerializer(serializers.Serializer):
    campaign = FarmScopedPrimaryKeyRelatedField(queryset=Campaign.objects.all())
    variety = OrgScopedRelatedField(queryset=Variety.objects.all())
    parcel = FarmScopedPrimaryKeyRelatedField(queryset=Parcel.objects.all())
    allocated_area_m2 = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=0)
    non_plantable_area_m2 = serializers.DecimalField(
        max_digits=14, decimal_places=4, min_value=0, required=False, allow_null=True
    )
    planned_start_date = serializers.DateField()
    name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    objectives = serializers.CharField(required=False, allow_blank=True)
    constraints = serializers.CharField(required=False, allow_blank=True)


class DecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["accept", "reject", "modify"])
    value = serializers.CharField(required=False, allow_null=True)
