from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from apps.core.admin import ReadOnlyTabularInline
from apps.core.admin_services import ServiceAdmin, platform_context
from apps.core.tenancy import TenantContext
from apps.farms import services
from apps.farms.models import Farm, FarmMembership

FARM_FIELDS = [
    "name",
    "code",
    "country",
    "region",
    "locality",
    "latitude",
    "longitude",
    "timezone",
    "currency",
    "locale",
    "declared_area_m2",
    "settings",
    "status",
]


class FarmMembershipInline(ReadOnlyTabularInline):
    model = FarmMembership
    fields = ["user", "role", "status", "valid_from", "valid_to"]


@admin.register(Farm)
class FarmAdmin(ServiceAdmin):
    scope = "organization"
    add_fields = FARM_FIELDS
    change_fields = FARM_FIELDS
    inlines = [FarmMembershipInline]

    def context_for(self, request: HttpRequest, obj: Any) -> TenantContext:
        return platform_context(request, organization_id=obj.organization_id, farm_id=obj.id)

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> Farm:
        return services.create_farm(ctx, data=data)

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        return services.update_farm(ctx, expected_version=expected_version, changes=changes)


@admin.register(FarmMembership)
class FarmMembershipAdmin(ServiceAdmin):
    list_display = ["user", "farm", "role", "status", "valid_from", "valid_to"]
    list_select_related = ["user", "farm", "role"]
    search_fields = ["user__full_name", "user__email", "user__phone", "farm__name"]
    list_filter = ["status"]
    add_fields = ["user", "role", "valid_from", "valid_to"]
    change_fields = ["role", "status", "valid_from", "valid_to"]

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> FarmMembership:
        extra = {k: v for k, v in data.items() if k not in ("user", "role") and v is not None}
        return services.add_farm_member(
            ctx, user_id=data["user"].id, role_id=data["role"].id, **extra
        )

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        return services.update_farm_member(
            ctx, membership_id=obj.id, expected_version=expected_version, changes=changes
        )
