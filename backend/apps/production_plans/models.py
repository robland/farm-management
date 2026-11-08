"""Campaigns and production plans: the central business object (PROJECT_CONTEXT §11).

A plan has versions (FR-034). Only a draft version is editable; a validated
version is immutable and is the only source of operational tasks (FR-035).
"""

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import (
    AuthoredModel,
    FarmScopedModel,
    SoftDeleteModel,
    TimestampedModel,
    UUIDModel,
    VersionedModel,
)

POSITIVE = MinValueValidator(0)
RATE = [MinValueValidator(0), MaxValueValidator(1)]


class Campaign(FarmScopedModel, AuthoredModel, VersionedModel, SoftDeleteModel):
    class Status(models.TextChoices):
        PLANNED = "planned", "Planifiée"
        ACTIVE = "active", "En cours"
        CLOSED = "closed", "Clôturée"

    name = models.CharField(max_length=150)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNED)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="campaign_dates_valid",
            )
        ]
        ordering = ["-start_date"]

    def __str__(self) -> str:
        return self.name


class ProductionPlan(FarmScopedModel, AuthoredModel, VersionedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Brouillon"
        VALIDATED = "validated", "Validé"
        IN_PROGRESS = "in_progress", "En exécution"
        CLOSED = "closed", "Clôturé"
        CANCELLED = "cancelled", "Annulé"

    campaign = models.ForeignKey(Campaign, on_delete=models.PROTECT, related_name="plans")
    variety = models.ForeignKey("varieties.Variety", on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=150)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    current_version = models.ForeignKey(
        "PlanVersion", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    class Meta:
        indexes = [models.Index(fields=["farm", "campaign"])]

    def __str__(self) -> str:
        return self.name


class PlanVersion(FarmScopedModel, AuthoredModel, VersionedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Brouillon"
        VALIDATED = "validated", "Validée"
        SUPERSEDED = "superseded", "Remplacée"
        REJECTED = "rejected", "Rejetée"

    class Origin(models.TextChoices):
        MANUAL = "manual", "Saisie manuelle"
        AI_DRAFT = "ai_draft", "Brouillon IA"
        COPY = "copy", "Copie d'une version"

    plan = models.ForeignKey(ProductionPlan, on_delete=models.PROTECT, related_name="versions")
    number = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    origin = models.CharField(max_length=20, choices=Origin.choices, default=Origin.MANUAL)
    based_on = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    technical_data_set = models.ForeignKey(
        "varieties.TechnicalDataSet",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    planned_start_date = models.DateField(null=True, blank=True)
    planned_end_date = models.DateField(null=True, blank=True)
    target_yield_kg_per_ha = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True, validators=[POSITIVE]
    )
    objectives = models.TextField(blank=True)
    constraints_notes = models.TextField(blank=True)
    change_note = models.TextField(blank=True)
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    engine_version = models.CharField(max_length=20, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["plan", "number"], name="plan_version_number_unique"),
            models.UniqueConstraint(
                fields=["plan"],
                condition=models.Q(status="validated"),
                name="plan_single_validated_version",
            ),
        ]
        ordering = ["plan", "-number"]

    def __str__(self) -> str:
        return f"{self.plan_id} v{self.number} ({self.status})"

    @property
    def is_draft(self) -> bool:
        return self.status == self.Status.DRAFT


class PlanAllocation(UUIDModel):
    plan_version = models.ForeignKey(
        PlanVersion, on_delete=models.CASCADE, related_name="allocations"
    )
    parcel = models.ForeignKey("fields.Parcel", on_delete=models.PROTECT, related_name="+")
    allocated_area_m2 = models.DecimalField(
        max_digits=14, decimal_places=4, validators=[MinValueValidator(0)]
    )
    non_plantable_area_m2 = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True, validators=[POSITIVE]
    )
    plot_length_m = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    plot_width_m = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plan_version", "parcel"], name="plan_allocation_unique_parcel"
            ),
            models.CheckConstraint(
                condition=models.Q(allocated_area_m2__gt=0), name="plan_allocation_area_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.parcel_id}: {self.allocated_area_m2} m2"


class PlantingSpec(models.Model):
    """Planting parameters of a version (FR-032). Results are in CalculationResult."""

    class Method(models.TextChoices):
        DIRECT_SEEDING = "direct_seeding", "Semis direct"
        TRANSPLANTING = "transplanting", "Repiquage"

    class Layout(models.TextChoices):
        SINGLE_ROW = "single_row", "Lignes simples"
        BEDS = "beds", "Planches"

    plan_version = models.OneToOneField(
        PlanVersion, on_delete=models.CASCADE, primary_key=True, related_name="planting_spec"
    )
    planting_method = models.CharField(max_length=20, choices=Method.choices, blank=True)
    layout = models.CharField(max_length=20, choices=Layout.choices, default=Layout.SINGLE_ROW)
    row_spacing_m = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    plant_spacing_m = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    plants_per_hole = models.PositiveSmallIntegerField(null=True, blank=True)
    seeds_per_hole = models.PositiveSmallIntegerField(null=True, blank=True)
    bed_width_m = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    path_width_m = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    rows_per_bed = models.PositiveSmallIntegerField(null=True, blank=True)
    headland_m = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    germination_rate = models.DecimalField(
        max_digits=5, decimal_places=4, null=True, blank=True, validators=RATE
    )
    nursery_success_rate = models.DecimalField(
        max_digits=5, decimal_places=4, null=True, blank=True, validators=RATE
    )
    safety_margin_rate = models.DecimalField(
        max_digits=5, decimal_places=4, null=True, blank=True, validators=[POSITIVE]
    )
    seeds_per_gram = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    thousand_seed_weight_g = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    seed_package_size_g = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )

    def __str__(self) -> str:
        return f"PlantingSpec {self.plan_version_id}"


