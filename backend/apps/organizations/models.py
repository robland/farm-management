from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

from apps.core.models import TimestampedModel, UUIDModel, VersionedModel

currency_validator = RegexValidator(r"^[A-Z]{3}$", "Code devise ISO 4217 attendu (ex. XAF).")
country_validator = RegexValidator(r"^[A-Z]{2}$", "Code pays ISO 3166-1 alpha-2 attendu (ex. CG).")


class Organization(UUIDModel, TimestampedModel, VersionedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspendue"

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80, unique=True)
    country = models.CharField(max_length=2, validators=[country_validator])
    default_currency = models.CharField(max_length=3, validators=[currency_validator])
    default_timezone = models.CharField(max_length=64)
    default_locale = models.CharField(max_length=10, default="fr")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    def __str__(self) -> str:
        return self.name


class OrganizationMembership(UUIDModel, TimestampedModel, VersionedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DISABLED = "disabled", "Désactivée"

    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="organization_memberships"
    )
    is_org_admin = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "user"], name="org_membership_unique")
        ]
        indexes = [models.Index(fields=["user", "status"])]

    def __str__(self) -> str:
        return f"{self.user} @ {self.organization}"


class Role(UUIDModel, TimestampedModel, VersionedModel):
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="roles")
    code = models.SlugField(max_length=64)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_system = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "code"], name="role_code_unique")
        ]

    def __str__(self) -> str:
        return self.name

    def permission_codes(self) -> set[str]:
        return set(self.permissions.values_list("permission_code", flat=True))


class RolePermission(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="permissions")
    permission_code = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["role", "permission_code"], name="role_permission_unique"
            )
        ]

    def __str__(self) -> str:
        return f"{self.role_id}:{self.permission_code}"


class Invitation(UUIDModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="invitations"
    )
    farm = models.ForeignKey(
        "farms.Farm", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    role = models.ForeignKey(Role, on_delete=models.PROTECT, null=True, blank=True)
    make_org_admin = models.BooleanField(default=False)
    # NULL (not "") means "not provided": the CHECK constraint requires one of the two.
    email = models.EmailField(null=True, blank=True)  # noqa: DJ001
    phone = models.CharField(max_length=20, null=True, blank=True)  # noqa: DJ001
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(email__isnull=False) | models.Q(phone__isnull=False),
                name="invitation_email_or_phone",
            ),
            models.CheckConstraint(
                condition=models.Q(farm__isnull=True) | models.Q(role__isnull=False),
                name="invitation_farm_requires_role",
            ),
        ]

    def __str__(self) -> str:
        return f"Invitation {self.email or self.phone} -> {self.organization_id}"
