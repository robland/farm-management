"""File upload and access control.

- The MIME type is detected from the content signature, never trusted from
  the client or the extension.
- Storage keys are opaque (no original name), files are never publicly served:
  downloads go through a permission check (ARCHITECTURE.md §10).
"""

import hashlib
import uuid
from typing import IO, Any

from django.conf import settings
from django.core.files.base import File
from django.core.files.storage import default_storage
from django.db import transaction

from apps.audit.services import record_event
from apps.core.exceptions import BusinessRuleError, IdentifierConflictError, NotFoundError
from apps.core.tenancy import TenantContext
from apps.files.models import StoredFile

P = StoredFile.Purpose

# (read permission, write permission, allowed MIME types, farm-scoped?)
POLICIES: dict[str, tuple[str, str, frozenset[str], bool]] = {
    P.TECHNICAL_SHEET: (
        "varieties.view",
        "varieties.edit",
        frozenset({"application/pdf", "image/jpeg", "image/png", "image/webp"}),
        False,
    ),
    P.PRODUCT_LABEL: (
        "inventory.view",
        "inventory.edit",
        frozenset({"application/pdf", "image/jpeg", "image/png", "image/webp"}),
        False,
    ),
    P.RECEIPT: (
        "finance.view",
        "finance.transaction.create",
        frozenset({"application/pdf", "image/jpeg", "image/png", "image/webp"}),
        True,
    ),
    P.TASK_PHOTO: (
        "tasks.view",
        "tasks.report",
        frozenset({"image/jpeg", "image/png", "image/webp"}),
        True,
    ),
    P.OBSERVATION_PHOTO: (
        "observations.view",
        "observations.create",
        frozenset({"image/jpeg", "image/png", "image/webp"}),
        True,
    ),
    P.OTHER: (
        "farm.view",
        "farm.manage",
        frozenset({"application/pdf", "image/jpeg", "image/png", "image/webp"}),
        True,
    ),
}

_SIGNATURES: list[tuple[bytes, int, str]] = [
    (b"%PDF-", 0, "application/pdf"),
    (b"\xff\xd8\xff", 0, "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", 0, "image/png"),
]


def detect_mime(head: bytes) -> str | None:
    for signature, offset, mime in _SIGNATURES:
        if head[offset : offset + len(signature)] == signature:
            return mime
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def max_size_bytes(purpose: str) -> int:
    megabytes = (
        settings.FMS_MAX_TECHNICAL_SHEET_MB
        if purpose == P.TECHNICAL_SHEET
        else settings.FMS_MAX_UPLOAD_MB
    )
    return int(megabytes) * 1024 * 1024


def _hash_and_size(stream: IO[bytes]) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    stream.seek(0)
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
        size += len(chunk)
    stream.seek(0)
    return digest.hexdigest(), size


@transaction.atomic
def upload_file(
    ctx: TenantContext,
    *,
    stream: IO[bytes],
    original_name: str,
    purpose: str,
    declared_mime: str = "",
    file_id: uuid.UUID | None = None,
) -> tuple[StoredFile, bool]:
    """Store a file. Returns (file, created); a replay with the same id and content is a no-op."""
    policy = POLICIES.get(purpose)
    if policy is None:
        raise BusinessRuleError(
            "Usage de fichier inconnu.", field_errors={"purpose": ["Invalide."]}
        )
    _, write_permission, allowed, farm_scoped = policy
    if farm_scoped and ctx.farm_id is None:
        raise BusinessRuleError("Ce type de fichier doit être déposé dans une exploitation.")
    if not farm_scoped and ctx.farm_id is not None:
        raise BusinessRuleError("Ce type de fichier se dépose au niveau de l'organisation.")
    ctx.require(write_permission)

    sha256, size = _hash_and_size(stream)
    if file_id is not None:
        existing = StoredFile.objects.filter(id=file_id).first()
        if existing is not None:
            if existing.organization_id != ctx.organization_id or existing.sha256 != sha256:
                raise IdentifierConflictError("Identifiant de fichier déjà utilisé.")
            return existing, False
    if size == 0:
        raise BusinessRuleError("Fichier vide.", field_errors={"file": ["Fichier vide."]})
    if size > max_size_bytes(purpose):
        raise BusinessRuleError("Fichier trop volumineux.", field_errors={"file": ["Trop gros."]})
    detected = detect_mime(stream.read(16))
    stream.seek(0)
    if detected is None or detected not in allowed:
        raise BusinessRuleError(
            "Type de fichier non autorisé.", field_errors={"file": ["Type non autorisé."]}
        )

    stored = StoredFile(
        id=file_id or uuid.uuid4(),
        organization_id=ctx.organization_id,
        farm_id=ctx.farm_id,
        original_name=original_name[:255],
        declared_mime=declared_mime[:100],
        detected_mime=detected,
        size_bytes=size,
        sha256=sha256,
        purpose=purpose,
        uploaded_by=ctx.user,
    )
    key = f"{ctx.organization_id}/{stored.id.hex}"
    stored.storage_key = default_storage.save(key, File(stream))
    stored.save()
    record_event(
        action="file.uploaded",
        actor=ctx.user,
        organization_id=ctx.organization_id,
        farm_id=ctx.farm_id,
        entity_type="files.stored_file",
        entity_id=stored.id,
        after={"purpose": purpose, "size": size, "sha256": sha256},
    )
    return stored, True


def get_file_for_read(ctx: TenantContext, file_id: Any) -> StoredFile:
    """Return the file if the context may read it. Foreign files are reported as not found."""
    try:
        fid = uuid.UUID(str(file_id))
    except ValueError as exc:
        raise NotFoundError() from exc
    stored = StoredFile.objects.filter(id=fid, organization_id=ctx.organization_id).first()
    if stored is None or stored.farm_id != ctx.farm_id:
        raise NotFoundError()
    if stored.status != StoredFile.Status.AVAILABLE:
        raise NotFoundError()
    ctx.require(POLICIES[stored.purpose][0])
    return stored


def require_usable_file(ctx: TenantContext, file_id: uuid.UUID, purpose: str) -> StoredFile:
    """For services linking a file to a business object (same tenant, expected purpose)."""
    stored = StoredFile.objects.filter(
        id=file_id, organization_id=ctx.organization_id, purpose=purpose
    ).first()
    if stored is None or (stored.farm_id is not None and stored.farm_id != ctx.farm_id):
        raise BusinessRuleError("Fichier introuvable.", field_errors={"file": ["Introuvable."]})
    return stored


def open_file(stored: StoredFile) -> IO[bytes]:
    return default_storage.open(stored.storage_key, "rb")
