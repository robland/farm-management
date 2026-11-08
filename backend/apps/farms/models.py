from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import SoftDeleteModel, TimestampedModel, UUIDModel, VersionedModel
from apps.organizations.models import (
    Organization,
    Role,
    country_validator,
    currency_validator,
)

# Configurable farm parameters (OPEN_QUESTIONS Q2, Q8, Q9). Values are
# product defaults, not agronomic data.
FARM_SETTINGS_DEFAULTS: dict[str, Any] = {
    "area_tolerance_pct": 0,
    "auto_validate_own_transactions": True,
    "backdate_limit_days": 30,
}

_SETTINGS_TYPES: dict[str, type] = {
    "area_tolerance_pct": int,
    "auto_validate_own_transactions": bool,
    "backdate_limit_days": int,
}


def validate_farm_settings(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValidationError("Les paramètres doivent être un objet.")
    for key, item in value.items():
        expected = _SETTINGS_TYPES.get(key)
        if expected is None:
            raise ValidationError(f"Paramètre inconnu : {key}.")
        # bool is a subclass of int: reject it explicitly for numeric settings.
        if expected is int and (isinstance(item, bool) or not isinstance(item, int)):
            raise ValidationError(f"{key} doit être un entier.")
        if expected is bool and not isinstance(item, bool):
            raise ValidationError(f"{key} doit être un booléen.")
        if expected is int and item < 0:
            raise ValidationError(f"{key} doit être positif.")


class Farm(UUIDModel, TimestampedModel, VersionedModel, SoftDeleteModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archivée"

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="farms")
    name = models.CharField(max_length=200)
    code = models.SlugField(max_length=32)
    country = models.CharField(max_length=2, validators=[country_validator])
    region = models.CharField(max_length=120, blank=True)
    locality = models.CharField(max_length=120, blank=True)
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
    timezone = models.CharField(max_length=64)
    currency = models.CharField(max_length=3, validators=[currency_validator])
    locale = models.CharField(max_length=10, default="fr")
    declared_area_m2 = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    settings = models.JSONField(
        default=dict, blank=True, encoder=DjangoJSONEncoder, validators=[validate_farm_settings]
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"],
                condition=models.Q(deleted_at__isnull=True),
                name="farm_code_unique_per_org",
            ),
            models.CheckConstraint(
                condition=models.Q(latitude__isnull=True)
                | models.Q(latitude__gte=-90, latitude__lte=90),
                name="farm_latitude_range",
            ),
            models.CheckConstraint(
                condition=models.Q(longitude__isnull=True)
                | models.Q(longitude__gte=-180, longitude__lte=180),
                name="farm_longitude_range",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def get_setting(self, key: str) -> Any:
        return self.settings.get(key, FARM_SETTINGS_DEFAULTS[key])


class FarmMembership(UUIDModel, TimestampedModel, VersionedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DISABLED = "disabled", "Désactivée"

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="+")
    farm = models.ForeignKey(Farm, on_delete=models.PROTECT, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="farm_memberships"
    )
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="farm_memberships")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["farm", "user"], name="farm_membership_unique"),
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True)
                | models.Q(valid_from__isnull=True)
                | models.Q(valid_to__gte=models.F("valid_from")),
                name="farm_membership_valid_range",
            ),
        ]
        indexes = [models.Index(fields=["user", "status"])]

    def __str__(self) -> str:
        return f"{self.user_id} @ {self.farm_id} ({self.role_id})"
