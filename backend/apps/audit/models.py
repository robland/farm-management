from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models


class AuditEvent(models.Model):
    """Append-only journal of sensitive actions (NFR-002).

    UPDATE and DELETE are blocked by a database trigger (migration 0002).
    """

    id = models.BigAutoField(primary_key=True)
    organization_id = models.UUIDField(null=True, blank=True)
    farm_id = models.UUIDField(null=True, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    action = models.CharField(max_length=100)
    entity_type = models.CharField(max_length=100)
    entity_id = models.UUIDField(null=True, blank=True)
    before = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    after = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    request_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["organization_id", "-created_at"]),
            models.Index(fields=["entity_type", "entity_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} {self.entity_type}:{self.entity_id}"