class PlanPhase(UUIDModel):
    plan_version = models.ForeignKey(PlanVersion, on_delete=models.CASCADE, related_name="phases")
    phase_code = models.CharField(max_length=40)
    sequence = models.PositiveSmallIntegerField()
    duration_days = models.PositiveIntegerField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plan_version", "sequence"], name="plan_phase_sequence_unique"
            ),
            models.UniqueConstraint(
                fields=["plan_version", "phase_code"], name="plan_phase_code_unique"
            ),
        ]
        ordering = ["sequence"]

    def __str__(self) -> str:
        return f"{self.phase_code} ({self.duration_days} j)"


class FieldProvenance(UUIDModel, TimestampedModel):
    """Where each plan value comes from (FR-103, CLAUDE.md §10)."""

    class SourceKind(models.TextChoices):
        DOCUMENT = "document", "Source documentaire"
        CALCULATION = "calculation", "Calcul déterministe"
        AI_SUGGESTION = "ai_suggestion", "Recommandation IA"
        USER_INPUT = "user_input", "Saisie utilisateur"

    plan_version = models.ForeignKey(
        PlanVersion, on_delete=models.CASCADE, related_name="provenances"
    )
    field_path = models.CharField(max_length=150)
    source_kind = models.CharField(max_length=20, choices=SourceKind.choices)
    technical_data_item = models.ForeignKey(
        "varieties.TechnicalDataItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    calculation_result = models.ForeignKey(
        "CalculationRecord", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    ai_suggestion_id = models.UUIDField(null=True, blank=True)
    set_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    note = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plan_version", "field_path"], name="provenance_unique_field"
            )
        ]

    def __str__(self) -> str:
        return f"{self.field_path}: {self.source_kind}"


class CalculationRecord(FarmScopedModel):
    """Stored output of an agronomy_engine calculation, with all its traceability data."""

    plan_version = models.ForeignKey(
        PlanVersion, on_delete=models.CASCADE, null=True, blank=True, related_name="calculations"
    )
    calc_type = models.CharField(max_length=60)
    engine_version = models.CharField(max_length=20)
    scope = models.CharField(max_length=100, blank=True, help_text="ex. parcel id")
    inputs = models.JSONField(encoder=DjangoJSONEncoder)
    outputs = models.JSONField(encoder=DjangoJSONEncoder)
    formula = models.TextField()
    assumptions = models.JSONField(default=list, encoder=DjangoJSONEncoder)
    warnings = models.JSONField(default=list, encoder=DjangoJSONEncoder)
    details = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    computed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    class Meta:
        indexes = [models.Index(fields=["plan_version", "calc_type"])]

    def __str__(self) -> str:
        return f"{self.calc_type} {self.scope}"


class CropCycle(FarmScopedModel, VersionedModel):
    """Occupation of (part of) a parcel by a plan during a period (FR-010, OPEN_QUESTIONS Q1)."""

    class Status(models.TextChoices):
        PLANNED = "planned", "Planifié"
        ACTIVE = "active", "En cours"
        HARVESTED = "harvested", "Récolté"
        CLOSED = "closed", "Clôturé"
        CANCELLED = "cancelled", "Annulé"

    plan = models.ForeignKey(ProductionPlan, on_delete=models.PROTECT, related_name="cycles")
    plan_version = models.ForeignKey(PlanVersion, on_delete=models.PROTECT, related_name="+")
    parcel = models.ForeignKey("fields.Parcel", on_delete=models.PROTECT, related_name="+")
    area_m2 = models.DecimalField(max_digits=14, decimal_places=4)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNED)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["plan", "parcel"], name="crop_cycle_plan_parcel"),
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="crop_cycle_dates_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(area_m2__gt=0), name="crop_cycle_area_positive"
            ),
        ]
        indexes = [models.Index(fields=["farm", "parcel", "start_date", "end_date"])]

    def __str__(self) -> str:
        return f"{self.parcel_id} {self.start_date}→{self.end_date}"
