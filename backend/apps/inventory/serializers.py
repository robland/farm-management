from typing import Any

from rest_framework import serializers

from apps.inventory.models import CatalogItem, PriceList, PriceListItem, Supplier


class OrgScopedRelatedField(serializers.PrimaryKeyRelatedField):
    """Only resolves non-deleted objects of the request's organization."""

    default_error_messages = {"does_not_exist": "Objet introuvable."}

    def get_queryset(self) -> Any:
        # The declared queryset only names the model; the tenant filter is applied here.
        declared: Any = getattr(self, "queryset", None)
        model: Any = declared.model
        queryset = model.objects.filter(organization_id=self.context["tenant"].organization_id)
        if hasattr(queryset.model, "deleted_at"):
            queryset = queryset.filter(deleted_at__isnull=True)
        return queryset


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = [
            "id",
            "name",
            "kind",
            "phone",
            "email",
            "address",
            "notes",
            "version",
            "created_at",
        ]
        read_only_fields = ["id", "version", "created_at"]


class CatalogItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = CatalogItem
        fields = [
            "id",
            "category",
            "name",
            "reference",
            "base_unit",
            "spec",
            "version",
            "created_at",
        ]
        read_only_fields = ["id", "version", "created_at"]


class PriceListItemSerializer(serializers.ModelSerializer):
    catalog_item = OrgScopedRelatedField(queryset=CatalogItem.objects.all())

    class Meta:
        model = PriceListItem
        fields = ["catalog_item", "unit", "unit_price"]
        validators: list[Any] = []


class PriceListSerializer(serializers.ModelSerializer):
    supplier = OrgScopedRelatedField(queryset=Supplier.objects.all())
    items = PriceListItemSerializer(many=True, read_only=True)

    class Meta:
        model = PriceList
        fields = [
            "id",
            "supplier",
            "name",
            "currency",
            "valid_from",
            "valid_to",
            "status",
            "notes",
            "items",
            "version",
            "created_at",
        ]
        read_only_fields = ["id", "items", "version", "created_at"]


class PriceItemsInputSerializer(serializers.Serializer):
    items = PriceListItemSerializer(many=True)
