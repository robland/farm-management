"""Fields (champs / îlots) and parcels (FR-010). Units: m, m², pH."""

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.geojson import validate_geometry
from apps.core.models import AuthoredModel, FarmScopedModel, SoftDeleteModel, VersionedModel

POSITIVE = MinValueValidator(Decimal("0.0001"))


class Field(FarmScopedModel, AuthoredModel, VersionedModel, SoftDeleteModel):
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=32)
    description = models.TextField(blank=True)
    area_m2 = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True, validators=[POSITIVE]
    )
    geometry = models.JSONField(null=True, blank=True, validators=[validate_geometry])

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["farm", "code"],
                condition=models.Q(deleted_at__isnull=True),
                name="field_code_unique_per_farm",
            ),
            models.CheckConstraint(
                condition=models.Q(area_m2__isnull=True) | models.Q(area_m2__gt=0),
                name="field_area_positive",
            ),
        ]
        indexes = [models.Index(fields=["farm", "deleted_at"])]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class Parcel(FarmScopedModel, AuthoredModel, VersionedModel, SoftDeleteModel):
    class WaterAvailability(models.TextChoices):
        NONE = "none", "Aucune"
        LOW = "low", "Faible"
        MEDIUM = "medium", "Moyenne"
        HIGH = "high", "Élevée"
        UNKNOWN = "unknown", "Inconnue"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        FALLOW = "fallow", "En jachère"
        ARCHIVED = "archived", "Archivée"

    field = models.ForeignKey(
        Field, on_delete=models.PROTECT, null=True, blank=True, related_name="parcels"
    )
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=32)
    area_m2 = models.DecimalField(max_digits=14, decimal_places=4, validators=[POSITIVE])
    length_m = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True, validators=[POSITIVE]
    )
    width_m = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True, validators=[POSITIVE]
    )
    geometry = models.JSONField(null=True, blank=True, validators=[validate_geometry])
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    soil_type = models.CharField(max_length=50, blank=True)
    soil_ph = models.DecimalField(
        max_digits=3,
        decimal_places=1,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(14)],
    )
    water_availability = models.CharField(
        max_length=20, choices=WaterAvailability.choices, default=WaterAvailability.UNKNOWN
    )
    water_notes = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["farm", "code"],
                condition=models.Q(deleted_at__isnull=True),
                name="parcel_code_unique_per_farm",
            ),
            models.CheckConstraint(condition=models.Q(area_m2__gt=0), name="parcel_area_positive"),
            models.CheckConstraint(
                condition=models.Q(soil_ph__isnull=True)
                | models.Q(soil_ph__gte=0, soil_ph__lte=14),
                name="parcel_ph_range",
            ),
        ]
        indexes = [
            models.Index(fields=["farm", "deleted_at"]),
            models.Index(fields=["farm", "field"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class ParcelHistoryEntry(FarmScopedModel, AuthoredModel):
    """Cropping history prior to the system (FR-010 « historique cultural »)."""

    parcel = models.ForeignKey(Parcel, on_delete=models.PROTECT, related_name="history_entries")
    period_start = models.DateField()
    period_end = models.DateField(null=True, blank=True)
    crop_label = models.CharField(max_length=120)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(period_end__isnull=True)
                | models.Q(period_end__gte=models.F("period_start")),
                name="parcel_history_period_valid",
            )
        ]
        ordering = ["-period_start"]

    def __str__(self) -> str:
        return f"{self.parcel_id} {self.crop_label} {self.period_start}"
