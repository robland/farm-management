"""Harvest services and campaign results (FR-090..092).

Costs and revenues of a crop cycle come from VALIDATED transactions linked to
it, plus a share of the plan-level transactions prorated by allocated area
(OPEN_QUESTIONS Q21). Only the farm currency is consolidated.
"""

import uuid
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from agronomy_engine.errors import MissingInputError
from agronomy_engine.yield_ import HarvestLine, YieldInput, compute_yield, to_kg
from apps.audit.services import record_event
from apps.core.exceptions import BusinessRuleError, IdentifierConflictError, NotFoundError
from apps.core.tenancy import TenantContext
from apps.farms.models import Farm
from apps.finance.models import FinancialTransaction
from apps.harvest.models import HarvestRecord, UnitConversion
from apps.production_plans.models import CropCycle
from apps.synchronization.services import record_change
from apps.tasks.models import InputConsumption

VIEW, RECORD = "harvest.view", "harvest.record"
HARVEST_ENTITY = "harvest.harvest_record"


@transaction.atomic
def set_unit_conversion(ctx: TenantContext, *, data: dict[str, Any]) -> UnitConversion:
    ctx.require(RECORD)
    crop = data["crop"]
    if crop.organization_id not in {None, ctx.organization_id}:
        raise BusinessRuleError("Culture introuvable.", field_errors={"crop": ["Introuvable."]})
    conversion, created = UnitConversion.objects.select_for_update().get_or_create(
        farm_id=ctx.require_farm_id,
        crop=crop,
        unit=data["unit"],
        defaults={
            "organization_id": ctx.organization_id,
            "kg_per_unit": data["kg_per_unit"],
            "measured_on": data["measured_on"],
            "notes": data.get("notes", ""),
        },
    )
    if not created:
        conversion.kg_per_unit = data["kg_per_unit"]
        conversion.measured_on = data["measured_on"]
        conversion.notes = data.get("notes", conversion.notes)
        conversion.version += 1
        conversion.save()
    record_event(
        action="unit_conversion.set",
        actor=ctx.user,
        organization_id=ctx.organization_id,
        farm_id=ctx.farm_id,
        entity_type="harvest.unit_conversion",
        entity_id=conversion.id,
        after={"unit": conversion.unit, "kg_per_unit": str(conversion.kg_per_unit)},
    )
    return conversion


@transaction.atomic
def record_harvest(
    ctx: TenantContext, *, data: dict[str, Any], origin_op_id: uuid.UUID | None = None
) -> tuple[HarvestRecord, bool]:
    """Append-only, idempotent on the client id. Converts to kg with a measured factor."""
    ctx.require(RECORD)
    data = dict(data)
    record_id = data.get("id")
    if record_id is not None:
        existing = HarvestRecord.objects.filter(id=record_id).first()
        if existing is not None:
            if existing.farm_id != ctx.farm_id:
                raise IdentifierConflictError("Identifiant déjà utilisé.")
            return existing, False
    if data["quantity"] <= 0:
        raise BusinessRuleError(
            "La quantité doit être positive.", field_errors={"quantity": ["> 0"]}
        )
    if data.get("loss_quantity_kg", 0) < 0:
        raise BusinessRuleError(
            "Les pertes ne peuvent pas être négatives.", field_errors={"loss_quantity_kg": [">= 0"]}
        )
    cycle: CropCycle = data["crop_cycle"]
    if cycle.farm_id != ctx.farm_id or cycle.status == CropCycle.Status.CANCELLED:
        raise BusinessRuleError(
            "Cycle cultural introuvable ou annulé.", field_errors={"crop_cycle": ["Introuvable."]}
        )
    if data["harvested_on"] < cycle.start_date:
        raise BusinessRuleError(
            "Récolte antérieure au début du cycle.",
            field_errors={"harvested_on": ["Avant le début du cycle."]},
        )
    crop_id = cycle.plan.variety.crop_id
    conversion = UnitConversion.objects.filter(
        farm_id=ctx.require_farm_id, crop_id=crop_id, unit=data["unit"]
    ).first()
    try:
        quantity_kg, factor = to_kg(
            data["quantity"], data["unit"], conversion.kg_per_unit if conversion else None
        )
    except MissingInputError as exc:
        raise BusinessRuleError(
            f"Aucun poids mesuré pour l'unité « {data['unit']} » : enregistrez d'abord la "
            "conversion (kg par unité).",
            field_errors={"unit": exc.fields},
        ) from exc
    responsible = data.pop("responsible", None) or ctx.user
    record = HarvestRecord.objects.create(
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        parcel=cycle.parcel,
        quantity_kg=quantity_kg,
        conversion_factor_used=factor,
        responsible=responsible,
        **data,
    )
    record_change(
        farm_id=ctx.require_farm_id,
        entity_type=HARVEST_ENTITY,
        entity_id=record.id,
        entity_version=record.version,
        required_permission=VIEW,
        origin_op_id=origin_op_id,
    )
    return record, True


