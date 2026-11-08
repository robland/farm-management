"""Pull protocol: change feed since a cursor (OFFLINE_SYNC.md §4.3, §5)."""

from typing import Any

from apps.core.exceptions import DomainError
from apps.core.tenancy import TenantContext
from apps.synchronization.models import ChangeLog, FarmSyncState
from apps.synchronization.registry import all_handlers, get_handler

MAX_LIMIT = 500


class CursorExpiredError(DomainError):
    code = "cursor_expired"
    http_status = 410


def pull_changes(ctx: TenantContext, *, cursor: int, limit: int) -> dict[str, Any]:
    farm_id = ctx.require_farm_id
    limit = max(1, min(limit, MAX_LIMIT))
    state = FarmSyncState.objects.filter(farm_id=farm_id).first()
    if state is not None and cursor < state.compacted_before_seq:
        raise CursorExpiredError(
            "Curseur trop ancien : rechargement complet nécessaire.",
            details={"min_cursor": state.compacted_before_seq},
        )

    entries = list(
        ChangeLog.objects.filter(farm_id=farm_id, seq__gt=cursor).order_by("seq")[: limit + 1]
    )
    has_more = len(entries) > limit
    entries = entries[:limit]
    next_cursor = entries[-1].seq if entries else cursor

    # Keep only the latest entry per entity in this page.
    latest: dict[tuple[str, Any], ChangeLog] = {}
    for entry in entries:
        latest[(entry.entity_type, entry.entity_id)] = entry
    visible = [
        e
        for e in sorted(latest.values(), key=lambda e: e.seq)
        if ctx.has_perm(e.required_permission)
    ]

    # Batch-load current states per entity type.
    instances: dict[tuple[str, Any], Any] = {}
    by_type: dict[str, list[Any]] = {}
    for entry in visible:
        if entry.operation == ChangeLog.Operation.UPSERT:
            by_type.setdefault(entry.entity_type, []).append(entry.entity_id)
    for entity_type, ids in by_type.items():
        handler = get_handler(entity_type)
        if handler is None:
            continue
        for instance in handler.queryset_for(ctx).filter(pk__in=ids):
            instances[(entity_type, instance.pk)] = instance

    changes = []
    for entry in visible:
        handler = get_handler(entry.entity_type)
        if handler is None:
            continue
        instance = instances.get((entry.entity_type, entry.entity_id))
        deleted = entry.operation == ChangeLog.Operation.DELETE or (
            instance is not None and getattr(instance, "deleted_at", None) is not None
        )
        if deleted or instance is None:
            changes.append(
                {
                    "seq": entry.seq,
                    "entity_type": entry.entity_type,
                    "entity_id": str(entry.entity_id),
                    "operation": "delete",
                    "version": entry.entity_version,
                }
            )
            continue
        changes.append(
            {
                "seq": entry.seq,
                "entity_type": entry.entity_type,
                "entity_id": str(entry.entity_id),
                "operation": "upsert",
                "version": instance.version,
                "data": handler.serialize(instance, ctx),
            }
        )

    # Entity types the user may no longer read: the client must purge them.
    purge = sorted(h.entity_type for h in all_handlers() if not ctx.has_perm(h.read_permission))
    return {
        "changes": changes,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "purge": purge,
        "server_seq": state.last_seq if state else 0,
    }
