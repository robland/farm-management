"""Agronomic programme and observations (FR-050..052, FR-111).

- Doses are never generated: they come from a document or a user.
- A phytosanitary dose can never come from the AI (DB constraint + service check),
  must cite the label, and always carries a regulatory warning (FR-052).
- Programme items belong to a draft plan version; validated versions are immutable.
"""

import uuid
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Max, Sum

from agronomy_engine.errors import InvalidInputError, MissingInputError
from agronomy_engine.inputs import (
    NutrientDoseInput,
    ProductDoseInput,
    WaterNeedInput,
    compute_nutrient_dose,
    compute_product_dose,
    compute_water_need,
)
from apps.agronomy.models import (
    NUTRIENTS,
    InputProduct,
    Observation,
    PlannedFertilization,
    PlannedIrrigation,
    PlannedPhytoIntervention,
    SourceKind,
)
from apps.audit.services import record_event
from apps.core.exceptions import BusinessRuleError, IdentifierConflictError, NotFoundError
from apps.core.tenancy import TenantContext
from apps.files.models import StoredFile
from apps.files.services import require_usable_file
from apps.production_plans import services as plans
from apps.production_plans.models import PlanVersion
from apps.synchronization.services import record_change

OBSERVATION_ENTITY = "agronomy.observation"
PHYTO_WARNING = (
    "Vérifier l'autorisation du produit dans le pays et respecter strictement les instructions "
    "de l'étiquette (dose, délai avant récolte, équipements de protection)."
)
PLANNED_MODELS: dict[str, Any] = {
    "fertilization": PlannedFertilization,
    "phyto": PlannedPhytoIntervention,
    "irrigation": PlannedIrrigation,
}


def validate_composition(composition: dict[str, Any]) -> dict[str, Decimal]:
    cleaned: dict[str, Decimal] = {}
    for nutrient, value in composition.items():
        if nutrient not in NUTRIENTS:
            raise BusinessRuleError(
                f"Nutriment inconnu : {nutrient}.", field_errors={"composition": [nutrient]}
            )
        pct = Decimal(str(value))
        if not 0 <= pct <= 100:
            raise BusinessRuleError(
                "Teneur hors limites (0 à 100 %).", field_errors={"composition": [nutrient]}
            )
        cleaned[nutrient] = pct
    return cleaned


def product_warnings(product: InputProduct, on_date: Any = None) -> list[str]:
    warnings = []
    if product.kind == InputProduct.Kind.PHYTO:
        warnings.append(PHYTO_WARNING)
        if not product.registration_number:
            warnings.append("Numéro d'homologation non renseigné.")
    if product.registration_valid_until and on_date and product.registration_valid_until < on_date:
        warnings.append("L'homologation du produit est expirée à la date prévue.")
    return warnings


# --- Products ------------------------------------------------------------------------


def _check_label(ctx: TenantContext, data: dict[str, Any]) -> None:
    label = data.get("label_file")
    if label is not None:
        require_usable_file(ctx, label.id, StoredFile.Purpose.PRODUCT_LABEL)


@transaction.atomic
def create_product(ctx: TenantContext, *, data: dict[str, Any]) -> InputProduct:
    ctx.require("inventory.edit")
    data = {**data, "composition": validate_composition(data.get("composition") or {})}
    _check_label(ctx, data)
    product = InputProduct(
        organization_id=ctx.organization_id, created_by=ctx.user, updated_by=ctx.user, **data
    )
    product.full_clean()
    product.save()
    record_event(
        action="input_product.created",
        actor=ctx.user,
        organization_id=ctx.organization_id,
        entity_type="agronomy.input_product",
        entity_id=product.id,
        after={"name": product.name, "kind": product.kind},
    )
    return product


@transaction.atomic
def update_product(
    ctx: TenantContext, *, product_id: uuid.UUID, expected_version: int, changes: dict[str, Any]
) -> InputProduct:
    from apps.core.versioning import apply_changes, check_version

    ctx.require("inventory.edit")
    product = (
        InputProduct.objects.select_for_update()
        .filter(id=product_id, organization_id=ctx.organization_id, deleted_at__isnull=True)
        .first()
    )
    if product is None:
        raise NotFoundError()
    check_version(product, expected_version)
    if "composition" in changes:
        changes = {**changes, "composition": validate_composition(changes["composition"])}
    _check_label(ctx, changes)
    if apply_changes(product, changes):
        product.full_clean()
        product.version += 1
        product.updated_by = ctx.user
        product.save()
    return product


# --- Programme -----------------------------------------------------------------------


def _version_area_and_plants(version: PlanVersion) -> tuple[Decimal | None, int | None]:
    area = version.allocations.aggregate(total=Sum("allocated_area_m2"))["total"]
    plants = None
    records = version.calculations.filter(calc_type="planting.density")
    if records.exists():
        plants = sum(int(r.outputs["plant_count"]["value"]) for r in records)
    return area, plants


