"""Organization, role, membership and invitation business services."""

import hashlib
import secrets
import uuid
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.audit.services import diff_to_before_after, record_event
from apps.core.exceptions import BusinessRuleError, NotFoundError
from apps.core.tenancy import TenantContext
from apps.core.versioning import apply_changes, check_version
from apps.organizations.models import (
    Invitation,
    Organization,
    OrganizationMembership,
    Role,
    RolePermission,
)
from apps.organizations.permissions_catalog import DEFAULT_ROLES, is_valid_permission
from apps.users.models import User, normalize_email, normalize_phone

# Reserved code: only organization administrators hold it (never assignable to a role).
ORG_MANAGE = "organization.manage"


def _unique_slug(name: str) -> str:
    base = slugify(name)[:60] or "organisation"
    slug = base
    while Organization.objects.filter(slug=slug).exists():
        slug = f"{base}-{secrets.token_hex(3)}"
    return slug


def seed_default_roles(organization: Organization) -> list[Role]:
    roles = []
    for code, spec in DEFAULT_ROLES.items():
        role, _ = Role.objects.get_or_create(
            organization=organization,
            code=code,
            defaults={"name": spec["name"], "is_system": True},
        )
        RolePermission.objects.bulk_create(
            [RolePermission(role=role, permission_code=p) for p in spec["permissions"]],
            ignore_conflicts=True,
        )
        roles.append(role)
    return roles


@transaction.atomic
def create_organization(
    *,
    user: User,
    name: str,
    country: str,
    default_currency: str,
    default_timezone: str,
    default_locale: str = "fr",
) -> Organization:
    organization = Organization(
        name=name,
        slug=_unique_slug(name),
        country=country,
        default_currency=default_currency,
        default_timezone=default_timezone,
        default_locale=default_locale,
    )
    organization.full_clean()
    organization.save()
    OrganizationMembership.objects.create(organization=organization, user=user, is_org_admin=True)
    seed_default_roles(organization)
    record_event(
        action="organization.created",
        actor=user,
        organization_id=organization.id,
        entity_type="organizations.organization",
        entity_id=organization.id,
        after={"name": name},
    )
    return organization


@transaction.atomic
def update_organization(
    ctx: TenantContext, *, expected_version: int, changes: dict[str, Any]
) -> Organization:
    ctx.require(ORG_MANAGE)
    organization = Organization.objects.select_for_update().get(id=ctx.organization_id)
    check_version(organization, expected_version)
    diff = apply_changes(organization, changes)
    if diff:
        organization.full_clean()
        organization.version += 1
        organization.save()
        before, after = diff_to_before_after(diff)
        record_event(
            action="organization.updated",
            actor=ctx.user,
            organization_id=organization.id,
            entity_type="organizations.organization",
            entity_id=organization.id,
            before=before,
            after=after,
        )
    return organization


def _validate_permissions(codes: list[str]) -> list[str]:
    invalid = sorted({c for c in codes if not is_valid_permission(c)})
    if invalid:
        raise BusinessRuleError(
            "Permissions inconnues.", field_errors={"permissions": [", ".join(invalid)]}
        )
    return sorted(set(codes))


@transaction.atomic
def create_role(
    ctx: TenantContext, *, code: str, name: str, description: str, permissions: list[str]
) -> Role:
    ctx.require(ORG_MANAGE)
    codes = _validate_permissions(permissions)
    try:
        with transaction.atomic():
            role = Role.objects.create(
                organization_id=ctx.organization_id, code=code, name=name, description=description
            )
    except IntegrityError as exc:
        raise BusinessRuleError(
            "Ce code de rôle existe déjà.", field_errors={"code": ["Déjà utilisé."]}
        ) from exc
    RolePermission.objects.bulk_create(
        [RolePermission(role=role, permission_code=c) for c in codes]
    )
    record_event(
        action="role.created",
        actor=ctx.user,
        organization_id=ctx.organization_id,
        entity_type="organizations.role",
        entity_id=role.id,
        after={"code": code, "permissions": codes},
    )
    return role


@transaction.atomic
def update_role(
    ctx: TenantContext,
    *,
    role_id: uuid.UUID,
    expected_version: int,
    changes: dict[str, Any],
    permissions: list[str] | None,
) -> Role:
    ctx.require(ORG_MANAGE)
    role = (
        Role.objects.select_for_update()
        .filter(id=role_id, organization_id=ctx.organization_id)
        .first()
    )
    if role is None:
        raise NotFoundError()
    check_version(role, expected_version)
    diff = apply_changes(role, changes)
    before, after = diff_to_before_after(diff)
    if permissions is not None:
        codes = _validate_permissions(permissions)
        current = sorted(role.permission_codes())
        if codes != current:
            role.permissions.all().delete()
            RolePermission.objects.bulk_create(
                [RolePermission(role=role, permission_code=c) for c in codes]
            )
            before["permissions"], after["permissions"] = current, codes
    if after:
        role.version += 1
        role.save()
        record_event(
            action="role.updated",
            actor=ctx.user,
            organization_id=ctx.organization_id,
            entity_type="organizations.role",
            entity_id=role.id,
            before=before,
            after=after,
        )
    return role


