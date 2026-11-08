"""Harvest and campaign results tests. Quantities and amounts are fictitious."""

import uuid
from decimal import Decimal as D

import pytest
from django.utils import timezone

from apps.farms.access import resolve_farm_context
from apps.finance import services as finance
from apps.finance.models import FinanceCategory, TreasuryAccount
from apps.harvest.models import HarvestRecord
from apps.production_plans import services as plans
from apps.production_plans.models import CropCycle
from tests.factories import make_parcel
from tests.factories_plans import make_validated_plan, make_validated_variety

pytestmark = pytest.mark.django_db


def url(world, path):
    return f"/api/v1/farms/{world.farm_a1.id}/{path}"


@pytest.fixture
def cycle(world):
    ctx = resolve_farm_context(world.manager_a1, world.farm_a1.id)
    variety = make_validated_variety(world.org_a, world.admin_a)

    def target(ctx, version):
        plans.update_header(
            ctx,
            version_id=version.id,
            expected_version=version.version,
            changes={"target_yield_kg_per_ha": D(15000)},
        )

    version = make_validated_plan(
        ctx, variety, make_parcel(world.farm_a1, area_m2=D(1000)), program=target
    )
    return CropCycle.objects.get(plan_version=version)


def harvest(cycle, **extra):
    return {
        "crop_cycle": str(cycle.id),
        "harvested_on": "2026-02-20",
        "quantity": "500",
        "unit": "kg",
        "quality_grade": "grade_1",
        **extra,
    }


def test_record_harvest_in_kg_and_measured_units(world, client_for, cycle):
    worker = client_for(world.worker_a1)
    kg = worker.post(url(world, "harvests/"), harvest(cycle), format="json")
    assert kg.status_code == 201, kg.json()
    assert D(kg.json()["quantity_kg"]) == D(500)
    crates = worker.post(
        url(world, "harvests/"), harvest(cycle, quantity="20", unit="crate"), format="json"
    )
    assert crates.status_code == 400  # no average weight is ever assumed
    crop_id = str(cycle.plan.variety.crop_id)
    conversion = worker.post(
        url(world, "unit-conversions/"),
        {"crop": crop_id, "unit": "crate", "kg_per_unit": "12.5", "measured_on": "2026-02-19"},
        format="json",
    )
    assert conversion.status_code == 201, conversion.json()
    crates = worker.post(
        url(world, "harvests/"), harvest(cycle, quantity="20", unit="crate"), format="json"
    )
    assert crates.status_code == 201
    assert D(crates.json()["quantity_kg"]) == D(250)
    assert D(crates.json()["conversion_factor_used"]) == D("12.5")


def test_harvest_validation(world, client_for, cycle):
    worker = client_for(world.worker_a1)
    early = worker.post(
        url(world, "harvests/"), harvest(cycle, harvested_on="2025-12-01"), format="json"
    )
    assert early.status_code == 400
    negative = worker.post(url(world, "harvests/"), harvest(cycle, quantity="-1"), format="json")
    assert negative.status_code == 400
    assert (
        client_for(world.finance_a1)
        .post(url(world, "harvests/"), harvest(cycle), format="json")
        .status_code
        == 403
    )


