from typing import Any

from django import forms
from django.contrib import admin
from django.http import HttpRequest

from apps.agronomy import services as agronomy
from apps.core.admin import ReadOnlyStackedInline, ReadOnlyTabularInline, register_read_only
from apps.core.admin_services import ServiceAdmin, platform_context, service_action
from apps.core.tenancy import TenantContext
from apps.production_plans import services
from apps.production_plans.models import (
    CalculationRecord,
    Campaign,
    CropCycle,
    FieldProvenance,
    PlanAllocation,
    PlanPhase,
    PlantingSpec,
    PlanVersion,
    ProductionPlan,
)
from apps.tasks import services as tasks

CAMPAIGN_FIELDS = ["name", "start_date", "end_date", "status", "notes"]
HEADER_FIELDS = [
    "planned_start_date",
    "planned_end_date",
    "target_yield_kg_per_ha",
    "objectives",
    "constraints_notes",
    "change_note",
    "technical_data_set",
]
SPEC_FIELDS = [
    "planting_method",
    "layout",
    "row_spacing_m",
    "plant_spacing_m",
    "plants_per_hole",
    "seeds_per_hole",
    "bed_width_m",
    "path_width_m",
    "rows_per_bed",
    "headland_m",
    "germination_rate",
    "nursery_success_rate",
    "safety_margin_rate",
    "seeds_per_gram",
    "thousand_seed_weight_g",
    "seed_package_size_g",
]
ALLOCATION_FIELDS = [
    "allocated_area_m2",
    "non_plantable_area_m2",
    "plot_length_m",
    "plot_width_m",
    "notes",
]


@admin.register(Campaign)
class CampaignAdmin(ServiceAdmin):
    add_fields = change_fields = CAMPAIGN_FIELDS

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> Campaign:
        return services.create_campaign(ctx, data=data)

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        return services.update_campaign(
            ctx, campaign_id=obj.id, expected_version=expected_version, changes=changes
        )


@admin.register(ProductionPlan)
class ProductionPlanAdmin(ServiceAdmin):
    """Creating a plan creates its first draft version (see "Versions de plan")."""

    add_fields = ["campaign", "variety", "name"]

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> ProductionPlan:
        return services.create_plan(
            ctx, campaign_id=data["campaign"].id, variety_id=data["variety"].id, name=data["name"]
        )


class PlantingSpecInline(ReadOnlyStackedInline):
    model = PlantingSpec


class PlanAllocationInline(ReadOnlyTabularInline):
    model = PlanAllocation


class PlanPhaseInline(ReadOnlyTabularInline):
    model = PlanPhase


class NewVersionForm(forms.Form):
    change_note = forms.CharField(label="Motif de la nouvelle version", required=False)


def _draft(version: PlanVersion) -> bool:
    return version.status == PlanVersion.Status.DRAFT


@admin.register(PlanVersion)
class PlanVersionAdmin(ServiceAdmin):
    """Plan workflow: prefill → allocations, spec, phases → compute → validate → tasks.

    Only a draft is editable; a validated version is changed by creating a new one.
    """

    change_fields = HEADER_FIELDS
    inlines = [PlantingSpecInline, PlanAllocationInline, PlanPhaseInline]
    actions = [
        "prefill",
        "compute",
        "recompute_program",
        "validate",
        "new_version",
        "generate_tasks",
    ]

    def can_change(self, obj: Any) -> bool:
        return _draft(obj)

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        return services.update_header(
            ctx, version_id=obj.id, expected_version=expected_version, changes=changes
        )

    @service_action("Préremplir depuis les données techniques validées")
    def prefill(self, ctx: TenantContext, obj: PlanVersion) -> None:
        services.prefill_from_technical_data(ctx, version_id=obj.id, expected_version=obj.version)

    @service_action("Calculer (densités, plants, semences, calendrier)")
    def compute(self, ctx: TenantContext, obj: PlanVersion) -> None:
        services.compute_version(ctx, version_id=obj.id)

    @service_action("Recalculer les quantités du programme agronomique")
    def recompute_program(self, ctx: TenantContext, obj: PlanVersion) -> None:
        agronomy.recompute_program(ctx, version_id=obj.id)

    @service_action("Valider la version (décision humaine)")
    def validate(self, ctx: TenantContext, obj: PlanVersion) -> None:
        services.validate_version(ctx, version_id=obj.id, expected_version=obj.version)

    @service_action("Créer une nouvelle version à partir de celle-ci", form=NewVersionForm)
    def new_version(self, ctx: TenantContext, obj: PlanVersion, change_note: str) -> None:
        services.create_new_version(
            ctx, plan_id=obj.plan_id, based_on_id=obj.id, change_note=change_note
        )

    @service_action("Générer les tâches (version validée)")
    def generate_tasks(self, ctx: TenantContext, obj: PlanVersion) -> None:
        tasks.generate_tasks(ctx, version_id=obj.id)


