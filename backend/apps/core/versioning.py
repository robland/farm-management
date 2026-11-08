"""Optimistic concurrency helpers (ARCHITECTURE.md §2.3).

PATCH/PUT/DELETE on versioned resources require `If-Match: <version>`.
A missing header yields 428, a stale version yields 409.
"""

from typing import Any

from django.db import models
from rest_framework.request import Request

from apps.core.exceptions import PreconditionRequiredError, VersionConflictError


def parse_if_match(request: Request) -> int:
    raw = request.headers.get("If-Match", "").strip()
    if raw.startswith("W/"):
        raw = raw[2:]
    raw = raw.strip('"')
    if not raw:
        raise PreconditionRequiredError("L'en-tête If-Match (version) est obligatoire.")
    try:
        version = int(raw)
    except ValueError as exc:
        raise PreconditionRequiredError("L'en-tête If-Match doit contenir un entier.") from exc
    if version < 1:
        raise PreconditionRequiredError("Version invalide.")
    return version


def check_version(instance: Any, expected_version: int) -> None:
    if instance.version != expected_version:
        raise VersionConflictError(current_version=instance.version)


def apply_changes(instance: models.Model, changes: dict[str, Any]) -> dict[str, list[Any]]:
    """Set attributes and return the diff `{field: [old, new]}` of actually changed fields."""
    diff: dict[str, list[Any]] = {}
    for name, value in changes.items():
        old = getattr(instance, name)
        if old != value:
            setattr(instance, name, value)
            diff[name] = [old, value]
    return diff
