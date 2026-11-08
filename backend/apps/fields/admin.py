from typing import Any

from django.contrib import admin

from apps.core.admin import ReadOnlyTabularInline
from apps.core.admin_services import ServiceAdmin
from apps.core.tenancy import TenantContext
from apps.fields import services
from apps.fields.models import Field, Parcel, ParcelHistoryEntry

FIELD_FIELDS = ["name", "code", "description", "area_m2", "geometry"]
PARCEL_FIELDS = [
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
]


def _alive(obj: Any) -> bool:
    return obj.deleted_at is None


class ParcelInline(ReadOnlyTabularInline):
    model = Parcel
    fields = ["name", "status", "version", "deleted_at"]


@admin.register(Field)
class FieldAdmin(ServiceAdmin):
    replay_by_id = True
    add_fields = FIELD_FIELDS
    change_fields = FIELD_FIELDS
    inlines = [ParcelInline]

    def can_change(self, obj: Any) -> bool:
        return _alive(obj)

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> Field:
        return services.create_field(ctx, data=data)[0]

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        return services.update_field(
            ctx, field_id=obj.id, expected_version=expected_version, changes=changes
        )

    def perform_delete(self, ctx: TenantContext, obj: Any) -> None:
        # Tombstone: offline clients receive the deletion through the change log.
        services.delete_field(ctx, field_id=obj.id, expected_version=obj.version)


@admin.register(Parcel)
class ParcelAdmin(ServiceAdmin):
    replay_by_id = True
    add_fields = PARCEL_FIELDS
    change_fields = PARCEL_FIELDS

    def can_change(self, obj: Any) -> bool:
        return _alive(obj)

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> Parcel:
        return services.create_parcel(ctx, data=data)[0]

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        return services.update_parcel(
            ctx, parcel_id=obj.id, expected_version=expected_version, changes=changes
        )

    def perform_delete(self, ctx: TenantContext, obj: Any) -> None:
        services.delete_parcel(ctx, parcel_id=obj.id, expected_version=obj.version)


@admin.register(ParcelHistoryEntry)
class ParcelHistoryEntryAdmin(ServiceAdmin):
    scope = "parcel"
    add_fields = ["period_start", "period_end", "crop_label", "notes"]

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> ParcelHistoryEntry:
        parcel = data.pop("parcel")
        return services.add_history_entry(ctx, parcel_id=parcel.id, data=data)
