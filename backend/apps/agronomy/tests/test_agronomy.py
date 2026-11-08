"""Agronomic programme and observation tests. Doses are fictitious test inputs."""

import uuid
from decimal import Decimal as D

import pytest

from apps.agronomy.models import InputProduct, PlannedFertilization
from apps.farms.access import resolve_farm_context
from apps.production_plans import services as plans
from tests.factories import make_parcel
from tests.factories_plans import make_validated_variety

pytestmark = pytest.mark.django_db


def org_url(world, path):
    return f"/api/v1/organizations/{world.org_a.id}/{path}"


def farm_url(world, path):
    return f"/api/v1/farms/{world.farm_a1.id}/{path}"


def make_product(world, kind="fertilizer", **kwargs):
    return InputProduct.objects.create(
        organization=world.org_a, kind=kind, name=kwargs.pop("name", f"Produit {kind}"), **kwargs
    )


def make_draft(world, parcel_area=D(1000)):
    """A draft version with one 1000 m² allocation and its planting calculation."""
    ctx = resolve_farm_context(world.manager_a1, world.farm_a1.id)
    variety = make_validated_variety(world.org_a, world.admin_a)
    campaign = plans.create_campaign(
        ctx, data={"name": "C", "start_date": "2026-01-01", "end_date": "2026-12-31"}
    )
    plan = plans.create_plan(ctx, campaign_id=campaign.id, variety_id=variety.id, name="P")
    version = plan.versions.get()
    plans.prefill_from_technical_data(ctx, version_id=version.id, expected_version=None)
    version.refresh_from_db()
    plans.set_allocations(
        ctx,
        version_id=version.id,
        expected_version=version.version,
        allocations=[
            {
                "parcel": make_parcel(world.farm_a1, area_m2=parcel_area),
                "allocated_area_m2": parcel_area,
                "non_plantable_area_m2": D(0),
            }
        ],
    )
    version.refresh_from_db()
    plans.compute_version(ctx, version_id=version.id)
    version.refresh_from_db()
    return version


def test_product_composition_is_validated(world, client_for):
    client = client_for(world.admin_a)
    ok = client.post(
        org_url(world, "input-products/"),
        {"kind": "fertilizer", "name": "NPK", "composition": {"N": 15, "P2O5": 15, "K2O": 15}},
        format="json",
    )
    assert ok.status_code == 201, ok.json()
    unknown = client.post(
        org_url(world, "input-products/"),
        {"kind": "fertilizer", "name": "X", "composition": {"Unobtainium": 5}},
        format="json",
    )
    assert unknown.status_code == 400
    too_much = client.post(
        org_url(world, "input-products/"),
        {"kind": "fertilizer", "name": "Y", "composition": {"N": 120}},
        format="json",
    )
    assert too_much.status_code == 400


def test_fertilization_quantity_from_composition(world, client_for):
    version = make_draft(world)
    urea = make_product(world, composition={"N": 46})
    client = client_for(world.manager_a1)
    response = client.post(
        farm_url(world, f"plan-programs/{version.id}/fertilizations/"),
        {
            "product": str(urea.id),
            "phase_code": "vegetative",
            "day_offset": 5,
            "mode": "nutrient_target",
            "target_nutrient": "N",
            "nutrient_dose_kg_per_ha": "100",
            "method": "broadcast",
            "source_kind": "user_input",
        },
        format="json",
        HTTP_IF_MATCH=str(version.version),
    )
    assert response.status_code == 200, response.json()
    item = response.json()["fertilizations"][0]
    # 100 kg N/ha × 0.1 ha / 0.46 = 21.739 kg
    assert D(item["computed_quantity"]) == D("21.739") and item["computed_unit"] == "kg"


def test_per_plant_dose_uses_computed_plant_count(world, client_for):
    version = make_draft(world)
    product = make_product(world)
    response = client_for(world.manager_a1).post(
        farm_url(world, f"plan-programs/{version.id}/fertilizations/"),
        {
            "product": str(product.id),
            "mode": "product_dose",
            "dose_value": "10",
            "dose_unit": "g",
            "basis": "per_plant",
            "source_kind": "user_input",
        },
        format="json",
        HTTP_IF_MATCH=str(version.version),
    )
    item = response.json()["fertilizations"][0]
    assert D(item["computed_quantity"]) == D("13.33")  # 1333 plants × 10 g


def test_documentary_dose_requires_a_source(world, client_for):
    version = make_draft(world)
    response = client_for(world.manager_a1).post(
        farm_url(world, f"plan-programs/{version.id}/fertilizations/"),
        {
            "product": str(make_product(world, composition={"N": 46}).id),
            "mode": "nutrient_target",
            "target_nutrient": "N",
            "nutrient_dose_kg_per_ha": "50",
            "source_kind": "document",
        },
        format="json",
        HTTP_IF_MATCH=str(version.version),
    )
    assert response.status_code == 400


