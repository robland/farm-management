"""Resolve an organization-scoped tenant context from server-side memberships."""

import uuid
from typing import Any

from apps.core.exceptions import NotFoundError
from apps.core.tenancy import TenantContext
from apps.organizations.models import Organization, OrganizationMembership, RolePermission


def _parse_uuid(value: Any) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError) as exc:
        raise NotFoundError() from exc


def resolve_org_context(user: Any, organization_id: Any) -> TenantContext:
    org_id = _parse_uuid(organization_id)
    membership = (
        OrganizationMembership.objects.select_related("organization")
        .filter(
            user=user,
            organization_id=org_id,
            status=OrganizationMembership.Status.ACTIVE,
            organization__status=Organization.Status.ACTIVE,
        )
        .first()
    )
    if membership is None or not user.is_active:
        raise NotFoundError()

    # Org-scoped resources: permissions are the union of the user's active
    # farm roles inside this organization.
    permissions = frozenset(
        RolePermission.objects.filter(
            role__farm_memberships__user=user,
            role__farm_memberships__status="active",
            role__farm_memberships__farm__organization_id=org_id,
            role__farm_memberships__farm__deleted_at__isnull=True,
        ).values_list("permission_code", flat=True)
    )
    return TenantContext(
        user=user,
        organization_id=org_id,
        is_org_admin=membership.is_org_admin,
        permissions=permissions,
    )