def test_yields_costs_and_margin(world, client_for, cycle):
    worker = client_for(world.worker_a1)
    worker.post(
        url(world, "harvests/"),
        harvest(cycle, quantity="1200", loss_quantity_kg="50"),
        format="json",
    )
    worker.post(
        url(world, "harvests/"),
        harvest(cycle, quantity="300", quality_grade="rejected"),
        format="json",
    )
    ctx = resolve_farm_context(world.finance_a1, world.farm_a1.id)
    org, farm = world.org_a, world.farm_a1
    account = TreasuryAccount.objects.create(
        organization=org, farm=farm, name="Caisse", kind="cash", currency="XAF"
    )
    spend = FinanceCategory.objects.create(organization=org, kind="expense", code="c", name="C")
    sell = FinanceCategory.objects.create(organization=org, kind="income", code="v", name="V")
    today = timezone.localdate()

    def record(kind, amount, category, **links):
        finance.record_transaction(
            ctx,
            data={
                "kind": kind,
                "business_date": today,
                "amount": D(amount),
                "account": account,
                "category": category,
                "idempotency_key": uuid.uuid4(),
                **links,
            },
        )

    record("expense", "300000", spend, crop_cycle=cycle)
    record("expense", "150000", spend, plan=cycle.plan)  # plan level: single cycle -> 100 %
    record("income", "900000", sell, crop_cycle=cycle)
    results = client_for(world.manager_a1).get(url(world, f"harvest-results/{cycle.id}/")).json()
    outputs = results["yield"]["outputs"]
    assert outputs["gross_yield_kg_per_ha"]["value"] == "15000.00"
    assert outputs["marketable_yield_kg_per_ha"]["value"] == "12000.00"
    assert outputs["gap_to_target_pct"]["value"] == "-20.00"
    assert outputs["cost_per_kg"]["value"] == "375.0000"  # 450 000 / 1 200 kg
    assert D(results["finance"]["margin"]) == D(450000)

    # Without finance.view the financial part is hidden.
    technician_like = client_for(world.worker_a1).get(url(world, f"harvest-results/{cycle.id}/"))
    assert technician_like.status_code == 200
    assert technician_like.json()["finance"] is None
    campaign = client_for(world.manager_a1).get(
        url(world, "harvest-results/campaign/"), {"campaign": str(cycle.plan.campaign_id)}
    )
    assert len(campaign.json()) == 1


def test_void_keeps_the_record_and_excludes_it(world, client_for, cycle):
    created = (
        client_for(world.worker_a1)
        .post(url(world, "harvests/"), harvest(cycle), format="json")
        .json()
    )
    refused = client_for(world.worker_a1).post(
        url(world, f"harvests/{created['id']}/void/"), {"reason": "Erreur"}, format="json"
    )
    assert refused.status_code == 403
    voided = client_for(world.manager_a1).post(
        url(world, f"harvests/{created['id']}/void/"), {"reason": "Saisie en double"}, format="json"
    )
    assert voided.status_code == 200 and voided.json()["voided_at"]
    assert HarvestRecord.objects.filter(id=created["id"]).exists()
    results = client_for(world.manager_a1).get(url(world, f"harvest-results/{cycle.id}/")).json()
    assert results["yield"]["outputs"]["gross_harvest_kg"]["value"] == "0.000"


def test_offline_harvest_push_is_idempotent(world, client_for, cycle):
    record_id = str(uuid.uuid4())
    operation = {
        "op_id": str(uuid.uuid4()),
        "farm_id": str(world.farm_a1.id),
        "op_type": "create",
        "entity_type": "harvest.harvest_record",
        "entity_id": record_id,
        "payload": harvest(cycle),
    }
    worker = client_for(world.worker_a1)
    first = worker.post("/api/v1/sync/push/", {"operations": [operation]}, format="json").json()[
        "results"
    ][0]
    assert first["status"] == "applied", first
    again = worker.post(
        "/api/v1/sync/push/",
        {"operations": [{**operation, "op_id": str(uuid.uuid4())}]},
        format="json",
    ).json()["results"][0]
    assert again["status"] == "applied" and again["created"] is False
    assert HarvestRecord.objects.filter(id=record_id).count() == 1


def test_cycle_of_other_farm_is_rejected(world, client_for):
    ctx = resolve_farm_context(world.admin_a, world.farm_a2.id)
    variety = make_validated_variety(world.org_a, world.admin_a)
    version = make_validated_plan(
        ctx, variety, make_parcel(world.farm_a2, area_m2=D(500)), area=D(500)
    )
    other_cycle = CropCycle.objects.get(plan_version=version)
    response = client_for(world.admin_a).post(
        url(world, "harvests/"), harvest(other_cycle), format="json"
    )
    assert response.status_code == 400
