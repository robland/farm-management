"""Resolve a farm-scoped tenant context from server-side memberships."""

from typing import Any

from django.db.models import Q
from django.utils import timezone

from apps.core.exceptions import NotFoundError
from apps.core.tenancy import TenantContext
from apps.farms.models import Farm, FarmMembership
from apps.organizations.access import _parse_uuid
from apps.organizations.models import Organization, OrganizationMembership


def resolve_farm_context(user: Any, farm_id: Any) -> TenantContext:
    fid = _parse_uuid(farm_id)
    if not user.is_active:
        raise NotFoundError()
    farm = (
        Farm.objects.filter(
            id=fid, deleted_at__isnull=True, organization__status=Organization.Status.ACTIVE
        )
        .only("id", "organization_id")
        .first()
    )
    if farm is None:
        raise NotFoundError()
    org_membership = OrganizationMembership.objects.filter(
        user=user,
        organization_id=farm.organization_id,
        status=OrganizationMembership.Status.ACTIVE,
    ).first()
    if org_membership is None:
        raise NotFoundError()

    if org_membership.is_org_admin:
        return TenantContext(
            user=user, organization_id=farm.organization_id, farm_id=farm.id, is_org_admin=True
        )

    today = timezone.localdate()
    membership = (
        FarmMembership.objects.select_related("role")
        .filter(farm=farm, user=user, status=FarmMembership.Status.ACTIVE)
        .first()
    )
    if (
        membership is None
        or (membership.valid_from and membership.valid_from > today)
        or (membership.valid_to and membership.valid_to < today)
    ):
        raise NotFoundError()
    return TenantContext(
        user=user,
        organization_id=farm.organization_id,
        farm_id=farm.id,
        permissions=frozenset(membership.role.permission_codes()),
    )


def accessible_farms(user: Any) -> Any:
    """Farms the user can open (used by the bootstrap endpoint `/farms/`)."""
    today = timezone.localdate()
    admin_orgs = OrganizationMembership.objects.filter(
        user=user, status="active", is_org_admin=True
    ).values("organization_id")
    member_orgs = OrganizationMembership.objects.filter(user=user, status="active").values(
        "organization_id"
    )
    direct = (
        FarmMembership.objects.filter(user=user, status="active")
        .exclude(valid_from__gt=today)
        .exclude(valid_to__lt=today)
        .values("farm_id")
    )
    return (
        Farm.objects.filter(
            deleted_at__isnull=True,
            organization__status=Organization.Status.ACTIVE,
            organization_id__in=member_orgs,
        )
        .filter(Q(organization_id__in=admin_orgs) | Q(id__in=direct))
        .select_related("organization")
        .order_by("organization__name", "name")
    )
