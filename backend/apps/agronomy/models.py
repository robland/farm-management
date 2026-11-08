"""Agronomic programme of a plan version and field observations (FR-050..052)."""

from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import (
    AuthoredModel,
    FarmScopedModel,
    OrgScopedModel,
    SoftDeleteModel,
    TimestampedModel,
    UUIDModel,
    VersionedModel,
)

NUTRIENTS = [
    "N",
    "P2O5",
    "P",
    "K2O",
    "K",
    "CaO",
    "Ca",
    "MgO",
    "Mg",
    "S",
    "SO3",
    "B",
    "Zn",
    "Fe",
    "Mn",
    "Cu",
    "Mo",
]


class InputProduct(OrgScopedModel, AuthoredModel, VersionedModel, SoftDeleteModel):
    class Kind(models.TextChoices):
        FERTILIZER = "fertilizer", "Engrais"
        PHYTO = "phyto", "Produit phytosanitaire"
        AMENDMENT = "amendment", "Amendement"
        SEED = "seed", "Semence"
        OTHER = "other", "Autre"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    name = models.CharField(max_length=200)
    manufacturer = models.CharField(max_length=150, blank=True)
    catalog_item = models.ForeignKey(
        "inventory.CatalogItem", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    # Mass percentages as declared on the label, e.g. {"N": 15, "P2O5": 15, "K2O": 15}.
    composition = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)
    formulation = models.CharField(max_length=50, blank=True)
    density_kg_per_l = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    active_ingredients = models.JSONField(default=list, blank=True, encoder=DjangoJSONEncoder)
    registration_number = models.CharField(max_length=100, blank=True)
    registration_country = models.CharField(max_length=2, blank=True)
    registration_valid_until = models.DateField(null=True, blank=True)
    label_file = models.ForeignKey(
        "files.StoredFile", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class SourceKind(models.TextChoices):
    DOCUMENT = "document", "Source documentaire"
    USER_INPUT = "user_input", "Saisie utilisateur"
    AI_SUGGESTION = "ai_suggestion", "Recommandation IA"


class PlannedFertilization(UUIDModel, TimestampedModel):
    class Mode(models.TextChoices):
        NUTRIENT_TARGET = "nutrient_target", "Dose de nutriment"
        PRODUCT_DOSE = "product_dose", "Dose de produit"

    class Method(models.TextChoices):
        FERTIGATION = "fertigation", "Fertigation"
        BROADCAST = "broadcast", "À la volée"
        LOCALIZED = "localized", "Localisé"
        FOLIAR = "foliar", "Foliaire"
        OTHER = "other", "Autre"

    plan_version = models.ForeignKey(
        "production_plans.PlanVersion", on_delete=models.CASCADE, related_name="fertilizations"
    )
    sequence = models.PositiveIntegerField()
    product = models.ForeignKey(InputProduct, on_delete=models.PROTECT, related_name="+")
    phase_code = models.CharField(max_length=40, blank=True)
    day_offset = models.IntegerField(default=0)
    mode = models.CharField(max_length=20, choices=Mode.choices)
    target_nutrient = models.CharField(max_length=10, blank=True)
    nutrient_dose_kg_per_ha = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    dose_value = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    dose_unit = models.CharField(max_length=5, blank=True)
    basis = models.CharField(max_length=10, blank=True)
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.OTHER)
    source_kind = models.CharField(max_length=20, choices=SourceKind.choices)
    technical_data_item = models.ForeignKey(
        "varieties.TechnicalDataItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    source_note = models.TextField(blank=True)
    computed_quantity = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    computed_unit = models.CharField(max_length=5, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["sequence"]

    def __str__(self) -> str:
        return f"{self.product_id} ({self.mode})"


class PlannedPhytoIntervention(UUIDModel, TimestampedModel):
    """A planned treatment. The dose comes from the label or the user, never from the AI."""

    plan_version = models.ForeignKey(
        "production_plans.PlanVersion", on_delete=models.CASCADE, related_name="phyto_interventions"
    )
    sequence = models.PositiveIntegerField()
    product = models.ForeignKey(InputProduct, on_delete=models.PROTECT, related_name="+")
    target_organism = models.CharField(max_length=200)
    phase_code = models.CharField(max_length=40, blank=True)
    day_offset = models.IntegerField(default=0)
    dose_value = models.DecimalField(max_digits=12, decimal_places=4)
    dose_unit = models.CharField(max_length=5)
    basis = models.CharField(max_length=10)
    label_reference = models.TextField(help_text="Référence de l'étiquette ou de l'autorisation")
    pre_harvest_interval_days = models.PositiveIntegerField(null=True, blank=True)
    reentry_interval_hours = models.PositiveIntegerField(null=True, blank=True)
    source_kind = models.CharField(
        max_length=20,
        choices=[
            (SourceKind.DOCUMENT, SourceKind.DOCUMENT.label),
            (SourceKind.USER_INPUT, SourceKind.USER_INPUT.label),
        ],
    )
    computed_quantity = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    computed_unit = models.CharField(max_length=5, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["sequence"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(source_kind__in=["document", "user_input"]),
                name="phyto_dose_never_from_ai",
            )
        ]

    def __str__(self) -> str:
        return f"{self.product_id} → {self.target_organism}"


class PlannedIrrigation(UUIDModel, TimestampedModel):
    """Irrigation programme by phase (FR-051). ET0 and Kc are user/document inputs."""

    plan_version = models.ForeignKey(
        "production_plans.PlanVersion", on_delete=models.CASCADE, related_name="irrigation_schedule"
    )
    phase_code = models.CharField(max_length=40)
    et0_mm_per_day = models.DecimalField(max_digits=6, decimal_places=3)
    kc = models.DecimalField(max_digits=5, decimal_places=3)
    application_efficiency_rate = models.DecimalField(max_digits=5, decimal_places=4)
    frequency_days = models.PositiveIntegerField(default=1)
    source_kind = models.CharField(max_length=20, choices=SourceKind.choices)
    computed_gross_l_per_day = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plan_version", "phase_code"], name="planned_irrigation_phase_unique"
            )
        ]

    def __str__(self) -> str:
        return f"{self.phase_code}: Kc {self.kc}"


class Observation(FarmScopedModel):
    """Field observation, created online or offline; append-only (FR-052, FR-111)."""

    class Kind(models.TextChoices):
        PEST = "pest", "Ravageur"
        DISEASE = "disease", "Maladie"
        GROWTH = "growth", "Croissance"
        WEATHER = "weather", "Météo"
        WATER = "water", "Eau / irrigation"
        OTHER = "other", "Autre"

    parcel = models.ForeignKey("fields.Parcel", on_delete=models.PROTECT, related_name="+")
    crop_cycle = models.ForeignKey(
        "production_plans.CropCycle",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    observed_at = models.DateTimeField()
    kind = models.CharField(max_length=20, choices=Kind.choices)
    target = models.CharField(max_length=200, blank=True)
    severity = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    affected_area_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    notes = models.TextField(blank=True)
    author = models.ForeignKey("users.User", on_delete=models.PROTECT, related_name="+")
    device = models.ForeignKey(
        "users.Device", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    photos = models.ManyToManyField("files.StoredFile", blank=True, related_name="+")
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-observed_at"]
        indexes = [models.Index(fields=["farm", "parcel", "observed_at"])]

    def __str__(self) -> str:
        return f"{self.kind} {self.observed_at:%Y-%m-%d}"
