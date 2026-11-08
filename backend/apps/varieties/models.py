"""Varieties, technical documents and versioned technical data (FR-021..023)."""

from django.conf import settings
from django.db import models

from apps.core.models import (
    AuthoredModel,
    OrgScopedModel,
    SoftDeleteModel,
    TimestampedModel,
    UUIDModel,
    VersionedModel,
)


class Variety(OrgScopedModel, AuthoredModel, VersionedModel, SoftDeleteModel):
    crop = models.ForeignKey("crops.Crop", on_delete=models.PROTECT, related_name="varieties")
    name = models.CharField(max_length=150)
    seed_company = models.CharField(max_length=150, blank=True)
    description = models.TextField(blank=True)
    is_hybrid = models.BooleanField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "crop", "name", "seed_company"],
                condition=models.Q(deleted_at__isnull=True),
                name="variety_unique_per_org",
            )
        ]
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class TechnicalDocument(OrgScopedModel, AuthoredModel):
    """An imported technical sheet. The original file is kept unchanged (FR-022)."""

    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Importé"
        EXTRACTED = "extracted", "Extrait"
        REVIEWED = "reviewed", "Revu"

    variety = models.ForeignKey(Variety, on_delete=models.PROTECT, related_name="documents")
    file = models.ForeignKey("files.StoredFile", on_delete=models.PROTECT, related_name="+")
    title = models.CharField(max_length=200, blank=True)
    supplier = models.CharField(max_length=150, blank=True)
    document_date = models.DateField(null=True, blank=True)
    language = models.CharField(max_length=10, default="fr")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPLOADED)

    def __str__(self) -> str:
        return self.title or str(self.file_id)


class TechnicalDataSet(OrgScopedModel, AuthoredModel, VersionedModel):
    """A versioned set of technical data. Immutable once validated."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Brouillon"
        VALIDATED = "validated", "Validé"
        SUPERSEDED = "superseded", "Remplacé"

    variety = models.ForeignKey(Variety, on_delete=models.PROTECT, related_name="data_sets")
    source_document = models.ForeignKey(
        TechnicalDocument, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    version_number = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    based_on = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    notes = models.TextField(blank=True)
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    validated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["variety", "version_number"], name="dataset_version_unique"
            ),
            models.UniqueConstraint(
                fields=["variety"],
                condition=models.Q(status="validated"),
                name="dataset_single_validated_per_variety",
            ),
        ]
        ordering = ["-version_number"]

    def __str__(self) -> str:
        return f"{self.variety_id} v{self.version_number} ({self.status})"


class TechnicalDataItem(UUIDModel, TimestampedModel):
    class Provenance(models.TextChoices):
        DOCUMENT = "document", "Source documentaire"
        USER_INPUT = "user_input", "Saisie utilisateur"
        AI_EXTRACTION = "ai_extraction", "Extraction IA (à vérifier)"

    data_set = models.ForeignKey(TechnicalDataSet, on_delete=models.CASCADE, related_name="items")
    key = models.CharField(max_length=100)
    value_numeric = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    value_min = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    value_max = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    value_text = models.TextField(blank=True)
    unit = models.CharField(max_length=20, blank=True)
    provenance = models.CharField(max_length=20, choices=Provenance.choices)
    source_page = models.PositiveIntegerField(null=True, blank=True)
    source_section = models.CharField(max_length=200, blank=True)
    source_quote = models.TextField(blank=True)
    confidence = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    validated = models.BooleanField(default=False)
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["data_set", "key"], name="dataitem_key_unique"),
            models.CheckConstraint(
                condition=models.Q(confidence__isnull=True)
                | models.Q(confidence__gte=0, confidence__lte=1),
                name="dataitem_confidence_range",
            ),
        ]
        ordering = ["key"]

    def __str__(self) -> str:
        return f"{self.key}={self.value_numeric or self.value_text} {self.unit}"
