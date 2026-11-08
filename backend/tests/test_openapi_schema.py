"""The OpenAPI document must generate without warnings and validate (CLAUDE.md §13)."""

import io

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_schema_generates_without_warnings_and_validates() -> None:
    out = io.StringIO()
    # --fail-on-warn turns any drf-spectacular warning into a CommandError.
    call_command("spectacular", "--fail-on-warn", "--validate", stdout=out)
    schema = out.getvalue()
    assert "openapi: 3." in schema
    assert "jwtAuth" in schema  # device-aware JWT documented as bearer auth
