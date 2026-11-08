import datetime
import uuid
from decimal import Decimal as D

import pytest

from apps.agronomy import services as agronomy
from apps.agronomy.models import InputProduct
from apps.farms.access import resolve_farm_context
from apps.production_plans import services as plans
from apps.synchronization.models import SyncConflict
from apps.tasks.models import InputConsumption, Task
from tests.factories import make_parcel
from tests.factories_plans import make_validated_plan, make_validated_variety

pytestmark = pytest.mark.django_db


def farm_url(world, path):
    return f"/api/v1/farms/{world.farm_a1.id}/{path}"


@pytest.fixture
def plan_setup(world):
    ctx = resolve_farm_context(world.manager_a1, world.farm_a1.id)
    variety = make_validated_variety(world.org_a, world.admin_a)
    parcel = make_parcel(world.farm_a1, area_m2=D(1000))
    product = InputProduct.objects.create(
        organization=world.org_a, kind="fertilizer", name="Urée", composition={"N": 46}
    )

    def program(ctx, version):
        agronomy.add_fertilization(
            ctx,
            version_id=version.id,
            expected_version=version.version,
            data={
                "product": product,
                "mode": "nutrient_target",
                "target_nutrient": "N",
                "nutrient_dose_kg_per_ha": D(50),
                "phase_code": "vegetative",
                "day_offset": 10,
                "source_kind": "user_input",
            },
        )

    version = make_validated_plan(ctx, variety, parcel, program=program)
    return ctx, version, parcel, product


def generate(client, world, version):
    return client.post(
        farm_url(world, "tasks/generate/"), {"plan_version": str(version.id)}, format="json"
    )


def test_generation_requires_validated_version(world, client_for):
    ctx = resolve_farm_context(world.manager_a1, world.farm_a1.id)
    variety = make_validated_variety(world.org_a, world.admin_a)
    campaign = plans.create_campaign(
        ctx, data={"name": "C", "start_date": "2026-01-01", "end_date": "2026-12-31"}
    )
    plan = plans.create_plan(ctx, campaign_id=campaign.id, variety_id=variety.id, name="P")
    response = generate(client_for(world.manager_a1), world, plan.versions.get())
    assert response.status_code == 400  # FR-035: no definitive task from a draft


def test_generation_from_validated_plan(world, client_for, plan_setup):
    _, version, parcel, _ = plan_setup
    response = generate(client_for(world.manager_a1), world, version)
    assert response.status_code == 200, response.json()
    assert response.json()["created"] == 4
    tasks = {t.source_ref: t for t in Task.objects.filter(plan_version=version)}
    assert set(tasks) == {
        "phase:soil_preparation",
        "phase:sowing",
        "phase:harvest",
        "fertilization:1",
    }
    fert = tasks["fertilization:1"]
    # vegetative starts on day 9 (2026-01-09) + 10 days
    assert fert.planned_start_date == datetime.date(2026, 1, 19)
    assert fert.parcel == parcel and fert.origin == "generated"
    # Idempotent: generating again changes nothing.
    again = generate(client_for(world.manager_a1), world, version).json()
    assert again["created"] == 0 and again["unchanged"] == 4


def test_regeneration_keeps_history(world, client_for, plan_setup):
    ctx, version, _, _ = plan_setup
    client = client_for(world.manager_a1)
    generate(client, world, version)
    soil = Task.objects.get(source_ref="phase:soil_preparation")
    client.post(farm_url(world, f"tasks/{soil.id}/status/"), {"to": "done"}, format="json")

    draft = plans.create_new_version(ctx, plan_id=version.plan_id)
    plans.update_header(
        ctx,
        version_id=draft.id,
        expected_version=draft.version,
        changes={"planned_start_date": datetime.date(2026, 1, 15)},
    )
    draft.refresh_from_db()
    plans.validate_version(ctx, version_id=draft.id, expected_version=draft.version)
    summary = generate(client, world, draft).json()
    assert summary == {"created": 0, "unchanged": 0, "replanned": 3, "cancelled": 0, "kept": 1}
    soil.refresh_from_db()
    assert soil.status == "done" and soil.plan_version_id == version.id  # history untouched
    old_sowing = Task.objects.get(source_ref="phase:sowing", plan_version=version)
    assert old_sowing.status == "cancelled" and old_sowing.superseded_by is not None
    assert old_sowing.superseded_by.planned_start_date == datetime.date(2026, 1, 22)


def test_status_permissions_and_transitions(world, client_for, plan_setup):
    _, version, _, _ = plan_setup
    generate(client_for(world.manager_a1), world, version)
    task = Task.objects.get(source_ref="phase:sowing")
    worker = client_for(world.worker_a1)
    assert (
        worker.post(
            farm_url(world, f"tasks/{task.id}/status/"), {"to": "in_progress"}, format="json"
        ).status_code
        == 200
    )
    assert (
        worker.post(
            farm_url(world, f"tasks/{task.id}/status/"), {"to": "cancelled"}, format="json"
        ).status_code
        == 403
    )
    assert (
        worker.post(
            farm_url(world, f"tasks/{task.id}/status/"), {"to": "done"}, format="json"
        ).status_code
        == 200
    )
    assert (
        worker.post(
            farm_url(world, f"tasks/{task.id}/status/"), {"to": "todo"}, format="json"
        ).status_code
        == 400
    )  # done -> todo is not allowed
    history = worker.get(farm_url(world, f"tasks/{task.id}/history/")).json()
    assert [(e["from_status"], e["to_status"]) for e in history] == [
        ("todo", "in_progress"),
        ("in_progress", "done"),
    ]


