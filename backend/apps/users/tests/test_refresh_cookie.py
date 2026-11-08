"""Web refresh token in an HttpOnly cookie (OPEN_QUESTIONS Q26, apps/users/cookies.py)."""

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.users.cookies import COOKIE_NAME, COOKIE_PATH, TRANSPORT_HEADER
from tests.factories import PASSWORD, make_user

pytestmark = pytest.mark.django_db

COOKIE_MODE = {f"HTTP_{TRANSPORT_HEADER.upper().replace('-', '_')}": "cookie"}


def web_login(api: APIClient, email: str):
    return api.post(
        "/api/v1/auth/login/",
        {"identifier": email, "password": PASSWORD, "platform": "web"},
        format="json",
        **COOKIE_MODE,
    )


def test_login_puts_the_refresh_token_in_an_httponly_cookie_only(api):
    make_user(email="web@example.test")
    response = web_login(api, "web@example.test")
    assert response.status_code == 200
    assert "refresh" not in response.json() and "access" in response.json()
    cookie = response.cookies[COOKIE_NAME]
    assert cookie.value
    assert cookie["httponly"] and cookie["secure"]
    assert cookie["samesite"] == "Strict" and cookie["path"] == COOKIE_PATH
    assert int(cookie["max-age"]) > 0


def test_mobile_login_is_unchanged(api):
    make_user(email="mobile@example.test")
    response = api.post(
        "/api/v1/auth/login/",
        {"identifier": "mobile@example.test", "password": PASSWORD, "platform": "android"},
        format="json",
    )
    assert "refresh" in response.json()
    assert COOKIE_NAME not in response.cookies


def test_refresh_from_cookie_rotates_and_the_old_cookie_is_refused(api):
    make_user(email="rot@example.test")
    old = web_login(api, "rot@example.test").cookies[COOKIE_NAME].value
    response = api.post("/api/v1/auth/refresh/", {}, format="json", **COOKIE_MODE)
    assert response.status_code == 200, response.json()
    assert "access" in response.json() and "refresh" not in response.json()
    new = response.cookies[COOKIE_NAME].value
    assert new and new != old

    replay = APIClient()
    replay.cookies[COOKIE_NAME] = old
    refused = replay.post("/api/v1/auth/refresh/", {}, format="json", **COOKIE_MODE)
    assert refused.status_code == 401
    assert refused.json()["code"]  # uniform error body
    assert refused.cookies[COOKIE_NAME].value == ""  # cleared


def test_cookie_is_ignored_without_the_transport_header(api):
    """A cross-site request cannot add the header: the cookie alone authenticates nothing."""
    make_user(email="csrf@example.test")
    web_login(api, "csrf@example.test")
    response = api.post("/api/v1/auth/refresh/", {}, format="json")
    assert response.status_code == 400  # body token required, the cookie is not read
    assert "access" not in response.json()


def test_refresh_without_cookie_is_unauthenticated():
    response = APIClient().post("/api/v1/auth/refresh/", {}, format="json", **COOKIE_MODE)
    assert response.status_code == 401


def test_legacy_local_storage_token_is_moved_to_the_cookie(api):
    make_user(email="legacy@example.test")
    tokens = api.post(
        "/api/v1/auth/login/",
        {"identifier": "legacy@example.test", "password": PASSWORD, "platform": "web"},
        format="json",
    ).json()
    response = APIClient().post(
        "/api/v1/auth/refresh/", {"refresh": tokens["refresh"]}, format="json", **COOKIE_MODE
    )
    assert response.status_code == 200
    assert "refresh" not in response.json() and response.cookies[COOKIE_NAME].value


def test_revoked_device_clears_the_cookie(api):
    make_user(email="lost@example.test")
    login = web_login(api, "lost@example.test").json()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {login['access']}")
    api.post(f"/api/v1/me/devices/{login['device_id']}/revoke/")
    api.credentials()
    response = api.post("/api/v1/auth/refresh/", {}, format="json", **COOKIE_MODE)
    assert response.status_code == 400
    assert response.cookies[COOKIE_NAME].value == ""


def test_logout_revokes_the_cookie_token_without_an_access_token(api):
    make_user(email="out@example.test")
    token = web_login(api, "out@example.test").cookies[COOKIE_NAME].value
    response = api.post("/api/v1/auth/logout/", {}, format="json", **COOKIE_MODE)
    assert response.status_code == 204
    assert response.cookies[COOKIE_NAME].value == ""
    replay = APIClient()
    replay.cookies[COOKIE_NAME] = token
    assert replay.post("/api/v1/auth/refresh/", {}, format="json", **COOKIE_MODE).status_code == 401


def test_body_logout_still_requires_authentication():
    assert (
        APIClient().post("/api/v1/auth/logout/", {"refresh": "x"}, format="json").status_code == 401
    )


@override_settings(FMS_REFRESH_COOKIE_SECURE=False)
def test_cookie_can_be_sent_over_http_in_local_development(api):
    make_user(email="dev@example.test")
    assert not web_login(api, "dev@example.test").cookies[COOKIE_NAME]["secure"]
