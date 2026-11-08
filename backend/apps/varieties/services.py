"""Variety and technical data services.

Rules (FR-022, FR-023, CLAUDE.md §10):
- A value with provenance `document` must cite its source (page or section,
  and the quoted text) and the data set must reference the source document.
- AI-extracted values are drafts: a data set can only be validated once
  every item has been explicitly validated by a user with `varieties.validate`.
- A validated data set is immutable; changes go into a new version.
"""

import uuid
from decimal import Decimal
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.services import diff_to_before_after, record_event
from apps.core.exceptions import BusinessRuleError, NotFoundError
from apps.core.tenancy import TenantContext
from apps.core.versioning import apply_changes, check_version
from apps.crops.services import visible_crops
from apps.files.models import StoredFile
from apps.files.services import require_usable_file
from apps.varieties.models import TechnicalDataItem, TechnicalDataSet, TechnicalDocument, Variety
from apps.varieties.technical_keys import get_key_spec

VIEW = "varieties.view"
EDIT = "varieties.edit"
VALIDATE = "varieties.validate"


def _event(
    ctx: TenantContext, action: str, entity_type: str, entity_id: uuid.UUID, **extra: Any
) -> None:
    record_event(
        action=action,
        actor=ctx.user,
        organization_id=ctx.organization_id,
        entity_type=entity_type,
        entity_id=entity_id,
        **extra,
    )


# --- Varieties -----------------------------------------------------------------


def _check_crop(ctx: TenantContext, crop: Any) -> None:
    if crop is not None and not visible_crops(ctx).filter(id=crop.id).exists():
        raise BusinessRuleError("Culture introuvable.", field_errors={"crop": ["Introuvable."]})


def _save_variety(variety: Variety) -> None:
    try:
        with transaction.atomic():
            variety.save()
    except IntegrityError as exc:
        raise BusinessRuleError(
            "Cette variété existe déjà.", field_errors={"name": ["Déjà utilisé."]}
        ) from exc


@transaction.atomic
def create_variety(ctx: TenantContext, *, data: dict[str, Any]) -> Variety:
    ctx.require(EDIT)
    _check_crop(ctx, data.get("crop"))
    variety = Variety(
        organization_id=ctx.organization_id, created_by=ctx.user, updated_by=ctx.user, **data
    )
    variety.full_clean(validate_unique=False, validate_constraints=False)
    _save_variety(variety)
    _event(ctx, "variety.created", "varieties.variety", variety.id, after={"name": variety.name})
    return variety


def _variety_for_update(ctx: TenantContext, variety_id: uuid.UUID) -> Variety:
    variety = (
        Variety.objects.select_for_update()
        .filter(id=variety_id, organization_id=ctx.organization_id, deleted_at__isnull=True)
        .first()
    )
    if variety is None:
        raise NotFoundError()
    return variety


@transaction.atomic
def update_variety(
    ctx: TenantContext, *, variety_id: uuid.UUID, expected_version: int, changes: dict[str, Any]
) -> Variety:
    ctx.require(EDIT)
    variety = _variety_for_update(ctx, variety_id)
    check_version(variety, expected_version)
    _check_crop(ctx, changes.get("crop"))
    diff = apply_changes(variety, changes)
    if diff:
        variety.full_clean(validate_unique=False, validate_constraints=False)
        variety.version += 1
        variety.updated_by = ctx.user
        _save_variety(variety)
        before, after = diff_to_before_after(
            {k: [getattr(v[0], "pk", v[0]), getattr(v[1], "pk", v[1])] for k, v in diff.items()}
        )
        _event(ctx, "variety.updated", "varieties.variety", variety.id, before=before, after=after)
    return variety


@transaction.atomic
def delete_variety(ctx: TenantContext, *, variety_id: uuid.UUID, expected_version: int) -> None:
    ctx.require(EDIT)
    variety = _variety_for_update(ctx, variety_id)
    check_version(variety, expected_version)
    variety.deleted_at = timezone.now()
    variety.deleted_by = ctx.user
    variety.version += 1
    variety.save()
    _event(ctx, "variety.deleted", "varieties.variety", variety.id)


# --- Documents -----------------------------------------------------------------


@transaction.atomic
def add_document(
    ctx: TenantContext, *, variety_id: uuid.UUID, file_id: uuid.UUID, data: dict[str, Any]
) -> TechnicalDocument:
    ctx.require(EDIT)
    variety = _variety_for_update(ctx, variety_id)
    stored = require_usable_file(ctx, file_id, StoredFile.Purpose.TECHNICAL_SHEET)
    document = TechnicalDocument.objects.create(
        organization_id=ctx.organization_id,
        variety=variety,
        file=stored,
        created_by=ctx.user,
        updated_by=ctx.user,
        **data,
    )
    _event(
        ctx,
        "technical_document.added",
        "varieties.technical_document",
        document.id,
        after={"file": str(stored.id), "supplier": document.supplier},
    )
    return document