def _check_product(ctx: TenantContext, product: InputProduct, kinds: set[str]) -> None:
    if product.organization_id != ctx.organization_id or product.deleted_at is not None:
        raise BusinessRuleError("Produit introuvable.", field_errors={"product": ["Introuvable."]})
    if product.kind not in kinds:
        raise BusinessRuleError(
            "Type de produit incompatible.", field_errors={"product": ["Type incompatible."]}
        )


def _quantity(item: Any, version: PlanVersion) -> tuple[Decimal | None, str, list[str]]:
    """Compute the planned quantity; returns (quantity, unit, missing_fields)."""
    area, plants = _version_area_and_plants(version)
    product = item.product
    try:
        if isinstance(item, PlannedFertilization) and item.mode == item.Mode.NUTRIENT_TARGET:
            result = compute_nutrient_dose(
                NutrientDoseInput(
                    target_nutrient=item.target_nutrient or None,
                    nutrient_dose_kg_per_ha=item.nutrient_dose_kg_per_ha,
                    area_m2=area,
                    composition_pct={k: Decimal(str(v)) for k, v in product.composition.items()},
                    density_kg_per_l=product.density_kg_per_l,
                )
            )
            if "product_l" in result.outputs:
                return result.output("product_l"), "L", []
            return result.output("product_kg"), "kg", []
        result = compute_product_dose(
            ProductDoseInput(
                dose_value=item.dose_value,
                dose_unit=item.dose_unit or None,
                basis=item.basis or None,
                area_m2=area,
                plant_count=plants,
                density_kg_per_l=product.density_kg_per_l,
            )
        )
        quantity = result.outputs["total_quantity"]
        return quantity.value, quantity.unit, []  # type: ignore[return-value]
    except MissingInputError as exc:
        return None, "", exc.fields
    except InvalidInputError as exc:
        raise BusinessRuleError(exc.reason, field_errors={exc.field: [exc.reason]}) from exc


def _next_sequence(model: type[Any], version: PlanVersion) -> int:
    return (model.objects.filter(plan_version=version).aggregate(m=Max("sequence"))["m"] or 0) + 1


@transaction.atomic
def add_fertilization(
    ctx: TenantContext, *, version_id: uuid.UUID, expected_version: int, data: dict[str, Any]
) -> tuple[PlannedFertilization, list[str]]:
    version = plans.lock_draft_version(ctx, version_id, expected_version)
    product = data["product"]
    _check_product(ctx, product, {InputProduct.Kind.FERTILIZER, InputProduct.Kind.AMENDMENT})
    mode = data["mode"]
    if mode == PlannedFertilization.Mode.NUTRIENT_TARGET:
        if not data.get("target_nutrient") or data.get("nutrient_dose_kg_per_ha") is None:
            raise BusinessRuleError(
                "Nutriment et dose de nutriment obligatoires.",
                field_errors={"nutrient_dose_kg_per_ha": ["Obligatoire."]},
            )
    elif data.get("dose_value") is None or not data.get("dose_unit") or not data.get("basis"):
        raise BusinessRuleError(
            "Dose, unité et base obligatoires.", field_errors={"dose_value": ["Obligatoire."]}
        )
    if (
        data["source_kind"] == SourceKind.DOCUMENT
        and data.get("technical_data_item") is None
        and not data.get("source_note")
    ):
        raise BusinessRuleError(
            "Une dose documentaire doit citer sa source.",
            field_errors={"source_note": ["Obligatoire."]},
        )
    item = PlannedFertilization(
        plan_version=version, sequence=_next_sequence(PlannedFertilization, version), **data
    )
    item.computed_quantity, item.computed_unit, missing = _quantity(item, version)
    item.save()
    plans.touch_version(ctx, version)
    return item, missing


@transaction.atomic
def add_phyto(
    ctx: TenantContext, *, version_id: uuid.UUID, expected_version: int, data: dict[str, Any]
) -> tuple[PlannedPhytoIntervention, list[str]]:
    version = plans.lock_draft_version(ctx, version_id, expected_version)
    product = data["product"]
    _check_product(ctx, product, {InputProduct.Kind.PHYTO})
    if data.get("source_kind") not in {SourceKind.DOCUMENT, SourceKind.USER_INPUT}:
        raise BusinessRuleError(
            "Une dose phytosanitaire doit provenir de l'étiquette ou d'une saisie utilisateur.",
            field_errors={"source_kind": ["L'IA ne peut pas proposer de dose phytosanitaire."]},
        )
    if not (data.get("label_reference") or "").strip():
        raise BusinessRuleError(
            "La référence de l'étiquette est obligatoire.",
            field_errors={"label_reference": ["Obligatoire."]},
        )
    item = PlannedPhytoIntervention(
        plan_version=version, sequence=_next_sequence(PlannedPhytoIntervention, version), **data
    )
    item.computed_quantity, item.computed_unit, missing = _quantity(item, version)
    item.save()
    plans.touch_version(ctx, version)
    return item, product_warnings(product, version.planned_start_date) + (
        [f"Données manquantes pour la quantité : {', '.join(missing)}"] if missing else []
    )


