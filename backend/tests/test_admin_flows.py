"""End-to-end business flows driven from the Django admin, through the services (Q34)."""

import uuid
from decimal import Decimal
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.finance.models import FinanceCategory, FinancialTransaction, TreasuryAccount
from apps.harvest.models import HarvestRecord
from apps.production_plans.models import (
    Campaign,
    PlanAllocation,
    PlantingSpec,
    PlanVersion,
    ProductionPlan,
)
from apps.synchronization.models import SyncConflict
from apps.tasks.models import Task, TaskReport
from tests.factories import World, make_parcel, make_user
from tests.factories_plans import make_validated_variety
from tests.tenancy.test_isolation import _objects_of_org_a

pytestmark = pytest.mark.django_db


def url(model: type, view: str, *args: object) -> str:
    return reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_{view}", args=args)


def errors(response: Any) -> Any:
    context = getattr(response, "context", None)
    if context and "adminform" in context:
        form = context["adminform"].form
        return {"fields": dict(form.errors), "non_field": list(form.non_field_errors())}
    if context and "messages" in context:
        return [str(m) for m in context["messages"]]
    return None


def saved(response: Any) -> None:
    assert response.status_code == 302, errors(response)


def current(client: Client, change_url: str) -> dict[str, Any]:
    """Values of the change form as displayed (what a browser would submit back)."""
    form = client.get(change_url).context["adminform"].form
    data: dict[str, Any] = {}
    for name in form.fields:
        value = form[name].value()
        if value is None:
            continue
        data[name] = [str(v) for v in value] if isinstance(value, list) else str(value)
    return data


def run_action(client: Client, model: type, action: str, objs: list[Any], **extra: Any) -> Any:
    data = {"action": action, "_selected_action": [str(o.pk) for o in objs], **extra}
    return client.post(url(model, "changelist"), data, follow=True)


def messages_of(response: Any) -> list[str]:
    return [str(m) for m in response.context["messages"]]


@pytest.fixture
def client() -> Client:
    c = Client()
    c.force_login(make_user(is_staff=True, is_superuser=True))
    return c


def test_plan_flow_from_creation_to_generated_tasks(world: World, client: Client) -> None:
    variety = make_validated_variety(world.org_a, world.admin_a)
    parcel = make_parcel(world.farm_a1)
    saved(
        client.post(
            url(Campaign, "add"),
            {
                "farm": world.farm_a1.pk,
                "name": "Saison sèche",
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
                "status": "planned",
            },
        )
    )
    campaign = Campaign.objects.get(name="Saison sèche")
    saved(
        client.post(
            url(ProductionPlan, "add"),
            {
                "farm": world.farm_a1.pk,
                "campaign": campaign.pk,
                "variety": variety.pk,
                "name": "Pastèque",
            },
        )
    )
    version = PlanVersion.objects.get(plan__name="Pastèque")
    assert version.status == PlanVersion.Status.DRAFT

    response = run_action(client, PlanVersion, "prefill", [version])
    assert not [m for m in messages_of(response) if " : " in m and "élément" not in m]

    version.refresh_from_db()
    saved(
        client.post(
            url(PlanAllocation, "add"),
            {
                "plan_version": version.pk,
                "parcel": parcel.pk,
                "allocated_area_m2": "1000",
                "non_plantable_area_m2": "0",
            },
        )
    )
    spec_url = url(PlantingSpec, "change", version.pk)
    data = current(client, spec_url)
    data.update({"planting_method": "direct_seeding", "safety_margin_rate": "0.1"})
    saved(client.post(spec_url, data))

    version_url = url(PlanVersion, "change", version.pk)
    data = current(client, version_url)
    data["planned_start_date"] = "2026-01-01"
    saved(client.post(version_url, data))

    run_action(client, PlanVersion, "compute", [version])
    response = run_action(client, PlanVersion, "validate", [version])
    version.refresh_from_db()
    assert version.status == PlanVersion.Status.VALIDATED, messages_of(response)
    # A validated version is no longer editable: changes go through a new version.
    assert client.post(version_url, {}).status_code == 403

    response = run_action(client, PlanVersion, "generate_tasks", [version])
    assert Task.objects.filter(plan_version=version).exists(), messages_of(response)

    response = run_action(
        client, PlanVersion, "new_version", [version], apply="1", change_note="Densité revue"
    )
    assert PlanVersion.objects.filter(plan=version.plan, status=PlanVersion.Status.DRAFT).exists()


def _finance(world: World) -> tuple[TreasuryAccount, FinanceCategory]:
    category = FinanceCategory.objects.create(
        organization=world.org_a, kind="expense", code="intrants", name="Intrants"
    )
    account = TreasuryAccount.objects.create(
        organization=world.org_a, farm=world.farm_a1, name="Caisse", kind="cash", currency="XAF"
    )
    return account, category


