import uuid
from typing import Any

from django.db import IntegrityError, transaction

from apps.audit.services import diff_to_before_after, record_event
from apps.core.exceptions import BusinessRuleError, NotFoundError
from apps.core.tenancy import TenantContext
from apps.core.versioning import apply_changes, check_version
from apps.farms.models import Farm, FarmMembership
from apps.organizations.models import OrganizationMembership, Role
from apps.organizations.services import ORG_MANAGE
from apps.synchronization.models import FarmSyncState
from apps.synchronization.services import record_change

FARM_ENTITY = "farms.farm"


@transaction.atomic
def create_farm(org_ctx: TenantContext, *, data: dict[str, Any]) -> Farm:
    org_ctx.require(ORG_MANAGE)
    farm = Farm(organization_id=org_ctx.organization_id, **data)
    farm.full_clean()
    try:
        with transaction.atomic():
            farm.save()
    except IntegrityError as exc:
        raise BusinessRuleError(
            "Ce code d'exploitation existe déjà.", field_errors={"code": ["Déjà utilisé."]}
        ) from exc
    FarmSyncState.objects.create(farm=farm)
    record_event(
        action="farm.created",
        actor=org_ctx.user,
        organization_id=farm.organization_id,
        farm_id=farm.id,
        entity_type=FARM_ENTITY,
        entity_id=farm.id,
        after={"name": farm.name, "code": farm.code},
    )
    record_change(
        farm_id=farm.id,
        entity_type=FARM_ENTITY,
        entity_id=farm.id,
        entity_version=farm.version,
        required_permission="farm.view",
    )
    return farm


@transaction.atomic
def update_farm(ctx: TenantContext, *, expected_version: int, changes: dict[str, Any]) -> Farm:
    ctx.require("farm.manage")
    farm = Farm.objects.select_for_update().get(id=ctx.require_farm_id)
    check_version(farm, expected_version)
    if "settings" in changes:
        changes = {**changes, "settings": {**farm.settings, **changes["settings"]}}
    diff = apply_changes(farm, changes)
    if diff:
        farm.full_clean()
        farm.version += 1
        try:
            with transaction.atomic():
                farm.save()
        except IntegrityError as exc:
            raise BusinessRuleError(
                "Ce code d'exploitation existe déjà.", field_errors={"code": ["Déjà utilisé."]}
            ) from exc
        before, after = diff_to_before_after(diff)
        record_event(
            action="farm.updated",
            actor=ctx.user,
            organization_id=farm.organization_id,
            farm_id=farm.id,
            entity_type=FARM_ENTITY,
            entity_id=farm.id,
            before=before,
            after=after,
        )
        record_change(
            farm_id=farm.id,
            entity_type=FARM_ENTITY,
            entity_id=farm.id,
            entity_version=farm.version,
            required_permission="farm.view",
        )
    return farm


def _get_role(ctx: TenantContext, role_id: uuid.UUID) -> Role:
    role = Role.objects.filter(id=role_id, organization_id=ctx.organization_id).first()
    if role is None:
        raise BusinessRuleError("Rôle inconnu.", field_errors={"role": ["Introuvable."]})
    return role


@transaction.atomic
def add_farm_member(
    ctx: TenantContext, *, user_id: uuid.UUID, role_id: uuid.UUID, **extra: Any
) -> FarmMembership:
    """Grant an existing organization member access to this farm."""
    ctx.require("members.manage")
    role = _get_role(ctx, role_id)
    if not OrganizationMembership.objects.filter(
        organization_id=ctx.organization_id,
        user_id=user_id,
        status=OrganizationMembership.Status.ACTIVE,
    ).exists():
        # Do not reveal whether the user exists elsewhere.
        raise BusinessRuleError(
            "Utilisateur inconnu dans l'organisation : invitez-le d'abord.",
            field_errors={"user": ["Introuvable."]},
        )
    if FarmMembership.objects.filter(farm_id=ctx.require_farm_id, user_id=user_id).exists():
        raise BusinessRuleError(
            "Cet utilisateur est déjà membre de l'exploitation.",
            field_errors={"user": ["Déjà membre."]},
        )
    membership = FarmMembership(
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        user_id=user_id,
        role=role,
        **extra,
    )
    membership.full_clean()
    membership.save()
    record_event(
        action="farm_membership.created",
        actor=ctx.user,
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        entity_type="farms.farm_membership",
        entity_id=membership.id,
        after={"user": str(user_id), "role": role.code},
    )
    return membership


@transaction.atomic
def update_farm_member(
    ctx: TenantContext,
    *,
    membership_id: uuid.UUID,
    expected_version: int,
    changes: dict[str, Any],
) -> FarmMembership:
    ctx.require("members.manage")
    membership = (
        FarmMembership.objects.select_for_update()
        .filter(id=membership_id, farm_id=ctx.require_farm_id)
        .first()
    )
    if membership is None:
        raise NotFoundError()
    check_version(membership, expected_version)
    if "role" in changes:
        changes = {**changes, "role": _get_role(ctx, changes["role"])}
    diff = apply_changes(membership, changes)
    if diff:
        membership.full_clean()
        membership.version += 1
        membership.save()
        before, after = diff_to_before_after(
            {k: [getattr(v[0], "code", v[0]), getattr(v[1], "code", v[1])] for k, v in diff.items()}
        )
        record_event(
            action="farm_membership.updated",
            actor=ctx.user,
            organization_id=ctx.organization_id,
            farm_id=ctx.require_farm_id,
            entity_type="farms.farm_membership",
            entity_id=membership.id,
            before=before,
            after=after,
        )
    return membership
