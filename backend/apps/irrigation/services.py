"""Irrigation design, BOM and quote services (FR-040..043)."""

import uuid
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from agronomy_engine.errors import InvalidInputError, MissingInputError
from agronomy_engine.irrigation.bom import BomInput, compute_bom
from agronomy_engine.irrigation.drip import DripInput, PipeSegment, compute_drip
from agronomy_engine.irrigation.sprinkler import SprinklerInput, compute_sprinkler
from agronomy_engine.quotation import QuoteInput, QuoteLineInput, compute_quote
from apps.audit.services import record_event
from apps.core.exceptions import BusinessRuleError, NotFoundError
from apps.core.money import check_amount_precision, currency_exponent
from apps.core.tenancy import TenantContext
from apps.core.versioning import apply_changes, check_version
from apps.farms.models import Farm
from apps.inventory.models import PriceList, PriceListItem
from apps.irrigation.models import BomLine, IrrigationDesign, Quote, QuoteLine
from apps.production_plans.models import CalculationRecord

VIEW = "irrigation.view"
EDIT = "irrigation.edit"
DS = IrrigationDesign.SystemType


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


def _scope(design: IrrigationDesign) -> str:
    return f"irrigation_design:{design.id}"


def _dec(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


# --- Designs -------------------------------------------------------------------------


def _check_links(ctx: TenantContext, data: dict[str, Any]) -> None:
    parcel = data.get("parcel")
    if parcel is not None and (parcel.farm_id != ctx.farm_id or parcel.deleted_at is not None):
        raise BusinessRuleError("Parcelle introuvable.", field_errors={"parcel": ["Introuvable."]})
    version = data.get("plan_version")
    if version is not None and version.farm_id != ctx.farm_id:
        raise BusinessRuleError(
            "Plan introuvable.", field_errors={"plan_version": ["Introuvable."]}
        )


@transaction.atomic
def create_design(ctx: TenantContext, *, data: dict[str, Any]) -> IrrigationDesign:
    ctx.require(EDIT)
    _check_links(ctx, data)
    parcel = data["parcel"]
    number = (
        IrrigationDesign.objects.filter(parcel=parcel).aggregate(m=Max("number"))["m"] or 0
    ) + 1
    design = IrrigationDesign.objects.create(
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        number=number,
        created_by=ctx.user,
        updated_by=ctx.user,
        **data,
    )
    _event(
        ctx,
        "irrigation_design.created",
        "irrigation.design",
        design.id,
        after={"system_type": design.system_type, "number": number},
    )
    return design


def _draft(
    ctx: TenantContext, design_id: uuid.UUID, expected_version: int | None = None
) -> IrrigationDesign:
    ctx.require(EDIT)
    design = (
        IrrigationDesign.objects.select_for_update()
        .filter(id=design_id, farm_id=ctx.require_farm_id)
        .first()
    )
    if design is None:
        raise NotFoundError()
    if expected_version is not None:
        check_version(design, expected_version)
    if not design.is_draft:
        raise BusinessRuleError(
            "Un dimensionnement validé est immuable : créez une nouvelle version."
        )
    return design


def _touch(ctx: TenantContext, design: IrrigationDesign) -> None:
    design.version += 1
    design.updated_by = ctx.user
    design.save()


@transaction.atomic
def update_design(
    ctx: TenantContext, *, design_id: uuid.UUID, expected_version: int, changes: dict[str, Any]
) -> IrrigationDesign:
    design = _draft(ctx, design_id, expected_version)
    _check_links(ctx, changes)
    if apply_changes(design, changes):
        _touch(ctx, design)
    return design


def _segments(params: dict[str, Any]) -> list[PipeSegment]:
    return [
        PipeSegment(
            role=s["role"],
            length_m=Decimal(str(s["length_m"])),
            inner_diameter_mm=Decimal(str(s["inner_diameter_mm"])),
            hazen_williams_c=Decimal(str(s["hazen_williams_c"])),
            outlets=s.get("outlets"),
        )
        for s in params.get("segments") or []
    ]


def _store(ctx: TenantContext, design: IrrigationDesign, result: Any) -> CalculationRecord:
    data = result.to_dict()
    return CalculationRecord.objects.create(
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        plan_version=design.plan_version,
        calc_type=result.calc_type,
        engine_version=result.engine_version,
        scope=_scope(design),
        inputs=data["inputs"],
        outputs=data["outputs"],
        formula=result.formula,
        assumptions=data["assumptions"],
        warnings=data["warnings"],
        details=data["details"],
        computed_by=ctx.user,
    )


def _run_design(ctx: TenantContext, design: IrrigationDesign) -> dict[str, Any]:
    CalculationRecord.objects.filter(farm_id=ctx.require_farm_id, scope=_scope(design)).delete()
    params = design.parameters or {}
    missing: list[str] = []
    errors: list[dict[str, str]] = []
    records: list[CalculationRecord] = []
    bom_proposals: list[Any] = []
    try:
        if design.system_type == DS.DRIP:
            hydraulic = compute_drip(
                DripInput(
                    lateral_count=params.get("lateral_count"),
                    **{
                        name: _dec(params.get(name))
                        for name in (
                            "lateral_length_m",
                            "lateral_spacing_m",
                            "emitter_spacing_m",
                            "emitter_flow_lph",
                            "operating_pressure_bar",
                            "irrigated_area_m2",
                            "et0_mm_per_day",
                            "kc",
                            "application_efficiency_rate",
                            "source_max_flow_m3h",
                            "max_irrigation_hours_per_day",
                            "static_lift_m",
                            "elevation_difference_m",
                            "filter_head_loss_m",
                            "fittings_loss_rate",
                            "pump_efficiency_rate",
                        )
                    },
                    sector_count=params.get("sector_count"),
                    segments=_segments(params),
                )
            )
            records.append(_store(ctx, design, hydraulic))
            bom_params = design.bom_parameters or {}
            bom_result, bom_proposals = compute_bom(
                BomInput(
                    lateral_count=params["lateral_count"],
                    lateral_length_m=Decimal(str(params["lateral_length_m"])),
                    emitter_count=hydraulic.output("emitter_count"),
                    sector_count=hydraulic.output("sector_count"),
                    installation_waste_rate=_dec(bom_params.get("installation_waste_rate")),
                    emitters_integrated=bom_params.get("emitters_integrated", True),
                    dripline_roll_length_m=_dec(bom_params.get("dripline_roll_length_m")),
                    segments=_segments(params),
                    filter_count=bom_params.get("filter_count", 0),
                    pressure_regulator_count=bom_params.get("pressure_regulator_count", 0),
                    include_pump=bom_params.get("include_pump", False),
                    include_fertilizer_injector=bom_params.get(
                        "include_fertilizer_injector", False
                    ),
                )
            )
            records.append(_store(ctx, design, bom_result))
        elif design.system_type in {DS.SPRINKLER, DS.MICRO_SPRINKLER}:
            records.append(
                _store(
                    ctx,
                    design,
                    compute_sprinkler(
                        SprinklerInput(
                            sprinkler_count=params.get("sprinkler_count"),
                            sprinkler_flow_lph=_dec(params.get("sprinkler_flow_lph")),
                            spacing_along_m=_dec(params.get("spacing_along_m")),
                            spacing_between_m=_dec(params.get("spacing_between_m")),
                            sector_count=params.get("sector_count"),
                        )
                    ),
                )
            )
    except MissingInputError as exc:
        missing = exc.fields
    except InvalidInputError as exc:
        errors.append({"field": exc.field, "reason": exc.reason})

    if bom_proposals:
        # Keep manual lines and the catalogue links chosen by the user.
        links = {
            (line.component_type, line.description): line.catalog_item_id
            for line in design.bom_lines.filter(is_manual=False)
        }
        manual = list(design.bom_lines.filter(is_manual=True).order_by("sequence"))
        design.bom_lines.filter(is_manual=False).delete()
        BomLine.objects.bulk_create(
            [
                BomLine(
                    design=design,
                    sequence=index,
                    component_type=p.component_type,
                    description=p.description,
                    quantity=p.quantity,
                    unit=p.unit,
                    rationale=p.rationale,
                    spec=p.spec,
                    catalog_item_id=links.get((p.component_type, p.description)),
                )
                for index, p in enumerate(bom_proposals, start=1)
            ]
        )
        for offset, line in enumerate(manual, start=len(bom_proposals) + 1):
            line.sequence = offset
            line.save(update_fields=["sequence"])
    from apps.production_plans.serializers import CalculationRecordSerializer

    return {
        "complete": not missing and not errors,
        "missing": missing,
        "errors": errors,
        "results": CalculationRecordSerializer(records, many=True).data,
    }


@transaction.atomic
def compute_design(ctx: TenantContext, *, design_id: uuid.UUID) -> dict[str, Any]:
    design = _draft(ctx, design_id)
    outcome = _run_design(ctx, design)
    _touch(ctx, design)
    return outcome


@transaction.atomic
def validate_design(
    ctx: TenantContext, *, design_id: uuid.UUID, expected_version: int
) -> IrrigationDesign:
    design = _draft(ctx, design_id, expected_version)
    if design.system_type != DS.OTHER:
        outcome = _run_design(ctx, design)
        if not outcome["complete"]:
            raise BusinessRuleError(
                "Dimensionnement incomplet.",
                details={"missing": outcome["missing"], "errors": outcome["errors"]},
            )
    IrrigationDesign.objects.filter(
        parcel=design.parcel,
        plan_version=design.plan_version,
        status=IrrigationDesign.Status.VALIDATED,
    ).update(status=IrrigationDesign.Status.SUPERSEDED)
    design.status = IrrigationDesign.Status.VALIDATED
    design.validated_by = ctx.user
    design.validated_at = timezone.now()
    _touch(ctx, design)
    _event(ctx, "irrigation_design.validated", "irrigation.design", design.id)
    return design


@transaction.atomic
def new_design_version(ctx: TenantContext, *, design_id: uuid.UUID) -> IrrigationDesign:
    ctx.require(EDIT)
    source = IrrigationDesign.objects.filter(id=design_id, farm_id=ctx.require_farm_id).first()
    if source is None:
        raise NotFoundError()
    draft = create_design(
        ctx,
        data={
            "parcel": source.parcel,
            "plan_version": source.plan_version,
            "name": source.name,
            "system_type": source.system_type,
            "parameters": source.parameters,
            "bom_parameters": source.bom_parameters,
            "based_on": source,
        },
    )
    BomLine.objects.bulk_create(
        [
            BomLine(
                design=draft,
                sequence=line.sequence,
                component_type=line.component_type,
                description=line.description,
                quantity=line.quantity,
                unit=line.unit,
                rationale=line.rationale,
                spec=line.spec,
                catalog_item_id=line.catalog_item_id,
                is_manual=line.is_manual,
            )
            for line in source.bom_lines.all()
        ]
    )
    return draft


@transaction.atomic
def add_manual_bom_line(
    ctx: TenantContext, *, design_id: uuid.UUID, data: dict[str, Any]
) -> BomLine:
    design = _draft(ctx, design_id)
    sequence = (design.bom_lines.aggregate(m=Max("sequence"))["m"] or 0) + 1
    line = BomLine.objects.create(
        design=design,
        sequence=sequence,
        is_manual=True,
        rationale=data.pop("rationale", "") or "Ajout manuel",
        **data,
    )
    _touch(ctx, design)
    return line


@transaction.atomic
def link_bom_line(
    ctx: TenantContext, *, design_id: uuid.UUID, bom_line_id: uuid.UUID, catalog_item: Any
) -> BomLine:
    design = _draft(ctx, design_id)
    line = design.bom_lines.filter(id=bom_line_id).first()
    if line is None:
        raise NotFoundError()
    line.catalog_item = catalog_item
    line.save(update_fields=["catalog_item"])
    _touch(ctx, design)
    return line


# --- Quotes --------------------------------------------------------------------------


def _recompute_totals(quote: Quote) -> None:
    lines = list(quote.lines.all())
    result, totals = compute_quote(
        QuoteInput(
            currency=quote.currency,
            currency_exponent=currency_exponent(quote.currency),
            lines=[
                QuoteLineInput(str(line.id), line.description, line.quantity, line.unit_price)
                for line in lines
            ],
            discount_amount=quote.discount_amount,
            tax_rate=quote.tax_rate,
        )
    )
    for line in lines:
        line.line_total = totals[str(line.id)]
        line.save(update_fields=["line_total"])
    quote.subtotal = result.output("subtotal")
    quote.tax_amount = result.output("tax_amount")
    quote.total = result.output("total")
    quote.assumptions = result.assumptions
    quote.warnings = result.warnings


@transaction.atomic
def create_quote(
    ctx: TenantContext,
    *,
    design_id: uuid.UUID,
    price_list: PriceList | None,
    currency: str | None,
    notes: str = "",
) -> Quote:
    """Copy the BOM and the applicable unit prices into a new draft quote (FR-043)."""
    ctx.require(EDIT)
    design = IrrigationDesign.objects.filter(id=design_id, farm_id=ctx.require_farm_id).first()
    if design is None:
        raise NotFoundError()
    bom = list(design.bom_lines.all())
    if not bom:
        raise BusinessRuleError("La nomenclature est vide : calculez le dimensionnement.")
    if price_list is not None and price_list.status != PriceList.Status.ACTIVE:
        raise BusinessRuleError("La liste de prix doit être active.")
    quote_currency = (
        price_list.currency
        if price_list
        else (currency or Farm.objects.get(id=ctx.require_farm_id).currency)
    )
    currency_exponent(quote_currency)
    prices: dict[tuple[Any, str], Decimal] = {}
    if price_list is not None:
        prices = {
            (item.catalog_item_id, item.unit): item.unit_price
            for item in PriceListItem.objects.filter(price_list=price_list)
        }
    number = (design.quotes.aggregate(m=Max("number"))["m"] or 0) + 1
    quote = Quote.objects.create(
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        design=design,
        supplier=price_list.supplier if price_list else None,
        price_list=price_list,
        number=number,
        currency=quote_currency,
        notes=notes,
        created_by=ctx.user,
        updated_by=ctx.user,
    )
    QuoteLine.objects.bulk_create(
        [
            QuoteLine(
                quote=quote,
                sequence=line.sequence,
                bom_line=line,
                catalog_item_id=line.catalog_item_id,
                description=line.description,
                quantity=line.quantity,
                unit=line.unit,
                unit_price=prices.get((line.catalog_item_id, line.unit)),
                price_source="price_list" if (line.catalog_item_id, line.unit) in prices else "",
            )
            for line in bom
        ]
    )
    _recompute_totals(quote)
    quote.save()
    _event(
        ctx,
        "quote.created",
        "irrigation.quote",
        quote.id,
        after={
            "design": str(design.id),
            "price_list": str(price_list.id) if price_list else None,
            "total": str(quote.total),
        },
    )
    return quote


def _draft_quote(ctx: TenantContext, quote_id: uuid.UUID, expected_version: int) -> Quote:
    ctx.require(EDIT)
    quote = (
        Quote.objects.select_for_update().filter(id=quote_id, farm_id=ctx.require_farm_id).first()
    )
    if quote is None:
        raise NotFoundError()
    check_version(quote, expected_version)
    return quote


@transaction.atomic
def update_quote(
    ctx: TenantContext, *, quote_id: uuid.UUID, expected_version: int, data: dict[str, Any]
) -> Quote:
    quote = _draft_quote(ctx, quote_id, expected_version)
    if quote.status != Quote.Status.DRAFT:
        raise BusinessRuleError("Un devis émis est immuable : créez un nouveau devis.")
    for item in data.get("lines", []):
        line = quote.lines.filter(id=item["id"]).first()
        if line is None:
            raise BusinessRuleError("Ligne introuvable.", field_errors={"lines": [str(item["id"])]})
        if item["unit_price"] is not None:
            check_amount_precision(item["unit_price"], quote.currency, "unit_price")
        line.unit_price = item["unit_price"]
        line.price_source = "manual" if item["unit_price"] is not None else ""
        line.notes = item.get("notes", line.notes)
        line.save()
    for name in ("discount_amount", "tax_rate", "notes"):
        if name in data:
            setattr(quote, name, data[name])
    if quote.discount_amount is not None:
        check_amount_precision(quote.discount_amount, quote.currency, "discount_amount")
    try:
        _recompute_totals(quote)
    except InvalidInputError as exc:
        raise BusinessRuleError(exc.reason, field_errors={exc.field: [exc.reason]}) from exc
    quote.version += 1
    quote.updated_by = ctx.user
    quote.save()
    return quote


@transaction.atomic
def issue_quote(ctx: TenantContext, *, quote_id: uuid.UUID, expected_version: int) -> Quote:
    quote = _draft_quote(ctx, quote_id, expected_version)
    if quote.status != Quote.Status.DRAFT:
        raise BusinessRuleError("Ce devis a déjà été émis.")
    quote.status = Quote.Status.ISSUED
    quote.issued_by = ctx.user
    quote.issued_at = timezone.now()
    quote.version += 1
    quote.save()
    _event(ctx, "quote.issued", "irrigation.quote", quote.id, after={"total": str(quote.total)})
    return quote


@transaction.atomic
def decide_quote(
    ctx: TenantContext, *, quote_id: uuid.UUID, expected_version: int, status: str
) -> Quote:
    quote = _draft_quote(ctx, quote_id, expected_version)
    if quote.status != Quote.Status.ISSUED:
        raise BusinessRuleError("Seul un devis émis peut être accepté ou refusé.")
    quote.status = status
    quote.version += 1
    quote.save()
    _event(ctx, f"quote.{status}", "irrigation.quote", quote.id)
    return quote