class PlanChildAdmin(ServiceAdmin):
    """Rows of a draft plan version, written by the version-level services."""

    scope = "plan_version"

    def context_for(self, request: HttpRequest, obj: Any) -> TenantContext:
        version = obj.plan_version
        return platform_context(
            request, organization_id=version.organization_id, farm_id=version.farm_id
        )

    def version_of(self, obj: Any) -> int | None:
        return obj.plan_version.version

    def can_change(self, obj: Any) -> bool:
        return _draft(obj.plan_version)

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        if obj is not None and not self.can_change(obj):
            return False
        return super().has_delete_permission(request, obj)


@admin.register(PlantingSpec)
class PlantingSpecAdmin(PlanChildAdmin):
    change_fields = SPEC_FIELDS

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        services.update_planting_spec(
            ctx, version_id=obj.plan_version_id, expected_version=expected_version, changes=changes
        )
        return PlantingSpec.objects.get(pk=obj.pk)


def _allocations(version: PlanVersion) -> list[dict[str, Any]]:
    return [
        {"parcel": a.parcel, **{name: getattr(a, name) for name in ALLOCATION_FIELDS}}
        for a in version.allocations.select_related("parcel")
    ]


@admin.register(PlanAllocation)
class PlanAllocationAdmin(PlanChildAdmin):
    """One parcel at a time; the service replaces and checks the whole allocation."""

    add_fields = ["parcel", *ALLOCATION_FIELDS]
    change_fields = ALLOCATION_FIELDS

    def _replace(
        self, ctx: TenantContext, version: PlanVersion, rows: list[dict[str, Any]]
    ) -> None:
        services.set_allocations(
            ctx, version_id=version.id, expected_version=version.version, allocations=rows
        )

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> PlanAllocation:
        version = data.pop("plan_version")
        self._replace(ctx, version, [*_allocations(version), data])
        return version.allocations.get(parcel=data["parcel"])

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        rows = [
            {**row, **changes} if row["parcel"].pk == obj.parcel_id else row
            for row in _allocations(obj.plan_version)
        ]
        services.set_allocations(
            ctx, version_id=obj.plan_version_id, expected_version=expected_version, allocations=rows
        )
        return obj.plan_version.allocations.get(parcel_id=obj.parcel_id)

    def perform_delete(self, ctx: TenantContext, obj: Any) -> None:
        rows = [r for r in _allocations(obj.plan_version) if r["parcel"].pk != obj.parcel_id]
        self._replace(ctx, obj.plan_version, rows)


def _phases(version: PlanVersion) -> list[dict[str, Any]]:
    return [
        {"phase_code": p.phase_code, "duration_days": p.duration_days}
        for p in version.phases.order_by("sequence")
    ]


@admin.register(PlanPhase)
class PlanPhaseAdmin(PlanChildAdmin):
    add_fields = ["phase_code", "duration_days"]
    change_fields = ["duration_days"]

    def _replace(
        self, ctx: TenantContext, version: PlanVersion, rows: list[dict[str, Any]]
    ) -> None:
        services.set_phases(
            ctx, version_id=version.id, expected_version=version.version, phases=rows
        )

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> PlanPhase:
        version = data.pop("plan_version")
        self._replace(ctx, version, [*_phases(version), data])
        return version.phases.get(phase_code=data["phase_code"])

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        rows = [
            {**row, **changes} if row["phase_code"] == obj.phase_code else row
            for row in _phases(obj.plan_version)
        ]
        services.set_phases(
            ctx, version_id=obj.plan_version_id, expected_version=expected_version, phases=rows
        )
        return obj.plan_version.phases.get(phase_code=obj.phase_code)

    def perform_delete(self, ctx: TenantContext, obj: Any) -> None:
        rows = [r for r in _phases(obj.plan_version) if r["phase_code"] != obj.phase_code]
        self._replace(ctx, obj.plan_version, rows)


register_read_only(FieldProvenance, CalculationRecord, CropCycle)
