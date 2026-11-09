"""Member contributions, treasury account, loans (OPEN_QUESTIONS Q35). Amounts are fictitious."""

import importlib
import uuid
from decimal import Decimal as D

import pytest
from django.apps import apps as django_apps
from django.utils import timezone

from apps.farms.access import resolve_farm_context
from apps.finance import services
from apps.finance.models import FinanceCategory, FinancialTransaction, TreasuryAccount
from apps.organizations.models import Role, RolePermission
from tests.factories import add_member, make_user
from tests.factories_catalog import pdf_upload

pytestmark = pytest.mark.django_db
TODAY = timezone.localdate().isoformat()


@pytest.fixture
def money(world):
    org, farm = world.org_a, world.farm_a1
    contributor = make_user(full_name="Awa Contributrice")
    other = make_user(full_name="Jean Contributeur")
    for user in (contributor, other):
        add_member(org, farm, user, "contributor")
    return {
        "main": TreasuryAccount.objects.create(
            organization=org,
            farm=farm,
            name="Trésorerie",
            kind="bank",
            currency="XAF",
            role="main",
        ),
        "field_cash": TreasuryAccount.objects.create(
            organization=org, farm=farm, name="Caisse terrain", kind="cash", currency="XAF"
        ),
        "contribution": FinanceCategory.objects.create(
            organization=org, kind="investment", code="apport", name="Apport d'associé"
        ),
        "loan_category": FinanceCategory.objects.create(
            organization=org, kind="investment", code="pret", name="Prêt bancaire"
        ),
        "inputs": FinanceCategory.objects.create(
            organization=org, kind="expense", code="engrais", name="Engrais"
        ),
        "machine": FinanceCategory.objects.create(
            organization=org, kind="expense", code="machine", name="Motopompe", is_capex=True
        ),
        "sales": FinanceCategory.objects.create(
            organization=org, kind="income", code="ventes", name="Ventes"
        ),
        "contributor": contributor,
        "other": other,
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


def funding(account, category, amount="500000", **extra):
    return {
        "kind": "funding",
        "business_date": TODAY,
        "amount": amount,
        "account": str(account),
        "category": str(category.id),
        **extra,
    }


def balance(account):
    return services.validated_balance(TreasuryAccount.objects.get(id=account))


def open_account(client, world):
    response = client.post(url(world, "treasury-accounts/mine/"), {}, format="json")
    assert response.status_code in (200, 201), response.json()
    return response.json()["id"]


def validate(client, world, tx):
    return client.post(
        url(world, f"transactions/{tx['id']}/validate/"), HTTP_IF_MATCH=str(tx["version"])
    )


def test_contribution_journey_from_member_to_treasury(world, client_for, money):
    awa = client_for(money["contributor"])
    manager = client_for(world.manager_a1)

    # 1. Awa opens her member account (idempotent) and sends the proof of payment.
    first = awa.post(url(world, "treasury-accounts/mine/"), {}, format="json")
    assert first.status_code == 201
    account = first.json()
    assert account["role"] == "member" and account["holder"] == str(money["contributor"].id)
    again = awa.post(url(world, "treasury-accounts/mine/"), {}, format="json")
    assert again.status_code == 200 and again.json()["id"] == account["id"]
    proof = awa.post(
        url(world, "files/"),
        {"purpose": "funding_proof", "file": pdf_upload("envoi.pdf")},
        format="multipart",
    )
    assert proof.status_code == 201, proof.json()

    # 2. She records the contribution: submitted, not yet in the balance.
    recorded = post_tx(
        awa,
        world,
        funding(account["id"], money["contribution"], attachments=[proof.json()["id"]]),
    )
    assert recorded.status_code == 201, recorded.json()
    tx = recorded.json()
    assert tx["kind"] == "funding" and tx["status"] == "submitted"
    assert tx["attachments"] == [proof.json()["id"]]
    assert balance(account["id"]) == 0

    # She can neither validate it nor move money that is not validated yet.
    assert validate(awa, world, tx).status_code == 403
    early = post_tx(
        awa,
        world,
        {"kind": "transfer", "business_date": TODAY, "amount": "500000", "account": account["id"]},
    )
    assert early.status_code == 400
    assert early.json()["details"]["reason"] == "insufficient_balance"

    # 3. The farm manager checks the proof and validates.
    assert manager.get(url(world, f"files/{proof.json()['id']}/download/")).status_code == 200
    assert validate(manager, world, tx).status_code == 200
    assert balance(account["id"]) == D(500000)

    # 4. Awa transfers to the treasury without knowing its id: validated at once.
    moved = post_tx(
        awa,
        world,
        {"kind": "transfer", "business_date": TODAY, "amount": "500000", "account": account["id"]},
    )
    assert moved.status_code == 201, moved.json()
    assert moved.json()["status"] == "validated"
    assert balance(account["id"]) == 0
    assert balance(money["main"].id) == D(500000)

    # 5. The farm manager pays the fertiliser from the treasury.
    spent = post_tx(
        manager,
        world,
        {
            "kind": "expense",
            "business_date": TODAY,
            "amount": "420000",
            "account": str(money["main"].id),
            "category": str(money["inputs"].id),
        },
    )
    assert spent.status_code == 201
    assert balance(money["main"].id) == D(80000)

    statement = manager.get(url(world, "treasury-accounts/members/")).json()
    awa_row = next(r for r in statement if r["account"] == account["id"])
    assert D(awa_row["contributed"]) == D(500000)
    assert D(awa_row["transferred_to_treasury"]) == D(500000)
    assert D(awa_row["balance"]) == 0 and awa_row["holder_name"] == "Awa Contributrice"


def test_contributor_sees_only_their_own_account_and_movements(world, client_for, money):
    awa = client_for(money["contributor"])
    jean = client_for(money["other"])
    mine = open_account(awa, world)
    other = open_account(jean, world)
    post_tx(jean, world, funding(other, money["contribution"], "1000"))
    post_tx(awa, world, funding(mine, money["contribution"], "2000"))

    accounts = awa.get(url(world, "treasury-accounts/")).json()["results"]
    assert [a["id"] for a in accounts] == [mine]
    assert awa.get(url(world, f"treasury-accounts/{money['main'].id}/")).status_code == 404
    assert awa.get(url(world, f"treasury-accounts/{other}/")).status_code == 404
    movements = awa.get(url(world, "transactions/")).json()["results"]
    assert [m["amount"] for m in movements] == ["2000.0000"]
    assert [r["account"] for r in awa.get(url(world, "treasury-accounts/members/")).json()] == [
        mine
    ]
    assert [r["account"] for r in awa.get(url(world, "treasury-accounts/balances/")).json()] == [
        mine
    ]
    assert (
        awa.get(
            url(world, "transactions/treasury/?date_from=2026-01-01&date_to=2026-12-31")
        ).status_code
        == 403
    )
    assert awa.get(url(world, "loans/")).status_code == 403


def test_only_the_holder_moves_or_funds_a_member_account(world, client_for, money):
    awa = client_for(money["contributor"])
    jean = client_for(money["other"])
    manager = client_for(world.manager_a1)
    mine = open_account(awa, world)
    tx = post_tx(awa, world, funding(mine, money["contribution"])).json()
    validate(manager, world, tx)

    # Someone else, even the farm manager, cannot fund or empty Awa's account.
    assert post_tx(jean, world, funding(mine, money["contribution"])).status_code in (403, 404)
    assert post_tx(manager, world, funding(mine, money["contribution"])).status_code == 403
    steal = {
        "kind": "transfer",
        "business_date": TODAY,
        "amount": "1000",
        "account": mine,
        "to_account": str(money["main"].id),
    }
    assert post_tx(manager, world, steal).status_code == 403

    # Awa only transfers to the treasury, within her validated balance.
    to_field = {**steal, "to_account": str(money["field_cash"].id)}
    assert post_tx(awa, world, to_field).status_code == 400
    too_much = {**steal, "amount": "500001"}
    response = post_tx(awa, world, too_much)
    assert response.status_code == 400
    assert response.json()["details"]["available"] == "500000.0000"


def test_member_accounts_carry_neither_income_nor_expense_nor_incoming_transfer(
    world, client_for, money
):
    awa = client_for(money["contributor"])
    manager = client_for(world.manager_a1)
    mine = open_account(awa, world)
    for kind, category in (("expense", money["inputs"]), ("income", money["sales"])):
        response = post_tx(
            manager,
            world,
            {
                "kind": kind,
                "business_date": TODAY,
                "amount": "1000",
                "account": mine,
                "category": str(category.id),
            },
        )
        assert response.status_code == 400
        assert response.json()["details"]["reason"] == "member_account"
    incoming = post_tx(
        manager,
        world,
        {
            "kind": "transfer",
            "business_date": TODAY,
            "amount": "1000",
            "account": str(money["main"].id),
            "to_account": mine,
        },
    )
    assert incoming.status_code == 400
    # A contributor has no right to record the farm's expenses.
    expense = {
        "kind": "expense",
        "business_date": TODAY,
        "amount": "1000",
        "account": str(money["main"].id),
        "category": str(money["inputs"].id),
    }
    assert post_tx(awa, world, expense).status_code == 403


def test_funding_needs_an_investment_category_and_a_member_or_main_account(
    world, client_for, money
):
    awa = client_for(money["contributor"])
    manager = client_for(world.manager_a1)
    mine = open_account(awa, world)
    assert post_tx(awa, world, funding(mine, money["sales"])).status_code == 400
    assert (
        post_tx(manager, world, funding(money["field_cash"].id, money["contribution"])).status_code
        == 400
    )
    direct = post_tx(manager, world, funding(money["main"].id, money["contribution"]))
    assert direct.status_code == 201


def test_member_contribution_always_waits_for_validation(world, client_for, money):
    """Even a farm manager contributing personally does not validate it by recording it."""
    manager = client_for(world.manager_a1)
    mine = open_account(manager, world)
    tx = post_tx(manager, world, funding(mine, money["contribution"])).json()
    assert tx["status"] == "submitted"
    assert validate(manager, world, tx).status_code == 200


def test_contribution_replay_and_reversal(world, client_for, money):
    awa = client_for(money["contributor"])
    manager = client_for(world.manager_a1)
    mine = open_account(awa, world)
    key = uuid.uuid4()
    first = post_tx(awa, world, funding(mine, money["contribution"]), key=key)
    replay = post_tx(awa, world, funding(mine, money["contribution"]), key=key)
    assert first.status_code == 201 and replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    tx = first.json()
    validate(manager, world, tx)
    reversed_ = manager.post(
        url(world, f"transactions/{tx['id']}/reverse/"),
        {"reason": "Fonds jamais reçus"},
        format="json",
    )
    assert reversed_.status_code == 201
    assert balance(mine) == 0
    row = manager.get(url(world, "treasury-accounts/members/")).json()[0]
    assert D(row["contributed"]) == 0 and D(row["balance"]) == 0


def test_contributor_amends_own_pending_contribution_only(world, client_for, money):
    awa = client_for(money["contributor"])
    mine = open_account(awa, world)
    tx = post_tx(awa, world, funding(mine, money["contribution"])).json()
    amended = awa.patch(
        url(world, f"transactions/{tx['id']}/"),
        {"amount": "450000"},
        format="json",
        HTTP_IF_MATCH=str(tx["version"]),
    )
    assert amended.status_code == 200 and amended.json()["amount"] == "450000.0000"


def test_contribution_proof_is_readable_by_its_uploader_and_finance_only(world, client_for, money):
    awa = client_for(money["contributor"])
    proof = awa.post(
        url(world, "files/"), {"purpose": "funding_proof", "file": pdf_upload()}, format="multipart"
    ).json()
    download = url(world, f"files/{proof['id']}/download/")
    assert awa.get(download).status_code == 200
    assert client_for(money["other"]).get(download).status_code == 403
    assert client_for(world.finance_a1).get(download).status_code == 200


def test_loan_disbursement_repayment_and_outstanding(world, client_for, money):
    manager = client_for(world.manager_a1)
    loan = manager.post(
        url(world, "loans/"),
        {
            "lender": "Banque fictive",
            "principal": "1000000",
            "currency": "XAF",
            "started_on": TODAY,
        },
        format="json",
    ).json()
    main = str(money["main"].id)
    over = post_tx(
        manager, world, funding(main, money["loan_category"], "1000001", loan=loan["id"])
    )
    assert over.status_code == 400
    disbursed = post_tx(
        manager, world, funding(main, money["loan_category"], "1000000", loan=loan["id"])
    )
    assert disbursed.status_code == 201, disbursed.json()

    repayment = {
        "kind": "repayment",
        "business_date": TODAY,
        "amount": "300000",
        "account": main,
        "loan": loan["id"],
    }
    from_field = {**repayment, "account": str(money["field_cash"].id)}
    assert post_tx(manager, world, from_field).status_code == 400
    with_category = {**repayment, "category": str(money["inputs"].id)}
    assert post_tx(manager, world, with_category).status_code == 400
    repaid = post_tx(manager, world, repayment)
    assert repaid.status_code == 201, repaid.json()
    assert post_tx(manager, world, {**repayment, "amount": "700001"}).status_code == 400

    position = manager.get(url(world, "loans/positions/")).json()[0]
    assert D(position["disbursed"]) == D(1000000)
    assert D(position["repaid"]) == D(300000)
    assert D(position["outstanding"]) == D(700000)
    assert balance(money["main"].id) == D(700000)

    # A repayment reversed by mistake gives the principal back to the outstanding amount.
    manager.post(
        url(world, f"transactions/{repaid.json()['id']}/reverse/"),
        {"reason": "Erreur de saisie"},
        format="json",
    )
    assert D(manager.get(url(world, "loans/positions/")).json()[0]["outstanding"]) == D(1000000)


def test_treasury_report_separates_fundings_investments_and_repayments(world, client_for, money):
    manager = client_for(world.manager_a1)
    main = str(money["main"].id)
    loan = manager.post(
        url(world, "loans/"),
        {"lender": "Banque", "principal": "200000", "currency": "XAF", "started_on": TODAY},
        format="json",
    ).json()
    post_tx(manager, world, funding(main, money["contribution"], "2000000"))
    post_tx(manager, world, funding(main, money["loan_category"], "200000", loan=loan["id"]))
    for category, amount in ((money["machine"], "1500000"), (money["inputs"], "400000")):
        post_tx(
            manager,
            world,
            {
                "kind": "expense",
                "business_date": TODAY,
                "amount": amount,
                "account": main,
                "category": str(category.id),
            },
        )
    post_tx(
        manager,
        world,
        {
            "kind": "income",
            "business_date": TODAY,
            "amount": "900000",
            "account": main,
            "category": str(money["sales"].id),
        },
    )
    post_tx(
        manager,
        world,
        {
            "kind": "repayment",
            "business_date": TODAY,
            "amount": "50000",
            "account": main,
            "loan": loan["id"],
        },
    )
    post_tx(
        manager,
        world,
        {
            "kind": "transfer",
            "business_date": TODAY,
            "amount": "100000",
            "account": main,
            "to_account": str(money["field_cash"].id),
        },
    )

    report = manager.get(
        url(world, f"transactions/treasury/?period=month&date_from={TODAY}&date_to={TODAY}")
    ).json()
    period = report["currencies"]["XAF"]["periods"][0]
    assert D(period["inflows"]) == D(900000)
    assert D(period["outflows"]) == D(400000)  # campaign charges only
    assert D(period["investments"]) == D(1500000)
    assert D(period["fundings"]) == D(2200000)
    assert D(period["repayments"]) == D(50000)
    assert D(period["transfers"]) == D(100000)
    assert D(period["net"]) == D(900000 - 400000 - 1500000 + 2200000 - 50000)


def test_campaign_margin_excludes_investment_expenses(world, money):
    from apps.harvest.services import _money_for_cycle
    from tests.factories_catalog import make_variety
    from tests.tenancy.test_isolation import _plan_objects

    cycle = _plan_objects(world, make_variety(world.org_a))["crop_cycle"]
    ctx = resolve_farm_context(world.manager_a1, world.farm_a1.id)
    for category, amount in ((money["machine"], D(1500000)), (money["inputs"], D(400000))):
        services.record_transaction(
            ctx,
            data={
                "kind": "expense",
                "business_date": timezone.localdate(),
                "amount": amount,
                "account": money["main"],
                "category": category,
                "crop_cycle": cycle,
                "idempotency_key": uuid.uuid4(),
            },
        )
    FinancialTransaction.objects.filter(farm=world.farm_a1).update(status="validated")
    assert _money_for_cycle(cycle, "expense", "XAF") == D(400000)


def test_accounts_roles(world, client_for, money):
    manager = client_for(world.manager_a1)
    second_main = manager.post(
        url(world, "treasury-accounts/"),
        {"name": "Autre", "kind": "bank", "currency": "XAF", "role": "main"},
        format="json",
    )
    assert second_main.status_code == 400
    member = manager.post(
        url(world, "treasury-accounts/"),
        {"name": "Pour Awa", "kind": "cash", "currency": "XAF", "role": "member"},
        format="json",
    )
    assert member.status_code == 400
    switched = manager.post(url(world, f"treasury-accounts/{money['field_cash'].id}/set-main/"))
    assert switched.status_code == 200 and switched.json()["role"] == "main"
    money["main"].refresh_from_db()
    assert money["main"].role == "operating"
    patch = manager.patch(
        url(world, f"treasury-accounts/{money['main'].id}/"),
        {"role": "main"},
        format="json",
        HTTP_IF_MATCH=str(money["main"].version),
    )
    assert patch.status_code == 400


def test_first_account_of_a_farm_becomes_its_main_account(world):
    ctx = resolve_farm_context(world.admin_a, world.farm_a2.id)  # farm without any account
    first = services.create_account(ctx, data={"name": "Banque", "kind": "bank", "currency": "XAF"})
    second = services.create_account(
        ctx, data={"name": "Caisse", "kind": "cash", "currency": "XAF"}
    )
    assert (first.role, second.role) == ("main", "operating")


def test_capex_marker_is_for_expense_categories_only(world):
    ctx = resolve_farm_context(world.admin_a, world.farm_a1.id)
    with pytest.raises(services.BusinessRuleError):
        services.create_category(
            ctx, data={"kind": "income", "code": "x", "name": "X", "is_capex": True}
        )


def test_data_migration_sets_main_accounts_and_contributor_role(world):
    migration = importlib.import_module(
        "apps.finance.migrations.0004_main_accounts_and_contributor_role"
    )
    older = TreasuryAccount.objects.create(
        organization=world.org_a, farm=world.farm_a2, name="Ancien", kind="bank", currency="XAF"
    )
    TreasuryAccount.objects.create(
        organization=world.org_a, farm=world.farm_a2, name="Récent", kind="cash", currency="XAF"
    )
    RolePermission.objects.filter(permission_code="finance.funding.create").delete()
    Role.objects.filter(code="contributor").delete()

    migration.forwards(django_apps, None)

    roles = dict(TreasuryAccount.objects.filter(farm=world.farm_a2).values_list("name", "role"))
    assert roles == {"Ancien": "main", "Récent": "operating"}
    assert older.pk
    for org in (world.org_a, world.org_b):
        contributor = Role.objects.get(organization=org, code="contributor")
        assert contributor.permission_codes() == {"farm.view", "finance.funding.create"}
        assert (
            "finance.funding.create"
            in Role.objects.get(organization=org, code="farm_manager").permission_codes()
        )
