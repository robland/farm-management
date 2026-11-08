from typing import Any

from rest_framework import serializers

from apps.agronomy.models import (
    InputProduct,
    Observation,
    PlannedFertilization,
    PlannedIrrigation,
    PlannedPhytoIntervention,
)
from apps.core.serializers import FarmScopedPrimaryKeyRelatedField
from apps.fields.models import Parcel
from apps.files.models import StoredFile
from apps.inventory.serializers import OrgScopedRelatedField
from apps.production_plans.models import CropCycle


class InputProductSerializer(serializers.ModelSerializer):
    label_file = OrgScopedRelatedField(
        queryset=StoredFile.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = InputProduct
        fields = [
            "id",
            "kind",
            "name",
            "manufacturer",
            "catalog_item",
            "composition",
            "formulation",
            "density_kg_per_l",
            "active_ingredients",
            "registration_number",
            "registration_country",
            "registration_valid_until",
            "label_file",
            "notes",
            "version",
            "created_at",
        ]
        read_only_fields = ["id", "catalog_item", "version", "created_at"]


class PlannedFertilizationSerializer(serializers.ModelSerializer):
    product = OrgScopedRelatedField(queryset=InputProduct.objects.all())

    class Meta:
        model = PlannedFertilization
        fields = [
            "id",
            "sequence",
            "product",
            "phase_code",
            "day_offset",
            "mode",
            "target_nutrient",
            "nutrient_dose_kg_per_ha",
            "dose_value",
            "dose_unit",
            "basis",
            "method",
            "source_kind",
            "technical_data_item",
            "source_note",
            "computed_quantity",
            "computed_unit",
            "notes",
        ]
        read_only_fields = [
            "id",
            "sequence",
            "computed_quantity",
            "computed_unit",
            "technical_data_item",
        ]


class PlannedPhytoSerializer(serializers.ModelSerializer):
    product = OrgScopedRelatedField(queryset=InputProduct.objects.all())

    class Meta:
        model = PlannedPhytoIntervention
        fields = [
            "id",
            "sequence",
            "product",
            "target_organism",
            "phase_code",
            "day_offset",
            "dose_value",
            "dose_unit",
            "basis",
            "label_reference",
            "pre_harvest_interval_days",
            "reentry_interval_hours",
            "source_kind",
            "computed_quantity",
            "computed_unit",
            "notes",
        ]
        read_only_fields = ["id", "sequence", "computed_quantity", "computed_unit"]


class PlannedIrrigationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlannedIrrigation
        fields = [
            "id",
            "phase_code",
            "et0_mm_per_day",
            "kc",
            "application_efficiency_rate",
            "frequency_days",
            "source_kind",
            "computed_gross_l_per_day",
            "notes",
        ]
        read_only_fields = ["id", "computed_gross_l_per_day"]
        validators: list[Any] = []


class IrrigationScheduleSerializer(serializers.Serializer):
    items = PlannedIrrigationSerializer(many=True)


class ProgramSerializer(serializers.Serializer):
    fertilizations = PlannedFertilizationSerializer(many=True)
    phyto_interventions = PlannedPhytoSerializer(many=True)
    irrigation_schedule = PlannedIrrigationSerializer(many=True)


class ObservationSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(required=False)
    parcel = FarmScopedPrimaryKeyRelatedField(queryset=Parcel.objects.all())
    crop_cycle = FarmScopedPrimaryKeyRelatedField(
        queryset=CropCycle.objects.all(), required=False, allow_null=True
    )
    photos = OrgScopedRelatedField(queryset=StoredFile.objects.all(), many=True, required=False)

    class Meta:
        model = Observation
        fields = [
            "id",
            "parcel",
            "crop_cycle",
            "observed_at",
            "kind",
            "target",
            "severity",
            "affected_area_pct",
            "notes",
            "photos",
            "author",
            "created_at",
            "version",
        ]
        read_only_fields = ["author", "created_at", "version"]
