import uuid

from apps.core.tenancy import TenantContext
from apps.core.viewsets import TenantGenericViewSet, request_user
from apps.farms.access import resolve_farm_context


class FarmScopedGenericViewSet(TenantGenericViewSet):
    """Resolves the tenant from the `farm_id` URL kwarg."""

    def resolve_tenant(self) -> TenantContext:
        return resolve_farm_context(request_user(self.request), self.kwargs.get("farm_id"))

    @property
    def farm_id(self) -> uuid.UUID:
        return self.tenant.require_farm_id
