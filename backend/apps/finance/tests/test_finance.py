"""Financial tests (CLAUDE.md §11, §12). Amounts are fictitious."""

import threading
import uuid
from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from apps.farms.access import resolve_farm_context
from apps.finance import services
from apps.finance.models import (
    FinanceCategory,
    FinancialTransaction,
    LedgerEntry,
    TransactionRevision,
    TreasuryAccount,
)
from apps.organizations.models import Role
from apps.synchronization.models import SyncConflict
from tests.factories import add_member, make_user

pytestmark = pytest.mark.django_db
TODAY = timezone.localdate()


@pytest.fixture
def fin(world):
    org, farm = world.org_a, world.farm_a1
    expense = FinanceCategory.objects.create(
        organization=org, kind="expense", code="intrants", name="Intrants"
    )
    income = FinanceCategory.objects.create(
        organization=org, kind="income", code="ventes", name="Ventes"
    )
    cash = TreasuryAccount.objects.create(
        organization=org, farm=farm, name="Caisse", kind="cash", currency="XAF"
    )
    bank = TreasuryAccount.objects.create(
        organization=org, farm=farm, name="Banque", kind="bank", currency="XAF"
    )
    euro = TreasuryAccount.objects.create(
        organization=org, farm=farm, name="Compte EUR", kind="bank", currency="EUR"
    )
    storekeeper = make_user()
    add_member(org, farm, storekeeper, "storekeeper")
    return {
        "expense": expense,
        "income": income,
        "cash": cash,
        "bank": bank,
        "euro": euro,
        "storekeeper": storekeeper,
    }


def url(world, path):
    return f"/api/v1/farms/{world.farm_a1.id}/{path}"


def post_tx(client, world, payload, key=None):
    return client.post(
        url(world, "transactions/"),
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(key or uuid.uuid4()),
    )


def expense(fin, amount="15000", account="cash", **extra):
    return {
        "kind": "expense",
        "business_date": TODAY.isoformat(),
        "amount": amount,
        "account": str(fin[account].id),
        "category": str(fin["expense"].id),
        **extra,
    }


def balances(client, world):
    rows = client.get(url(world, "treasury-accounts/balances/")).json()
    return {row["name"]: (D(row["balance"]), D(row["provisional_balance"])) for row in rows}


def test_expense_and_income_update_balance(world, client_for, fin):
    client = client_for(world.finance_a1)
    spent = post_tx(client, world, expense(fin))
    assert spent.status_code == 201, spent.json()
    assert spent.json()["status"] == "validated"  # author holds finance.transaction.validate
    earned = post_tx(
        client,
        world,
        {
            "kind": "income",
            "business_date": TODAY.isoformat(),
            "amount": "40000",
            "account": str(fin["cash"].id),
            "category": str(fin["income"].id),
        },
    )
    assert earned.status_code == 201
    assert balances(client, world)["Caisse"] == (D(25000), D(25000))
    entries = LedgerEntry.objects.filter(account=fin["cash"]).values_list("amount", flat=True)
    assert sorted(entries) == [D(-15000), D(40000)]


def test_submitted_transactions_are_not_in_the_balance(world, client_for, fin):
    keeper = client_for(fin["storekeeper"])
    created = post_tx(keeper, world, expense(fin, "5000"))
    assert created.status_code == 201
    assert created.json()["status"] == "submitted"
    finance = client_for(world.finance_a1)
    assert balances(finance, world)["Caisse"] == (D(0), D(-5000))
    tx = created.json()
    validated = finance.post(
        url(world, f"transactions/{tx['id']}/validate/"), HTTP_IF_MATCH=str(tx["version"])
    )
    assert validated.status_code == 200
    assert balances(finance, world)["Caisse"] == (D(-5000), D(-5000))
    # The storekeeper may record but not validate.
    other = post_tx(keeper, world, expense(fin, "1000")).json()
    assert (
        keeper.post(
            url(world, f"transactions/{other['id']}/validate/"), HTTP_IF_MATCH="1"
        ).status_code
        == 403
    )


