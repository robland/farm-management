"""Push protocol: idempotent application of client operations (OFFLINE_SYNC.md §4.2, §6).

Receipt policy: only outcomes that changed (or deliberately did not change)
server state are stored, i.e. `applied` and `conflict`. Rejections leave no
trace in the database, so a rejected operation can be retried with the same
op_id once its cause is fixed (permission granted, dependency applied...).
"""

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, connection, transaction
from rest_framework import serializers

from apps.core.exceptions import DomainError, NotFoundError
from apps.core.tenancy import TenantContext
from apps.farms.access import resolve_farm_context
from apps.synchronization.models import SyncConflict, SyncOperationReceipt
from apps.synchronization.registry import (
    EntityHandler,
    MergeStrategy,
    SyncConflictRaised,
    get_handler,
)
from apps.users.models import Device, User

_MISSING = object()


@dataclass
class IncomingOperation:
    op_id: uuid.UUID
    farm_id: uuid.UUID
    op_type: str
    entity_type: str
    entity_id: uuid.UUID
    payload: dict[str, Any] = field(default_factory=dict)
    base_version: int | None = None
    base_values: dict[str, Any] = field(default_factory=dict)
    command: str = ""
    created_at: datetime | None = None
    depends_on: list[uuid.UUID] = field(default_factory=list)
    author_id: uuid.UUID | None = None

    def sha256(self) -> str:
        canonical = json.dumps(
            {
                "farm_id": str(self.farm_id),
                "op_type": self.op_type,
                "entity_type": self.entity_type,
                "entity_id": str(self.entity_id),
                "payload": self.payload,
                "base_version": self.base_version,
                "base_values": self.base_values,
                "command": self.command,
            },
            sort_keys=True,
            cls=DjangoJSONEncoder,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


_Conflict = SyncConflictRaised


def rejected(
    op_id: uuid.UUID,
    code: str,
    message: str = "",
    *,
    retryable: bool = False,
    field_errors: Any = None,
) -> dict[str, Any]:
    return {
        "op_id": str(op_id),
        "status": SyncOperationReceipt.Status.REJECTED,
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "field_errors": field_errors or {},
        },
    }


def process_batch(
    user: User, device: Device | None, operations: list[IncomingOperation]
) -> list[dict[str, Any]]:
    not_applied: set[uuid.UUID] = set()
    results = []
    for op in operations:
        if any(dep in not_applied for dep in op.depends_on):
            result = rejected(op.op_id, "dependency_failed", "Une opération préalable a échoué.")
        else:
            result = process_operation(user, device, op)
        if result["status"] != SyncOperationReceipt.Status.APPLIED:
            not_applied.add(op.op_id)
        results.append(result)
    return results


def process_operation(user: User, device: Device | None, op: IncomingOperation) -> dict[str, Any]:
    digest = op.sha256()
    replay = _replay(user, op, digest)
    if replay is not None:
        return replay
    if op.author_id is not None and op.author_id != user.id:
        return rejected(op.op_id, "author_mismatch", "L'auteur doit être l'utilisateur connecté.")
    try:
        ctx = resolve_farm_context(user, op.farm_id)
    except NotFoundError:
        return rejected(op.op_id, "not_found", "Exploitation introuvable.")
    handler = get_handler(op.entity_type)
    if handler is None:
        return rejected(op.op_id, "unknown_entity_type", op.entity_type)

    try:
        with transaction.atomic():
            # Serialise concurrent deliveries of the same op_id, then re-check
            # the receipt: the first delivery wins, the others replay its result.
            _lock_op_id(op.op_id)
            replay = _replay(user, op, digest)
            if replay is not None:
                return replay
            try:
                with transaction.atomic():
                    outcome = _apply(handler, ctx, op)
                status = SyncOperationReceipt.Status.APPLIED
            except _Conflict as conflict:
                status = SyncOperationReceipt.Status.CONFLICT
                outcome = {"conflict": conflict}
            return _store_receipt(user, device, ctx, handler, op, digest, status, outcome)
    except IntegrityError:
        # Concurrent push of the same op_id: the other transaction won.
        replay = _replay(user, op, digest)
        if replay is not None:
            return replay
        return rejected(op.op_id, "integrity_error", "Conflit d'intégrité.", retryable=True)
    except DomainError as exc:
        return rejected(op.op_id, exc.code, exc.message, field_errors=exc.field_errors)
    except serializers.ValidationError as exc:
        return rejected(op.op_id, "validation_error", "Données invalides.", field_errors=exc.detail)