def test_expense_recorded_once_even_if_the_form_is_submitted_twice(world: World, client) -> None:
    account, category = _finance(world)
    data = {
        "farm": world.farm_a1.pk,
        "idempotency_key": str(uuid.uuid4()),
        "kind": "expense",
        "business_date": timezone.localdate().isoformat(),
        "amount": "15000",
        "account": account.pk,
        "category": category.pk,
        "description": "Engrais",
    }
    saved(client.post(url(FinancialTransaction, "add"), data))
    saved(client.post(url(FinancialTransaction, "add"), data))  # double click
    tx = FinancialTransaction.objects.get(description="Engrais")
    assert tx.amount == Decimal("15000") and tx.currency == "XAF"
    assert tx.entries.get().amount == Decimal("-15000")


def test_reversal_requires_a_reason_and_never_edits_the_original(world: World, client) -> None:
    objects = _objects_of_org_a(world)
    tx = objects["transaction"]
    tx.refresh_from_db()
    if tx.status != FinancialTransaction.Status.VALIDATED:
        run_action(client, FinancialTransaction, "validate", [tx])
        tx.refresh_from_db()
    assert tx.status == FinancialTransaction.Status.VALIDATED
    amount = tx.amount

    # Without a reason, the intermediate form is displayed again and nothing happens.
    response = client.post(
        url(FinancialTransaction, "changelist"),
        {"action": "reverse", "_selected_action": [str(tx.pk)], "apply": "1", "reason": ""},
    )
    assert response.status_code == 200
    assert not FinancialTransaction.objects.filter(reverses=tx).exists()

    run_action(client, FinancialTransaction, "reverse", [tx], apply="1", reason="Doublon de saisie")
    tx.refresh_from_db()
    assert tx.status == FinancialTransaction.Status.REVERSED and tx.amount == amount
    reversal = FinancialTransaction.objects.get(reverses=tx)
    assert reversal.kind == FinancialTransaction.Kind.REVERSAL
    # A validated transaction is never edited nor deleted, even by a superuser.
    assert client.post(url(FinancialTransaction, "change", tx.pk), {}).status_code == 403
    assert client.get(url(FinancialTransaction, "delete", tx.pk)).status_code == 403


def test_opening_balance_action_is_idempotent(world: World, client) -> None:
    account, _ = _finance(world)
    key = str(uuid.uuid4())
    for _ in range(2):  # confirmation page submitted twice
        run_action(
            client,
            TreasuryAccount,
            "opening",
            [account],
            apply="1",
            balance="50000",
            business_date="2026-01-01",
            idempotency_key=key,
        )
    assert FinancialTransaction.objects.filter(kind="opening", farm=world.farm_a1).count() == 1


def test_task_status_and_report_without_duplicate(world: World, client) -> None:
    objects = _objects_of_org_a(world)
    task = objects["task"]
    response = run_action(
        client, Task, "change_status", [task], apply="1", to_status="in_progress", reason=""
    )
    task.refresh_from_db()
    assert task.status == Task.Status.IN_PROGRESS, messages_of(response)

    data = {
        "task": task.pk,
        "client_id": str(uuid.uuid4()),
        "actual_start_0": "2026-01-01",
        "actual_start_1": "08:00",
        "completion": "complete",
        "notes": "Fait",
    }
    before = TaskReport.objects.filter(task=task).count()
    saved(client.post(url(TaskReport, "add"), data))
    saved(client.post(url(TaskReport, "add"), data))  # second submission: replay
    assert TaskReport.objects.filter(task=task).count() == before + 1

    # An impossible transition is refused with the service's reason.
    response = run_action(
        client, Task, "change_status", [task], apply="1", to_status="todo", reason=""
    )
    task.refresh_from_db()
    assert task.status in (Task.Status.IN_PROGRESS, Task.Status.DONE, Task.Status.TO_VERIFY)


def test_harvest_void_keeps_the_record(world: World, client) -> None:
    record = _objects_of_org_a(world)["harvest_record"]
    run_action(client, HarvestRecord, "void", [record], apply="1", reason="Mauvaise parcelle")
    record.refresh_from_db()
    assert record.voided_at is not None and record.void_reason == "Mauvaise parcelle"


def test_sync_conflict_resolved_by_a_person(world: World, client) -> None:
    conflict = _objects_of_org_a(world)["conflict"]
    run_action(
        client, SyncConflict, "resolve", [conflict], apply="1", resolution="keep_server", note="OK"
    )
    conflict.refresh_from_db()
    assert conflict.status == SyncConflict.Status.RESOLVED
    assert conflict.resolution == "keep_server"
