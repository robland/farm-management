"""Production plan services (FR-030..035).

- Only draft versions are editable; a validated version is immutable.
- Every value carries a provenance (document / calculation / AI / user).
- Calculations are delegated to `agronomy_engine`; missing inputs are listed,
  never filled with a default.
- Validation requires `plans.validate`, recomputes everything and books the
  parcel occupation (crop cycles). The AI module can never call `validate_version`
  on its own: it only produces drafts.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone

from agronomy_engine import ENGINE_VERSION
from agronomy_engine.crop_calendar import CalendarInput, PhaseSpec, compute_calendar
from agronomy_engine.errors import InvalidInputError, MissingInputError
from agronomy_engine.planting import PlantingInput, compute_planting
from agronomy_engine.result import CalculationResult
from agronomy_engine.seeds import SeedInput, compute_seeds
from apps.audit.services import record_event
from apps.core.exceptions import BusinessRuleError, NotFoundError
from apps.core.tenancy import TenantContext
from apps.core.versioning import apply_changes, check_version
from apps.fields.models import Parcel
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
from apps.synchronization.services import record_change
from apps.varieties.models import TechnicalDataItem, TechnicalDataSet, Variety
from apps.varieties.technical_keys import PHASE_CODE_PATTERN, PHASE_CODES, phase_durations

VIEW = "plans.view"
EDIT = "plans.edit"
VALIDATE = "plans.validate"

CAMPAIGN_ENTITY = "production_plans.campaign"
PLAN_ENTITY = "production_plans.plan"
VERSION_ENTITY = "production_plans.plan_version"
CYCLE_ENTITY = "production_plans.crop_cycle"

SK = FieldProvenance.SourceKind

PLANTING_FIELDS = [
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
HEADER_FIELDS = [
    "planned_start_date",
    "planned_end_date",
    "target_yield_kg_per_ha",
    "objectives",
    "constraints_notes",
    "change_note",
]
# Validated technical data key -> planting spec field.
TECHNICAL_TO_PLANTING = {
    "row_spacing": "row_spacing_m",
    "plant_spacing": "plant_spacing_m",
    "plants_per_hole": "plants_per_hole",
    "seeds_per_hole": "seeds_per_hole",
    "germination_rate": "germination_rate",
    "seeds_per_gram": "seeds_per_gram",
    "thousand_seed_weight": "thousand_seed_weight_g",
}
INTEGER_FIELDS = {"plants_per_hole", "seeds_per_hole", "rows_per_bed"}


def _change(ctx: TenantContext, entity_type: str, instance: Any) -> None:
    record_change(
        farm_id=ctx.require_farm_id,
        entity_type=entity_type,
        entity_id=instance.pk,
        entity_version=instance.version,
        required_permission=VIEW,
    )


def _event(
    ctx: TenantContext, action: str, entity_type: str, entity_id: uuid.UUID, **extra: Any
) -> None:
    record_event(
        action=action,
        actor=ctx.user,
        organization_id=ctx.organization_id,
        farm_id=ctx.farm_id,
        entity_type=entity_type,
        entity_id=entity_id,
        **extra,
    )


# --- Campaigns ---------------------------------------------------------------------


@transaction.atomic
def create_campaign(ctx: TenantContext, *, data: dict[str, Any]) -> Campaign:
    ctx.require(EDIT)
    campaign = Campaign(
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        created_by=ctx.user,
        updated_by=ctx.user,
        **data,
    )
    campaign.full_clean()
    campaign.save()
    _event(ctx, "campaign.created", CAMPAIGN_ENTITY, campaign.id, after={"name": campaign.name})
    _change(ctx, CAMPAIGN_ENTITY, campaign)
    return campaign


@transaction.atomic
def update_campaign(
    ctx: TenantContext, *, campaign_id: uuid.UUID, expected_version: int, changes: dict[str, Any]
) -> Campaign:
    ctx.require(EDIT)
    campaign = (
        Campaign.objects.select_for_update()
        .filter(id=campaign_id, farm_id=ctx.require_farm_id, deleted_at__isnull=True)
        .first()
    )
    if campaign is None:
        raise NotFoundError()
    check_version(campaign, expected_version)
    diff = apply_changes(campaign, changes)
    if diff:
        campaign.full_clean()
        campaign.version += 1
        campaign.updated_by = ctx.user
        campaign.save()
        _event(
            ctx,
            "campaign.updated",
            CAMPAIGN_ENTITY,
            campaign.id,
            after={k: v[1] for k, v in diff.items()},
        )
        _change(ctx, CAMPAIGN_ENTITY, campaign)
    return campaign


# --- Plans and drafts --------------------------------------------------------------


@transaction.atomic
def create_plan(
    ctx: TenantContext,
    *,
    campaign_id: uuid.UUID,
    variety_id: uuid.UUID,
    name: str,
    origin: str = PlanVersion.Origin.MANUAL,
) -> ProductionPlan:
    """Manual creation (FR-030): a plan and an empty draft version 1."""
    ctx.require(EDIT)
    campaign = Campaign.objects.filter(
        id=campaign_id, farm_id=ctx.require_farm_id, deleted_at__isnull=True
    ).first()
    if campaign is None:
        raise BusinessRuleError(
            "Campagne introuvable.", field_errors={"campaign": ["Introuvable."]}
        )
    variety = Variety.objects.filter(
        id=variety_id, organization_id=ctx.organization_id, deleted_at__isnull=True
    ).first()
    if variety is None:
        raise BusinessRuleError("Variété introuvable.", field_errors={"variety": ["Introuvable."]})
    plan = ProductionPlan.objects.create(
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        campaign=campaign,
        variety=variety,
        name=name,
        created_by=ctx.user,
        updated_by=ctx.user,
    )
    version = PlanVersion.objects.create(
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        plan=plan,
        number=1,
        origin=origin,
        created_by=ctx.user,
        updated_by=ctx.user,
        planned_start_date=None,
    )
    PlantingSpec.objects.create(plan_version=version)
    _event(ctx, "plan.created", PLAN_ENTITY, plan.id, after={"name": name, "origin": origin})
    _change(ctx, PLAN_ENTITY, plan)
    _change(ctx, VERSION_ENTITY, version)
    return plan


def get_version(ctx: TenantContext, version_id: Any) -> PlanVersion:
    version = PlanVersion.objects.filter(id=version_id, farm_id=ctx.require_farm_id).first()
    if version is None:
        raise NotFoundError()
    return version


def _draft_for_update(
    ctx: TenantContext, version_id: uuid.UUID, expected_version: int | None
) -> PlanVersion:
    ctx.require(EDIT)
    version = (
        PlanVersion.objects.select_for_update()
        .filter(id=version_id, farm_id=ctx.require_farm_id)
        .first()
    )
    if version is None:
        raise NotFoundError()
    if expected_version is not None:
        check_version(version, expected_version)
    if not version.is_draft:
        raise BusinessRuleError("Seul un brouillon est modifiable : créez une nouvelle version.")
    return version


def _touch(ctx: TenantContext, version: PlanVersion) -> None:
    version.version += 1
    version.updated_by = ctx.user
    version.save()
    _change(ctx, VERSION_ENTITY, version)


# Public API for downstream modules (agronomy program, AI drafts) that attach data to a
# plan version: same draft guard and version bump as the plan's own edits.
lock_draft_version = _draft_for_update
touch_version = _touch

# Downstream modules register `hook(source_version, new_draft)` to copy their own data
# when a new version is created (production_plans never imports them).
VERSION_COPY_HOOKS: list[Callable[[PlanVersion, PlanVersion], None]] = []

# Downstream modules register `guard(version) -> list[str]` returning blocking reasons that
# prevent validation (e.g. AI suggestions not yet reviewed by a human, FR-105).
VALIDATION_GUARDS: list[Callable[[PlanVersion], list[str]]] = []


def set_provenance(
    version: PlanVersion,
    field_path: str,
    source_kind: str,
    *,
    user: Any = None,
    item: TechnicalDataItem | None = None,
    calculation: CalculationRecord | None = None,
    ai_suggestion_id: uuid.UUID | None = None,
    note: str = "",
) -> None:
    if source_kind == SK.DOCUMENT and item is None:
        raise BusinessRuleError("Une provenance documentaire doit citer la donnée source.")
    FieldProvenance.objects.update_or_create(
        plan_version=version,
        field_path=field_path,
        defaults={
            "source_kind": source_kind,
            "technical_data_item": item,
            "calculation_result": calculation,
            "ai_suggestion_id": ai_suggestion_id,
            "set_by": user,
            "note": note,
        },
    )


@transaction.atomic
def update_header(
    ctx: TenantContext, *, version_id: uuid.UUID, expected_version: int, changes: dict[str, Any]
) -> PlanVersion:
    version = _draft_for_update(ctx, version_id, expected_version)
    if "technical_data_set" in changes:
        data_set = changes["technical_data_set"]
        if data_set is not None and (
            data_set.variety_id != version.plan.variety_id
            or data_set.status != TechnicalDataSet.Status.VALIDATED
        ):
            raise BusinessRuleError("Le référentiel doit être une version validée de la variété.")
    diff = apply_changes(version, changes)
    if diff:
        version.full_clean(validate_unique=False, validate_constraints=False)
        _check_dates(version)
        for name in diff:
            if name in HEADER_FIELDS:
                set_provenance(version, name, SK.USER_INPUT, user=ctx.user)
        _touch(ctx, version)
    return version


def _check_dates(version: PlanVersion) -> None:
    start, end = version.planned_start_date, version.planned_end_date
    if start and end and end < start:
        raise BusinessRuleError(
            "La date de fin précède la date de début.",
            field_errors={"planned_end_date": ["Avant la date de début."]},
        )


@transaction.atomic
def update_planting_spec(
    ctx: TenantContext,
    *,
    version_id: uuid.UUID,
    expected_version: int,
    changes: dict[str, Any],
    source_kind: str = SK.USER_INPUT,
    ai_suggestion_ids: dict[str, uuid.UUID] | None = None,
) -> PlanVersion:
    version = _draft_for_update(ctx, version_id, expected_version)
    unknown = set(changes) - set(PLANTING_FIELDS)
    if unknown:
        raise BusinessRuleError("Champs inconnus.", field_errors={n: ["Inconnu."] for n in unknown})
    spec = PlantingSpec.objects.select_for_update().get(plan_version=version)
    diff = apply_changes(spec, changes)
    if diff:
        spec.full_clean()
        spec.save()
        for name in diff:
            set_provenance(
                version,
                f"planting_spec.{name}",
                source_kind,
                user=ctx.user,
                ai_suggestion_id=(ai_suggestion_ids or {}).get(name),
            )
        _touch(ctx, version)
    return version


@transaction.atomic
def set_allocations(
    ctx: TenantContext,
    *,
    version_id: uuid.UUID,
    expected_version: int,
    allocations: list[dict[str, Any]],
) -> PlanVersion:
    version = _draft_for_update(ctx, version_id, expected_version)
    seen: set[uuid.UUID] = set()
    rows = []
    for index, data in enumerate(allocations):
        parcel = data["parcel"]
        if (
            parcel.farm_id != ctx.farm_id
            or parcel.deleted_at is not None
            or parcel.status == Parcel.Status.ARCHIVED
        ):
            raise BusinessRuleError(
                "Parcelle introuvable.",
                field_errors={f"allocations.{index}.parcel": ["Introuvable."]},
            )
        if parcel.id in seen:
            raise BusinessRuleError(
                "Parcelle en double.", field_errors={f"allocations.{index}.parcel": ["En double."]}
            )
        seen.add(parcel.id)
        area = data["allocated_area_m2"]
        if area <= 0 or area > parcel.area_m2:
            raise BusinessRuleError(
                "Surface allouée invalide (supérieure à la parcelle ou nulle).",
                field_errors={
                    f"allocations.{index}.allocated_area_m2": [f"Maximum {parcel.area_m2} m²."]
                },
            )
        non_plantable = data.get("non_plantable_area_m2")
        if non_plantable is not None and not (0 <= non_plantable < area):
            raise BusinessRuleError(
                "La surface non plantable doit être inférieure à la surface allouée.",
                field_errors={f"allocations.{index}.non_plantable_area_m2": ["Invalide."]},
            )
        rows.append(PlanAllocation(plan_version=version, **data))
    version.allocations.all().delete()
    PlanAllocation.objects.bulk_create(rows)
    set_provenance(version, "allocations", SK.USER_INPUT, user=ctx.user)
    _touch(ctx, version)
    return version


@transaction.atomic
def set_phases(
    ctx: TenantContext,
    *,
    version_id: uuid.UUID,
    expected_version: int,
    phases: list[dict[str, Any]],
    source_kind: str = SK.USER_INPUT,
) -> PlanVersion:
    version = _draft_for_update(ctx, version_id, expected_version)
    codes = [p["phase_code"] for p in phases]
    invalid = [c for c in codes if not PHASE_CODE_PATTERN.match(c)]
    if invalid or len(codes) != len(set(codes)):
        raise BusinessRuleError(
            "Codes de phase invalides ou en double.",
            field_errors={"phases": invalid or ["Doublon."]},
        )
    version.phases.all().delete()
    PlanPhase.objects.bulk_create(
        [
            PlanPhase(
                plan_version=version,
                phase_code=p["phase_code"],
                sequence=i,
                duration_days=p.get("duration_days"),
            )
            for i, p in enumerate(phases, start=1)
        ]
    )
    for p in phases:
        set_provenance(
            version, f"phases.{p['phase_code']}.duration_days", source_kind, user=ctx.user
        )
    _touch(ctx, version)
    return version


@transaction.atomic
def prefill_from_technical_data(
    ctx: TenantContext, *, version_id: uuid.UUID, expected_version: int
) -> dict[str, Any]:
    """Copy validated reference data into empty fields only; never overwrite user input."""
    version = _draft_for_update(ctx, version_id, expected_version)
    data_set = (
        TechnicalDataSet.objects.filter(
            variety_id=version.plan.variety_id, status=TechnicalDataSet.Status.VALIDATED
        )
        .prefetch_related("items")
        .first()
    )
    if data_set is None:
        raise BusinessRuleError("La variété n'a pas de données techniques validées.")
    items = {item.key: item for item in data_set.items.all()}
    spec = PlantingSpec.objects.select_for_update().get(plan_version=version)
    filled: list[str] = []
    needs_choice: list[str] = []
    for key, field_name in TECHNICAL_TO_PLANTING.items():
        item = items.get(key)
        if item is None or getattr(spec, field_name) is not None:
            continue
        if item.value_numeric is None:
            # A documented range requires a user choice: the system does not pick one.
            needs_choice.append(field_name)
            continue
        value: Any = item.value_numeric
        if field_name in INTEGER_FIELDS:
            if value != value.to_integral_value():
                needs_choice.append(field_name)
                continue
            value = int(value)
        setattr(spec, field_name, value)
        _provenance_from_item(ctx, version, f"planting_spec.{field_name}", item)
        filled.append(field_name)
    spec.full_clean()
    spec.save()

    durations = phase_durations(
        {k: i.value_numeric for k, i in items.items() if i.value_numeric is not None}
    )
    if durations and not version.phases.exists():
        order = {code: i for i, code in enumerate(PHASE_CODES)}
        codes = sorted(durations, key=lambda c: (order.get(c, len(order)), c))
        for sequence, code in enumerate(codes, start=1):
            duration = durations[code]
            PlanPhase.objects.create(
                plan_version=version,
                phase_code=code,
                sequence=sequence,
                duration_days=int(duration) if duration == duration.to_integral_value() else None,
            )
            _provenance_from_item(
                ctx, version, f"phases.{code}.duration_days", items[f"phase.{code}.duration_days"]
            )
            filled.append(f"phases.{code}")
    version.technical_data_set = data_set
    _touch(ctx, version)
    _event(
        ctx,
        "plan_version.prefilled",
        VERSION_ENTITY,
        version.id,
        after={"filled": filled, "data_set": str(data_set.id)},
    )
    return {"filled": filled, "needs_user_choice": needs_choice}


def _provenance_from_item(
    ctx: TenantContext, version: PlanVersion, path: str, item: TechnicalDataItem
) -> None:
    if item.provenance == TechnicalDataItem.Provenance.DOCUMENT:
        set_provenance(version, path, SK.DOCUMENT, user=ctx.user, item=item)
    else:
        set_provenance(
            version,
            path,
            SK.USER_INPUT,
            user=ctx.user,
            note="Valeur du référentiel validé de la variété (saisie utilisateur).",
        )


# --- Calculations ------------------------------------------------------------------


@dataclass
class ComputeOutcome:
    records: list[CalculationRecord] = field(default_factory=list)
    missing: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    totals: dict[str, Any] = field(default_factory=dict)
    task_proposals: list[Any] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.missing and not self.errors

    def to_dict(self) -> dict[str, Any]:
        from apps.production_plans.serializers import CalculationRecordSerializer

        return {
            "complete": self.complete,
            "missing": self.missing,
            "errors": self.errors,
            "totals": self.totals,
            "results": CalculationRecordSerializer(self.records, many=True).data,
        }


def _store(
    ctx: TenantContext, version: PlanVersion, result: CalculationResult, scope: str
) -> CalculationRecord:
    data = result.to_dict()
    return CalculationRecord.objects.create(
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        plan_version=version,
        calc_type=result.calc_type,
        engine_version=result.engine_version,
        scope=scope,
        inputs=data["inputs"],
        outputs=data["outputs"],
        formula=result.formula,
        assumptions=data["assumptions"],
        warnings=data["warnings"],
        details=data["details"],
        computed_by=ctx.user,
    )


def _run(outcome: ComputeOutcome, scope: str, fn: Any, *args: Any) -> Any:
    try:
        return fn(*args)
    except MissingInputError as exc:
        outcome.missing.append({"scope": scope, "fields": exc.fields, "reason": exc.reason})
    except InvalidInputError as exc:
        outcome.errors.append({"scope": scope, "field": exc.field, "reason": exc.reason})
    return None


def _compute(ctx: TenantContext, version: PlanVersion) -> ComputeOutcome:
    """Run all engine calculations for a version and store the records (draft only)."""
    outcome = ComputeOutcome()
    version.calculations.all().delete()
    spec = version.planting_spec
    allocations = list(version.allocations.select_related("parcel"))
    if not allocations:
        outcome.missing.append({"scope": "plan", "fields": ["allocations"], "reason": ""})
    total_plants, total_seeds, total_mass = 0, 0, Decimal(0)
    total_area, total_plantable = Decimal(0), Decimal(0)
    for allocation in allocations:
        scope = f"parcel:{allocation.parcel_id}"
        planting = _run(
            outcome,
            scope,
            compute_planting,
            PlantingInput(
                row_spacing_m=spec.row_spacing_m,
                plant_spacing_m=spec.plant_spacing_m,
                plants_per_hole=spec.plants_per_hole,
                allocated_area_m2=allocation.allocated_area_m2,
                non_plantable_area_m2=allocation.non_plantable_area_m2,
                layout=spec.layout,
                plot_length_m=allocation.plot_length_m,
                plot_width_m=allocation.plot_width_m,
                headland_m=spec.headland_m,
                bed_width_m=spec.bed_width_m,
                path_width_m=spec.path_width_m,
                rows_per_bed=spec.rows_per_bed,
            ),
        )
        if planting is None:
            continue
        outcome.records.append(_store(ctx, version, planting, scope))
        plants = planting.output("plant_count")
        total_plants += plants
        total_area += allocation.allocated_area_m2
        total_plantable += planting.output("plantable_area_m2")
        if not spec.planting_method:
            outcome.missing.append({"scope": scope, "fields": ["planting_method"], "reason": ""})
            continue
        seeds = _run(
            outcome,
            scope,
            compute_seeds,
            SeedInput(
                plant_count=plants,
                plants_per_hole=spec.plants_per_hole,
                seeds_per_hole=spec.seeds_per_hole,
                germination_rate=spec.germination_rate,
                safety_margin_rate=spec.safety_margin_rate,
                planting_method=spec.planting_method,
                nursery_success_rate=spec.nursery_success_rate,
                seeds_per_gram=spec.seeds_per_gram,
                thousand_seed_weight_g=spec.thousand_seed_weight_g,
                seed_package_size_g=spec.seed_package_size_g,
            ),
        )
        if seeds is not None:
            outcome.records.append(_store(ctx, version, seeds, scope))
            total_seeds += seeds.output("seed_count")
            total_mass += seeds.output("seed_mass_g")

    phases = list(version.phases.all())
    if not phases:
        outcome.missing.append({"scope": "calendar", "fields": ["phases"], "reason": ""})
    else:
        calendar = _run(
            outcome,
            "calendar",
            compute_calendar,
            CalendarInput(
                start_date=version.planned_start_date,
                phases=[PhaseSpec(p.phase_code, p.duration_days) for p in phases],
            ),
        )
        if calendar is not None:
            result, dated, proposals = calendar
            outcome.records.append(_store(ctx, version, result, "calendar"))
            outcome.task_proposals = proposals
            by_code = {d.code: d for d in dated}
            for phase in phases:
                d = by_code[phase.phase_code]
                PlanPhase.objects.filter(id=phase.id).update(
                    start_date=d.start_date, end_date=d.end_date
                )
            outcome.totals["cycle_end_date"] = result.output("cycle_end_date")

    if allocations:
        outcome.totals.update(
            allocated_area_m2=str(total_area),
            plantable_area_m2=str(total_plantable),
            plant_count=total_plants,
            seed_count=total_seeds,
            seed_mass_g=str(total_mass),
        )
    for record in outcome.records:
        set_provenance(
            version,
            f"results.{record.calc_type}.{record.scope}",
            SK.CALCULATION,
            user=ctx.user,
            calculation=record,
        )
    version.engine_version = ENGINE_VERSION
    return outcome


@transaction.atomic
def compute_version(ctx: TenantContext, *, version_id: uuid.UUID) -> ComputeOutcome:
    version = _draft_for_update(ctx, version_id, None)
    outcome = _compute(ctx, version)
    _touch(ctx, version)
    return outcome


# --- Validation and versions --------------------------------------------------------


def _book_cycles(ctx: TenantContext, version: PlanVersion, start: Any, end: Any) -> None:
    """Create or update the plan's crop cycles, enforcing parcel capacity (Q1)."""
    plan = version.plan
    allocated_parcels = set()
    for allocation in version.allocations.all():
        parcel = Parcel.objects.select_for_update().get(id=allocation.parcel_id)
        allocated_parcels.add(parcel.id)
        overlapping = CropCycle.objects.filter(
            parcel=parcel, start_date__lte=end, end_date__gte=start
        ).exclude(status=CropCycle.Status.CANCELLED).exclude(plan=plan).aggregate(
            total=Sum("area_m2")
        )["total"] or Decimal(0)
        if overlapping + allocation.allocated_area_m2 > parcel.area_m2:
            raise BusinessRuleError(
                f"La parcelle {parcel.code} est déjà occupée sur cette période.",
                details={
                    "parcel": str(parcel.id),
                    "occupied_m2": str(overlapping),
                    "requested_m2": str(allocation.allocated_area_m2),
                    "parcel_area_m2": str(parcel.area_m2),
                },
            )
        cycle = CropCycle.objects.select_for_update().filter(plan=plan, parcel=parcel).first()
        if cycle is None:
            cycle = CropCycle(
                organization_id=ctx.organization_id,
                farm_id=ctx.require_farm_id,
                plan=plan,
                parcel=parcel,
                plan_version=version,
                area_m2=allocation.allocated_area_m2,
                start_date=start,
                end_date=end,
            )
        else:
            cycle.plan_version = version
            cycle.area_m2 = allocation.allocated_area_m2
            cycle.start_date, cycle.end_date = start, end
            cycle.version += 1
            if cycle.status == CropCycle.Status.CANCELLED:
                cycle.status = CropCycle.Status.PLANNED
        cycle.save()
        _change(ctx, CYCLE_ENTITY, cycle)
    for cycle in CropCycle.objects.filter(plan=plan, status=CropCycle.Status.PLANNED).exclude(
        parcel_id__in=allocated_parcels
    ):
        cycle.status = CropCycle.Status.CANCELLED
        cycle.version += 1
        cycle.save()
        _change(ctx, CYCLE_ENTITY, cycle)


