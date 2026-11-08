from typing import Any

from rest_framework import serializers

from apps.core.serializers import FarmScopedPrimaryKeyRelatedField
from apps.fields.models import Parcel
from apps.inventory.models import CatalogItem, PriceList
from apps.inventory.serializers import OrgScopedRelatedField
from apps.irrigation.models import BomLine, IrrigationDesign, Quote, QuoteLine
from apps.production_plans.models import PlanVersion


def _dec(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(
        max_digits=14, decimal_places=4, required=False, allow_null=True, **kwargs
    )


class PipeSegmentSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=["main", "submain", "lateral"])
    length_m = serializers.DecimalField(max_digits=10, decimal_places=3, min_value=0)
    inner_diameter_mm = serializers.DecimalField(max_digits=8, decimal_places=2, min_value=0)
    hazen_williams_c = serializers.DecimalField(max_digits=6, decimal_places=1, min_value=0)
    outlets = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class DripParametersSerializer(serializers.Serializer):
    lateral_count = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    lateral_length_m = _dec()
    lateral_spacing_m = _dec()
    emitter_spacing_m = _dec()
    emitter_flow_lph = _dec()
    operating_pressure_bar = _dec()
    irrigated_area_m2 = _dec()
    et0_mm_per_day = _dec()
    kc = _dec()
    application_efficiency_rate = _dec()
    source_max_flow_m3h = _dec()
    sector_count = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    max_irrigation_hours_per_day = _dec()
    static_lift_m = _dec()
    elevation_difference_m = _dec()
    filter_head_loss_m = _dec()
    fittings_loss_rate = _dec()
    pump_efficiency_rate = _dec()
    segments = PipeSegmentSerializer(many=True, required=False)


class SprinklerParametersSerializer(serializers.Serializer):
    sprinkler_count = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    sprinkler_flow_lph = _dec()
    spacing_along_m = _dec()
    spacing_between_m = _dec()
    sector_count = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class BomParametersSerializer(serializers.Serializer):
    installation_waste_rate = _dec()
    emitters_integrated = serializers.BooleanField(default=True)
    dripline_roll_length_m = _dec()
    filter_count = serializers.IntegerField(min_value=0, default=0)
    pressure_regulator_count = serializers.IntegerField(min_value=0, default=0)
    include_pump = serializers.BooleanField(default=False)
    include_fertilizer_injector = serializers.BooleanField(default=False)


PARAMETER_SERIALIZERS = {
    IrrigationDesign.SystemType.DRIP: DripParametersSerializer,
    IrrigationDesign.SystemType.SPRINKLER: SprinklerParametersSerializer,
    IrrigationDesign.SystemType.MICRO_SPRINKLER: SprinklerParametersSerializer,
}


class FarmPlanVersionField(FarmScopedPrimaryKeyRelatedField):
    pass


class BomLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = BomLine
        fields = [
            "id",
            "sequence",
            "component_type",
            "description",
            "quantity",
            "unit",
            "rationale",
            "spec",
            "catalog_item",
            "is_manual",
        ]
        read_only_fields = fields


class IrrigationDesignSerializer(serializers.ModelSerializer):
    parcel = FarmScopedPrimaryKeyRelatedField(queryset=Parcel.objects.all())
    plan_version = FarmPlanVersionField(
        queryset=PlanVersion.objects.all(), required=False, allow_null=True
    )
    bom_lines = BomLineSerializer(many=True, read_only=True)

    class Meta:
        model = IrrigationDesign
        fields = [
            "id",
            "parcel",
            "plan_version",
            "name",
            "number",
            "status",
            "system_type",
            "based_on",
            "parameters",
            "bom_parameters",
            "validated_by",
            "validated_at",
            "bom_lines",
            "version",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "number",
            "status",
            "based_on",
            "validated_by",
            "validated_at",
            "bom_lines",
            "version",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        system: Any = attrs.get("system_type", getattr(self.instance, "system_type", None))
        if "parameters" in attrs:
            serializer_class = PARAMETER_SERIALIZERS.get(system)
            if serializer_class is None:
                attrs["parameters"] = {}
            else:
                params = serializer_class(data=attrs["parameters"])
                if not params.is_valid():
                    raise serializers.ValidationError({"parameters": params.errors})
                attrs["parameters"] = params.validated_data
        if "bom_parameters" in attrs:
            bom = BomParametersSerializer(data=attrs["bom_parameters"])
            if not bom.is_valid():
                raise serializers.ValidationError({"bom_parameters": bom.errors})
            attrs["bom_parameters"] = bom.validated_data
        return attrs


class BomLineInputSerializer(serializers.Serializer):
    component_type = serializers.CharField(max_length=30)
    description = serializers.CharField(max_length=255)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=0)
    unit = serializers.ChoiceField(choices=CatalogItem.Unit.choices)
    rationale = serializers.CharField(required=False, allow_blank=True)


class BomLinkSerializer(serializers.Serializer):
    bom_line = serializers.UUIDField()
    catalog_item = OrgScopedRelatedField(queryset=CatalogItem.objects.all(), allow_null=True)


class QuoteLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuoteLine
        fields = [
            "id",
            "sequence",
            "bom_line",
            "catalog_item",
            "description",
            "quantity",
            "unit",
            "unit_price",
            "line_total",
            "price_source",
            "notes",
        ]
        read_only_fields = fields


class QuoteSerializer(serializers.ModelSerializer):
    lines = QuoteLineSerializer(many=True, read_only=True)

    class Meta:
        model = Quote
        fields = [
            "id",
            "design",
            "supplier",
            "price_list",
            "number",
            "currency",
            "status",
            "discount_amount",
            "tax_rate",
            "subtotal",
            "tax_amount",
            "total",
            "assumptions",
            "warnings",
            "notes",
            "issued_by",
            "issued_at",
            "lines",
            "version",
            "created_at",
        ]
        read_only_fields = fields


class QuoteCreateSerializer(serializers.Serializer):
    design = serializers.UUIDField()
    price_list = OrgScopedRelatedField(
        queryset=PriceList.objects.all(), required=False, allow_null=True
    )
    currency = serializers.CharField(max_length=3, required=False)
    notes = serializers.CharField(required=False, allow_blank=True)


class QuoteLinePriceSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    unit_price = serializers.DecimalField(
        max_digits=19, decimal_places=4, min_value=0, allow_null=True
    )
    notes = serializers.CharField(required=False, allow_blank=True)


class QuoteUpdateSerializer(serializers.Serializer):
    lines = QuoteLinePriceSerializer(many=True, required=False)
    discount_amount = serializers.DecimalField(
        max_digits=19, decimal_places=4, min_value=0, required=False, allow_null=True
    )
    tax_rate = serializers.DecimalField(
        max_digits=6, decimal_places=4, min_value=0, required=False, allow_null=True
    )
    notes = serializers.CharField(required=False, allow_blank=True)


class QuoteStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["accepted", "rejected"])
