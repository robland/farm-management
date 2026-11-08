from decimal import Decimal as D

import pytest

from apps.production_plans.models import CropCycle, FieldProvenance, PlanVersion
from tests.factories import make_parcel
from tests.factories_plans import make_validated_variety

pytestmark = pytest.mark.django_db


class PlanApi:
    def __init__(self, client, farm):
        self.client, self.base = client, f"/api/v1/farms/{farm.id}"

    def post(self, path, data=None, version=None):
        extra = {"HTTP_IF_MATCH": str(version)} if version is not None else {}
        return self.client.post(f"{self.base}/{path}", data or {}, format="json", **extra)

    def put(self, path, data, version):
        return self.client.put(
            f"{self.base}/{path}", data, format="json", HTTP_IF_MATCH=str(version)
        )

    def patch(self, path, data, version):
        return self.client.patch(
            f"{self.base}/{path}", data, format="json", HTTP_IF_MATCH=str(version)
        )

    def get(self, path, params=None):
        return self.client.get(f"{self.base}/{path}", params or {})

    def version(self, version_id):
        return self.get(f"plan-versions/{version_id}/").json()


def create_plan(api, variety, name="Plan pastèque"):
    campaign = api.post(
        "campaigns/", {"name": "Saison 1", "start_date": "2026-01-01", "end_date": "2026-06-30"}
    )
    assert campaign.status_code == 201, campaign.json()
    plan = api.post(
        "plans/", {"campaign": campaign.json()["id"], "variety": str(variety.id), "name": name}
    )
    assert plan.status_code == 201, plan.json()
    versions = api.get("plan-versions/", {"plan": plan.json()["id"]}).json()["results"]
    return plan.json(), versions[0]


def complete_draft(api, version, parcel, area="1000"):
    vid = version["id"]
    r = api.post(f"plan-versions/{vid}/prefill/", version=version["version"])
    assert r.status_code == 200, r.json()
    v = api.version(vid)
    r = api.put(
        f"plan-versions/{vid}/allocations/",
        {
            "allocations": [
                {"parcel": str(parcel.id), "allocated_area_m2": area, "non_plantable_area_m2": "0"}
            ]
        },
        v["version"],
    )
    assert r.status_code == 200, r.json()
    r = api.patch(
        f"plan-versions/{vid}/planting-spec/",
        {"planting_method": "direct_seeding", "safety_margin_rate": "0.1"},
        r.json()["version"],
    )
    assert r.status_code == 200, r.json()
    r = api.patch(
        f"plan-versions/{vid}/", {"planned_start_date": "2026-01-01"}, r.json()["version"]
    )
    assert r.status_code == 200, r.json()
    return r.json()


def test_manual_plan_full_workflow(world, client_for):
    api = PlanApi(client_for(world.manager_a1), world.farm_a1)
    variety = make_validated_variety(world.org_a, world.admin_a)
    parcel = make_parcel(world.farm_a1, area_m2=D(1000))
    plan, version = create_plan(api, variety)
    assert version["status"] == "draft" and version["number"] == 1

    # Prefill copies validated data with provenance; phases are created in FR-033 order.
    prefill = api.post(f"plan-versions/{version['id']}/prefill/", version=version["version"])
    assert prefill.status_code == 200
    assert "row_spacing_m" in prefill.json()["filled"]
    data = prefill.json()["version"]
    assert [p["phase_code"] for p in data["phases"]] == [
        "soil_preparation",
        "sowing",
        "vegetative",
        "harvest",
    ]
    provenance = {p["field_path"]: p["source_kind"] for p in data["provenances"]}
    assert provenance["planting_spec.row_spacing_m"] == "document"
    assert provenance["planting_spec.germination_rate"] == "user_input"

    # Missing information is listed explicitly, nothing is defaulted.
    computed = api.post(f"plan-versions/{version['id']}/compute/").json()
    assert computed["complete"] is False
    missing = {f for m in computed["missing"] for f in m["fields"]}
    assert {"allocations", "start_date"} <= missing

    version = complete_draft(api, api.version(version["id"]), parcel)
    computed = api.post(f"plan-versions/{version['id']}/compute/").json()
    assert computed["complete"] is True, computed
    assert computed["totals"]["plant_count"] == 1333
    assert computed["totals"]["seed_count"] == 3666  # ceil(1333 × 2 × 1.1 / 0.8)
    assert computed["totals"]["cycle_end_date"] == "2026-02-27"
    calc_types = {r["calc_type"] for r in computed["results"]}
    assert calc_types == {"planting.density", "planting.seeds", "calendar.phases"}

    version = api.version(version["id"])
    validated = api.post(f"plan-versions/{version['id']}/validate/", version=version["version"])
    assert validated.status_code == 200, validated.json()
    body = validated.json()
    assert body["status"] == "validated" and body["planned_end_date"] == "2026-02-27"
    assert api.get(f"plans/{plan['id']}/").json()["status"] == "validated"
    cycle = CropCycle.objects.get(plan_id=plan["id"])
    assert cycle.area_m2 == D(1000) and cycle.parcel == parcel

    # A validated version is immutable.
    refused = api.patch(
        f"plan-versions/{body['id']}/planting-spec/", {"plant_spacing_m": "0.4"}, body["version"]
    )
    assert refused.status_code == 400


