"""Field and parcel services.

Area consistency (FR-010, OPEN_QUESTIONS Q8): the sum of the active
parcels of a field must not exceed the field area plus the farm tolerance.
"""

import uuid
from decimal import Decimal
from typing import Any

from django.db import IntegrityError, models, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.audit.services import diff_to_before_after, record_event
from apps.core.exceptions import BusinessRuleError, IdentifierConflictError, NotFoundError
from apps.core.tenancy import TenantContext
from apps.core.versioning import apply_changes, check_version
from apps.farms.models import Farm
from apps.fields.models import Field, Parcel, ParcelHistoryEntry
from apps.synchronization.models import ChangeLog
from apps.synchronization.services import record_change

FIELD_ENTITY = "fields.field"
PARCEL_ENTITY = "fields.parcel"
VIEW_PERMISSION = "fields.view"
EDIT_PERMISSION = "fields.edit"


def _tolerance_factor(farm_id: uuid.UUID) -> Decimal:
    farm = Farm.objects.only("settings").get(id=farm_id)
    return Decimal(1) + Decimal(farm.get_setting("area_tolerance_pct")) / Decimal(100)


def _parcels_area_sum(field: Field, exclude_id: uuid.UUID | None = None) -> Decimal:
    queryset = Parcel.objects.filter(field=field, deleted_at__isnull=True).exclude(
        status=Parcel.Status.ARCHIVED
    )
    if exclude_id is not None:
        queryset = queryset.exclude(id=exclude_id)
    return queryset.aggregate(total=Sum("area_m2"))["total"] or Decimal(0)


def _check_parcel_fits(parcel: Parcel) -> None:
    if parcel.field_id is None or parcel.status == Parcel.Status.ARCHIVED:
        return
    # Lock the field row so that concurrent parcel writes are serialised.
    field = Field.objects.select_for_update().get(id=parcel.field_id)
    if field.area_m2 is None:
        return
    total = _parcels_area_sum(field, exclude_id=parcel.id) + parcel.area_m2
    limit = field.area_m2 * _tolerance_factor(parcel.farm_id)
    if total > limit:
        raise BusinessRuleError(
            "La somme des superficies des parcelles dépasse la superficie du champ.",
            details={
                "field_area_m2": str(field.area_m2),
                "parcels_area_m2": str(total),
                "allowed_m2": str(limit),
            },
            field_errors={"area_m2": ["Superficie incohérente avec le champ."]},
        )


def _check_field_holds_parcels(field: Field) -> None:
    if field.area_m2 is None:
        return
    total = _parcels_area_sum(field)
    if total > field.area_m2 * _tolerance_factor(field.farm_id):
        raise BusinessRuleError(
            "La superficie du champ est inférieure à la somme de ses parcelles.",
            details={"parcels_area_m2": str(total)},
            field_errors={"area_m2": ["Inférieure à la somme des parcelles."]},
        )


def _save_unique(instance: models.Model, label: str) -> None:
    try:
        with transaction.atomic():
            instance.save()
    except IntegrityError as exc:
        raise BusinessRuleError(
            f"Ce code de {label} existe déjà dans l'exploitation.",
            field_errors={"code": ["Déjà utilisé."]},
        ) from exc


def _existing_for_replay(model: type[Any], ctx: TenantContext, entity_id: uuid.UUID | None) -> Any:
    """Idempotent create: a client-generated id already stored in this farm is a replay."""
    if entity_id is None:
        return None
    existing = model.objects.filter(id=entity_id).first()
    if existing is None:
        return None
    if existing.farm_id != ctx.farm_id:
        raise IdentifierConflictError("Identifiant déjà utilisé.")
    return existing


def _log(
    ctx: TenantContext,
    action: str,
    entity_type: str,
    instance: Any,
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    operation: str = ChangeLog.Operation.UPSERT,
    origin_op_id: uuid.UUID | None = None,
) -> None:
    record_event(
        action=action,
        actor=ctx.user,
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        entity_type=entity_type,
        entity_id=instance.id,
        before=before,
        after=after,
    )
    record_change(
        farm_id=ctx.require_farm_id,
        entity_type=entity_type,
        entity_id=instance.id,
        entity_version=instance.version,
        required_permission=VIEW_PERMISSION,
        operation=operation,
        origin_op_id=origin_op_id,
    )


# --- Fields -----------------------------------------------------------------


@transaction.atomic
def create_field(
    ctx: TenantContext, *, data: dict[str, Any], origin_op_id: uuid.UUID | None = None
) -> tuple[Field, bool]:
    """Return (field, created). created=False means an idempotent replay."""
    ctx.require(EDIT_PERMISSION)
    existing = _existing_for_replay(Field, ctx, data.get("id"))
    if existing is not None:
        return existing, False
    field = Field(
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        created_by=ctx.user,
        updated_by=ctx.user,
        **data,
    )
    field.full_clean(validate_unique=False, validate_constraints=False)
    _save_unique(field, "champ")
    _log(
        ctx,
        "field.created",
        FIELD_ENTITY,
        field,
        after={"code": field.code},
        origin_op_id=origin_op_id,
    )
    return field, True


def _get_field_for_update(ctx: TenantContext, field_id: uuid.UUID) -> Field:
    field = (
        Field.objects.select_for_update()
        .filter(id=field_id, farm_id=ctx.require_farm_id, deleted_at__isnull=True)
        .first()
    )
    if field is None:
        raise NotFoundError()
    return field


