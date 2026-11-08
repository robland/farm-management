import pytest
from django.db import IntegrityError

from apps.audit.models import AuditEvent
from apps.users.models import Device, User
from tests.factories import PASSWORD, make_user

pytestmark = pytest.mark.django_db


def login(api, identifier, password=PASSWORD, **extra):
    return api.post(
        "/api/v1/auth/login/",
        {"identifier": identifier, "password": password, **extra},
        format="json",
    )


def test_login_with_email_case_insensitive(api):
    user = make_user(email="Awa@Example.test")
    assert user.email == "awa@example.test"
    response = login(api, "AWA@example.TEST", platform="web")
    assert response.status_code == 200, response.json()
    body = response.json()
    assert {"access", "refresh", "device_id", "user_id"} <= set(body)
    assert Device.objects.get(id=body["device_id"]).platform == "web"
    assert AuditEvent.objects.filter(action="auth.login", actor=user).exists()


def test_login_with_phone_number(api):
    make_user(email=None, phone="+242 06 111 22 33")
    response = login(api, "+242061112233")
    assert response.status_code == 200


def test_login_wrong_password_and_unknown_user(api):
    make_user(email="a@example.test")
    for identifier, password in [("a@example.test", "bad-password"), ("nobody@x.test", PASSWORD)]:
        response = login(api, identifier, password)
        assert response.status_code == 400
        assert response.json()["code"] == "validation_error"


def test_inactive_user_cannot_login(api):
    make_user(email="off@example.test", is_active=False)
    assert login(api, "off@example.test").status_code == 400


def test_user_requires_email_or_phone():
    with pytest.raises(ValueError):
        User.objects.create_user(None, PASSWORD, full_name="X")
    with pytest.raises(IntegrityError):
        User.objects.create(full_name="X")


def test_access_token_authenticates_and_me_works(api):
    make_user(email="me@example.test")
    token = login(api, "me@example.test").json()["access"]
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    response = api.get("/api/v1/me/")
    assert response.status_code == 200
    assert response.json()["user"]["email"] == "me@example.test"


def test_refresh_rotates_and_old_refresh_is_blacklisted(api):
    make_user(email="r@example.test")
    refresh = login(api, "r@example.test").json()["refresh"]
    first = api.post("/api/v1/auth/refresh/", {"refresh": refresh}, format="json")
    assert first.status_code == 200
    assert first.json()["refresh"] != refresh
    replay = api.post("/api/v1/auth/refresh/", {"refresh": refresh}, format="json")
    assert replay.status_code == 401


def test_revoked_device_blocks_access_and_refresh(api):
    make_user(email="d@example.test")
    tokens = login(api, "d@example.test").json()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    revoke = api.post(f"/api/v1/me/devices/{tokens['device_id']}/revoke/")
    assert revoke.status_code == 200
    assert api.get("/api/v1/me/").status_code == 401
    api.credentials()
    refresh = api.post("/api/v1/auth/refresh/", {"refresh": tokens["refresh"]}, format="json")
    assert refresh.status_code == 400
    # A revoked device id cannot be reused at login.
    again = login(api, "d@example.test", device_id=tokens["device_id"])
    assert again.status_code == 400


def test_device_of_another_user_is_not_reused(api):
    make_user(email="u1@example.test")
    make_user(email="u2@example.test")
    device_id = login(api, "u1@example.test").json()["device_id"]
    other = login(api, "u2@example.test", device_id=device_id).json()
    assert other["device_id"] != device_id


def test_cannot_list_or_revoke_devices_of_others(api, client_for):
    owner = make_user(email="o@example.test")
    device_id = login(api, "o@example.test").json()["device_id"]
    intruder = client_for(make_user())
    assert intruder.get("/api/v1/me/devices/").json()["results"] == []
    assert intruder.post(f"/api/v1/me/devices/{device_id}/revoke/").status_code == 404
    assert Device.objects.get(id=device_id, user=owner).revoked_at is None


def test_logout_blacklists_refresh(api):
    make_user(email="l@example.test")
    tokens = login(api, "l@example.test").json()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    assert (
        api.post("/api/v1/auth/logout/", {"refresh": tokens["refresh"]}, format="json").status_code
        == 204
    )
    api.credentials()
    assert (
        api.post("/api/v1/auth/refresh/", {"refresh": tokens["refresh"]}, format="json").status_code
        == 401
    )


def test_change_password(client_for):
    user = make_user()
    client = client_for(user)
    bad = client.post(
        "/api/v1/auth/password/",
        {"current_password": "wrong", "new_password": "N3w-strong-pass!"},
        format="json",
    )
    assert bad.status_code == 400
    ok = client.post(
        "/api/v1/auth/password/",
        {"current_password": PASSWORD, "new_password": "N3w-strong-pass!"},
        format="json",
    )
    assert ok.status_code == 204
    user.refresh_from_db()
    assert user.check_password("N3w-strong-pass!")


def test_me_patch_cannot_change_email(client_for):
    user = make_user(email="keep@example.test")
    response = client_for(user).patch(
        "/api/v1/me/", {"full_name": "Nouveau", "email": "x@x.test"}, format="json"
    )
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.full_name == "Nouveau"
    assert user.email == "keep@example.test"