def test_phyto_rules(world, client_for):
    version = make_draft(world)
    phyto = make_product(world, kind="phyto", name="Fongicide test")
    client = client_for(world.manager_a1)
    url = farm_url(world, f"plan-programs/{version.id}/phyto/")
    base = {
        "product": str(phyto.id),
        "target_organism": "Mildiou",
        "phase_code": "vegetative",
        "dose_value": "2",
        "dose_unit": "l",
        "basis": "per_ha",
        "label_reference": "Étiquette lot 42, p. 2",
        "source_kind": "user_input",
    }
    ai = client.post(
        url,
        {**base, "source_kind": "ai_suggestion"},
        format="json",
        HTTP_IF_MATCH=str(version.version),
    )
    assert ai.status_code == 400  # the AI can never propose a phytosanitary dose
    no_label = client.post(
        url, {**base, "label_reference": " "}, format="json", HTTP_IF_MATCH=str(version.version)
    )
    assert no_label.status_code == 400
    ok = client.post(url, base, format="json", HTTP_IF_MATCH=str(version.version))
    assert ok.status_code == 200, ok.json()
    warnings = ok.json()["warnings"]
    assert any("autorisation" in w for w in warnings)
    assert any("homologation" in w for w in warnings)
    assert D(ok.json()["phyto_interventions"][0]["computed_quantity"]) == D(
        "0.2"
    )  # 2 L/ha × 0.1 ha
    fertilizer_as_phyto = client.post(
        url,
        {**base, "product": str(make_product(world).id)},
        format="json",
        HTTP_IF_MATCH=str(ok.json()["version"]),
    )
    assert fertilizer_as_phyto.status_code == 400


def test_irrigation_schedule(world, client_for):
    version = make_draft(world)
    response = client_for(world.manager_a1).put(
        farm_url(world, f"plan-programs/{version.id}/irrigation/"),
        {
            "items": [
                {
                    "phase_code": "vegetative",
                    "et0_mm_per_day": "5",
                    "kc": "0.8",
                    "application_efficiency_rate": "0.9",
                    "frequency_days": 1,
                    "source_kind": "user_input",
                }
            ]
        },
        format="json",
        HTTP_IF_MATCH=str(version.version),
    )
    assert response.status_code == 200, response.json()
    # ETc = 0.8 × 5 = 4 mm/day ; 4 mm × 1000 m² = 4000 L net ; / 0.9 = 4444.4 L/day (1 decimal)
    assert D(response.json()["irrigation_schedule"][0]["computed_gross_l_per_day"]) == D("4444.4")
    unknown_phase = client_for(world.manager_a1).put(
        farm_url(world, f"plan-programs/{version.id}/irrigation/"),
        {
            "items": [
                {
                    "phase_code": "flowering",
                    "et0_mm_per_day": "5",
                    "kc": "1",
                    "application_efficiency_rate": "0.9",
                    "source_kind": "user_input",
                }
            ]
        },
        format="json",
        HTTP_IF_MATCH=str(response.json()["version"]),
    )
    assert unknown_phase.status_code == 400


def test_program_is_frozen_after_validation_and_copied_to_new_version(world):
    from datetime import date

    ctx = resolve_farm_context(world.manager_a1, world.farm_a1.id)
    from apps.agronomy import services as agronomy

    version = make_draft(world)
    product = make_product(world, composition={"N": 46})
    agronomy.add_fertilization(
        ctx,
        version_id=version.id,
        expected_version=version.version,
        data={
            "product": product,
            "mode": "nutrient_target",
            "target_nutrient": "N",
            "nutrient_dose_kg_per_ha": D(100),
            "source_kind": "user_input",
        },
    )
    version.refresh_from_db()
    plans.update_planting_spec(
        ctx,
        version_id=version.id,
        expected_version=version.version,
        changes={"planting_method": "direct_seeding", "safety_margin_rate": D(0)},
    )
    version.refresh_from_db()
    plans.update_header(
        ctx,
        version_id=version.id,
        expected_version=version.version,
        changes={"planned_start_date": date(2026, 1, 1)},
    )
    version.refresh_from_db()
    plans.validate_version(ctx, version_id=version.id, expected_version=version.version)
    version.refresh_from_db()
    from apps.core.exceptions import BusinessRuleError

    with pytest.raises(BusinessRuleError):
        agronomy.add_fertilization(
            ctx,
            version_id=version.id,
            expected_version=version.version,
            data={
                "product": product,
                "mode": "nutrient_target",
                "target_nutrient": "N",
                "nutrient_dose_kg_per_ha": D(1),
                "source_kind": "user_input",
            },
        )
    draft = plans.create_new_version(ctx, plan_id=version.plan_id)
    copied = PlannedFertilization.objects.filter(plan_version=draft)
    assert copied.count() == 1 and copied.get().sequence == 1


def test_observations(world, client_for):
    parcel = make_parcel(world.farm_a1)
    worker = client_for(world.worker_a1)
    obs_id = str(uuid.uuid4())
    payload = {
        "id": obs_id,
        "parcel": str(parcel.id),
        "observed_at": "2026-02-01T08:00:00Z",
        "kind": "pest",
        "target": "Pucerons",
        "severity": 3,
    }
    created = worker.post(farm_url(world, "observations/"), payload, format="json")
    assert created.status_code == 201, created.json()
    assert worker.post(farm_url(world, "observations/"), payload, format="json").status_code == 200
    assert created.json()["author"] == str(world.worker_a1.id)
    other_farm_parcel = make_parcel(world.farm_a2)
    refused = worker.post(
        farm_url(world, "observations/"),
        {**payload, "id": str(uuid.uuid4()), "parcel": str(other_farm_parcel.id)},
        format="json",
    )
    assert refused.status_code == 400
    assert (
        client_for(world.finance_a1)
        .post(farm_url(world, "observations/"), payload, format="json")
        .status_code
        == 403
    )
    bad = worker.post(
        farm_url(world, "observations/"),
        {**payload, "id": str(uuid.uuid4()), "severity": 9},
        format="json",
    )
    assert bad.status_code == 400
