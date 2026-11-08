"""User accounts and devices.

A user logs in with an email OR a phone number (OPEN_QUESTIONS Q3).
"""

import re
import uuid
from typing import Any, ClassVar

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

E164_PATTERN = re.compile(r"^\+[1-9]\d{6,14}$")


def normalize_email(email: str | None) -> str | None:
    if not email:
        return None
    return email.strip().lower()


def normalize_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    cleaned = re.sub(r"[\s\-().]", "", phone)
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    return cleaned


def validate_phone(phone: str) -> None:
    if not E164_PATTERN.match(phone):
        raise ValidationError("Numéro de téléphone invalide (format international +XXX…).")


class UserManager(BaseUserManager["User"]):
    use_in_migrations = True

    def create_user(
        self,
        email: str | None = None,
        password: str | None = None,
        *,
        phone: str | None = None,
        full_name: str = "",
        **extra: Any,
    ) -> "User":
        email = normalize_email(email)
        phone = normalize_phone(phone)
        if not email and not phone:
            raise ValueError("Un e-mail ou un numéro de téléphone est obligatoire.")
        user = self.model(email=email, phone=phone, full_name=full_name, **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_superuser(
        self, email: str | None = None, password: str | None = None, **extra: Any
    ) -> "User":
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra)

    def get_by_identifier(self, identifier: str) -> "User":
        identifier = identifier.strip()
        if "@" in identifier:
            return self.get(email=normalize_email(identifier))
        return self.get(phone=normalize_phone(identifier))


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(max_length=254, null=True, blank=True, unique=True)
    phone = models.CharField(
        max_length=20, null=True, blank=True, unique=True, validators=[validate_phone]
    )
    full_name = models.CharField(max_length=200)
    locale = models.CharField(max_length=10, default="fr")
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects: ClassVar[UserManager] = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(email__isnull=False) | models.Q(phone__isnull=False),
                name="user_email_or_phone_required",
            ),
            models.UniqueConstraint(Lower("email"), name="user_email_ci_unique"),
        ]

    def __str__(self) -> str:
        return self.full_name or self.email or self.phone or str(self.id)

    def clean(self) -> None:
        super().clean()
        self.email = normalize_email(self.email)
        self.phone = normalize_phone(self.phone)


class Device(models.Model):
    """A client installation. Revoking a device invalidates its tokens."""

    class Platform(models.TextChoices):
        WEB = "web", "Web"
        IOS = "ios", "iOS"
        ANDROID = "android", "Android"
        OTHER = "other", "Autre"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="devices")
    platform = models.CharField(max_length=10, choices=Platform.choices, default=Platform.OTHER)
    label = models.CharField(max_length=100, blank=True)
    client_version = models.CharField(max_length=50, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["user"])]

    def __str__(self) -> str:
        return f"{self.platform}:{self.label or self.id}"

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None
