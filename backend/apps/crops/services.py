import uuid
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet

from apps.audit.services import diff_to_before_after, record_event
from apps.core.exceptions import BusinessRuleError, NotFoundError
from apps.core.tenancy import TenantContext
from apps.core.versioning import apply_changes, check_version
from apps.crops.models import Crop

VIEW = "varieties.view"
EDIT = "varieties.edit"


def visible_crops(ctx: TenantContext) -> QuerySet[Crop]:
    return Crop.objects.filter(
        Q(organization__isnull=True) | Q(organization_id=ctx.organization_id)
    )


def _save(crop: Crop) -> None:
    try:
        with transaction.atomic():
            crop.save()
    except IntegrityError as exc:
        raise BusinessRuleError(
            "Cette culture existe déjà.", field_errors={"common_name": ["Déjà utilisé."]}
        ) from exc


@transaction.atomic
def create_crop(ctx: TenantContext, *, data: dict[str, Any]) -> Crop:
    ctx.require(EDIT)
    crop = Crop(
        organization_id=ctx.organization_id, created_by=ctx.user, updated_by=ctx.user, **data
    )
    crop.full_clean(validate_unique=False, validate_constraints=False)
    _save(crop)
    record_event(
        action="crop.created",
        actor=ctx.user,
        organization_id=ctx.organization_id,
        entity_type="crops.crop",
        entity_id=crop.id,
        after={"name": crop.common_name},
    )
    return crop


def _own_crop_for_update(ctx: TenantContext, crop_id: uuid.UUID) -> Crop:
    crop = visible_crops(ctx).select_for_update().filter(id=crop_id).first()
    if crop is None:
        raise NotFoundError()
    if crop.is_global:
        raise BusinessRuleError("Les cultures du référentiel commun ne sont pas modifiables.")
    return crop


@transaction.atomic
def update_crop(
    ctx: TenantContext, *, crop_id: uuid.UUID, expected_version: int, changes: dict[str, Any]
) -> Crop:
    ctx.require(EDIT)
    crop = _own_crop_for_update(ctx, crop_id)
    check_version(crop, expected_version)
    diff = apply_changes(crop, changes)
    if diff:
        crop.full_clean(validate_unique=False, validate_constraints=False)
        crop.version += 1
        crop.updated_by = ctx.user
        _save(crop)
        before, after = diff_to_before_after(diff)
        record_event(
            action="crop.updated",
            actor=ctx.user,
            organization_id=ctx.organization_id,
            entity_type="crops.crop",
            entity_id=crop.id,
            before=before,
            after=after,
        )
    return crop


@transaction.atomic
def delete_crop(ctx: TenantContext, *, crop_id: uuid.UUID) -> None:
    from apps.varieties.models import Variety

    ctx.require(EDIT)
    crop = _own_crop_for_update(ctx, crop_id)
    if Variety.objects.filter(crop=crop).exists():
        raise BusinessRuleError("Cette culture a des variétés et ne peut pas être supprimée.")
    record_event(
        action="crop.deleted",
        actor=ctx.user,
        organization_id=ctx.organization_id,
        entity_type="crops.crop",
        entity_id=crop.id,
        before={"name": crop.common_name},
    )
    crop.delete()
