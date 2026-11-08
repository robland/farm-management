from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from apps.core.admin import ReadOnlyTabularInline
from apps.core.admin_services import ServiceAdmin, platform_context
from apps.core.tenancy import TenantContext
from apps.inventory import services
from apps.inventory.models import CatalogItem, PriceList, PriceListItem, Supplier


class OrgObjectAdmin(ServiceAdmin):
    """Organization catalogue objects share the generic inventory services."""

    scope = "organization"

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> Any:
        return services.create_org_object(ctx, self.model, data)

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        return services.update_org_object(ctx, self.model, obj.pk, expected_version, changes)

    def perform_delete(self, ctx: TenantContext, obj: Any) -> None:
        services.delete_org_object(ctx, self.model, obj.pk, obj.version)


@admin.register(Supplier)
class SupplierAdmin(OrgObjectAdmin):
    add_fields = change_fields = ["name", "kind", "phone", "email", "address", "notes"]

    def can_change(self, obj: Any) -> bool:
        return obj.deleted_at is None


@admin.register(CatalogItem)
class CatalogItemAdmin(OrgObjectAdmin):
    add_fields = change_fields = ["category", "name", "reference", "base_unit", "spec"]

    def can_change(self, obj: Any) -> bool:
        return obj.deleted_at is None


class PriceListItemInline(ReadOnlyTabularInline):
    model = PriceListItem


@admin.register(PriceList)
class PriceListAdmin(OrgObjectAdmin):
    add_fields = change_fields = [
        "supplier",
        "name",
        "currency",
        "valid_from",
        "valid_to",
        "status",
        "notes",
    ]
    inlines = [PriceListItemInline]

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> PriceList:
        return services.create_price_list(ctx, data)

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False  # quotes copy their prices from price lists: archive instead


def _items(price_list: PriceList) -> list[dict[str, Any]]:
    return [
        {"catalog_item": item.catalog_item, "unit": item.unit, "unit_price": item.unit_price}
        for item in price_list.items.select_related("catalog_item")
    ]


@admin.register(PriceListItem)
class PriceListItemAdmin(ServiceAdmin):
    """One price at a time; the service replaces the whole list (validated together)."""

    list_display = ["catalog_item", "unit", "unit_price", "price_list"]
    list_select_related = ["catalog_item", "price_list"]
    search_fields = ["catalog_item__name", "price_list__name"]
    scope = "price_list"
    add_fields = ["catalog_item", "unit", "unit_price"]
    change_fields = ["unit", "unit_price"]

    def context_for(self, request: HttpRequest, obj: Any) -> TenantContext:
        return platform_context(request, organization_id=obj.price_list.organization_id)

    def can_change(self, obj: Any) -> bool:
        return obj.price_list.status == PriceList.Status.DRAFT

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        if obj is not None and not self.can_change(obj):
            return False
        return super().has_delete_permission(request, obj)

    def _replace(
        self, ctx: TenantContext, price_list: PriceList, items: list[dict[str, Any]]
    ) -> None:
        services.set_price_items(
            ctx, price_list_id=price_list.id, expected_version=price_list.version, items=items
        )

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> PriceListItem:
        price_list = data.pop("price_list")
        self._replace(ctx, price_list, [*_items(price_list), data])
        return price_list.items.get(catalog_item=data["catalog_item"], unit=data["unit"])

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        items = [
            {**item, **changes}
            if item["catalog_item"].pk == obj.catalog_item_id and item["unit"] == obj.unit
            else item
            for item in _items(obj.price_list)
        ]
        self._replace(ctx, obj.price_list, items)
        unit = changes.get("unit", obj.unit)
        return obj.price_list.items.get(catalog_item_id=obj.catalog_item_id, unit=unit)

    def perform_delete(self, ctx: TenantContext, obj: Any) -> None:
        items = [
            item
            for item in _items(obj.price_list)
            if not (item["catalog_item"].pk == obj.catalog_item_id and item["unit"] == obj.unit)
        ]
        self._replace(ctx, obj.price_list, items)