@transaction.atomic
def delete_role(ctx: TenantContext, *, role_id: uuid.UUID) -> None:
    ctx.require(ORG_MANAGE)
    role = Role.objects.filter(id=role_id, organization_id=ctx.organization_id).first()
    if role is None:
        raise NotFoundError()
    if role.is_system:
        raise BusinessRuleError("Un rôle initial ne peut pas être supprimé.")
    if role.farm_memberships.exists() or Invitation.objects.filter(role=role).exists():
        raise BusinessRuleError("Ce rôle est utilisé et ne peut pas être supprimé.")
    record_event(
        action="role.deleted",
        actor=ctx.user,
        organization_id=ctx.organization_id,
        entity_type="organizations.role",
        entity_id=role.id,
        before={"code": role.code},
    )
    role.delete()


@transaction.atomic
def update_org_membership(
    ctx: TenantContext,
    *,
    membership_id: uuid.UUID,
    expected_version: int,
    changes: dict[str, Any],
) -> OrganizationMembership:
    """Change admin flag or status. Disabling also disables all farm memberships (FR-003)."""
    from apps.farms.models import FarmMembership

    ctx.require(ORG_MANAGE)
    membership = (
        OrganizationMembership.objects.select_for_update()
        .filter(id=membership_id, organization_id=ctx.organization_id)
        .first()
    )
    if membership is None:
        raise NotFoundError()
    check_version(membership, expected_version)
    was_active_admin = (
        membership.is_org_admin and membership.status == OrganizationMembership.Status.ACTIVE
    )
    diff = apply_changes(membership, changes)
    if not diff:
        return membership
    is_active_admin = (
        membership.is_org_admin and membership.status == OrganizationMembership.Status.ACTIVE
    )
    if was_active_admin and not is_active_admin:
        remaining_admins = (
            OrganizationMembership.objects.select_for_update()
            .filter(
                organization_id=ctx.organization_id,
                is_org_admin=True,
                status=OrganizationMembership.Status.ACTIVE,
            )
            .exclude(id=membership.id)
            .count()
        )
        if remaining_admins == 0:
            raise BusinessRuleError(
                "L'organisation doit conserver au moins un administrateur actif."
            )
    membership.version += 1
    membership.save()
    if membership.status == OrganizationMembership.Status.DISABLED:
        FarmMembership.objects.filter(
            organization_id=ctx.organization_id, user_id=membership.user_id
        ).update(status=FarmMembership.Status.DISABLED)
    before, after = diff_to_before_after(diff)
    record_event(
        action="org_membership.updated",
        actor=ctx.user,
        organization_id=ctx.organization_id,
        entity_type="organizations.organization_membership",
        entity_id=membership.id,
        before=before,
        after=after,
    )
    return membership


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@transaction.atomic
def create_invitation(
    ctx: TenantContext,
    *,
    email: str | None,
    phone: str | None,
    farm_id: uuid.UUID | None,
    role_id: uuid.UUID | None,
    make_org_admin: bool = False,
) -> tuple[Invitation, str]:
    """Return the invitation and the plaintext token (shown once, only its hash is stored)."""
    from apps.farms.models import Farm

    email, phone = normalize_email(email), normalize_phone(phone)
    if not email and not phone:
        raise BusinessRuleError(
            "Un e-mail ou un téléphone est obligatoire.", field_errors={"email": ["Obligatoire."]}
        )
    if make_org_admin or farm_id is None:
        ctx.require(ORG_MANAGE)
    farm = None
    if farm_id is not None:
        farm = Farm.objects.filter(
            id=farm_id, organization_id=ctx.organization_id, deleted_at__isnull=True
        ).first()
        if farm is None:
            raise NotFoundError()
        if not ctx.is_org_admin:
            from apps.farms.access import resolve_farm_context

            resolve_farm_context(ctx.user, farm.id).require("members.manage")
    role = None
    if role_id is not None:
        role = Role.objects.filter(id=role_id, organization_id=ctx.organization_id).first()
        if role is None:
            raise BusinessRuleError("Rôle inconnu.", field_errors={"role": ["Introuvable."]})
    if farm is not None and role is None:
        raise BusinessRuleError("Un rôle est obligatoire.", field_errors={"role": ["Obligatoire."]})

    token = secrets.token_urlsafe(32)
    invitation = Invitation.objects.create(
        organization_id=ctx.organization_id,
        farm=farm,
        role=role,
        make_org_admin=make_org_admin,
        email=email,
        phone=phone,
        token_hash=_hash_token(token),
        expires_at=timezone.now() + timedelta(days=settings.FMS_INVITATION_TTL_DAYS),
        invited_by=ctx.user,
    )
    record_event(
        action="invitation.created",
        actor=ctx.user,
        organization_id=ctx.organization_id,
        farm_id=farm.id if farm else None,
        entity_type="organizations.invitation",
        entity_id=invitation.id,
        after={"email": email, "phone": phone, "role": role.code if role else None},
    )
    return invitation, token


