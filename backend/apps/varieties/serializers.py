from typing import Any

from rest_framework import serializers

from apps.crops.models import Crop
from apps.varieties.models import TechnicalDataItem, TechnicalDataSet, TechnicalDocument, Variety


class VisibleCropField(serializers.PrimaryKeyRelatedField):
    """Only resolves shared crops and crops of the request's organization."""

    default_error_messages = {"does_not_exist": "Culture introuvable."}

    def get_queryset(self) -> Any:
        from apps.crops.services import visible_crops

        return visible_crops(self.context["tenant"])


class VarietySerializer(serializers.ModelSerializer):
    crop = VisibleCropField(queryset=Crop.objects.none())
    crop_name = serializers.CharField(source="crop.common_name", read_only=True)

    class Meta:
        model = Variety
        fields = [
            "id",
            "crop",
            "crop_name",
            "name",
            "seed_company",
            "description",
            "is_hybrid",
            "version",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "crop_name", "version", "created_at", "updated_at"]


class TechnicalDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = TechnicalDocument
        fields = [
            "id",
            "variety",
            "file",
            "title",
            "supplier",
            "document_date",
            "language",
            "status",
            "created_at",
        ]
        read_only_fields = fields


class TechnicalDocumentCreateSerializer(serializers.Serializer):
    file = serializers.UUIDField()
    title = serializers.CharField(required=False, allow_blank=True, max_length=200)
    supplier = serializers.CharField(required=False, allow_blank=True, max_length=150)
    document_date = serializers.DateField(required=False, allow_null=True)
    language = serializers.CharField(required=False, max_length=10)


class TechnicalDataItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = TechnicalDataItem
        fields = [
            "key",
            "value_numeric",
            "value_min",
            "value_max",
            "value_text",
            "unit",
            "provenance",
            "source_page",
            "source_section",
            "source_quote",
            "confidence",
            "notes",
            "validated",
            "validated_by",
            "validated_at",
        ]
        read_only_fields = ["validated", "validated_by", "validated_at"]
        # Uniqueness of (data_set, key) is enforced by the upsert service.
        validators: list[Any] = []


class TechnicalDataSetSerializer(serializers.ModelSerializer):
    items = TechnicalDataItemSerializer(many=True, read_only=True)

    class Meta:
        model = TechnicalDataSet
        fields = [
            "id",
            "variety",
            "source_document",
            "version_number",
            "status",
            "based_on",
            "notes",
            "validated_by",
            "validated_at",
            "items",
            "version",
            "created_at",
        ]
        read_only_fields = fields


class TechnicalDataSetCreateSerializer(serializers.Serializer):
    variety = serializers.UUIDField()
    source_document = serializers.UUIDField(required=False, allow_null=True)
    based_on = serializers.UUIDField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class ItemsUpsertSerializer(serializers.Serializer):
    items = TechnicalDataItemSerializer(many=True)


class KeysSerializer(serializers.Serializer):
    keys = serializers.ListField(child=serializers.CharField(max_length=100), allow_empty=False)


class TechnicalKeySerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    unit = serializers.CharField()
    kind = serializers.CharField()
    min_value = serializers.DecimalField(max_digits=14, decimal_places=4, allow_null=True)
    max_value = serializers.DecimalField(max_digits=14, decimal_places=4, allow_null=True)
