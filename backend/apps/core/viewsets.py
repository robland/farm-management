"""Base view machinery enforcing the tenant context (ARCHITECTURE.md §6.2).

Subclasses declare `permission_map = {action: permission_code}`; a key
`"action:METHOD"` takes precedence for multi-method actions. An action
missing from the map is denied (fail closed).
"""

import uuid
from functools import cached_property
from typing import Any, cast

from django.contrib.auth.models import AnonymousUser
from rest_framework import viewsets
from rest_framework.request import Request

from apps.core.exceptions import PermissionDeniedError
from apps.core.tenancy import TenantContext
from apps.users.models import User

# permission_map value for actions whose permission depends on the payload and is
# enforced by the service itself (e.g. file upload, where it depends on the purpose).
CHECKED_IN_SERVICE = "@service"


def request_user(request: Request) -> User:
    """Authenticated user of a request (views are protected by IsAuthenticated)."""
    return cast(User, request.user)


class TenantGenericViewSet(viewsets.GenericViewSet):
    permission_map: dict[str, str] = {}

    def resolve_tenant(self) -> TenantContext:  # pragma: no cover - abstract
        raise NotImplementedError

    @cached_property
    def tenant(self) -> TenantContext:
        if getattr(self, "swagger_fake_view", False):
            # OpenAPI generation inspects querysets without a request: use an empty tenant
            # (nil ids, no permission) so that no real data can ever be reached.
            return TenantContext(
                user=cast(User, AnonymousUser()),
                organization_id=uuid.UUID(int=0),
                farm_id=uuid.UUID(int=0),
            )
        return self.resolve_tenant()

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        # Resolving the tenant first means a foreign tenant yields 404 before
        # any permission information is disclosed.
        context = self.tenant
        if request.method == "OPTIONS":
            return
        action_name = self.action or ""
        code = self.permission_map.get(
            f"{action_name}:{request.method}"
        ) or self.permission_map.get(action_name)
        if code is None:
            raise PermissionDeniedError(f"undeclared:{self.action}")
        if code != CHECKED_IN_SERVICE:
            context.require(code)

    def get_serializer_context(self) -> dict[str, Any]:
        context = dict(super().get_serializer_context())
        # drf-spectacular instantiates views without a real request.
        if not getattr(self, "swagger_fake_view", False):
            context["tenant"] = self.tenant
        return context