def test_new_version_compare_and_supersede(world, client_for):
    api = PlanApi(client_for(world.manager_a1), world.farm_a1)
    variety = make_validated_variety(world.org_a, world.admin_a)
    parcel = make_parcel(world.farm_a1, area_m2=D(2000))
    plan, version = create_plan(api, variety)
    version = complete_draft(api, version, parcel)
    v1 = api.post(f"plan-versions/{version['id']}/validate/", version=version["version"]).json()

    draft = api.post(f"plans/{plan['id']}/new-version/", {"change_note": "Écartement réduit"})
    assert draft.status_code == 201, draft.json()
    v2 = draft.json()
    assert v2["number"] == 2 and v2["based_on"] == v1["id"] and v2["status"] == "draft"
    assert api.post(f"plans/{plan['id']}/new-version/").status_code == 400  # one draft at a time

    changed = api.patch(
        f"plan-versions/{v2['id']}/planting-spec/", {"plant_spacing_m": "0.4"}, v2["version"]
    ).json()
    resized = api.put(
        f"plan-versions/{v2['id']}/allocations/",
        {
            "allocations": [
                {
                    "parcel": str(parcel.id),
                    "allocated_area_m2": "1500",
                    "non_plantable_area_m2": "0",
                }
            ]
        },
        changed["version"],
    ).json()
    api.post(f"plan-versions/{v2['id']}/compute/")
    comparison = api.get(f"plans/{plan['id']}/compare/", {"a": v1["id"], "b": v2["id"]}).json()
    fields = {(d["section"], d["field"]) for d in comparison["differences"]}
    assert ("planting_spec", "plant_spacing_m") in fields
    assert ("allocations", str(parcel.id)) in fields
    assert ("results", "plant_count") in fields

    validated = api.post(f"plan-versions/{v2['id']}/validate/", version=resized["version"] + 1)
    assert validated.status_code == 200, validated.json()
    statuses = dict(PlanVersion.objects.filter(plan_id=plan["id"]).values_list("number", "status"))
    assert statuses == {1: "superseded", 2: "validated"}
    cycle = CropCycle.objects.get(plan_id=plan["id"])
    assert cycle.area_m2 == D(1500) and str(cycle.plan_version_id) == v2["id"]


def test_parcel_overbooking_is_refused(world, client_for):
    api = PlanApi(client_for(world.manager_a1), world.farm_a1)
    variety = make_validated_variety(world.org_a, world.admin_a)
    parcel = make_parcel(world.farm_a1, area_m2=D(1000))
    _, first = create_plan(api, variety, "Plan 1")
    first = complete_draft(api, first, parcel, area="600")
    assert (
        api.post(f"plan-versions/{first['id']}/validate/", version=first["version"]).status_code
        == 200
    )
    _, second = create_plan(api, variety, "Plan 2")
    second = complete_draft(api, second, parcel, area="500")
    refused = api.post(f"plan-versions/{second['id']}/validate/", version=second["version"])
    assert refused.status_code == 400
    assert refused.json()["details"]["occupied_m2"] == "600.0000"
    # Fits once reduced to the remaining capacity.
    v = api.put(
        f"plan-versions/{second['id']}/allocations/",
        {
            "allocations": [
                {"parcel": str(parcel.id), "allocated_area_m2": "400", "non_plantable_area_m2": "0"}
            ]
        },
        api.version(second["id"])["version"],
    ).json()
    assert (
        api.post(f"plan-versions/{second['id']}/validate/", version=v["version"]).status_code == 200
    )


