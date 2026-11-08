from typing import Any

from django.contrib import admin

from apps.core.admin_services import ReasonForm, ServiceAdmin, service_action
from apps.core.tenancy import TenantContext
from apps.harvest import services
from apps.harvest.models import HarvestRecord, UnitConversion


@admin.register(UnitConversion)
class UnitConversionAdmin(ServiceAdmin):
    """Measured conversion factors (crate, bag… → kg): never assumed by the system."""

    add_fields = ["crop", "unit", "kg_per_unit", "measured_on", "notes"]

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> UnitConversion:
        return services.set_unit_conversion(ctx, data=data)


@admin.register(HarvestRecord)
class HarvestRecordAdmin(ServiceAdmin):
    """Harvests are append-only: an erroneous record is voided with a reason."""

    list_display = [
        "harvested_on",
        "crop_cycle",
        "parcel",
        "quantity",
        "unit",
        "quantity_kg",
        "quality_grade",
        "voided_at",
        "farm",
    ]
    list_select_related = ["crop_cycle", "parcel", "farm"]
    list_filter = ["quality_grade", ("voided_at", admin.EmptyFieldListFilter)]
    date_hierarchy = "harvested_on"
    replay_by_id = True
    add_fields = [
        "crop_cycle",
        "harvested_on",
        "quantity",
        "unit",
        "quality_grade",
        "loss_quantity_kg",
        "loss_reason",
        "responsible",
        "notes",
    ]
    actions = ["void"]

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> HarvestRecord:
        return services.record_harvest(ctx, data=data)[0]

    @service_action("Annuler les récoltes saisies par erreur", form=ReasonForm)
    def void(self, ctx: TenantContext, obj: HarvestRecord, reason: str) -> None:
        services.void_harvest(ctx, record_id=obj.id, reason=reason)
