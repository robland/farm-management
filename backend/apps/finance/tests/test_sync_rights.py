"""Offline creation rights of financial transactions (FR-112, Q35). Amounts are fictitious."""

import uuid

import pytest
from django.utils import timezone

from apps.finance.models import FinanceCategory, FinancialTransaction, TreasuryAccount
from tests.factories import add_member, make_user

pytestmark = pytest.mark.django_db
TODAY = timezone.localdate().isoformat()
PUSH = "/api/v1/sync/push/"


@pytest.fixture
def books(world):
    org, farm = world.org_a, world.farm_a1
    storekeeper, contributor = make_user(), make_user(full_name="Paul Contributeur")
    add_member(org, farm, storekeeper, "storekeeper")
    add_member(org, farm, contributor, "contributor")
    return {
        "cash": TreasuryAccount.objects.create(
            organization=org, farm=farm, name="Caisse", kind="cash", currency="XAF", role="main"
        ),
        "inputs": FinanceCategory.objects.create(
            organization=org, kind="expense", code="intrants", name="Intrants"
        ),
        "contribution": FinanceCategory.objects.create(
            organization=org, kind="investment", code="apport", name="Apport"
        ),
        "storekeeper": storekeeper,
        "contributor": contributor,
    }


def create_op(world, payload, entity_id=None):
    return {
        "op_id": str(uuid.uuid4()),
        "farm_id": str(world.farm_a1.id),
        "op_type": "create",
        "entity_type": "finance.transaction",
        "entity_id": str(entity_id or uuid.uuid4()),
        "payload": payload,
    }


def push(client, op):
    return client.post(PUSH, {"operations": [op]}, format="json").json()["results"][0]


def test_storekeeper_without_finance_view_records_an_offline_expense(world, client_for, books):
    op = create_op(
        world,
        {
            "kind": "expense",
            "business_date": TODAY,
            "amount": "15000",
            "account": str(books["cash"].id),
            "category": str(books["inputs"].id),
        },
    )
    result = push(client_for(books["storekeeper"]), op)
    assert result["status"] == "applied", result
    tx = FinancialTransaction.objects.get(id=op["entity_id"])
    # Recorded, never auto-validated: the storekeeper cannot validate.
    assert tx.status == "submitted" and tx.created_offline is True
    # Replaying the same operation does not count it twice.
    assert push(client_for(books["storekeeper"]), op)["replayed"] is True
    assert FinancialTransaction.objects.filter(id=op["entity_id"]).count() == 1


def test_contributor_funds_their_own_account_offline_but_records_no_expense(
    world, client_for, books
):
    contributor = client_for(books["contributor"])
    opened = contributor.post(
        f"/api/v1/farms/{world.farm_a1.id}/treasury-accounts/mine/", {}, format="json"
    )
    assert opened.status_code in (200, 201), opened.json()
    funding = create_op(
        world,
        {
            "kind": "funding",
            "business_date": TODAY,
            "amount": "50000",
            "account": opened.json()["id"],
            "category": str(books["contribution"].id),
        },
    )
    result = push(contributor, funding)
    assert result["status"] == "applied", result
    assert FinancialTransaction.objects.get(id=funding["entity_id"]).status == "submitted"

    # The service still refuses what the role may not do.
    expense = create_op(
        world,
        {
            "kind": "expense",
            "business_date": TODAY,
            "amount": "1000",
            "account": str(books["cash"].id),
            "category": str(books["inputs"].id),
        },
    )
    refused = push(contributor, expense)
    assert refused["status"] == "rejected"
    assert refused["error"]["code"] == "permission_denied"
    assert not FinancialTransaction.objects.filter(id=expense["entity_id"]).exists()


def test_reversal_command_still_requires_finance_view_and_validation(world, client_for, books):
    keeper = client_for(books["storekeeper"])
    op = create_op(
        world,
        {
            "kind": "expense",
            "business_date": TODAY,
            "amount": "2000",
            "account": str(books["cash"].id),
            "category": str(books["inputs"].id),
        },
    )
    assert push(keeper, op)["status"] == "applied"
    reverse = {
        **op,
        "op_id": str(uuid.uuid4()),
        "op_type": "command",
        "command": "finance.reverse",
        "payload": {"reason": "Erreur"},
    }
    result = push(keeper, reverse)
    assert result["status"] == "rejected"
    assert result["error"]["code"] == "permission_denied"


def test_user_without_any_finance_right_cannot_create(world, client_for, books):
    op = create_op(
        world,
        {
            "kind": "expense",
            "business_date": TODAY,
            "amount": "2000",
            "account": str(books["cash"].id),
            "category": str(books["inputs"].id),
        },
    )
    result = push(client_for(world.worker_a1), op)
    assert result["status"] == "rejected"
    assert result["error"]["code"] == "permission_denied"