def test_validation_requires_complete_plan(world, client_for):
    api = PlanApi(client_for(world.manager_a1), world.farm_a1)
    _, version = create_plan(api, make_validated_variety(world.org_a, world.admin_a))
    response = api.post(f"plan-versions/{version['id']}/validate/", version=version["version"])
    assert response.status_code == 400
    assert response.json()["details"]["missing"]


def test_allocation_rules(world, client_for):
    api = PlanApi(client_for(world.manager_a1), world.farm_a1)
    _, version = create_plan(api, make_validated_variety(world.org_a, world.admin_a))
    parcel = make_parcel(world.farm_a1, area_m2=D(100))
    other_farm_parcel = make_parcel(world.farm_a2)
    too_big = api.put(
        f"plan-versions/{version['id']}/allocations/",
        {"allocations": [{"parcel": str(parcel.id), "allocated_area_m2": "150"}]},
        version["version"],
    )
    assert too_big.status_code == 400
    foreign = api.put(
        f"plan-versions/{version['id']}/allocations/",
        {"allocations": [{"parcel": str(other_farm_parcel.id), "allocated_area_m2": "10"}]},
        version["version"],
    )
    assert foreign.status_code == 400
    assert "allocations" in foreign.json()["field_errors"]
    stale = api.put(f"plan-versions/{version['id']}/allocations/", {"allocations": []}, 99)
    assert stale.status_code == 409


def test_user_values_are_not_overwritten_by_prefill(world, client_for):
    api = PlanApi(client_for(world.manager_a1), world.farm_a1)
    _, version = create_plan(api, make_validated_variety(world.org_a, world.admin_a))
    v = api.patch(
        f"plan-versions/{version['id']}/planting-spec/",
        {"row_spacing_m": "2.0"},
        version["version"],
    ).json()
    api.post(f"plan-versions/{version['id']}/prefill/", version=v["version"])
    detail = api.version(version["id"])
    assert D(detail["planting_spec"]["row_spacing_m"]) == D("2.0")
    provenance = FieldProvenance.objects.get(
        plan_version_id=version["id"], field_path="planting_spec.row_spacing_m"
    )
    assert provenance.source_kind == "user_input"


def test_prefill_without_validated_data_fails(world, client_for):
    from tests.factories_catalog import make_variety

    api = PlanApi(client_for(world.manager_a1), world.farm_a1)
    _, version = create_plan(api, make_variety(world.org_a))
    assert (
        api.post(f"plan-versions/{version['id']}/prefill/", version=version["version"]).status_code
        == 400
    )


def test_permissions_on_plans(world, client_for):
    variety = make_validated_variety(world.org_a, world.admin_a)
    worker = PlanApi(client_for(world.worker_a1), world.farm_a1)
    assert worker.get("plans/").status_code == 403  # worker: no plans.view
    technician = PlanApi(client_for(world.worker_a1), world.farm_a2)  # technician on A2
    parcel = make_parcel(world.farm_a2, area_m2=D(1000))
    _, version = create_plan(technician, variety)
    version = complete_draft(technician, version, parcel)
    refused = technician.post(
        f"plan-versions/{version['id']}/validate/", version=version["version"]
    )
    assert refused.status_code == 403  # plans.validate is required (FR-035)


def test_plan_requires_variety_of_own_org(world, client_for):
    from tests.factories_catalog import make_variety

    api = PlanApi(client_for(world.manager_a1), world.farm_a1)
    campaign = api.post(
        "campaigns/", {"name": "S", "start_date": "2026-01-01", "end_date": "2026-02-01"}
    ).json()
    foreign_variety = make_variety(world.org_b)
    response = api.post(
        "plans/", {"campaign": campaign["id"], "variety": str(foreign_variety.id), "name": "X"}
    )
    assert response.status_code == 400
