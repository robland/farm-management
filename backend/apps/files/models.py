"""Stored files (ARCHITECTURE.md §10). Binary content lives in the storage backend."""

from django.conf import settings
from django.db import models

from apps.core.models import OrgScopedModel


class StoredFile(OrgScopedModel):
    class Purpose(models.TextChoices):
        TECHNICAL_SHEET = "technical_sheet", "Fiche technique"
        PRODUCT_LABEL = "product_label", "Étiquette produit"
        RECEIPT = "receipt", "Justificatif financier"
        FUNDING_PROOF = "funding_proof", "Justificatif d'apport"
        TASK_PHOTO = "task_photo", "Photo d'intervention"
        OBSERVATION_PHOTO = "observation_photo", "Photo d'observation"
        OTHER = "other", "Autre"

    class Status(models.TextChoices):
        AVAILABLE = "available", "Disponible"
        QUARANTINED = "quarantined", "En quarantaine"
        REJECTED = "rejected", "Refusé"

    farm = models.ForeignKey(
        "farms.Farm", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    storage_key = models.CharField(max_length=255, unique=True)
    original_name = models.CharField(max_length=255)
    declared_mime = models.CharField(max_length=100, blank=True)
    detected_mime = models.CharField(max_length=100)
    size_bytes = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    purpose = models.CharField(max_length=30, choices=Purpose.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AVAILABLE)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        indexes = [
            models.Index(fields=["organization", "purpose"]),
            models.Index(fields=["farm", "purpose"]),
            models.Index(fields=["sha256"]),
        ]

    def __str__(self) -> str:
        return self.original_name
