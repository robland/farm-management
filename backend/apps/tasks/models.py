"""Tasks, assignments, status history, reports and input consumptions (FR-060..064, FR-082)."""

from django.conf import settings
from django.db import models

from apps.core.models import (
    AuthoredModel,
    FarmScopedModel,
    TimestampedModel,
    UUIDModel,
    VersionedModel,
)


class Team(FarmScopedModel, VersionedModel):
    name = models.CharField(max_length=120)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["farm", "name"], name="team_name_unique")]

    def __str__(self) -> str:
        return self.name


class Task(FarmScopedModel, AuthoredModel, VersionedModel):
    class Status(models.TextChoices):
        TODO = "todo", "À faire"
        IN_PROGRESS = "in_progress", "En cours"
        DONE = "done", "Réalisée"
        CANCELLED = "cancelled", "Annulée"
        TO_VERIFY = "to_verify", "À vérifier"
        # "En retard" (late) is derived from the dates, never stored (FR-062).

    class Origin(models.TextChoices):
        GENERATED = "generated", "Générée depuis le plan"
        MANUAL = "manual", "Créée manuellement"

    plan_version = models.ForeignKey(
        "production_plans.PlanVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    plan = models.ForeignKey(
        "production_plans.ProductionPlan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    crop_cycle = models.ForeignKey(
        "production_plans.CropCycle",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    parcel = models.ForeignKey(
        "fields.Parcel", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    task_type = models.CharField(max_length=40)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    planned_start_date = models.DateField()
    planned_end_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TODO)
    origin = models.CharField(max_length=20, choices=Origin.choices, default=Origin.MANUAL)
    source_ref = models.CharField(max_length=150, blank=True)
    generation_batch = models.UUIDField(null=True, blank=True)
    superseded_by = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    assignees = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="+")
    teams = models.ManyToManyField(Team, blank=True, related_name="tasks")

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(planned_end_date__gte=models.F("planned_start_date")),
                name="task_dates_valid",
            )
        ]
        indexes = [
            models.Index(fields=["farm", "status", "planned_start_date"]),
            models.Index(fields=["farm", "plan"]),
        ]
        ordering = ["planned_start_date", "title"]

    def __str__(self) -> str:
        return self.title


class TaskStatusEvent(models.Model):
    """Append-only history of status transitions."""

    id = models.BigAutoField(primary_key=True)
    task = models.ForeignKey(Task, on_delete=models.PROTECT, related_name="status_events")
    from_status = models.CharField(max_length=20)
    to_status = models.CharField(max_length=20)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    reason = models.TextField(blank=True)
    origin_op_id = models.UUIDField(null=True, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["occurred_at", "id"]

    def __str__(self) -> str:
        return f"{self.task_id}: {self.from_status} → {self.to_status}"


class TaskReport(FarmScopedModel):
    """Field report (FR-063), created online or offline; append-only."""

    class Completion(models.TextChoices):
        PARTIAL = "partial", "Partielle"
        COMPLETE = "complete", "Terminée"

    task = models.ForeignKey(Task, on_delete=models.PROTECT, related_name="reports")
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    actual_start = models.DateTimeField()
    actual_end = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    completion = models.CharField(max_length=20, choices=Completion.choices)
    notes = models.TextField(blank=True)
    deviation_notes = models.TextField(blank=True, help_text="Écart par rapport au plan")
    photos = models.ManyToManyField("files.StoredFile", blank=True, related_name="+")
    device = models.ForeignKey(
        "users.Device", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(actual_end__isnull=True)
                | models.Q(actual_end__gte=models.F("actual_start")),
                name="report_dates_valid",
            )
        ]
        ordering = ["-actual_start"]

    def __str__(self) -> str:
        return f"Compte rendu {self.task_id}"


class InputConsumption(UUIDModel, TimestampedModel):
    """Input actually used during an intervention, linked to the plan (FR-082)."""

    report = models.ForeignKey(TaskReport, on_delete=models.PROTECT, related_name="consumptions")
    product = models.ForeignKey("agronomy.InputProduct", on_delete=models.PROTECT, related_name="+")
    quantity = models.DecimalField(max_digits=14, decimal_places=4)
    unit = models.CharField(max_length=5)
    quantity_base = models.DecimalField(max_digits=14, decimal_places=4)
    base_unit = models.CharField(max_length=5)
    plan_version = models.ForeignKey(
        "production_plans.PlanVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    lot_number = models.CharField(max_length=100, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="consumption_quantity_positive"
            )
        ]

    def __str__(self) -> str:
        return f"{self.product_id}: {self.quantity} {self.unit}"