# --- Technical data sets -------------------------------------------------------


def _data_set_for_update(ctx: TenantContext, data_set_id: uuid.UUID) -> TechnicalDataSet:
    data_set = (
        TechnicalDataSet.objects.select_for_update()
        .filter(id=data_set_id, organization_id=ctx.organization_id)
        .first()
    )
    if data_set is None:
        raise NotFoundError()
    return data_set


def _require_draft(data_set: TechnicalDataSet) -> None:
    if data_set.status != TechnicalDataSet.Status.DRAFT:
        raise BusinessRuleError(
            "Un jeu de données validé est immuable : créez une nouvelle version."
        )


@transaction.atomic
def create_data_set(
    ctx: TenantContext,
    *,
    variety_id: uuid.UUID,
    source_document_id: uuid.UUID | None = None,
    based_on_id: uuid.UUID | None = None,
    notes: str = "",
) -> TechnicalDataSet:
    ctx.require(EDIT)
    variety = _variety_for_update(ctx, variety_id)  # also serialises version numbering
    source_document = None
    if source_document_id is not None:
        source_document = TechnicalDocument.objects.filter(
            id=source_document_id, variety=variety
        ).first()
        if source_document is None:
            raise BusinessRuleError(
                "Document introuvable pour cette variété.",
                field_errors={"source_document": ["Introuvable."]},
            )
    based_on = None
    if based_on_id is not None:
        based_on = TechnicalDataSet.objects.filter(id=based_on_id, variety=variety).first()
        if based_on is None:
            raise BusinessRuleError(
                "Version de base introuvable.", field_errors={"based_on": ["Introuvable."]}
            )
        source_document = source_document or based_on.source_document
    number = (variety.data_sets.aggregate(m=Max("version_number"))["m"] or 0) + 1
    data_set = TechnicalDataSet.objects.create(
        organization_id=ctx.organization_id,
        variety=variety,
        source_document=source_document,
        version_number=number,
        based_on=based_on,
        notes=notes,
        created_by=ctx.user,
        updated_by=ctx.user,
    )
    if based_on is not None:
        # Unchanged values keep their provenance and validation.
        TechnicalDataItem.objects.bulk_create(
            [
                TechnicalDataItem(
                    data_set=data_set,
                    **{
                        f.name: getattr(item, f.name)
                        for f in TechnicalDataItem._meta.concrete_fields
                        if f.name not in {"id", "data_set", "created_at", "updated_at"}
                    },
                )
                for item in based_on.items.all()
            ]
        )
    _event(
        ctx,
        "technical_data_set.created",
        "varieties.technical_data_set",
        data_set.id,
        after={"version": number, "based_on": str(based_on_id) if based_on_id else None},
    )
    return data_set


def _validate_item(data_set: TechnicalDataSet, item: dict[str, Any]) -> dict[str, Any]:
    key = item["key"]
    spec = get_key_spec(key)
    if spec is None:
        raise BusinessRuleError(
            f"Clé technique inconnue : {key}.", field_errors={key: ["Clé inconnue."]}
        )
    errors: list[str] = []
    unit = item.get("unit") or spec.unit
    if unit != spec.unit:
        errors.append(f"Unité attendue : {spec.unit or 'aucune'} (reçue : {unit}).")
    if spec.kind == "text":
        if not item.get("value_text"):
            errors.append("Valeur textuelle obligatoire.")
        for name in ("value_numeric", "value_min", "value_max"):
            if item.get(name) is not None:
                errors.append(f"{name} interdit pour une donnée textuelle.")
    else:
        numbers = {n: item.get(n) for n in ("value_numeric", "value_min", "value_max")}
        if all(v is None for v in numbers.values()):
            errors.append("Une valeur ou une plage est obligatoire.")
        for name, value in numbers.items():
            if value is None:
                continue
            if spec.min_value is not None and (
                value < spec.min_value or (spec.min_exclusive and value == spec.min_value)
            ):
                errors.append(f"{name} hors limites (minimum {spec.min_value}).")
            if spec.max_value is not None and value > spec.max_value:
                errors.append(f"{name} hors limites (maximum {spec.max_value}).")
        low, high = numbers["value_min"], numbers["value_max"]
        if low is not None and high is not None and low > high:
            errors.append("value_min doit être inférieure ou égale à value_max.")
        value = numbers["value_numeric"]
        if value is not None and (
            (low is not None and value < low) or (high is not None and value > high)
        ):
            errors.append("value_numeric doit être comprise dans la plage.")
    provenance = item["provenance"]
    if provenance == TechnicalDataItem.Provenance.DOCUMENT:
        if data_set.source_document_id is None:
            errors.append("Provenance documentaire impossible : aucun document source.")
        if item.get("source_page") is None and not item.get("source_section"):
            errors.append("La page ou la section source est obligatoire.")
        if not item.get("source_quote"):
            errors.append("L'extrait cité de la source est obligatoire.")
    if errors:
        raise BusinessRuleError("Donnée technique invalide.", field_errors={key: errors})
    return {**item, "unit": unit}


