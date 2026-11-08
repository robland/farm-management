from django.contrib import admin

from apps.core.admin import (
    ReadOnlyAdmin,
    ReadOnlyStackedInline,
    ReadOnlyTabularInline,
    register_read_only,
)
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


class PlantingSpecInline(ReadOnlyStackedInline):
    model = PlantingSpec


class PlanAllocationInline(ReadOnlyTabularInline):
    model = PlanAllocation


class PlanPhaseInline(ReadOnlyTabularInline):
    model = PlanPhase


@admin.register(PlanVersion)
class PlanVersionAdmin(ReadOnlyAdmin):
    inlines = [PlantingSpecInline, PlanAllocationInline, PlanPhaseInline]


register_read_only(
    Campaign,
    ProductionPlan,
    PlanAllocation,
    PlantingSpec,
    PlanPhase,
    FieldProvenance,
    CalculationRecord,
    CropCycle,
)
