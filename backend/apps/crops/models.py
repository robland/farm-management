"""Crop species (FR-020).

`organization = NULL` marks a shared, read-only reference entry maintained by
platform administrators; organizations add their own entries (OPEN_QUESTIONS Q6).
No agronomic parameter is stored at species level: they belong to validated
variety technical data.
"""

from django.db import models

from apps.core.models import AuthoredModel, TimestampedModel, UUIDModel, VersionedModel


class Crop(UUIDModel, TimestampedModel, AuthoredModel, VersionedModel):
    class Category(models.TextChoices):
        VEGETABLE = "vegetable", "Légume"
        FRUIT = "fruit", "Fruit"
        LEGUME = "legume", "Légumineuse"
        CEREAL = "cereal", "Céréale"
        TUBER = "tuber", "Tubercule"
        OTHER = "other", "Autre"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    common_name = models.CharField(max_length=120)
    scientific_name = models.CharField(max_length=200, blank=True)
    family = models.CharField(max_length=120, blank=True)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "common_name"],
                name="crop_name_unique_per_org",
                nulls_distinct=False,
            )
        ]
        ordering = ["common_name"]

    def __str__(self) -> str:
        return self.common_name

    @property
    def is_global(self) -> bool:
        return self.organization_id is None
