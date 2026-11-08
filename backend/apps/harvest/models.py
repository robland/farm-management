"""Harvest records and measured unit conversions (FR-090..092)."""

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.core.models import FarmScopedModel, VersionedModel


class UnitConversion(FarmScopedModel, VersionedModel):
    """Measured weight of a non-mass harvest unit (crate, piece...) for a crop."""

    crop = models.ForeignKey("crops.Crop", on_delete=models.PROTECT, related_name="+")
    unit = models.SlugField(max_length=30)
    kg_per_unit = models.DecimalField(
        max_digits=10, decimal_places=4, validators=[MinValueValidator(0)]
    )
    measured_on = models.DateField()
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["farm", "crop", "unit"], name="unit_conversion_unique"),
            models.CheckConstraint(
                condition=models.Q(kg_per_unit__gt=0), name="unit_conversion_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"1 {self.unit} = {self.kg_per_unit} kg"


class HarvestRecord(FarmScopedModel):
    """A harvest, created online or offline; append-only. Errors are voided, not deleted."""

    class Grade(models.TextChoices):
        EXTRA = "extra", "Extra"
        GRADE_1 = "grade_1", "Catégorie I"
        GRADE_2 = "grade_2", "Catégorie II"
        REJECTED = "rejected", "Rebut"

    crop_cycle = models.ForeignKey(
        "production_plans.CropCycle", on_delete=models.PROTECT, related_name="+"
    )
    parcel = models.ForeignKey("fields.Parcel", on_delete=models.PROTECT, related_name="+")
    harvested_on = models.DateField()
    quantity = models.DecimalField(max_digits=14, decimal_places=4)
    unit = models.SlugField(max_length=30)
    quantity_kg = models.DecimalField(max_digits=14, decimal_places=4)
    conversion_factor_used = models.DecimalField(max_digits=10, decimal_places=4)
    quality_grade = models.CharField(max_length=20, choices=Grade.choices)
    loss_quantity_kg = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    loss_reason = models.CharField(max_length=200, blank=True)
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    notes = models.TextField(blank=True)
    device = models.ForeignKey(
        "users.Device", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    void_reason = models.TextField(blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="harvest_quantity_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(loss_quantity_kg__gte=0), name="harvest_loss_non_negative"
            ),
        ]
        indexes = [models.Index(fields=["farm", "crop_cycle", "harvested_on"])]
        ordering = ["-harvested_on", "-created_at"]

    def __str__(self) -> str:
        return f"{self.quantity} {self.unit} ({self.harvested_on})"
