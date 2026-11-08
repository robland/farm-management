"""NFR-004: list endpoints must not issue one query per row (no N+1)."""

import datetime
import uuid
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.farms.access import resolve_farm_context
from apps.finance import services as finance
from apps.finance.models import FinanceCategory, TreasuryAccount
from apps.tasks.models import Task
from tests.factories import make_parcel

pytestmark = pytest.mark.django_db


def count_queries(client, url) -> int:
    with CaptureQueriesContext(connection) as ctx:
        assert client.get(url).status_code == 200
    return len(ctx.captured_queries)


def grow(fn, before: int, after: int) -> None:
    for _ in range(after - before):
        fn()


@pytest.mark.parametrize("kind", ["parcels", "tasks", "transactions"])
def test_list_query_count_is_constant(world, client_for, kind):
    farm = world.farm_a1
    client = client_for(world.admin_a)
    ctx = resolve_farm_context(world.admin_a, farm.id)
    account = TreasuryAccount.objects.create(
        organization=world.org_a, farm=farm, name="C", kind="cash", currency="XAF"
    )
    category = FinanceCategory.objects.create(
        organization=world.org_a, kind="expense", code="c", name="C"
    )

    def add() -> None:
        if kind == "parcels":
            make_parcel(farm)
        elif kind == "tasks":
            task = Task.objects.create(
                organization=world.org_a,
                farm=farm,
                task_type="other",
                title="T",
                planned_start_date=datetime.date(2026, 1, 1),
                planned_end_date=datetime.date(2026, 1, 2),
            )
            task.assignees.add(world.worker_a1)
        else:
            finance.record_transaction(
                ctx,
                data={
                    "kind": "expense",
                    "business_date": timezone.localdate(),
                    "amount": Decimal(1000),
                    "account": account,
                    "category": category,
                    "idempotency_key": uuid.uuid4(),
                    "description": str(uuid.uuid4()),
                },
            )

    url = f"/api/v1/farms/{farm.id}/{kind}/"
    grow(add, 0, 3)
    few = count_queries(client, url)
    grow(add, 3, 25)
    many = count_queries(client, url)
    assert many == few, f"{kind}: {few} queries for 3 rows, {many} for 25"
