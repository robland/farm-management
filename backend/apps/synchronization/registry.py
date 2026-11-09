"""Registry of synchronizable entity types.

Each business module declares its handlers in `<app>/sync.py`, imported from
its AppConfig.ready(). A handler only adapts the sync protocol to the
module's existing services: there is a single write path (ARCHITECTURE.md §2.2).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from django.db import models
from rest_framework import serializers

from apps.core.tenancy import TenantContext


class MergeStrategy(Enum):
    """OFFLINE_SYNC.md §6."""

    THREE_WAY = "three_way"  # descriptive data: field-level merge
    STRICT = "strict"  # any stale version is a conflict
    APPEND_ONLY = "append_only"  # events / financial: creation only, never updated


class SyncConflictRaised(Exception):
    """Raised by a handler (or a command) when an operation must become a conflict.

    Nothing of the operation is applied; a SyncConflict is recorded and returned.
    """

    def __init__(
        self,
        conflict_type: str,
        *,
        fields: list[str] | None = None,
        server: dict[str, Any] | None = None,
        message: str = "",
    ) -> None:
        super().__init__(conflict_type)
        self.conflict_type = conflict_type
        self.fields = fields or []
        self.server = server or {}
        self.message = message


CreateFn = Callable[..., tuple[Any, bool]]
UpdateFn = Callable[..., Any]
DeleteFn = Callable[..., Any]
CommandFn = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class EntityHandler:
    entity_type: str
    model: type[models.Model]
    serializer_class: type[serializers.Serializer]
    read_permission: str
    # Checked before anything else so that conflicts never disclose server state
    # to users who may not write (commands may check finer permissions themselves).
    write_permission: str
    strategy: MergeStrategy
    create: CreateFn | None = None
    update: UpdateFn | None = None
    delete: DeleteFn | None = None
    commands: dict[str, CommandFn] = field(default_factory=dict)
    # Attribute holding the farm id ("farm_id", or "id" for the farm itself).
    farm_attr: str = "farm_id"
    # Keyword used by the update/delete services for the entity id.
    id_kwarg: str = "entity_id"
    # Relations read by the serializer: loaded in one query per page of the pull (no N+1).
    prefetch: tuple[str, ...] = ()

    def queryset_for(self, ctx: TenantContext) -> models.QuerySet[Any]:
        queryset = self.model._default_manager.filter(**{self.farm_attr: ctx.require_farm_id})
        return queryset.prefetch_related(*self.prefetch) if self.prefetch else queryset

    def serialize(self, instance: Any, ctx: TenantContext) -> dict[str, Any]:
        return dict(self.serializer_class(instance, context={"tenant": ctx}).data)


_REGISTRY: dict[str, EntityHandler] = {}


def register(handler: EntityHandler) -> EntityHandler:
    if handler.entity_type in _REGISTRY:
        raise RuntimeError(f"Entity type already registered: {handler.entity_type}")
    _REGISTRY[handler.entity_type] = handler
    return handler


def get_handler(entity_type: str) -> EntityHandler | None:
    return _REGISTRY.get(entity_type)


def all_handlers() -> list[EntityHandler]:
    return list(_REGISTRY.values())
