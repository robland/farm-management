"""Abstract base models shared by every business module.

See DATABASE_SCHEMA.md §1.1 for the conventions these mixins implement.
"""

import uuid

from django.conf import settings
from django.db import models


class UUIDModel(models.Model):
    """UUID primary key. Clients may generate the id for offline creation."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AuthoredModel(models.Model):
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        abstract = True


class VersionedModel(models.Model):
    """Optimistic concurrency counter, incremented on every update."""

    version = models.PositiveIntegerField(default=1)

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    def alive(self) -> "SoftDeleteQuerySet":
        return self.filter(deleted_at__isnull=True)


class SoftDeleteModel(models.Model):
    """Tombstone for descriptive data. Never used for validated financial data."""

    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        abstract = True

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class OrgScopedModel(UUIDModel, TimestampedModel):
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        abstract = True


class FarmScopedModel(OrgScopedModel):
    """Farm-owned data. `organization` is denormalised for tenant filtering."""

    farm = models.ForeignKey("farms.Farm", on_delete=models.PROTECT, related_name="+")

    class Meta:
        abstract = True
