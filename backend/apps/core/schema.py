"""OpenAPI schema extensions (drf-spectacular)."""

from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme


class DeviceAwareJWTScheme(SimpleJWTScheme):
    """Document the device-aware JWT authentication as a bearer token."""

    target_class = "apps.users.authentication.DeviceAwareJWTAuthentication"
    name = "jwtAuth"
