"""Suppliers, catalogue items and price lists (FR-043, FR-080).

Prices are never hard-coded: they are entered in versioned price lists, and
quotes copy the prices they use.
"""

from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import MinValueValidator
from django.db import models

from apps.core.models import (
    AuthoredModel,
    OrgScopedModel,
    SoftDeleteModel,
    UUIDModel,
    VersionedModel,
)
from apps.organizations.models import currency_validator


class Supplier(OrgScopedModel, AuthoredModel, VersionedModel, SoftDeleteModel):
    """Supplier and/or customer (counterparty of financial transactions)."""

    class Kind(models.TextChoices):
        SUPPLIER = "supplier", "Fournisseur"
        CUSTOMER = "customer", "Client"
        BOTH = "both", "Fournisseur et client"

    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.SUPPLIER)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                condition=models.Q(deleted_at__isnull=True),
                name="supplier_name_unique_per_org",
            )
        ]
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class CatalogItem(OrgScopedModel, AuthoredModel, VersionedModel, SoftDeleteModel):
    class Category(models.TextChoices):
        PIPE = "pipe", "Tuyau"
        DRIPLINE = "dripline", "Rampe goutte-à-goutte"
        EMITTER = "emitter", "Goutteur"
        FILTER = "filter", "Filtre"
        VALVE = "valve", "Vanne"
        REGULATOR = "regulator", "Régulateur"
        PUMP = "pump", "Pompe"
        INJECTOR = "injector", "Injecteur"
        FITTING = "fitting", "Raccord"
        SEED = "seed", "Semence"
        FERTILIZER = "fertilizer", "Engrais"
        PHYTO = "phyto", "Produit phytosanitaire"
        CONSUMABLE = "consumable", "Consommable"
        OTHER = "other", "Autre"

    class Unit(models.TextChoices):
        M = "m", "mètre"
        PIECE = "piece", "pièce"
        ROLL = "roll", "rouleau"
        KG = "kg", "kilogramme"
        G = "g", "gramme"
        L = "l", "litre"
        ML = "ml", "millilitre"
        BAG = "bag", "sac"

    category = models.CharField(max_length=20, choices=Category.choices)
    name = models.CharField(max_length=200)
    reference = models.CharField(max_length=100, blank=True)
    base_unit = models.CharField(max_length=10, choices=Unit.choices)
    spec = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)

    class Meta:
        ordering = ["category", "name"]
        indexes = [models.Index(fields=["organization", "category"])]

    def __str__(self) -> str:
        return self.name


class PriceList(OrgScopedModel, AuthoredModel, VersionedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Brouillon"
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archivée"

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="price_lists")
    name = models.CharField(max_length=150)
    currency = models.CharField(max_length=3, validators=[currency_validator])
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True)
                | models.Q(valid_to__gte=models.F("valid_from")),
                name="price_list_validity",
            )
        ]
        ordering = ["-valid_from"]

    def __str__(self) -> str:
        return f"{self.supplier} — {self.name}"


class PriceListItem(UUIDModel):
    price_list = models.ForeignKey(PriceList, on_delete=models.CASCADE, related_name="items")
    catalog_item = models.ForeignKey(CatalogItem, on_delete=models.PROTECT, related_name="+")
    unit = models.CharField(max_length=10, choices=CatalogItem.Unit.choices)
    unit_price = models.DecimalField(
        max_digits=19, decimal_places=4, validators=[MinValueValidator(0)]
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["price_list", "catalog_item", "unit"], name="price_item_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0), name="price_item_non_negative"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.catalog_item_id}: {self.unit_price}/{self.unit}"