@transaction.atomic
def validate_version(
    ctx: TenantContext, *, version_id: uuid.UUID, expected_version: int
) -> PlanVersion:
    """Explicit human validation (FR-035). Recomputes and checks completeness first."""
    ctx.require(VALIDATE)
    version = _draft_for_update(ctx, version_id, expected_version)
    plan = ProductionPlan.objects.select_for_update().get(id=version.plan_id)
    if plan.status in {ProductionPlan.Status.CLOSED, ProductionPlan.Status.CANCELLED}:
        raise BusinessRuleError("Le plan est clôturé ou annulé.")
    blocking = [reason for guard in VALIDATION_GUARDS for reason in guard(version)]
    if blocking:
        raise BusinessRuleError("Validation impossible.", details={"blocking": blocking})
    outcome = _compute(ctx, version)
    if not outcome.complete:
        raise BusinessRuleError(
            "Le plan est incomplet : complétez les données manquantes avant validation.",
            details={"missing": outcome.missing, "errors": outcome.errors},
        )
    if version.planned_start_date is None:
        raise BusinessRuleError("Date de début manquante.")
    cycle_end = outcome.totals["cycle_end_date"]
    if version.planned_end_date is None:
        from datetime import date

        version.planned_end_date = date.fromisoformat(cycle_end)
    _check_dates(version)
    _book_cycles(ctx, version, version.planned_start_date, version.planned_end_date)

    previous = PlanVersion.objects.filter(plan=plan, status=PlanVersion.Status.VALIDATED).first()
    if previous is not None:
        previous.status = PlanVersion.Status.SUPERSEDED
        previous.version += 1
        previous.save()
        _change(ctx, VERSION_ENTITY, previous)
    version.status = PlanVersion.Status.VALIDATED
    version.validated_by = ctx.user
    version.validated_at = timezone.now()
    _touch(ctx, version)
    plan.current_version = version
    if plan.status == ProductionPlan.Status.DRAFT:
        plan.status = ProductionPlan.Status.VALIDATED
    plan.version += 1
    plan.save()
    _change(ctx, PLAN_ENTITY, plan)
    _event(
        ctx,
        "plan_version.validated",
        VERSION_ENTITY,
        version.id,
        after={
            "plan": str(plan.id),
            "number": version.number,
            "superseded": str(previous.id) if previous else None,
        },
    )
    return version


