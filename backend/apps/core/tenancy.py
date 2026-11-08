"""Tenant context carried through views and services.

The context is resolved server-side from the authenticated user and the
memberships stored in the database. Identifiers sent by clients are never
trusted on their own (ARCHITECTURE.md §6.2).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from apps.core.exceptions import PermissionDeniedError

if TYPE_CHECKING:
    from apps.users.models import User


@dataclass(frozen=True)
class TenantContext:
    user: User
    organization_id: uuid.UUID
    farm_id: uuid.UUID | None = None
    is_org_admin: bool = False
    permissions: frozenset[str] = field(default_factory=frozenset)

    def has_perm(self, code: str) -> bool:
        return self.is_org_admin or code in self.permissions

    def require(self, code: str) -> None:
        if not self.has_perm(code):
            raise PermissionDeniedError(code)

    @property
    def require_farm_id(self) -> uuid.UUID:
        if self.farm_id is None:
            raise RuntimeError("This operation requires a farm-scoped tenant context.")
        return self.farm_id