@transaction.atomic
def void_harvest(ctx: TenantContext, *, record_id: uuid.UUID, reason: str) -> HarvestRecord:
    """Mark an erroneous record as void (kept for traceability, excluded from results)."""
    ctx.require("farm.manage")
    record = (
        HarvestRecord.objects.select_for_update()
        .filter(id=record_id, farm_id=ctx.require_farm_id)
        .first()
    )
    if record is None:
        raise NotFoundError()
    if record.voided_at is not None:
        return record
    if not reason.strip():
        raise BusinessRuleError("Motif obligatoire.", field_errors={"reason": ["Obligatoire."]})
    record.voided_at = timezone.now()
    record.voided_by = ctx.user
    record.void_reason = reason
    record.version += 1
    record.save()
    record_event(
        action="harvest.voided",
        actor=ctx.user,
        organization_id=ctx.organization_id,
        farm_id=ctx.farm_id,
        entity_type=HARVEST_ENTITY,
        entity_id=record.id,
        after={"reason": reason},
    )
    record_change(
        farm_id=ctx.require_farm_id,
        entity_type=HARVEST_ENTITY,
        entity_id=record.id,
        entity_version=record.version,
        required_permission=VIEW,
    )
    return record


def _money_for_cycle(cycle: CropCycle, kind: str, currency: str) -> Decimal:
    """Validated income or campaign expenses of a cycle. Fundings, repayments and transfers
    are other kinds; investment expenses (machines, irrigation) are excluded (Q35)."""
    validated = FinancialTransaction.objects.filter(
        farm_id=cycle.farm_id,
        kind=kind,
        status=FinancialTransaction.Status.VALIDATED,
        currency=currency,
    ).exclude(category__is_capex=True)
    direct = validated.filter(crop_cycle=cycle).aggregate(s=Sum("amount"))["s"] or Decimal(0)
    plan_level = validated.filter(plan_id=cycle.plan_id, crop_cycle__isnull=True).aggregate(
        s=Sum("amount")
    )["s"] or Decimal(0)
    if plan_level:
        plan_area = (
            CropCycle.objects.filter(plan_id=cycle.plan_id)
            .exclude(status=CropCycle.Status.CANCELLED)
            .aggregate(s=Sum("area_m2"))["s"]
        )
        if plan_area:
            direct += plan_level * cycle.area_m2 / plan_area
    return direct


def cycle_results(ctx: TenantContext, *, cycle_id: Any) -> dict[str, Any]:
    """Objectives vs results of a crop cycle (FR-092)."""
    ctx.require(VIEW)
    cycle = (
        CropCycle.objects.filter(id=cycle_id, farm_id=ctx.require_farm_id)
        .select_related("plan_version", "parcel", "plan__variety")
        .first()
    )
    if cycle is None:
        raise NotFoundError()
    currency = Farm.objects.get(id=ctx.require_farm_id).currency
    records = HarvestRecord.objects.filter(crop_cycle=cycle, voided_at__isnull=True)
    show_money = ctx.has_perm("finance.view")
    costs = (
        _money_for_cycle(cycle, FinancialTransaction.Kind.EXPENSE, currency) if show_money else None
    )
    revenues = (
        _money_for_cycle(cycle, FinancialTransaction.Kind.INCOME, currency) if show_money else None
    )
    result = compute_yield(
        YieldInput(
            harvested_area_m2=cycle.area_m2,
            harvests=[
                HarvestLine(
                    r.quantity_kg,
                    r.loss_quantity_kg,
                    r.quality_grade != HarvestRecord.Grade.REJECTED,
                )
                for r in records
            ],
            target_yield_kg_per_ha=cycle.plan_version.target_yield_kg_per_ha,
            total_cost=costs,
            cost_currency=currency,
        )
    )
    consumptions = (
        InputConsumption.objects.filter(report__task__crop_cycle=cycle)
        .values("product__name", "base_unit")
        .annotate(total=Sum("quantity_base"))
        .order_by("product__name")
    )
    finance: dict[str, Any] | None = None
    if show_money:
        assert costs is not None and revenues is not None  # noqa: S101 - both set together
        finance = {
            "currency": currency,
            "costs": costs,
            "revenues": revenues,
            "margin": revenues - costs,
            "note": "Transactions validées liées au cycle + part au prorata de la surface "
            "des transactions rattachées au plan.",
        }
    return {
        "crop_cycle": str(cycle.id),
        "parcel": cycle.parcel.code,
        "variety": cycle.plan.variety.name,
        "area_m2": cycle.area_m2,
        "period": {"start": cycle.start_date, "end": cycle.end_date},
        "yield": result.to_dict(),
        "input_consumptions": [
            {"product": c["product__name"], "unit": c["base_unit"], "quantity": c["total"]}
            for c in consumptions
        ],
        "finance": finance,
    }


def campaign_results(ctx: TenantContext, *, campaign_id: Any) -> list[dict[str, Any]]:
    ctx.require(VIEW)
    cycles = CropCycle.objects.filter(
        farm_id=ctx.require_farm_id, plan__campaign_id=campaign_id
    ).exclude(status=CropCycle.Status.CANCELLED)
    return [cycle_results(ctx, cycle_id=cycle.id) for cycle in cycles]