def _lock_op_id(op_id: uuid.UUID) -> None:
    """Transaction-scoped PostgreSQL advisory lock keyed on the op_id."""
    key = int.from_bytes(op_id.bytes[:8], "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])


def _replay(user: User, op: IncomingOperation, digest: str) -> dict[str, Any] | None:
    receipt = SyncOperationReceipt.objects.filter(op_id=op.op_id).first()
    if receipt is None:
        return None
    if receipt.user_id != user.id or receipt.payload_sha256 != digest:
        return rejected(op.op_id, "idempotency_key_reused", "Identifiant d'opération déjà utilisé.")
    return {**receipt.result, "replayed": True}


def _store_receipt(
    user: User,
    device: Device | None,
    ctx: TenantContext,
    handler: EntityHandler,
    op: IncomingOperation,
    digest: str,
    status: str,
    outcome: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "op_id": str(op.op_id),
        "status": status,
        "entity_type": op.entity_type,
        "entity_id": str(op.entity_id),
    }
    conflict: _Conflict | None = outcome.pop("conflict", None)
    if conflict is None:
        result.update(outcome)
    else:
        conflict_id = uuid.uuid4()
        result.update(
            conflict_id=str(conflict_id),
            conflict_type=conflict.conflict_type,
            fields=conflict.fields,
            server=conflict.server,
        )
    receipt = SyncOperationReceipt.objects.create(
        op_id=op.op_id,
        organization_id=ctx.organization_id,
        farm_id=ctx.require_farm_id,
        user=user,
        device=device,
        entity_type=op.entity_type,
        entity_id=op.entity_id,
        op_type=op.op_type,
        command=op.command,
        base_version=op.base_version,
        payload_sha256=digest,
        status=status,
        result=result,
        client_created_at=op.created_at,
    )
    if conflict is not None:
        SyncConflict.objects.create(
            id=conflict_id,
            organization_id=ctx.organization_id,
            farm_id=ctx.require_farm_id,
            receipt=receipt,
            raised_for=user,
            entity_type=op.entity_type,
            entity_id=op.entity_id,
            conflict_type=conflict.conflict_type,
            fields=conflict.fields,
            client_payload={
                "payload": op.payload,
                "base_values": op.base_values,
                "base_version": op.base_version,
            },
            server_snapshot=conflict.server,
            message=conflict.message,
        )
    # Round-trip through JSON so that the response equals a later replay.
    return json.loads(json.dumps(result, cls=DjangoJSONEncoder))


# --- Operation application ---------------------------------------------------


def _apply(handler: EntityHandler, ctx: TenantContext, op: IncomingOperation) -> dict[str, Any]:
    if op.op_type == "create" and handler.create_permissions:
        if not any(ctx.has_perm(code) for code in handler.create_permissions):
            ctx.require(handler.create_permissions[0])
    else:
        ctx.require(handler.write_permission)
        ctx.require(handler.read_permission)
    if op.op_type == "create":
        return _apply_create(handler, ctx, op)
    if op.op_type == "update":
        return _apply_update(handler, ctx, op)
    if op.op_type == "delete":
        return _apply_delete(handler, ctx, op)
    if op.op_type == "command":
        command = handler.commands.get(op.command)
        if command is None:
            raise DomainError(f"Commande inconnue : {op.command}")
        return command(
            ctx,
            entity_id=op.entity_id,
            payload=op.payload,
            base_version=op.base_version,
            origin_op_id=op.op_id,
        )
    raise DomainError(f"Type d'opération inconnu : {op.op_type}")


def _check_payload_fields(serializer: serializers.Serializer, payload: dict[str, Any]) -> None:
    writable = {name for name, f in serializer.fields.items() if not f.read_only}
    unknown = sorted(set(payload) - writable)
    if unknown:
        raise serializers.ValidationError(
            {name: ["Champ inconnu ou non modifiable."] for name in unknown}
        )


def _apply_create(handler: EntityHandler, ctx: TenantContext, op: IncomingOperation) -> dict:
    if handler.create is None:
        raise DomainError("Création non autorisée pour ce type.")
    serializer = handler.serializer_class(
        data={**op.payload, "id": str(op.entity_id)}, context={"tenant": ctx}
    )
    _check_payload_fields(serializer, {**op.payload, "id": op.entity_id})
    serializer.is_valid(raise_exception=True)
    instance, created = handler.create(ctx, data=serializer.validated_data, origin_op_id=op.op_id)
    return {"entity_version": instance.version, "created": created}


def _lock(handler: EntityHandler, ctx: TenantContext, entity_id: uuid.UUID) -> Any:
    instance = handler.queryset_for(ctx).select_for_update().filter(pk=entity_id).first()
    if instance is None:
        raise NotFoundError()
    return instance


def _normalize(serializer: serializers.Serializer, name: str, value: Any) -> Any:
    if value is None:
        return None
    try:
        internal = serializer.fields[name].to_internal_value(value)
    except (serializers.ValidationError, KeyError):
        return value
    return getattr(internal, "pk", internal)


def _apply_update(handler: EntityHandler, ctx: TenantContext, op: IncomingOperation) -> dict:
    if handler.update is None or handler.strategy is MergeStrategy.APPEND_ONLY:
        raise DomainError("Modification non autorisée pour ce type (ajout seul).")
    if op.base_version is None:
        raise DomainError("base_version est obligatoire pour une modification.")
    instance = _lock(handler, ctx, op.entity_id)
    server = handler.serialize(instance, ctx)
    if getattr(instance, "deleted_at", None) is not None:
        raise _Conflict(
            "stale_version",
            server={**server, "deleted": True},
            message="L'élément a été supprimé sur le serveur.",
        )

    serializer = handler.serializer_class(
        instance, data=op.payload, partial=True, context={"tenant": ctx}
    )
    _check_payload_fields(serializer, op.payload)
    serializer.is_valid(raise_exception=True)
    changes = dict(serializer.validated_data)
    merged = False

    if op.base_version != instance.version:
        if handler.strategy is not MergeStrategy.THREE_WAY:
            raise _Conflict("stale_version", server=server)
        conflicting: list[str] = []
        for name in list(changes):
            current = _normalize(serializer, name, server.get(name))
            client = _normalize(serializer, name, op.payload[name])
            base = op.base_values.get(name, _MISSING)
            if base is _MISSING:
                conflicting.append(name)
            elif current == _normalize(serializer, name, base):
                continue  # only the client changed it
            elif current == client:
                changes.pop(name)  # both sides converged
            else:
                conflicting.append(name)
        if conflicting:
            raise _Conflict("field_conflict", fields=sorted(conflicting), server=server)
        merged = True

    updated = handler.update(
        ctx,
        **{handler.id_kwarg: instance.pk},
        expected_version=instance.version,
        changes=changes,
        origin_op_id=op.op_id,
    )
    return {"entity_version": updated.version, "merged": merged}


def _apply_delete(handler: EntityHandler, ctx: TenantContext, op: IncomingOperation) -> dict:
    if handler.delete is None or handler.strategy is MergeStrategy.APPEND_ONLY:
        raise DomainError("Suppression non autorisée pour ce type.")
    instance = _lock(handler, ctx, op.entity_id)
    if getattr(instance, "deleted_at", None) is not None:
        return {"entity_version": instance.version, "already_deleted": True}
    if op.base_version != instance.version:
        raise _Conflict("stale_version", server=handler.serialize(instance, ctx))
    deleted = handler.delete(
        ctx,
        **{handler.id_kwarg: instance.pk},
        expected_version=instance.version,
        origin_op_id=op.op_id,
    )
    return {"entity_version": deleted.version}
