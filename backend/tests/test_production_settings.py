"""Production settings hardening (ARCHITECTURE.md §11): Django deployment checks."""

import importlib
import sys

import pytest
from django.core.checks import run_checks
from django.test import override_settings

SECURITY_SETTINGS = [
    "DEBUG",
    "SECURE_PROXY_SSL_HEADER",
    "SECURE_SSL_REDIRECT",
    "SECURE_HSTS_SECONDS",
    "SECURE_HSTS_INCLUDE_SUBDOMAINS",
    "SESSION_COOKIE_SECURE",
    "CSRF_COOKIE_SECURE",
    "SECURE_CONTENT_TYPE_NOSNIFF",
    "X_FRAME_OPTIONS",
    "SECURE_HSTS_PRELOAD",
    "SILENCED_SYSTEM_CHECKS",
]


@pytest.fixture
def prod(monkeypatch):
    monkeypatch.setenv("DJANGO_SECRET_KEY", "prod-check-" + "k" * 60)
    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "fms.example.org")
    monkeypatch.delenv("DJANGO_DEBUG", raising=False)
    sys.modules.pop("config.settings.prod", None)
    sys.modules.pop("config.settings.base", None)
    module = importlib.import_module("config.settings.prod")
    yield module
    sys.modules.pop("config.settings.prod", None)
    sys.modules.pop("config.settings.base", None)


def test_production_settings_pass_deployment_checks(prod):
    values = {name: getattr(prod, name) for name in SECURITY_SETTINGS}
    values.update(SECRET_KEY=prod.SECRET_KEY, ALLOWED_HOSTS=prod.ALLOWED_HOSTS)
    with override_settings(**values):
        warnings = [
            m
            for m in run_checks(include_deployment_checks=True)
            if m.id.startswith("security.") and not m.is_silenced()
        ]
    assert warnings == [], [f"{w.id}: {w.msg}" for w in warnings]
    # Only the HSTS preload opt-in may be silenced, nothing else.
    assert set(prod.SILENCED_SYSTEM_CHECKS) <= {"security.W021"}


def test_production_never_runs_in_debug(prod):
    assert prod.DEBUG is False
    assert prod.ALLOWED_HOSTS == ["fms.example.org"]
    assert prod.SECURE_HSTS_SECONDS >= 31536000
