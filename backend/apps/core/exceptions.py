"""Domain exceptions and the uniform API error format.

Error body (inspired by RFC 9457):
    {"code": str, "message": str, "details": dict, "field_errors": dict}
"""

import logging
from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.http import Http404
from rest_framework import exceptions as drf_exceptions
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


class DomainError(Exception):
    """Base class for business rule violations raised by services."""

    code: str = "domain_error"
    http_status: int = status.HTTP_400_BAD_REQUEST

    def __init__(
        self,
        message: str = "",
        *,
        details: dict[str, Any] | None = None,
        field_errors: dict[str, list[str]] | None = None,
    ) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        self.details = details or {}
        self.field_errors = field_errors or {}


class BusinessRuleError(DomainError):
    code = "business_rule_violation"


class NotFoundError(DomainError):
    """Also used for resources of another tenant: never reveal their existence."""

    code = "not_found"
    http_status = status.HTTP_404_NOT_FOUND


class PermissionDeniedError(DomainError):
    code = "permission_denied"
    http_status = status.HTTP_403_FORBIDDEN

    def __init__(self, permission: str = "") -> None:
        super().__init__(
            "Vous n'avez pas la permission requise.",
            details={"permission": permission} if permission else None,
        )


class VersionConflictError(DomainError):
    code = "version_conflict"
    http_status = status.HTTP_409_CONFLICT

    def __init__(self, current_version: int, current: dict[str, Any] | None = None) -> None:
        super().__init__(
            "La ressource a été modifiée entre-temps.",
            details={"current_version": current_version, "current": current or {}},
        )
        self.current_version = current_version


class PreconditionRequiredError(DomainError):
    code = "precondition_required"
    http_status = status.HTTP_428_PRECONDITION_REQUIRED


class IdentifierConflictError(DomainError):
    code = "identifier_conflict"
    http_status = status.HTTP_409_CONFLICT


def _body(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    field_errors: Any = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "details": details or {},
        "field_errors": field_errors or {},
    }


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    if isinstance(exc, DomainError):
        return Response(
            _body(exc.code, exc.message, exc.details, exc.field_errors), status=exc.http_status
        )
    if isinstance(exc, IntegrityError):
        # A database constraint caught what a service should have validated: never a
        # silent 500, but logged loudly so that the missing service check gets fixed.
        logger.error("Unhandled integrity error", exc_info=exc)
        return Response(
            _body("integrity_error", "Opération refusée par une contrainte d'intégrité."),
            status=status.HTTP_409_CONFLICT,
        )
    if isinstance(exc, DjangoValidationError):
        exc = drf_exceptions.ValidationError(
            exc.message_dict if hasattr(exc, "error_dict") else {"non_field_errors": exc.messages}
        )
    if isinstance(exc, Http404):
        exc = drf_exceptions.NotFound()
    if isinstance(exc, DjangoPermissionDenied):
        exc = drf_exceptions.PermissionDenied()

    response = exception_handler(exc, context)
    if response is None:
        return None

    if isinstance(exc, drf_exceptions.ValidationError):
        field_errors = (
            response.data
            if isinstance(response.data, dict)
            else {"non_field_errors": response.data}
        )
        response.data = _body("validation_error", "Données invalides.", field_errors=field_errors)
    elif isinstance(exc, drf_exceptions.APIException):
        codes = exc.get_codes()
        code = codes if isinstance(codes, str) else "error"
        response.data = _body(code, str(exc.detail))
    return response
