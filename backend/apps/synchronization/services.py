import uuid
from typing import Any

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.audit.services import record_event
from apps.core.exceptions import BusinessRuleError, NotFoundError
from apps.core.tenancy import TenantContext
from apps.synchronization.models import ChangeLog, FarmSyncState, SyncConflict

CONFLICT_SUPERVISOR_PERMISSION = "farm.manage"


def record_change(
    *,
    farm_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    entity_version: int,
    required_permission: str,
    operation: str = ChangeLog.Operation.UPSERT,
    origin_op_id: uuid.UUID | None = None,
) -> ChangeLog:
    """Append a change to the farm journal.

    Must be called inside the business transaction, as late as possible:
    the row lock on FarmSyncState serialises sequence allocation per farm so
    that sequence order equals commit order (OFFLINE_SYNC.md §5).
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("record_change() must run inside transaction.atomic().")
    FarmSyncState.objects.get_or_create(farm_id=farm_id)
    state = FarmSyncState.objects.select_for_update().get(farm_id=farm_id)
    state.last_seq += 1
    state.save(update_fields=["last_seq"])
    return ChangeLog.objects.create(
        farm_id=farm_id,
        seq=state.last_seq,
        entity_type=entity_type,
        entity_id=entity_id,
        operation=operation,
        entity_version=entity_version,
        required_permission=required_permission,
        origin_op_id=origin_op_id,
    )


def flag_conflict(
    ctx: TenantContext,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    conflict_type: str,
    message: str,
    client_payload: dict[str, Any] | None = None,
    server_snapshot: dict[str, Any] | None = None,
) -> SyncConflict:
    """Record a conflict for review WITHOUT blocking the operation.

    Used for append-only events that are kept but need a human decision (report on a
    cancelled task, probable financial duplicate...), OFFLINE_SYNC.md §6.2 and §7.
    """
    return SyncConflict.objects.create(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        raised_for=ctx.user,
        entity_type=entity_type,
        entity_id=entity_id,
        conflict_type=conflict_type,
        client_payload=client_payload or {},
        server_snapshot=server_snapshot or {},
        message=message,
    )


def visible_conflicts(ctx: TenantContext) -> QuerySet[SyncConflict]:
    """A user sees the conflicts raised for them; supervisors see all the farm's conflicts."""
    queryset = SyncConflict.objects.filter(farm_id=ctx.require_farm_id)
    if not ctx.has_perm(CONFLICT_SUPERVISOR_PERMISSION):
        queryset = queryset.filter(Q(raised_for=ctx.user))
    return queryset


@transaction.atomic
def resolve_conflict(
    ctx: TenantContext, *, conflict_id: uuid.UUID, resolution: str, note: str = ""
) -> SyncConflict:
    conflict = visible_conflicts(ctx).select_for_update().filter(id=conflict_id).first()
    if conflict is None:
        raise NotFoundError()
    if conflict.status != SyncConflict.Status.OPEN:
        raise BusinessRuleError("Ce conflit est déjà traité.")
    if resolution not in SyncConflict.Resolution.values and resolution != "dismiss":
        raise BusinessRuleError("Résolution inconnue.", field_errors={"resolution": ["Invalide."]})
    if resolution == "dismiss":
        conflict.status = SyncConflict.Status.DISMISSED
    else:
        conflict.status = SyncConflict.Status.RESOLVED
        conflict.resolution = resolution
    conflict.resolved_by = ctx.user
    conflict.resolved_at = timezone.now()
    conflict.save()
    record_event(
        action="sync_conflict.resolved",
        actor=ctx.user,
        organization_id=ctx.organization_id,
        farm_id=ctx.farm_id,
        entity_type="synchronization.sync_conflict",
        entity_id=conflict.id,
        after={"resolution": resolution, "note": note},
    )
    return conflict
