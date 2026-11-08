import pytest

from apps.farms.models import FarmMembership
from apps.organizations.models import Invitation, OrganizationMembership, Role
from apps.organizations.permissions_catalog import DEFAULT_ROLES, PERMISSIONS
from tests.factories import PASSWORD, make_user

pytestmark = pytest.mark.django_db

ORG_PAYLOAD = {
    "name": "Coopérative Test",
    "country": "CG",
    "default_currency": "XAF",
    "default_timezone": "Africa/Brazzaville",
}


def test_create_organization_makes_creator_admin_and_seeds_roles(client_for):
    user = make_user()
    response = client_for(user).post("/api/v1/organizations/", ORG_PAYLOAD, format="json")
    assert response.status_code == 201, response.json()
    org_id = response.json()["id"]
    membership = OrganizationMembership.objects.get(organization_id=org_id, user=user)
    assert membership.is_org_admin
    codes = set(Role.objects.filter(organization_id=org_id).values_list("code", flat=True))
    assert codes == set(DEFAULT_ROLES)


def test_default_roles_only_reference_known_permissions():
    for spec in DEFAULT_ROLES.values():
        assert set(spec["permissions"]) <= set(PERMISSIONS)


@pytest.mark.parametrize(
    "field,value", [("country", "Congo"), ("default_currency", "xaf"), ("default_timezone", "Mars")]
)
def test_create_organization_validation(client_for, field, value):
    response = client_for(make_user()).post(
        "/api/v1/organizations/", {**ORG_PAYLOAD, field: value}, format="json"
    )
    assert response.status_code == 400
    assert field in response.json()["field_errors"]


def test_list_only_own_organizations(world, client_for):
    names = [
        o["name"] for o in client_for(world.admin_a).get("/api/v1/organizations/").json()["results"]
    ]
    assert names == ["Org A"]


def test_update_organization_requires_if_match_and_detects_conflict(world, client_for):
    client = client_for(world.admin_a)
    url = f"/api/v1/organizations/{world.org_a.id}/"
    assert client.patch(url, {"name": "X"}, format="json").status_code == 428
    assert client.patch(url, {"name": "X"}, format="json", HTTP_IF_MATCH="5").status_code == 409
    ok = client.patch(url, {"name": "Org A bis"}, format="json", HTTP_IF_MATCH="1")
    assert ok.status_code == 200
    assert ok.json()["version"] == 2


def test_non_admin_cannot_update_organization(world, client_for):
    url = f"/api/v1/organizations/{world.org_a.id}/"
    response = client_for(world.manager_a1).patch(
        url, {"name": "X"}, format="json", HTTP_IF_MATCH="1"
    )
    assert response.status_code == 403


def test_other_org_is_not_found(world, client_for):
    url = f"/api/v1/organizations/{world.org_b.id}/"
    assert client_for(world.admin_a).get(url).status_code == 404
    assert (
        client_for(world.admin_a)
        .patch(url, {"name": "X"}, format="json", HTTP_IF_MATCH="1")
        .status_code
        == 404
    )


def test_custom_role_lifecycle(world, client_for):
    client = client_for(world.admin_a)
    base = f"/api/v1/organizations/{world.org_a.id}/roles/"
    created = client.post(
        base,
        {
            "code": "scout",
            "name": "Observateur",
            "permissions": ["fields.view", "observations.create"],
        },
        format="json",
    )
    assert created.status_code == 201, created.json()
    role_id = created.json()["id"]
    assert created.json()["permissions"] == ["fields.view", "observations.create"]

    bad = client.post(
        base, {"code": "bad", "name": "Bad", "permissions": ["root.all"]}, format="json"
    )
    assert bad.status_code == 400
    dup = client.post(base, {"code": "scout", "name": "Dup"}, format="json")
    assert dup.status_code == 400

    updated = client.patch(
        f"{base}{role_id}/", {"permissions": ["fields.view"]}, format="json", HTTP_IF_MATCH="1"
    )
    assert updated.status_code == 200
    assert updated.json()["permissions"] == ["fields.view"]
    assert client.delete(f"{base}{role_id}/").status_code == 204


def test_system_role_cannot_be_deleted(world, client_for):
    role = Role.objects.get(organization=world.org_a, code="worker")
    url = f"/api/v1/organizations/{world.org_a.id}/roles/{role.id}/"
    assert client_for(world.admin_a).delete(url).status_code == 400


def test_role_edition_requires_org_admin(world, client_for):
    base = f"/api/v1/organizations/{world.org_a.id}/roles/"
    assert client_for(world.manager_a1).get(base).status_code == 200
    response = client_for(world.manager_a1).post(base, {"code": "x", "name": "x"}, format="json")
    assert response.status_code == 403


def test_disable_member_cascades_to_farm_memberships(world, client_for):
    membership = OrganizationMembership.objects.get(organization=world.org_a, user=world.worker_a1)
    url = f"/api/v1/organizations/{world.org_a.id}/members/{membership.id}/"
    response = client_for(world.admin_a).patch(
        url, {"status": "disabled"}, format="json", HTTP_IF_MATCH="1"
    )
    assert response.status_code == 200
    assert not FarmMembership.objects.filter(user=world.worker_a1, status="active").exists()
    farm_url = f"/api/v1/farms/{world.farm_a1.id}/"
    assert client_for(world.worker_a1).get(farm_url).status_code == 404