def test_idempotency_key_is_required_and_replays(world, client_for, fin):
    client = client_for(world.finance_a1)
    missing = client.post(url(world, "transactions/"), expense(fin), format="json")
    assert missing.status_code == 428
    key = uuid.uuid4()
    first = post_tx(client, world, expense(fin), key)
    replay = post_tx(client, world, expense(fin), key)
    assert (first.status_code, replay.status_code) == (201, 200)
    assert first.json()["id"] == replay.json()["id"]
    assert FinancialTransaction.objects.count() == 1
    assert LedgerEntry.objects.count() == 1  # never counted twice
    other = post_tx(client, world, expense(fin, "99999"), key)
    assert other.status_code == 409


@pytest.mark.parametrize(
    "override,field",
    [
        ({"amount": "10.50"}, "amount"),  # XAF has no minor unit
        ({"amount": "-10"}, "amount"),
        ({"currency": "EUR"}, "currency"),
        ({"category": None}, "category"),
    ],
)
def test_invalid_transactions(world, client_for, fin, override, field):
    response = post_tx(client_for(world.finance_a1), world, {**expense(fin), **override})
    assert response.status_code == 400, response.json()
    assert field in response.json()["field_errors"]


def test_category_kind_and_inactive_account(world, client_for, fin):
    client = client_for(world.finance_a1)
    wrong_kind = post_tx(client, world, {**expense(fin), "category": str(fin["income"].id)})
    assert wrong_kind.status_code == 400
    fin["cash"].is_active = False
    fin["cash"].save()
    inactive = post_tx(client, world, expense(fin))
    assert inactive.status_code == 400
    assert inactive.json()["details"]["reason"] == "account_inactive"


def test_future_and_backdated_transactions(world, client_for, fin):
    client = client_for(world.finance_a1)
    future = post_tx(
        client, world, expense(fin, business_date=(TODAY + timedelta(days=5)).isoformat())
    )
    assert future.status_code == 400
    old = post_tx(
        client, world, expense(fin, business_date=(TODAY - timedelta(days=60)).isoformat())
    )
    assert old.status_code == 201
    assert old.json()["status"] == "submitted"  # backdate limit forces a review (Q9)


def test_transfer_moves_money_but_is_not_income_or_expense(world, client_for, fin):
    client = client_for(world.finance_a1)
    post_tx(
        client,
        world,
        {
            "kind": "income",
            "business_date": TODAY.isoformat(),
            "amount": "100000",
            "account": str(fin["cash"].id),
            "category": str(fin["income"].id),
        },
    )
    transfer = post_tx(
        client,
        world,
        {
            "kind": "transfer",
            "business_date": TODAY.isoformat(),
            "amount": "60000",
            "account": str(fin["cash"].id),
            "to_account": str(fin["bank"].id),
        },
    )
    assert transfer.status_code == 201, transfer.json()
    result = balances(client, world)
    assert result["Caisse"][0] == D(40000) and result["Banque"][0] == D(60000)
    treasury = client.get(
        url(world, "transactions/treasury/"),
        {
            "period": "month",
            "date_from": TODAY.replace(day=1).isoformat(),
            "date_to": TODAY.isoformat(),
        },
    ).json()
    month = treasury["currencies"]["XAF"]["periods"][0]
    assert D(month["inflows"]) == D(100000) and D(month["outflows"]) == D(0)
    assert D(month["transfers"]) == D(60000)
    assert D(month["closing_balance"]) == D(100000)


def test_transfer_rules(world, client_for, fin):
    client = client_for(world.finance_a1)
    same = post_tx(
        client,
        world,
        {
            "kind": "transfer",
            "business_date": TODAY.isoformat(),
            "amount": "10",
            "account": str(fin["cash"].id),
            "to_account": str(fin["cash"].id),
        },
    )
    assert same.status_code == 400
    currencies = post_tx(
        client,
        world,
        {
            "kind": "transfer",
            "business_date": TODAY.isoformat(),
            "amount": "10",
            "account": str(fin["cash"].id),
            "to_account": str(fin["euro"].id),
        },
    )
    assert currencies.status_code == 400


