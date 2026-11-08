import uuid
from typing import Any

from apps.audit.models import AuditEvent
from apps.core.middleware import get_request_id


def record_event(
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    actor: Any = None,
    organization_id: uuid.UUID | None = None,
    farm_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditEvent:
    actor_obj = actor if actor is not None and getattr(actor, "is_authenticated", False) else None
    request_id = get_request_id()
    return AuditEvent.objects.create(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor=actor_obj,
        organization_id=organization_id,
        farm_id=farm_id,
        before=before,
        after=after,
        request_id="" if request_id == "-" else request_id,
    )


def diff_to_before_after(diff: dict[str, list[Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    return {k: v[0] for k, v in diff.items()}, {k: v[1] for k, v in diff.items()}
