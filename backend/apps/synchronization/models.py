"""Server-side synchronization journal (docs/architecture/OFFLINE_SYNC.md)."""

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models


class FarmSyncState(models.Model):
    """Per-farm monotonic sequence, incremented under row lock in the writing transaction."""

    farm = models.OneToOneField(
        "farms.Farm", on_delete=models.PROTECT, primary_key=True, related_name="+"
    )
    last_seq = models.BigIntegerField(default=0)
    # Cursors older than this were compacted: clients must reload (HTTP 410).
    compacted_before_seq = models.BigIntegerField(default=0)

    def __str__(self) -> str:
        return f"{self.farm_id}@{self.last_seq}"


class ChangeLog(models.Model):
    class Operation(models.TextChoices):
        UPSERT = "upsert", "Création ou modification"
        DELETE = "delete", "Suppression"

    id = models.BigAutoField(primary_key=True)
    farm = models.ForeignKey("farms.Farm", on_delete=models.PROTECT, related_name="+")
    seq = models.BigIntegerField()
    entity_type = models.CharField(max_length=100)
    entity_id = models.UUIDField()
    operation = models.CharField(max_length=10, choices=Operation.choices)
    entity_version = models.PositiveIntegerField()
    required_permission = models.CharField(max_length=100)
    changed_at = models.DateTimeField(auto_now_add=True)
    origin_op_id = models.UUIDField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["farm", "seq"], name="changelog_farm_seq_unique")
        ]
        indexes = [models.Index(fields=["entity_type", "entity_id"])]

    def __str__(self) -> str:
        return f"{self.farm_id}#{self.seq} {self.operation} {self.entity_type}:{self.entity_id}"


class SyncOperationReceipt(models.Model):
    """Idempotency record of a pushed operation: `op_id` is the client's idempotency key."""

    class Status(models.TextChoices):
        APPLIED = "applied", "Appliquée"
        REJECTED = "rejected", "Refusée"
        CONFLICT = "conflict", "Conflit"

    op_id = models.UUIDField(primary_key=True)
    organization_id = models.UUIDField()
    farm = models.ForeignKey("farms.Farm", on_delete=models.PROTECT, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    device = models.ForeignKey(
        "users.Device", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    entity_type = models.CharField(max_length=100)
    entity_id = models.UUIDField()
    op_type = models.CharField(max_length=20)
    command = models.CharField(max_length=100, blank=True)
    base_version = models.PositiveIntegerField(null=True, blank=True)
    payload_sha256 = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=Status.choices)
    result = models.JSONField(encoder=DjangoJSONEncoder)
    client_created_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["farm", "received_at"]),
            models.Index(fields=["entity_type", "entity_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.op_id} {self.status}"


class SyncConflict(models.Model):
    class ConflictType(models.TextChoices):
        STALE_VERSION = "stale_version", "Version obsolète"
        FIELD_CONFLICT = "field_conflict", "Conflit de champs"
        INVALID_TRANSITION = "invalid_transition", "Transition invalide"
        POSSIBLE_DUPLICATE = "possible_duplicate", "Doublon possible"
        RULE_VIOLATION = "rule_violation", "Règle métier"

    class Status(models.TextChoices):
        OPEN = "open", "Ouvert"
        RESOLVED = "resolved", "Résolu"
        DISMISSED = "dismissed", "Ignoré"

    class Resolution(models.TextChoices):
        KEEP_SERVER = "keep_server", "Conserver la version serveur"
        APPLY_CLIENT = "apply_client", "Appliquer la version client"
        MERGED = "merged", "Fusion"
        MANUAL = "manual", "Traitement manuel"

    id = models.UUIDField(primary_key=True)
    organization_id = models.UUIDField()
    farm = models.ForeignKey("farms.Farm", on_delete=models.PROTECT, related_name="+")
    receipt = models.OneToOneField(
        SyncOperationReceipt,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="conflict",
    )
    raised_for = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    entity_type = models.CharField(max_length=100)
    entity_id = models.UUIDField()
    conflict_type = models.CharField(max_length=30, choices=ConflictType.choices)
    fields = models.JSONField(default=list, encoder=DjangoJSONEncoder)
    client_payload = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    server_snapshot = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    message = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    resolution = models.CharField(max_length=20, choices=Resolution.choices, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["farm", "status"])]

    def __str__(self) -> str:
        return f"{self.conflict_type} {self.entity_type}:{self.entity_id}"
