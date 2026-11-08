from typing import Any

from rest_framework import serializers

from apps.core.serializers import FarmScopedPrimaryKeyRelatedField
from apps.crops.models import Crop
from apps.harvest.models import HarvestRecord, UnitConversion
from apps.production_plans.models import CropCycle
from apps.users.models import User


class VisibleCropField(serializers.PrimaryKeyRelatedField):
    default_error_messages = {"does_not_exist": "Culture introuvable."}

    def get_queryset(self) -> Any:
        from apps.crops.services import visible_crops

        return visible_crops(self.context["tenant"])


class UnitConversionSerializer(serializers.ModelSerializer):
    crop = VisibleCropField(queryset=Crop.objects.none())

    class Meta:
        model = UnitConversion
        fields = ["id", "crop", "unit", "kg_per_unit", "measured_on", "notes", "version"]
        read_only_fields = ["id", "version"]
        validators: list[Any] = []


class FarmMemberField(serializers.PrimaryKeyRelatedField):
    default_error_messages = {"does_not_exist": "Utilisateur introuvable."}

    def get_queryset(self) -> Any:
        return User.objects.filter(
            farm_memberships__farm_id=self.context["tenant"].farm_id,
            farm_memberships__status="active",
        )


class HarvestRecordSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(required=False)
    crop_cycle = FarmScopedPrimaryKeyRelatedField(queryset=CropCycle.objects.all())
    responsible = FarmMemberField(queryset=User.objects.none(), required=False, allow_null=True)

    class Meta:
        model = HarvestRecord
        fields = [
            "id",
            "crop_cycle",
            "parcel",
            "harvested_on",
            "quantity",
            "unit",
            "quantity_kg",
            "conversion_factor_used",
            "quality_grade",
            "loss_quantity_kg",
            "loss_reason",
            "responsible",
            "notes",
            "voided_at",
            "void_reason",
            "created_at",
            "version",
        ]
        read_only_fields = [
            "parcel",
            "quantity_kg",
            "conversion_factor_used",
            "voided_at",
            "void_reason",
            "created_at",
            "version",
        ]


class VoidSerializer(serializers.Serializer):
    reason = serializers.CharField()


class CampaignQuerySerializer(serializers.Serializer):
    campaign = serializers.UUIDField()