def test_reversal_and_correction(world, client_for, fin):
    client = client_for(world.finance_a1)
    tx = post_tx(client, world, expense(fin, "20000")).json()
    refused = client.patch(
        url(world, f"transactions/{tx['id']}/"),
        {"amount": "1"},
        format="json",
        HTTP_IF_MATCH=str(tx["version"]),
    )
    assert refused.status_code == 400  # validated: no silent overwrite
    reversal = client.post(
        url(world, f"transactions/{tx['id']}/reverse/"),
        {"reason": "Saisie en double"},
        format="json",
    )
    assert reversal.status_code == 201, reversal.json()
    assert reversal.json()["kind"] == "reversal" and reversal.json()["reverses"] == tx["id"]
    assert FinancialTransaction.objects.get(id=tx["id"]).status == "reversed"
    assert balances(client, world)["Caisse"][0] == D(0)
    again = client.post(
        url(world, f"transactions/{tx['id']}/reverse/"), {"reason": "x"}, format="json"
    )
    assert again.json()["id"] == reversal.json()["id"]  # converges, no second reversal

    original = post_tx(client, world, expense(fin, "30000")).json()
    corrected = client.post(
        url(world, f"transactions/{original['id']}/correct/"),
        {"reason": "Montant erroné", "amount": "3000"},
        format="json",
    )
    assert corrected.status_code == 201, corrected.json()
    assert corrected.json()["corrects"] == original["id"]
    assert balances(client, world)["Caisse"][0] == D(-3000)
    # The full history is kept: 2 originals, 2 reversals, 1 correction.
    assert FinancialTransaction.objects.count() == 5


def test_amend_submitted_keeps_revisions_and_reject(world, client_for, fin):
    keeper = client_for(fin["storekeeper"])
    tx = post_tx(keeper, world, expense(fin, "8000")).json()
    amended = keeper.patch(
        url(world, f"transactions/{tx['id']}/"),
        {"amount": "8500", "reason": "Reçu relu"},
        format="json",
        HTTP_IF_MATCH=str(tx["version"]),
    )
    assert amended.status_code == 200, amended.json()
    assert amended.json()["revision"] == 2
    assert D(amended.json()["entries"][0]["amount"]) == D(-8500)
    revision = TransactionRevision.objects.get(transaction_id=tx["id"])
    assert D(revision.snapshot["amount"]) == D(8000)
    finance = client_for(world.finance_a1)
    no_reason = finance.post(
        url(world, f"transactions/{tx['id']}/reject/"),
        {"reason": ""},
        format="json",
        HTTP_IF_MATCH=str(amended.json()["version"]),
    )
    assert no_reason.status_code == 400
    rejected = finance.post(
        url(world, f"transactions/{tx['id']}/reject/"),
        {"reason": "Justificatif absent"},
        format="json",
        HTTP_IF_MATCH=str(amended.json()["version"]),
    )
    assert rejected.json()["status"] == "rejected"
    assert balances(finance, world)["Caisse"] == (D(0), D(0))