@transaction.atomic
def create_new_version(
    ctx: TenantContext,
    *,
    plan_id: uuid.UUID,
    based_on_id: uuid.UUID | None = None,
    change_note: str = "",
    origin: str = PlanVersion.Origin.COPY,
) -> PlanVersion:
    """Start a new draft from an existing version (FR-034, FR-064)."""
    ctx.require(EDIT)
    plan = (
        ProductionPlan.objects.select_for_update()
        .filter(id=plan_id, farm_id=ctx.require_farm_id)
        .first()
    )
    if plan is None:
        raise NotFoundError()
    if plan.versions.filter(status=PlanVersion.Status.DRAFT).exists():
        raise BusinessRuleError("Un brouillon est déjà en cours pour ce plan.")
    source = (
        plan.versions.filter(id=based_on_id).first()
        if based_on_id
        else plan.current_version or plan.versions.order_by("-number").first()
    )
    if source is None:
        raise BusinessRuleError("Version de base introuvable.")
    number = (plan.versions.aggregate(m=Max("number"))["m"] or 0) + 1
    draft = PlanVersion.objects.create(
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        plan=plan,
        number=number,
        origin=origin,
        based_on=source,
        technical_data_set=source.technical_data_set,
        **{name: getattr(source, name) for name in HEADER_FIELDS if name != "change_note"},
        change_note=change_note,
        created_by=ctx.user,
        updated_by=ctx.user,
    )
    source_spec = source.planting_spec
    PlantingSpec.objects.create(
        plan_version=draft, **{name: getattr(source_spec, name) for name in PLANTING_FIELDS}
    )
    PlanAllocation.objects.bulk_create(
        [
            PlanAllocation(
                plan_version=draft,
                parcel_id=a.parcel_id,
                allocated_area_m2=a.allocated_area_m2,
                non_plantable_area_m2=a.non_plantable_area_m2,
                plot_length_m=a.plot_length_m,
                plot_width_m=a.plot_width_m,
                notes=a.notes,
            )
            for a in source.allocations.all()
        ]
    )
    PlanPhase.objects.bulk_create(
        [
            PlanPhase(
                plan_version=draft,
                phase_code=p.phase_code,
                sequence=p.sequence,
                duration_days=p.duration_days,
            )
            for p in source.phases.all()
        ]
    )
    FieldProvenance.objects.bulk_create(
        [
            FieldProvenance(
                plan_version=draft,
                field_path=p.field_path,
                source_kind=p.source_kind,
                technical_data_item_id=p.technical_data_item_id,
                ai_suggestion_id=p.ai_suggestion_id,
                set_by_id=p.set_by_id,
                note=p.note,
            )
            for p in source.provenances.exclude(source_kind=SK.CALCULATION)
        ]
    )
    for hook in VERSION_COPY_HOOKS:
        hook(source, draft)
    _event(
        ctx,
        "plan_version.created",
        VERSION_ENTITY,
        draft.id,
        after={"number": number, "based_on": str(source.id)},
    )
    _change(ctx, VERSION_ENTITY, draft)
    return draft


