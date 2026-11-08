"""Traceability of AI runs, suggestions and calls (FR-100..107).

The AI module only writes here and through the business services as DRAFTS;
it can never validate a technical data set or a plan.
"""

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from apps.core.models import OrgScopedModel, TimestampedModel, UUIDModel


class AIRun(OrgScopedModel):
    class Kind(models.TextChoices):
        EXTRACTION = "extraction", "Extraction de fiche technique"
        PLAN_DRAFT = "plan_draft", "Brouillon de plan"

    class Status(models.TextChoices):
        RUNNING = "running", "En cours"
        SUCCEEDED = "succeeded", "Terminé"
        FAILED = "failed", "Échec"
        UNAVAILABLE = "unavailable", "Assistant indisponible"

    farm = models.ForeignKey(
        "farms.Farm", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)
    provider = models.CharField(max_length=50)
    model = models.CharField(max_length=100, blank=True)
    prompt_version = models.CharField(max_length=20)
    schema_version = models.CharField(max_length=20)
    document = models.ForeignKey(
        "varieties.TechnicalDocument",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    data_set = models.ForeignKey(
        "varieties.TechnicalDataSet",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    plan_version = models.ForeignKey(
        "production_plans.PlanVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    input_snapshot = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    raw_output = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    missing_info = models.JSONField(default=list, encoder=DjangoJSONEncoder)
    rejected_items = models.JSONField(default=list, encoder=DjangoJSONEncoder)
    error_code = models.CharField(max_length=60, blank=True)
    error_message = models.TextField(blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.kind} {self.status}"


class AISuggestion(UUIDModel, TimestampedModel):
    """A value proposed by the AI for a plan field; must be decided by a human (FR-104/105)."""

    class Status(models.TextChoices):
        SUGGESTED = "suggested", "Proposée"
        ACCEPTED = "accepted", "Acceptée"
        MODIFIED = "modified", "Modifiée"
        REJECTED = "rejected", "Rejetée"

    run = models.ForeignKey(AIRun, on_delete=models.PROTECT, related_name="suggestions")
    plan_version = models.ForeignKey(
        "production_plans.PlanVersion", on_delete=models.PROTECT, related_name="+"
    )
    field_path = models.CharField(max_length=150)
    value = models.JSONField(null=True, encoder=DjangoJSONEncoder)
    rationale = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUGGESTED)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plan_version", "field_path"], name="ai_suggestion_unique_field"
            )
        ]

    def __str__(self) -> str:
        return f"{self.field_path} = {self.value} ({self.status})"


class AIRequestLog(models.Model):
    """One provider call: tokens, estimated cost, latency, errors (FR-107)."""

    id = models.BigAutoField(primary_key=True)
    organization_id = models.UUIDField()
    run = models.ForeignKey(AIRun, on_delete=models.PROTECT, related_name="requests")
    provider = models.CharField(max_length=50)
    model = models.CharField(max_length=100, blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    estimated_cost = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    cost_currency = models.CharField(max_length=3, default="USD")
    latency_ms = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20)
    error_code = models.CharField(max_length=60, blank=True)
    request_id = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["organization_id", "created_at"])]

    def __str__(self) -> str:
        return f"{self.provider}/{self.model} {self.status}"