# Public: lets the AI module pre-check extracted items with the very same rules.
validate_item = _validate_item


@transaction.atomic
def upsert_items(
    ctx: TenantContext, *, data_set_id: uuid.UUID, items: list[dict[str, Any]]
) -> TechnicalDataSet:
    """Create or replace items of a draft. A changed value must be validated again."""
    ctx.require(EDIT)
    data_set = _data_set_for_update(ctx, data_set_id)
    _require_draft(data_set)
    cleaned = [_validate_item(data_set, item) for item in items]
    for item in cleaned:
        defaults = {
            "value_numeric": item.get("value_numeric"),
            "value_min": item.get("value_min"),
            "value_max": item.get("value_max"),
            "value_text": item.get("value_text", ""),
            "unit": item["unit"],
            "provenance": item["provenance"],
            "source_page": item.get("source_page"),
            "source_section": item.get("source_section", ""),
            "source_quote": item.get("source_quote", ""),
            "confidence": item.get("confidence"),
            "notes": item.get("notes", ""),
            "validated": False,
            "validated_by": None,
            "validated_at": None,
        }
        TechnicalDataItem.objects.update_or_create(
            data_set=data_set, key=item["key"], defaults=defaults
        )
    data_set.version += 1
    data_set.updated_by = ctx.user
    data_set.save()
    _event(
        ctx,
        "technical_data_set.items_upserted",
        "varieties.technical_data_set",
        data_set.id,
        after={"keys": [i["key"] for i in cleaned]},
    )
    return data_set


@transaction.atomic
def remove_items(ctx: TenantContext, *, data_set_id: uuid.UUID, keys: list[str]) -> None:
    ctx.require(EDIT)
    data_set = _data_set_for_update(ctx, data_set_id)
    _require_draft(data_set)
    data_set.items.filter(key__in=keys).delete()
    data_set.version += 1
    data_set.save()


@transaction.atomic
def validate_items(ctx: TenantContext, *, data_set_id: uuid.UUID, keys: list[str]) -> int:
    """Explicit human validation of extracted or entered values (FR-023)."""
    ctx.require(VALIDATE)
    data_set = _data_set_for_update(ctx, data_set_id)
    _require_draft(data_set)
    found = set(data_set.items.filter(key__in=keys).values_list("key", flat=True))
    missing = sorted(set(keys) - found)
    if missing:
        raise BusinessRuleError("Clés introuvables.", field_errors={"keys": missing})
    count = data_set.items.filter(key__in=keys).update(
        validated=True, validated_by=ctx.user, validated_at=timezone.now()
    )
    _event(
        ctx,
        "technical_data_set.items_validated",
        "varieties.technical_data_set",
        data_set.id,
        after={"keys": sorted(keys)},
    )
    return count


@transaction.atomic
def validate_data_set(ctx: TenantContext, *, data_set_id: uuid.UUID) -> TechnicalDataSet:
    ctx.require(VALIDATE)
    data_set = _data_set_for_update(ctx, data_set_id)
    _require_draft(data_set)
    items = list(data_set.items.all())
    if not items:
        raise BusinessRuleError("Le jeu de données est vide.")
    pending = sorted(i.key for i in items if not i.validated)
    if pending:
        raise BusinessRuleError(
            "Toutes les données doivent être vérifiées avant validation.",
            details={"pending_keys": pending},
        )
    TechnicalDataSet.objects.filter(
        variety_id=data_set.variety_id, status=TechnicalDataSet.Status.VALIDATED
    ).update(status=TechnicalDataSet.Status.SUPERSEDED)
    data_set.status = TechnicalDataSet.Status.VALIDATED
    data_set.validated_by = ctx.user
    data_set.validated_at = timezone.now()
    data_set.version += 1
    data_set.save()
    if data_set.source_document_id:
        TechnicalDocument.objects.filter(id=data_set.source_document_id).update(
            status=TechnicalDocument.Status.REVIEWED
        )
    _event(
        ctx,
        "technical_data_set.validated",
        "varieties.technical_data_set",
        data_set.id,
        after={"version": data_set.version_number},
    )
    return data_set


def validated_values(variety: Variety) -> dict[str, TechnicalDataItem]:
    """Reference data of a variety: items of its validated data set only."""
    data_set = variety.data_sets.filter(status=TechnicalDataSet.Status.VALIDATED).first()
    if data_set is None:
        return {}
    return {item.key: item for item in data_set.items.all()}


def numeric(items: dict[str, TechnicalDataItem], key: str) -> Decimal | None:
    item = items.get(key)
    return item.value_numeric if item is not None else None