@transaction.atomic
def set_irrigation_schedule(
    ctx: TenantContext, *, version_id: uuid.UUID, expected_version: int, items: list[dict[str, Any]]
) -> list[PlannedIrrigation]:
    version = plans.lock_draft_version(ctx, version_id, expected_version)
    phases = set(version.phases.values_list("phase_code", flat=True))
    area, _ = _version_area_and_plants(version)
    version.irrigation_schedule.all().delete()
    created = []
    for index, data in enumerate(items):
        if data["phase_code"] not in phases:
            raise BusinessRuleError(
                "Phase absente du plan.", field_errors={f"items.{index}.phase_code": ["Inconnue."]}
            )
        if data["source_kind"] == SourceKind.AI_SUGGESTION:
            raise BusinessRuleError("Valeur IA à valider par l'utilisateur avant enregistrement.")
        item = PlannedIrrigation(plan_version=version, **data)
        try:
            result = compute_water_need(
                WaterNeedInput(item.et0_mm_per_day, item.kc, item.application_efficiency_rate, area)
            )
            item.computed_gross_l_per_day = result.output("gross_volume_l_per_day")
        except MissingInputError:
            item.computed_gross_l_per_day = None
        except InvalidInputError as exc:
            raise BusinessRuleError(exc.reason, field_errors={exc.field: [exc.reason]}) from exc
        item.save()
        created.append(item)
    plans.touch_version(ctx, version)
    return created


@transaction.atomic
def remove_program_item(
    ctx: TenantContext,
    *,
    version_id: uuid.UUID,
    expected_version: int,
    kind: str,
    item_id: uuid.UUID,
) -> None:
    version = plans.lock_draft_version(ctx, version_id, expected_version)
    model = PLANNED_MODELS.get(kind)
    if model is None or not model.objects.filter(plan_version=version, id=item_id).exists():
        raise NotFoundError()
    model.objects.filter(plan_version=version, id=item_id).delete()
    plans.touch_version(ctx, version)


@transaction.atomic
def recompute_program(ctx: TenantContext, *, version_id: uuid.UUID) -> dict[str, Any]:
    version = plans.lock_draft_version(ctx, version_id, None)
    missing: dict[str, list[str]] = {}
    for model in (PlannedFertilization, PlannedPhytoIntervention):
        for item in model.objects.filter(plan_version=version).select_related("product"):
            item.computed_quantity, item.computed_unit, item_missing = _quantity(item, version)
            item.save(update_fields=["computed_quantity", "computed_unit"])
            if item_missing:
                missing[str(item.id)] = item_missing
    plans.touch_version(ctx, version)
    return {"missing": missing}


def copy_program(source: PlanVersion, draft: PlanVersion) -> None:
    """VERSION_COPY_HOOKS entry: carry the programme over to a new draft version."""
    models: tuple[Any, ...] = (PlannedFertilization, PlannedPhytoIntervention, PlannedIrrigation)
    for model in models:
        rows = []
        for item in model.objects.filter(plan_version=source):
            item.pk = uuid.uuid4()
            item.plan_version = draft
            rows.append(item)
        model.objects.bulk_create(rows)


# --- Observations --------------------------------------------------------------------


@transaction.atomic
def create_observation(
    ctx: TenantContext, *, data: dict[str, Any], origin_op_id: uuid.UUID | None = None
) -> tuple[Observation, bool]:
    """Append-only, idempotent on the client-generated id."""
    ctx.require("observations.create")
    photos = data.pop("photos", [])
    observation_id = data.get("id")
    if observation_id is not None:
        existing = Observation.objects.filter(id=observation_id).first()
        if existing is not None:
            if existing.farm_id != ctx.farm_id:
                raise IdentifierConflictError("Identifiant déjà utilisé.")
            return existing, False
    parcel = data["parcel"]
    if parcel.farm_id != ctx.farm_id or parcel.deleted_at is not None:
        raise BusinessRuleError("Parcelle introuvable.", field_errors={"parcel": ["Introuvable."]})
    cycle = data.get("crop_cycle")
    if cycle is not None and (cycle.farm_id != ctx.farm_id or cycle.parcel_id != parcel.id):
        raise BusinessRuleError(
            "Cycle incohérent avec la parcelle.", field_errors={"crop_cycle": ["Incohérent."]}
        )
    observation = Observation.objects.create(
        organization_id=ctx.organization_id, farm_id=ctx.require_farm_id, author=ctx.user, **data
    )
    for photo in photos:
        observation.photos.add(
            require_usable_file(ctx, photo.id, StoredFile.Purpose.OBSERVATION_PHOTO)
        )
    record_change(
        farm_id=ctx.require_farm_id,
        entity_type=OBSERVATION_ENTITY,
        entity_id=observation.id,
        entity_version=1,
        required_permission="observations.view",
        origin_op_id=origin_op_id,
    )
    return observation, True