def test_database_triggers_protect_validated_transactions(world, fin):
    ctx = resolve_farm_context(world.finance_a1, world.farm_a1.id)
    tx, _ = services.record_transaction(
        ctx,
        data={
            "kind": "expense",
            "business_date": TODAY,
            "amount": D(1000),
            "account": fin["cash"],
            "category": fin["expense"],
            "idempotency_key": uuid.uuid4(),
        },
    )
    assert tx.status == "validated"
    for attempt in (
        lambda: FinancialTransaction.objects.filter(id=tx.id).update(amount=D(1)),
        lambda: FinancialTransaction.objects.filter(id=tx.id).update(status="submitted"),
        lambda: FinancialTransaction.objects.filter(id=tx.id).delete(),
        lambda: LedgerEntry.objects.filter(transaction=tx).update(amount=D(-1)),
        lambda: LedgerEntry.objects.filter(transaction=tx).delete(),
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            attempt()
    tx.refresh_from_db()
    assert tx.amount == D(1000)


def test_possible_duplicate_from_another_device_is_flagged(world, client_for, fin):
    # Two people record the same cash expense from two phones.
    first = post_tx(client_for(world.finance_a1), world, expense(fin, "7000"))
    assert first.json()["status"] == "validated"
    second = post_tx(client_for(world.manager_a1), world, expense(fin, "7000"))
    assert second.status_code == 201
    body = second.json()
    assert body["possible_duplicate"] is True and body["status"] == "submitted"
    assert SyncConflict.objects.filter(
        entity_id=body["id"], conflict_type="possible_duplicate"
    ).exists()
    assert balances(client_for(world.finance_a1), world)["Caisse"][0] == D(-7000)


@pytest.mark.django_db(transaction=True)
def test_concurrent_submissions_with_same_key_create_one_transaction(world, fin):
    ctx = resolve_farm_context(world.finance_a1, world.farm_a1.id)
    key = uuid.uuid4()
    results: list = []
    errors: list = []

    def worker() -> None:
        try:
            results.append(
                services.record_transaction(
                    ctx,
                    data={
                        "kind": "expense",
                        "business_date": TODAY,
                        "amount": D(2500),
                        "account": fin["cash"],
                        "category": fin["expense"],
                        "idempotency_key": key,
                    },
                )
            )
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert FinancialTransaction.objects.filter(idempotency_key=key).count() == 1
    assert LedgerEntry.objects.filter(transaction__idempotency_key=key).count() == 1
    assert sum(1 for _, created in results if created) == 1


def test_budget_vs_actual(world, client_for, fin):
    client = client_for(world.manager_a1)
    line = client.post(
        url(world, "budget-lines/"),
        {
            "category": str(fin["expense"].id),
            "label": "Engrais",
            "planned_amount": "100000",
            "currency": "XAF",
        },
        format="json",
    )
    assert line.status_code == 201, line.json()
    line_id = line.json()["id"]
    finance = client_for(world.finance_a1)
    tx1 = post_tx(finance, world, expense(fin, "60000")).json()
    tx2 = post_tx(client_for(fin["storekeeper"]), world, expense(fin, "30000")).json()
    assert (
        client.post(
            url(world, f"transactions/{tx1['id']}/allocate/"),
            {"budget_line": line_id, "amount": "60000"},
            format="json",
        ).status_code
        == 200
    )
    over = client.post(
        url(world, f"transactions/{tx2['id']}/allocate/"),
        {"budget_line": line_id, "amount": "40000"},
        format="json",
    )
    assert over.status_code == 400  # cannot allocate more than the transaction amount
    client.post(
        url(world, f"transactions/{tx2['id']}/allocate/"),
        {"budget_line": line_id, "amount": "30000"},
        format="json",
    )
    report = client.get(url(world, "budget-lines/report/")).json()[0]
    assert D(report["planned"]) == D(100000)
    assert D(report["actual"]) == D(60000)  # tx2 is only submitted
    assert D(report["pending"]) == D(30000)
    assert D(report["variance"]) == D(-40000) and D(report["variance_pct"]) == D("-40.00")
    # A reversed expense no longer counts as actual.
    finance.post(
        url(world, f"transactions/{tx1['id']}/reverse/"), {"reason": "Erreur"}, format="json"
    )
    assert D(client.get(url(world, "budget-lines/report/")).json()[0]["actual"]) == D(0)


def test_opening_balance(world, client_for, fin):
    client = client_for(world.finance_a1)
    response = client.post(
        url(world, "treasury-accounts/opening/"),
        {"account": str(fin["bank"].id), "balance": "-25000", "business_date": TODAY.isoformat()},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    assert response.status_code == 201, response.json()
    assert balances(client, world)["Banque"][0] == D(-25000)
    twice = client.post(
        url(world, "treasury-accounts/opening/"),
        {"account": str(fin["bank"].id), "balance": "10", "business_date": TODAY.isoformat()},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    assert twice.status_code == 400


def test_finance_permissions(world, client_for, fin):
    worker = client_for(world.worker_a1)
    assert worker.get(url(world, "transactions/")).status_code == 403
    assert worker.get(url(world, "treasury-accounts/balances/")).status_code == 403
    assert post_tx(worker, world, expense(fin)).status_code == 403
    # An account of another farm cannot be used.
    foreign = TreasuryAccount.objects.create(
        organization=world.org_a, farm=world.farm_a2, name="Autre", kind="cash", currency="XAF"
    )
    response = post_tx(
        client_for(world.admin_a), world, {**expense(fin), "account": str(foreign.id)}
    )
    assert response.status_code == 400


def test_offline_expense_sync_and_reversal_command(world, client_for, fin):
    client = client_for(world.finance_a1)
    tx_id = str(uuid.uuid4())
    create = {
        "op_id": str(uuid.uuid4()),
        "farm_id": str(world.farm_a1.id),
        "op_type": "create",
        "entity_type": "finance.transaction",
        "entity_id": tx_id,
        "payload": expense(fin, "12000"),
    }
    first = client.post("/api/v1/sync/push/", {"operations": [create]}, format="json").json()[
        "results"
    ][0]
    assert first["status"] == "applied", first
    # Same transaction re-sent under a new op id (e.g. after reinstall): still one transaction.
    resent = {**create, "op_id": str(uuid.uuid4())}
    second = client.post("/api/v1/sync/push/", {"operations": [resent]}, format="json").json()[
        "results"
    ][0]
    assert second["status"] == "applied" and second["created"] is False
    assert FinancialTransaction.objects.filter(id=tx_id).count() == 1
    tx = FinancialTransaction.objects.get(id=tx_id)
    assert tx.created_offline is True and tx.idempotency_key == uuid.UUID(tx_id)
    # Financial transactions can never be updated through sync.
    update = {
        **create,
        "op_id": str(uuid.uuid4()),
        "op_type": "update",
        "base_version": 1,
        "payload": {"amount": "1"},
    }
    assert (
        client.post("/api/v1/sync/push/", {"operations": [update]}, format="json").json()[
            "results"
        ][0]["status"]
        == "rejected"
    )
    reverse = {
        "op_id": str(uuid.uuid4()),
        "farm_id": str(world.farm_a1.id),
        "op_type": "command",
        "command": "finance.reverse",
        "entity_type": "finance.transaction",
        "entity_id": tx_id,
        "payload": {"reason": "Annulée hors ligne"},
    }
    result = client.post("/api/v1/sync/push/", {"operations": [reverse]}, format="json").json()[
        "results"
    ][0]
    assert result["status"] == "applied", result
    replay = client.post("/api/v1/sync/push/", {"operations": [reverse]}, format="json").json()[
        "results"
    ][0]
    assert replay["replayed"] is True
    assert FinancialTransaction.objects.filter(reverses_id=tx_id).count() == 1
    pulled = client.get("/api/v1/sync/pull/", {"farm_id": str(world.farm_a1.id)}).json()
    types = {c["entity_type"] for c in pulled["changes"]}
    assert {"finance.transaction", "farms.farm"} <= types
    # A worker without finance.view must purge finance data locally.
    worker_pull = (
        client_for(world.worker_a1)
        .get("/api/v1/sync/pull/", {"farm_id": str(world.farm_a1.id)})
        .json()
    )
    assert "finance.transaction" in worker_pull["purge"]
    assert all(c["entity_type"] != "finance.transaction" for c in worker_pull["changes"])


def test_auto_validation_setting(world, client_for, fin):
    world.farm_a1.settings = {"auto_validate_own_transactions": False}
    world.farm_a1.save()
    response = post_tx(client_for(world.finance_a1), world, expense(fin))
    assert response.json()["status"] == "submitted"


def test_storekeeper_records_but_does_not_validate(world):
    # Default role matrix (Q2, Q14).
    role = Role.objects.get(organization=world.org_a, code="storekeeper")
    codes = role.permission_codes()
    assert "finance.transaction.create" in codes and "finance.transaction.validate" not in codes
