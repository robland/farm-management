"""Irrigation designs, bills of materials and quotes (FR-040..043)."""

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from apps.core.models import AuthoredModel, FarmScopedModel, UUIDModel, VersionedModel


class IrrigationDesign(FarmScopedModel, AuthoredModel, VersionedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Brouillon"
        VALIDATED = "validated", "Validé"
        SUPERSEDED = "superseded", "Remplacé"

    class SystemType(models.TextChoices):
        DRIP = "drip", "Goutte-à-goutte"
        SPRINKLER = "sprinkler", "Aspersion"
        MICRO_SPRINKLER = "micro_sprinkler", "Micro-aspersion"
        OTHER = "other", "Autre (sans calcul automatique)"

    parcel = models.ForeignKey("fields.Parcel", on_delete=models.PROTECT, related_name="+")
    plan_version = models.ForeignKey(
        "production_plans.PlanVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    name = models.CharField(max_length=150)
    number = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    system_type = models.CharField(max_length=20, choices=SystemType.choices)
    based_on = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    parameters = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    bom_parameters = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    validated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["parcel", "number"], name="design_number_per_parcel")
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} v{self.number}"

    @property
    def is_draft(self) -> bool:
        return self.status == self.Status.DRAFT


class BomLine(UUIDModel):
    design = models.ForeignKey(IrrigationDesign, on_delete=models.CASCADE, related_name="bom_lines")
    sequence = models.PositiveIntegerField()
    component_type = models.CharField(max_length=30)
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=14, decimal_places=4)
    unit = models.CharField(max_length=10)
    rationale = models.TextField(blank=True)
    spec = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    catalog_item = models.ForeignKey(
        "inventory.CatalogItem", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    is_manual = models.BooleanField(default=False)

    class Meta:
        ordering = ["sequence"]

    def __str__(self) -> str:
        return f"{self.description}: {self.quantity} {self.unit}"


class Quote(FarmScopedModel, AuthoredModel, VersionedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Brouillon"
        ISSUED = "issued", "Émis"
        ACCEPTED = "accepted", "Accepté"
        REJECTED = "rejected", "Refusé"
        SUPERSEDED = "superseded", "Remplacé"

    design = models.ForeignKey(IrrigationDesign, on_delete=models.PROTECT, related_name="quotes")
    supplier = models.ForeignKey(
        "inventory.Supplier", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    price_list = models.ForeignKey(
        "inventory.PriceList", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    number = models.PositiveIntegerField()
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    discount_amount = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    tax_rate = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    subtotal = models.DecimalField(max_digits=19, decimal_places=4, default=0)
    tax_amount = models.DecimalField(max_digits=19, decimal_places=4, default=0)
    total = models.DecimalField(max_digits=19, decimal_places=4, default=0)
    assumptions = models.JSONField(default=list, encoder=DjangoJSONEncoder)
    warnings = models.JSONField(default=list, encoder=DjangoJSONEncoder)
    notes = models.TextField(blank=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    issued_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["design", "number"], name="quote_number_per_design")
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Devis {self.number} ({self.status})"


class QuoteLine(UUIDModel):
    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name="lines")
    sequence = models.PositiveIntegerField()
    bom_line = models.ForeignKey(
        BomLine, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    catalog_item = models.ForeignKey(
        "inventory.CatalogItem", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=14, decimal_places=4)
    unit = models.CharField(max_length=10)
    # Prices are COPIED at quote time (FR-043): later price list edits do not alter the quote.
    unit_price = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    line_total = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    price_source = models.CharField(max_length=30, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["sequence"]

    def __str__(self) -> str:
        return self.description