def test_last_admin_cannot_be_removed(world, client_for):
    membership = OrganizationMembership.objects.get(organization=world.org_a, user=world.admin_a)
    url = f"/api/v1/organizations/{world.org_a.id}/members/{membership.id}/"
    response = client_for(world.admin_a).patch(
        url, {"is_org_admin": False}, format="json", HTTP_IF_MATCH="1"
    )
    assert response.status_code == 400


def _invite(client, org_id, **payload):
    return client.post(f"/api/v1/organizations/{org_id}/invitations/", payload, format="json")


def test_invitation_creates_account_and_farm_access(world, client_for, api):
    role = Role.objects.get(organization=world.org_a, code="worker")
    response = _invite(
        client_for(world.admin_a),
        world.org_a.id,
        phone="+242065550000",
        farm=str(world.farm_a1.id),
        role=str(role.id),
    )
    assert response.status_code == 201, response.json()
    token = response.json()["token"]
    invitation = Invitation.objects.get(id=response.json()["id"])
    assert invitation.token_hash != token  # only the hash is stored

    accepted = api.post(
        "/api/v1/invitations/accept/",
        {"token": token, "full_name": "Nouvel Ouvrier", "password": PASSWORD},
        format="json",
    )
    assert accepted.status_code == 200, accepted.json()
    login = api.post(
        "/api/v1/auth/login/", {"identifier": "+242065550000", "password": PASSWORD}, format="json"
    )
    assert login.status_code == 200
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {login.json()['access']}")
    farms = api.get("/api/v1/me/").json()["farms"]
    assert [f["id"] for f in farms] == [str(world.farm_a1.id)]
    assert farms[0]["role"] == "worker"

    # Single use.
    again = api.post("/api/v1/invitations/accept/", {"token": token}, format="json")
    assert again.status_code == 400


def test_invitation_for_existing_account_requires_login_and_identity(world, client_for, api):
    existing = make_user(email="exist@example.test")
    role = Role.objects.get(organization=world.org_a, code="technician")
    token = _invite(
        client_for(world.admin_a),
        world.org_a.id,
        email="exist@example.test",
        farm=str(world.farm_a2.id),
        role=str(role.id),
    ).json()["token"]
    anonymous = api.post(
        "/api/v1/invitations/accept/",
        {"token": token, "full_name": "X", "password": PASSWORD},
        format="json",
    )
    assert anonymous.status_code == 400
    wrong_user = client_for(make_user()).post(
        "/api/v1/invitations/accept/", {"token": token}, format="json"
    )
    assert wrong_user.status_code == 400
    ok = client_for(existing).post("/api/v1/invitations/accept/", {"token": token}, format="json")
    assert ok.status_code == 200
    assert FarmMembership.objects.filter(user=existing, farm=world.farm_a2).exists()


def test_revoked_invitation_cannot_be_accepted(world, client_for, api):
    created = _invite(client_for(world.admin_a), world.org_a.id, email="rev@example.test").json()
    revoke = client_for(world.admin_a).post(
        f"/api/v1/organizations/{world.org_a.id}/invitations/{created['id']}/revoke/"
    )
    assert revoke.status_code == 200
    response = api.post(
        "/api/v1/invitations/accept/",
        {"token": created["token"], "full_name": "X", "password": PASSWORD},
        format="json",
    )
    assert response.status_code == 400


def test_farm_manager_can_invite_only_to_own_farm(world, client_for):
    role = Role.objects.get(organization=world.org_a, code="worker")
    client = client_for(world.manager_a1)
    own = _invite(
        client,
        world.org_a.id,
        email="w1@example.test",
        farm=str(world.farm_a1.id),
        role=str(role.id),
    )
    assert own.status_code == 201
    other = _invite(
        client,
        world.org_a.id,
        email="w2@example.test",
        farm=str(world.farm_a2.id),
        role=str(role.id),
    )
    assert other.status_code == 404
    org_level = _invite(client, world.org_a.id, email="w3@example.test")
    assert org_level.status_code == 403


def test_invitation_cannot_target_other_org_farm_or_role(world, client_for):
    role_b = Role.objects.get(organization=world.org_b, code="worker")
    client = client_for(world.admin_a)
    farm_b = _invite(
        client,
        world.org_a.id,
        email="x@example.test",
        farm=str(world.farm_b1.id),
        role=str(Role.objects.get(organization=world.org_a, code="worker").id),
    )
    assert farm_b.status_code == 404
    role_other = _invite(
        client,
        world.org_a.id,
        email="y@example.test",
        farm=str(world.farm_a1.id),
        role=str(role_b.id),
    )
    assert role_other.status_code == 400


def test_permission_catalog(client_for):
    response = client_for(make_user()).get("/api/v1/permissions/")
    assert response.status_code == 200
    assert {p["code"] for p in response.json()} == set(PERMISSIONS)
