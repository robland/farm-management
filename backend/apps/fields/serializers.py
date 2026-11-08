from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.core.serializers import FarmScopedPrimaryKeyRelatedField
from apps.fields.models import Field, Parcel, ParcelHistoryEntry

# Declared area vs length × width discrepancy that triggers a warning (not a block).
DIMENSION_WARNING_RATE = Decimal("0.05")


class FieldSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(required=False, help_text="UUID généré par le client (hors ligne).")

    class Meta:
        model = Field
        fields = [
            "id",
            "name",
            "code",
            "description",
            "area_m2",
            "geometry",
            "version",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["version", "created_at", "updated_at"]


class ParcelSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(required=False, help_text="UUID généré par le client (hors ligne).")
    field = FarmScopedPrimaryKeyRelatedField(
        queryset=Field.objects.all(), required=False, allow_null=True
    )
    warnings = serializers.SerializerMethodField()

    class Meta:
        model = Parcel
        fields = [
            "id",
            "field",
            "name",
            "code",
            "area_m2",
            "length_m",
            "width_m",
            "geometry",
            "latitude",
            "longitude",
            "soil_type",
            "soil_ph",
            "water_availability",
            "water_notes",
            "notes",
            "status",
            "warnings",
            "version",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["version", "created_at", "updated_at"]

    def get_warnings(self, parcel: Parcel) -> list[str]:
        warnings: list[str] = []
        if parcel.length_m and parcel.width_m and parcel.area_m2:
            computed = parcel.length_m * parcel.width_m
            if abs(computed - parcel.area_m2) / parcel.area_m2 > DIMENSION_WARNING_RATE:
                warnings.append(
                    f"La superficie déclarée ({parcel.area_m2} m²) diffère de plus de 5 % "
                    f"de longueur × largeur ({computed} m²)."
                )
        return warnings

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if self.instance is not None and "id" in attrs:
            attrs.pop("id")
        return attrs


class ParcelHistoryEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = ParcelHistoryEntry
        fields = ["id", "period_start", "period_end", "crop_label", "notes", "created_at"]
        read_only_fields = ["id", "created_at"]