@transaction.atomic
def revoke_invitation(ctx: TenantContext, *, invitation_id: uuid.UUID) -> Invitation:
    ctx.require(ORG_MANAGE)
    invitation = (
        Invitation.objects.select_for_update()
        .filter(id=invitation_id, organization_id=ctx.organization_id)
        .first()
    )
    if invitation is None:
        raise NotFoundError()
    if invitation.accepted_at is not None:
        raise BusinessRuleError("Invitation déjà acceptée.")
    if invitation.revoked_at is None:
        invitation.revoked_at = timezone.now()
        invitation.save(update_fields=["revoked_at"])
    return invitation


@transaction.atomic
def accept_invitation(
    *,
    token: str,
    user: User | None,
    full_name: str = "",
    password: str = "",
) -> tuple[Invitation, User]:
    """Accept with the current user, or create the account if no user is authenticated."""
    from django.contrib.auth.password_validation import validate_password

    from apps.farms.models import FarmMembership

    invitation = (
        Invitation.objects.select_for_update().filter(token_hash=_hash_token(token)).first()
    )
    if (
        invitation is None
        or invitation.revoked_at is not None
        or invitation.accepted_at is not None
        or invitation.expires_at < timezone.now()
    ):
        raise BusinessRuleError("Invitation invalide ou expirée.", details={"reason": "invalid"})

    if user is None:
        existing = User.objects.filter(
            **({"email": invitation.email} if invitation.email else {"phone": invitation.phone})
        ).first()
        if existing is not None:
            raise BusinessRuleError(
                "Un compte existe déjà : connectez-vous pour accepter l'invitation.",
                details={"reason": "account_exists"},
            )
        if not full_name or not password:
            raise BusinessRuleError(
                "Nom et mot de passe obligatoires.",
                field_errors={"full_name": ["Obligatoire."], "password": ["Obligatoire."]},
            )
        validate_password(password)
        user = User.objects.create_user(
            invitation.email, password, phone=invitation.phone, full_name=full_name
        )
    else:
        matches = (invitation.email and user.email == invitation.email) or (
            invitation.phone and user.phone == invitation.phone
        )
        if not matches:
            raise BusinessRuleError(
                "Cette invitation est destinée à un autre compte.",
                details={"reason": "identity_mismatch"},
            )

    org_membership, created = OrganizationMembership.objects.get_or_create(
        organization_id=invitation.organization_id,
        user=user,
        defaults={"is_org_admin": invitation.make_org_admin},
    )
    if not created:
        org_membership.status = OrganizationMembership.Status.ACTIVE
        org_membership.is_org_admin = org_membership.is_org_admin or invitation.make_org_admin
        org_membership.version += 1
        org_membership.save()
    if invitation.farm_id is not None and invitation.role_id is not None:
        farm_membership = (
            FarmMembership.objects.select_for_update()
            .filter(farm_id=invitation.farm_id, user=user)
            .first()
        )
        if farm_membership is None:
            FarmMembership.objects.create(
                organization_id=invitation.organization_id,
                farm_id=invitation.farm_id,
                user=user,
                role_id=invitation.role_id,
            )
        else:
            farm_membership.role_id = invitation.role_id
            farm_membership.status = FarmMembership.Status.ACTIVE
            farm_membership.version += 1
            farm_membership.save()
    invitation.accepted_at = timezone.now()
    invitation.accepted_by = user
    invitation.save(update_fields=["accepted_at", "accepted_by"])
    record_event(
        action="invitation.accepted",
        actor=user,
        organization_id=invitation.organization_id,
        farm_id=invitation.farm_id,
        entity_type="organizations.invitation",
        entity_id=invitation.id,
    )
    return invitation, user