def _snapshot(version: PlanVersion) -> dict[str, Any]:
    spec = version.planting_spec
    totals: dict[str, Any] = {}
    for record in version.calculations.all():
        for name in ("plant_count", "seed_count"):
            if name in record.outputs:
                totals[name] = totals.get(name, 0) + record.outputs[name]["value"]
    return {
        "header": {name: getattr(version, name) for name in HEADER_FIELDS},
        "planting_spec": {name: getattr(spec, name) for name in PLANTING_FIELDS},
        "allocations": {
            str(a.parcel_id): {
                "allocated_area_m2": a.allocated_area_m2,
                "non_plantable_area_m2": a.non_plantable_area_m2,
            }
            for a in version.allocations.all()
        },
        "phases": {p.phase_code: p.duration_days for p in version.phases.all()},
        "results": totals,
    }


def compare_versions(ctx: TenantContext, *, version_a_id: Any, version_b_id: Any) -> dict[str, Any]:
    """Compare the assumptions of two versions of the same plan (FR-034)."""
    ctx.require(VIEW)
    a, b = get_version(ctx, version_a_id), get_version(ctx, version_b_id)
    if a.plan_id != b.plan_id:
        raise BusinessRuleError("Les deux versions doivent appartenir au même plan.")
    left, right = _snapshot(a), _snapshot(b)
    differences: list[dict[str, Any]] = []
    for section in left:
        keys = sorted(set(left[section]) | set(right[section]))
        for key in keys:
            before, after = left[section].get(key), right[section].get(key)
            if before != after:
                differences.append({"section": section, "field": key, "from": before, "to": after})
    return {"from_version": a.number, "to_version": b.number, "differences": differences}
