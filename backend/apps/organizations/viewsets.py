from apps.core.tenancy import TenantContext
from apps.core.viewsets import TenantGenericViewSet, request_user
from apps.organizations.access import resolve_org_context


class OrgScopedGenericViewSet(TenantGenericViewSet):
    """Resolves the tenant from the `organization_id` URL kwarg."""

    def resolve_tenant(self) -> TenantContext:
        return resolve_org_context(request_user(self.request), self.kwargs.get("organization_id"))