@transaction.atomic
def update_field(
    ctx: TenantContext,
    *,
    field_id: uuid.UUID,
    expected_version: int,
    changes: dict[str, Any],
    origin_op_id: uuid.UUID | None = None,
) -> Field:
    ctx.require(EDIT_PERMISSION)
    field = _get_field_for_update(ctx, field_id)
    check_version(field, expected_version)
    diff = apply_changes(field, changes)
    if not diff:
        return field
    field.full_clean(validate_unique=False, validate_constraints=False)
    if "area_m2" in diff:
        _check_field_holds_parcels(field)
    field.version += 1
    field.updated_by = ctx.user
    _save_unique(field, "champ")
    before, after = diff_to_before_after(diff)
    _log(
        ctx,
        "field.updated",
        FIELD_ENTITY,
        field,
        before=before,
        after=after,
        origin_op_id=origin_op_id,
    )
    return field


@transaction.atomic
def delete_field(
    ctx: TenantContext,
    *,
    field_id: uuid.UUID,
    expected_version: int,
    origin_op_id: uuid.UUID | None = None,
) -> Field:
    ctx.require(EDIT_PERMISSION)
    field = _get_field_for_update(ctx, field_id)
    check_version(field, expected_version)
    if field.parcels.filter(deleted_at__isnull=True).exists():
        raise BusinessRuleError("Le champ contient des parcelles : supprimez-les ou déplacez-les.")
    field.deleted_at = timezone.now()
    field.deleted_by = ctx.user
    field.version += 1
    field.save()
    _log(
        ctx,
        "field.deleted",
        FIELD_ENTITY,
        field,
        operation=ChangeLog.Operation.DELETE,
        origin_op_id=origin_op_id,
    )
    return field


# --- Parcels ----------------------------------------------------------------


@transaction.atomic
def create_parcel(
    ctx: TenantContext, *, data: dict[str, Any], origin_op_id: uuid.UUID | None = None
) -> tuple[Parcel, bool]:
    ctx.require(EDIT_PERMISSION)
    existing = _existing_for_replay(Parcel, ctx, data.get("id"))
    if existing is not None:
        return existing, False
    parcel = Parcel(
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        created_by=ctx.user,
        updated_by=ctx.user,
        **data,
    )
    _assert_same_farm(ctx, parcel.field)
    parcel.full_clean(validate_unique=False, validate_constraints=False)
    _check_parcel_fits(parcel)
    _save_unique(parcel, "parcelle")
    _log(
        ctx,
        "parcel.created",
        PARCEL_ENTITY,
        parcel,
        after={"code": parcel.code, "area_m2": parcel.area_m2},
        origin_op_id=origin_op_id,
    )
    return parcel, True


def _assert_same_farm(ctx: TenantContext, field: Field | None) -> None:
    # Defence in depth: serializers already restrict the queryset to the farm.
    if field is not None and (field.farm_id != ctx.farm_id or field.deleted_at is not None):
        raise NotFoundError()


def _get_parcel_for_update(ctx: TenantContext, parcel_id: uuid.UUID) -> Parcel:
    parcel = (
        Parcel.objects.select_for_update()
        .filter(id=parcel_id, farm_id=ctx.require_farm_id, deleted_at__isnull=True)
        .first()
    )
    if parcel is None:
        raise NotFoundError()
    return parcel


@transaction.atomic
def update_parcel(
    ctx: TenantContext,
    *,
    parcel_id: uuid.UUID,
    expected_version: int,
    changes: dict[str, Any],
    origin_op_id: uuid.UUID | None = None,
) -> Parcel:
    ctx.require(EDIT_PERMISSION)
    parcel = _get_parcel_for_update(ctx, parcel_id)
    check_version(parcel, expected_version)
    diff = apply_changes(parcel, changes)
    if not diff:
        return parcel
    _assert_same_farm(ctx, parcel.field)
    parcel.full_clean(validate_unique=False, validate_constraints=False)
    if {"area_m2", "field", "status"} & diff.keys():
        _check_parcel_fits(parcel)
    parcel.version += 1
    parcel.updated_by = ctx.user
    _save_unique(parcel, "parcelle")
    before, after = diff_to_before_after(
        {k: [getattr(v[0], "pk", v[0]), getattr(v[1], "pk", v[1])] for k, v in diff.items()}
    )
    _log(
        ctx,
        "parcel.updated",
        PARCEL_ENTITY,
        parcel,
        before=before,
        after=after,
        origin_op_id=origin_op_id,
    )
    return parcel


@transaction.atomic
def delete_parcel(
    ctx: TenantContext,
    *,
    parcel_id: uuid.UUID,
    expected_version: int,
    origin_op_id: uuid.UUID | None = None,
) -> Parcel:
    ctx.require(EDIT_PERMISSION)
    parcel = _get_parcel_for_update(ctx, parcel_id)
    check_version(parcel, expected_version)
    parcel.deleted_at = timezone.now()
    parcel.deleted_by = ctx.user
    parcel.version += 1
    parcel.save()
    _log(
        ctx,
        "parcel.deleted",
        PARCEL_ENTITY,
        parcel,
        operation=ChangeLog.Operation.DELETE,
        origin_op_id=origin_op_id,
    )
    return parcel


@transaction.atomic
def add_history_entry(
    ctx: TenantContext, *, parcel_id: uuid.UUID, data: dict[str, Any]
) -> ParcelHistoryEntry:
    ctx.require(EDIT_PERMISSION)
    parcel = Parcel.objects.filter(
        id=parcel_id, farm_id=ctx.require_farm_id, deleted_at__isnull=True
    ).first()
    if parcel is None:
        raise NotFoundError()
    entry = ParcelHistoryEntry(
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        parcel=parcel,
        created_by=ctx.user,
        updated_by=ctx.user,
        **data,
    )
    entry.full_clean()
    entry.save()
    record_event(
        action="parcel.history_added",
        actor=ctx.user,
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        entity_type="fields.parcel_history_entry",
        entity_id=entry.id,
        after={"crop_label": entry.crop_label},
    )
    return entry
