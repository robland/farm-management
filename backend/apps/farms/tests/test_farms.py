import pytest

from apps.farms.models import FarmMembership
from apps.organizations.models import Role
from apps.synchronization.models import ChangeLog, FarmSyncState
from tests.factories import make_user

pytestmark = pytest.mark.django_db

FARM_PAYLOAD = {
    "name": "Ferme de Test",
    "code": "test-1",
    "country": "CG",
    "timezone": "Africa/Brazzaville",
    "currency": "XAF",
}


def test_org_admin_creates_several_farms(world, client_for):
    client = client_for(world.admin_a)
    url = f"/api/v1/organizations/{world.org_a.id}/farms/"
    response = client.post(url, FARM_PAYLOAD, format="json")
    assert response.status_code == 201, response.json()
    farm_id = response.json()["id"]
    assert FarmSyncState.objects.filter(farm_id=farm_id).exists()
    assert ChangeLog.objects.filter(farm_id=farm_id, entity_type="farms.farm").count() == 1
    duplicate = client.post(url, FARM_PAYLOAD, format="json")
    assert duplicate.status_code == 400
    assert len(client.get(url).json()["results"]) == 3


def test_only_org_admin_creates_farms(world, client_for):
    url = f"/api/v1/organizations/{world.org_a.id}/farms/"
    response = client_for(world.manager_a1).post(url, FARM_PAYLOAD, format="json")
    assert response.status_code == 403


def test_user_sees_only_authorized_farms_with_distinct_roles(world, client_for):
    me = client_for(world.worker_a1).get("/api/v1/me/").json()
    farms = {f["id"]: f for f in me["farms"]}
    assert set(farms) == {str(world.farm_a1.id), str(world.farm_a2.id)}
    assert farms[str(world.farm_a1.id)]["role"] == "worker"
    assert farms[str(world.farm_a2.id)]["role"] == "technician"
    assert "fields.edit" not in farms[str(world.farm_a1.id)]["permissions"]
    listed = client_for(world.worker_a1).get("/api/v1/farms/").json()["results"]
    assert {f["id"] for f in listed} == set(farms)


def test_org_admin_sees_all_org_farms(world, client_for):
    listed = client_for(world.admin_a).get("/api/v1/farms/").json()["results"]
    assert {f["id"] for f in listed} == {str(world.farm_a1.id), str(world.farm_a2.id)}


def test_outsider_member_without_farm_role_sees_no_farm(world, client_for):
    client = client_for(world.outsider)
    assert client.get("/api/v1/farms/").json()["results"] == []
    assert client.get(f"/api/v1/farms/{world.farm_a1.id}/").status_code == 404


def test_update_farm_settings_merges_and_validates(world, client_for):
    client = client_for(world.manager_a1)
    url = f"/api/v1/farms/{world.farm_a1.id}/"
    ok = client.patch(
        url, {"settings": {"area_tolerance_pct": 5}}, format="json", HTTP_IF_MATCH="1"
    )
    assert ok.status_code == 200, ok.json()
    assert ok.json()["settings"] == {"area_tolerance_pct": 5}
    unknown = client.patch(url, {"settings": {"foo": 1}}, format="json", HTTP_IF_MATCH="2")
    assert unknown.status_code == 400
    wrong_type = client.patch(
        url, {"settings": {"area_tolerance_pct": True}}, format="json", HTTP_IF_MATCH="2"
    )
    assert wrong_type.status_code == 400


def test_worker_cannot_update_farm(world, client_for):
    response = client_for(world.worker_a1).patch(
        f"/api/v1/farms/{world.farm_a1.id}/", {"name": "X"}, format="json", HTTP_IF_MATCH="1"
    )
    assert response.status_code == 403


def test_member_management(world, client_for):
    newcomer = make_user()
    from apps.organizations.models import OrganizationMembership

    OrganizationMembership.objects.create(organization=world.org_a, user=newcomer)
    role = Role.objects.get(organization=world.org_a, code="storekeeper")
    client = client_for(world.manager_a1)
    url = f"/api/v1/farms/{world.farm_a1.id}/members/"
    created = client.post(url, {"user": str(newcomer.id), "role": str(role.id)}, format="json")
    assert created.status_code == 201, created.json()
    duplicate = client.post(url, {"user": str(newcomer.id), "role": str(role.id)}, format="json")
    assert duplicate.status_code == 400

    worker_role = Role.objects.get(organization=world.org_a, code="worker")
    updated = client.patch(
        f"{url}{created.json()['id']}/",
        {"role": str(worker_role.id)},
        format="json",
        HTTP_IF_MATCH="1",
    )
    assert updated.status_code == 200
    assert updated.json()["role_code"] == "worker"


def test_cannot_add_user_from_another_organization(world, client_for):
    role = Role.objects.get(organization=world.org_a, code="worker")
    response = client_for(world.admin_a).post(
        f"/api/v1/farms/{world.farm_a1.id}/members/",
        {"user": str(world.admin_b.id), "role": str(role.id)},
        format="json",
    )
    assert response.status_code == 400
    assert not FarmMembership.objects.filter(user=world.admin_b, farm=world.farm_a1).exists()


def test_membership_validity_window(world, client_for):
    import datetime

    FarmMembership.objects.filter(user=world.worker_a1, farm=world.farm_a1).update(
        valid_to=datetime.date(2000, 1, 1)
    )
    client = client_for(world.worker_a1)
    assert client.get(f"/api/v1/farms/{world.farm_a1.id}/").status_code == 404
    assert client.get(f"/api/v1/farms/{world.farm_a2.id}/").status_code == 200
