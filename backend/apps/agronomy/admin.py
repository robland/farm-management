from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from apps.agronomy import services
from apps.agronomy.models import (
    InputProduct,
    Observation,
    PlannedFertilization,
    PlannedIrrigation,
    PlannedPhytoIntervention,
)
from apps.core.admin_services import ServiceAdmin, platform_context
from apps.core.tenancy import TenantContext
from apps.production_plans.models import PlanVersion

# Doses are never invented: every programme line is entered by a person and checked
# by the agronomy services (product type, label, units) like through the API (CLAUDE.md §9).

PRODUCT_FIELDS = [
    "kind",
    "name",
    "manufacturer",
    "composition",
    "formulation",
    "density_kg_per_l",
    "active_ingredients",
    "registration_number",
    "registration_country",
    "registration_valid_until",
    "label_file",
    "notes",
]
FERTILIZATION_FIELDS = [
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
    "source_note",
    "notes",
]
PHYTO_FIELDS = [
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
    "notes",
]
IRRIGATION_FIELDS = [
    "phase_code",
    "et0_mm_per_day",
    "kc",
    "application_efficiency_rate",
    "frequency_days",
    "source_kind",
    "notes",
]


@admin.register(InputProduct)
class InputProductAdmin(ServiceAdmin):
    scope = "organization"
    add_fields = change_fields = PRODUCT_FIELDS

    def can_change(self, obj: Any) -> bool:
        return obj.deleted_at is None

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> InputProduct:
        return services.create_product(ctx, data=data)

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        return services.update_product(
            ctx, product_id=obj.id, expected_version=expected_version, changes=changes
        )


class ProgramItemAdmin(ServiceAdmin):
    """Programme lines of a draft plan version: added or removed, never edited in place."""

    scope = "plan_version"
    kind = ""

    def context_for(self, request: HttpRequest, obj: Any) -> TenantContext:
        version = obj.plan_version
        return platform_context(
            request, organization_id=version.organization_id, farm_id=version.farm_id
        )

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        if obj is not None and obj.plan_version.status != PlanVersion.Status.DRAFT:
            return False
        return super().has_delete_permission(request, obj)

    def perform_delete(self, ctx: TenantContext, obj: Any) -> None:
        services.remove_program_item(
            ctx,
            version_id=obj.plan_version_id,
            expected_version=obj.plan_version.version,
            kind=self.kind,
            item_id=obj.id,
        )


@admin.register(PlannedFertilization)
class PlannedFertilizationAdmin(ProgramItemAdmin):
    kind = "fertilization"
    add_fields = FERTILIZATION_FIELDS

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> Any:
        version = data.pop("plan_version")
        item, _ = services.add_fertilization(
            ctx, version_id=version.id, expected_version=version.version, data=data
        )
        return item


@admin.register(PlannedPhytoIntervention)
class PlannedPhytoInterventionAdmin(ProgramItemAdmin):
    kind = "phyto"
    add_fields = PHYTO_FIELDS

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> Any:
        version = data.pop("plan_version")
        item, _ = services.add_phyto(
            ctx, version_id=version.id, expected_version=version.version, data=data
        )
        return item


def _schedule(version: PlanVersion) -> list[dict[str, Any]]:
    return [
        {name: getattr(row, name) for name in IRRIGATION_FIELDS}
        for row in version.irrigation_schedule.all()
    ]


@admin.register(PlannedIrrigation)
class PlannedIrrigationAdmin(ProgramItemAdmin):
    """The service replaces the whole schedule; one phase is added or removed at a time."""

    kind = "irrigation"
    add_fields = IRRIGATION_FIELDS

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> Any:
        version = data.pop("plan_version")
        rows = [*_schedule(version), data]
        created = services.set_irrigation_schedule(
            ctx, version_id=version.id, expected_version=version.version, items=rows
        )
        return created[-1]


@admin.register(Observation)
class ObservationAdmin(ServiceAdmin):
    replay_by_id = True
    add_fields = [
        "parcel",
        "crop_cycle",
        "observed_at",
        "kind",
        "target",
        "severity",
        "affected_area_pct",
        "notes",
    ]

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> Observation:
        return services.create_observation(ctx, data=data)[0]
