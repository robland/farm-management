from typing import Any

from rest_framework import serializers

from apps.core.serializers import FarmScopedPrimaryKeyRelatedField
from apps.fields.models import Parcel
from apps.production_plans.models import (
    CalculationRecord,
    Campaign,
    CropCycle,
    FieldProvenance,
    PlanAllocation,
    PlanPhase,
    PlantingSpec,
    PlanVersion,
    ProductionPlan,
)
from apps.production_plans.services import PLANTING_FIELDS
from apps.varieties.models import TechnicalDataSet


class CampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = Campaign
        fields = [
            "id",
            "name",
            "start_date",
            "end_date",
            "status",
            "notes",
            "version",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "version", "created_at", "updated_at"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start and end and end < start:
            raise serializers.ValidationError({"end_date": ["Avant la date de début."]})
        return attrs


class ProductionPlanSerializer(serializers.ModelSerializer):
    variety_name = serializers.CharField(source="variety.name", read_only=True)

    class Meta:
        model = ProductionPlan
        fields = [
            "id",
            "campaign",
            "variety",
            "variety_name",
            "name",
            "status",
            "current_version",
            "version",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ProductionPlanCreateSerializer(serializers.Serializer):
    campaign = serializers.UUIDField()
    variety = serializers.UUIDField()
    name = serializers.CharField(max_length=150)


class PlanAllocationSerializer(serializers.ModelSerializer):
    parcel = FarmScopedPrimaryKeyRelatedField(queryset=Parcel.objects.all())

    class Meta:
        model = PlanAllocation
        fields = [
            "parcel",
            "allocated_area_m2",
            "non_plantable_area_m2",
            "plot_length_m",
            "plot_width_m",
            "notes",
        ]
        validators: list[Any] = []


class PlantingSpecSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlantingSpec
        fields = PLANTING_FIELDS


class PlanPhaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanPhase
        fields = ["phase_code", "sequence", "duration_days", "start_date", "end_date"]
        read_only_fields = ["sequence", "start_date", "end_date"]
        validators: list[Any] = []


class FieldProvenanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = FieldProvenance
        fields = [
            "field_path",
            "source_kind",
            "technical_data_item",
            "calculation_result",
            "ai_suggestion_id",
            "set_by",
            "note",
            "updated_at",
        ]
        read_only_fields = fields


class CalculationRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = CalculationRecord
        fields = [
            "id",
            "calc_type",
            "engine_version",
            "scope",
            "inputs",
            "outputs",
            "formula",
            "assumptions",
            "warnings",
            "details",
            "created_at",
        ]
        read_only_fields = fields


class PlanVersionSerializer(serializers.ModelSerializer):
    planting_spec = PlantingSpecSerializer(read_only=True)
    allocations = PlanAllocationSerializer(many=True, read_only=True)
    phases = PlanPhaseSerializer(many=True, read_only=True)
    provenances = FieldProvenanceSerializer(many=True, read_only=True)
    calculations = CalculationRecordSerializer(many=True, read_only=True)

    class Meta:
        model = PlanVersion
        fields = [
            "id",
            "plan",
            "number",
            "status",
            "origin",
            "based_on",
            "technical_data_set",
            "planned_start_date",
            "planned_end_date",
            "target_yield_kg_per_ha",
            "objectives",
            "constraints_notes",
            "change_note",
            "validated_by",
            "validated_at",
            "engine_version",
            "planting_spec",
            "allocations",
            "phases",
            "provenances",
            "calculations",
            "version",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class OrgDataSetField(serializers.PrimaryKeyRelatedField):
    """Only resolves technical data sets of the request's organization."""

    default_error_messages = {"does_not_exist": "Référentiel introuvable."}

    def get_queryset(self) -> Any:
        return TechnicalDataSet.objects.filter(
            organization_id=self.context["tenant"].organization_id
        )


class PlanVersionHeaderSerializer(serializers.ModelSerializer):
    technical_data_set = OrgDataSetField(
        queryset=TechnicalDataSet.objects.none(), required=False, allow_null=True
    )

    class Meta:
        model = PlanVersion
        fields = [
            "planned_start_date",
            "planned_end_date",
            "target_yield_kg_per_ha",
            "objectives",
            "constraints_notes",
            "change_note",
            "technical_data_set",
        ]


class AllocationsInputSerializer(serializers.Serializer):
    allocations = PlanAllocationSerializer(many=True)


class PhaseInputSerializer(serializers.Serializer):
    phase_code = serializers.CharField(max_length=40)
    duration_days = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class PhasesInputSerializer(serializers.Serializer):
    phases = PhaseInputSerializer(many=True)


class NewVersionSerializer(serializers.Serializer):
    based_on = serializers.UUIDField(required=False, allow_null=True)
    change_note = serializers.CharField(required=False, allow_blank=True)


class CompareQuerySerializer(serializers.Serializer):
    a = serializers.UUIDField()
    b = serializers.UUIDField()


class CropCycleSerializer(serializers.ModelSerializer):
    class Meta:
        model = CropCycle
        fields = [
            "id",
            "plan",
            "plan_version",
            "parcel",
            "area_m2",
            "start_date",
            "end_date",
            "status",
            "version",
        ]
        read_only_fields = fields
