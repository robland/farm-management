from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import QuerySet
from rest_framework import serializers


class FarmScopedPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    """FK field that only resolves objects of the request's farm (ARCHITECTURE.md §6.2).

    Objects of another farm or organization are reported as not found,
    without revealing their existence.
    """

    default_error_messages = {
        "does_not_exist": "Objet introuvable.",
        "incorrect_type": "Identifiant invalide.",
    }

    def get_queryset(self) -> QuerySet[Any]:
        queryset = super().get_queryset()
        assert queryset is not None, "A queryset is required."  # noqa: S101
        tenant = self.context["tenant"]
        queryset = queryset.filter(farm_id=tenant.farm_id)
        if hasattr(queryset.model, "deleted_at"):
            queryset = queryset.filter(deleted_at__isnull=True)
        return queryset

    def to_internal_value(self, data: Any) -> Any:
        try:
            return super().to_internal_value(data)
        except DjangoValidationError:
            # Malformed UUID raised by the model field.
            self.fail("incorrect_type", data_type=type(data).__name__)