def test_report_with_consumptions_completes_the_task(world, client_for, plan_setup):
    _, version, _, product = plan_setup
    generate(client_for(world.manager_a1), world, version)
    task = Task.objects.get(source_ref="fertilization:1")
    report = client_for(world.worker_a1).post(
        farm_url(world, "task-reports/"),
        {
            "id": str(uuid.uuid4()),
            "task": str(task.id),
            "actual_start": "2026-01-19T07:00:00Z",
            "actual_end": "2026-01-19T09:30:00Z",
            "completion": "complete",
            "deviation_notes": "Apport réduit (sol humide)",
            "consumptions": [{"product": str(product.id), "quantity": "9500", "unit": "g"}],
        },
        format="json",
    )
    assert report.status_code == 201, report.json()
    assert report.json()["duration_minutes"] == 150
    task.refresh_from_db()
    assert task.status == "done"
    consumption = InputConsumption.objects.get()
    assert consumption.quantity_base == D("9.5") and consumption.base_unit == "kg"
    assert consumption.plan_version_id == version.id  # FR-082


def test_report_on_cancelled_task_is_kept_and_flagged(world, client_for, plan_setup):
    _, version, _, _ = plan_setup
    generate(client_for(world.manager_a1), world, version)
    task = Task.objects.get(source_ref="phase:harvest")
    client_for(world.manager_a1).post(
        farm_url(world, f"tasks/{task.id}/status/"), {"to": "cancelled"}, format="json"
    )
    response = client_for(world.worker_a1).post(
        farm_url(world, "task-reports/"),
        {"task": str(task.id), "actual_start": "2026-02-20T07:00:00Z", "completion": "complete"},
        format="json",
    )
    assert response.status_code == 201
    task.refresh_from_db()
    assert task.status == "to_verify"
    assert SyncConflict.objects.filter(
        entity_id=task.id, conflict_type="invalid_transition"
    ).exists()


def test_late_tasks_are_derived(world, client_for, plan_setup):
    _, version, _, _ = plan_setup
    generate(client_for(world.manager_a1), world, version)
    response = client_for(world.manager_a1).get(farm_url(world, "tasks/"), {"late": "true"})
    # The plan is in the past relative to "today" only if today > 2026 dates; compute expected.
    from apps.tasks.services import farm_today

    today = farm_today(world.farm_a1.id)
    expected = Task.objects.filter(
        status__in=["todo", "in_progress"], planned_end_date__lt=today
    ).count()
    assert response.json()["count"] == expected
    listed = client_for(world.manager_a1).get(farm_url(world, "tasks/")).json()["results"]
    assert all(
        t["is_late"] == (datetime.date.fromisoformat(t["planned_end_date"]) < today) for t in listed
    )


def test_assignment_and_my_tasks(world, client_for, plan_setup):
    _, version, _, _ = plan_setup
    manager = client_for(world.manager_a1)
    generate(manager, world, version)
    task = Task.objects.get(source_ref="phase:sowing")
    assert (
        manager.post(
            farm_url(world, f"tasks/{task.id}/assign/"),
            {"users": [str(world.worker_a1.id)]},
            format="json",
        ).status_code
        == 200
    )
    outsider = manager.post(
        farm_url(world, f"tasks/{task.id}/assign/"),
        {"users": [str(world.admin_b.id)]},
        format="json",
    )
    assert outsider.status_code == 400
    mine = client_for(world.worker_a1).get(farm_url(world, "tasks/mine/")).json()
    assert [t["id"] for t in mine["results"]] == [str(task.id)]


def test_offline_status_command_and_report_sync(world, client_for, plan_setup):
    _, version, _, _ = plan_setup
    generate(client_for(world.manager_a1), world, version)
    task = Task.objects.get(source_ref="phase:sowing")
    worker = client_for(world.worker_a1)

    def op(**extra):
        return {"op_id": str(uuid.uuid4()), "farm_id": str(world.farm_a1.id), **extra}

    command = op(
        op_type="command",
        command="task.change_status",
        entity_type="tasks.task",
        entity_id=str(task.id),
        payload={"from": "todo", "to": "in_progress"},
    )
    report = op(
        op_type="create",
        entity_type="tasks.task_report",
        entity_id=str(uuid.uuid4()),
        payload={
            "task": str(task.id),
            "actual_start": "2026-01-08T07:00:00Z",
            "completion": "complete",
        },
    )
    results = worker.post(
        "/api/v1/sync/push/", {"operations": [command, report]}, format="json"
    ).json()["results"]
    assert [r["status"] for r in results] == ["applied", "applied"], results
    task.refresh_from_db()
    assert task.status == "done"
    # Another device, offline since "todo", also starts the task: stale -> conflict.
    stale = op(
        op_type="command",
        command="task.change_status",
        entity_type="tasks.task",
        entity_id=str(task.id),
        payload={"from": "todo", "to": "in_progress"},
    )
    result = worker.post("/api/v1/sync/push/", {"operations": [stale]}, format="json").json()[
        "results"
    ][0]
    assert result["status"] == "conflict" and result["conflict_type"] == "invalid_transition"
    # Converging command (already done) is applied without effect.
    converge = op(
        op_type="command",
        command="task.change_status",
        entity_type="tasks.task",
        entity_id=str(task.id),
        payload={"from": "in_progress", "to": "done"},
    )
    result = worker.post("/api/v1/sync/push/", {"operations": [converge]}, format="json").json()[
        "results"
    ][0]
    assert result["status"] == "applied" and result["converged"] is True
    # Reports cannot be modified through sync (append-only).
    update = op(
        op_type="update",
        entity_type="tasks.task_report",
        entity_id=report["entity_id"],
        base_version=1,
        payload={"notes": "x"},
    )
    result = worker.post("/api/v1/sync/push/", {"operations": [update]}, format="json").json()[
        "results"
    ][0]
    assert result["status"] == "rejected"
