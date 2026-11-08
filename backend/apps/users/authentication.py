from typing import Any

from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.users.models import Device


class DeviceAwareJWTAuthentication(JWTAuthentication):
    """JWT authentication that rejects tokens issued to a revoked device."""

    def authenticate(self, request: Request) -> tuple[Any, Any] | None:
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        device_id = token.get("device_id")
        if (
            device_id is not None
            and not Device.objects.filter(
                id=device_id, user_id=user.pk, revoked_at__isnull=True
            ).exists()
        ):
            raise AuthenticationFailed("Appareil révoqué.", code="device_revoked")
        return user, token
