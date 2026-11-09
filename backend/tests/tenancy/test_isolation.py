"""Generated multi-tenant isolation suite (ARCHITECTURE.md §6.3).

Every named route under /api/v1/ must be declared in ROUTES. A new route
that is not declared makes `test_every_route_is_declared` fail, forcing the
author to state its tenant scope explicitly.

Scopes:
- public: no authentication required.
- user: authenticated, data limited to the current user.
- org: resolved from `organization_id` (or `pk` for organization-detail).
- farm: resolved from `farm_id`.
"""

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

import pytest
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from apps.farms.models import FarmMembership
from apps.organizations.models import Invitation, OrganizationMembership, Role
from apps.synchronization.models import SyncConflict
from tests.factories import World, make_field, make_parcel
from tests.factories_catalog import PDF_BYTES, make_data_set, make_sheet, make_variety

pytestmark = pytest.mark.django_db


@dataclass(frozen=True)
class Route:
    scope: str
    methods: tuple[str, ...]
    kind: str | None = None  # object needed for detail routes
    extra: dict = field(default_factory=dict)


ROUTES: dict[str, Route] = {
    "health": Route("public", ("get",)),
    "schema": Route("public", ("get",)),
    "docs": Route("public", ("get",)),
    "auth-login": Route("public", ("post",)),
    "auth-refresh": Route("public", ("post",)),
    "invitation-accept": Route("public", ("post",)),
    "auth-logout": Route("user", ("post",)),
    "auth-password": Route("user", ("post",)),
    "me": Route("user", ("get", "patch")),
    "my-device-list": Route("user", ("get",)),
    "my-device-revoke": Route("user", ("post",), kind="device"),
    "permission-catalog": Route("user", ("get",)),
    "organization-list": Route("user", ("get", "post")),
    "farm-list": Route("user", ("get",)),
    "organization-detail": Route("org", ("get", "patch"), kind="organization"),
    "org-role-list": Route("org", ("get", "post")),
    "org-role-detail": Route("org", ("get", "patch", "delete"), kind="role"),
    "org-member-list": Route("org", ("get",)),
    "org-member-detail": Route("org", ("get", "patch"), kind="org_member"),
    "org-invitation-list": Route("org", ("get", "post")),
    "org-invitation-revoke": Route("org", ("post",), kind="invitation"),
    "org-farm-list": Route("org", ("get", "post")),
    "farm-detail": Route("farm", ("get", "patch")),
    "farm-member-list": Route("farm", ("get", "post")),
    "farm-member-detail": Route("farm", ("get", "patch"), kind="farm_member"),
    "farm-field-list": Route("farm", ("get", "post")),
    "farm-field-detail": Route("farm", ("get", "patch", "delete"), kind="field"),
    "farm-parcel-list": Route("farm", ("get", "post")),
    "farm-parcel-detail": Route("farm", ("get", "patch", "delete"), kind="parcel"),
    "farm-parcel-history": Route("farm", ("get", "post"), kind="parcel"),
    # Sync push/pull resolve the farm from the body / query string: covered by
    # apps/synchronization/tests (cross-tenant push and pull return not_found / 404).
    "sync-push": Route("user", ("post",)),
    "sync-pull": Route("user", ("get",)),
    "sync-conflict-list": Route("farm", ("get",)),
    "sync-conflict-detail": Route("farm", ("get",), kind="conflict"),
    "sync-conflict-resolve": Route("farm", ("post",), kind="conflict"),
    "org-file-list": Route("org", ("post",)),
    "org-file-detail": Route("org", ("get",), kind="org_file"),
    "org-file-download": Route("org", ("get",), kind="org_file"),
    "farm-file-list": Route("farm", ("post",)),
    "farm-file-detail": Route("farm", ("get",), kind="farm_file"),
    "farm-file-download": Route("farm", ("get",), kind="farm_file"),
    "org-crop-list": Route("org", ("get", "post")),
    "org-crop-detail": Route("org", ("get", "patch", "delete"), kind="crop"),
    "org-variety-list": Route("org", ("get", "post")),
    "org-variety-detail": Route("org", ("get", "patch", "delete"), kind="variety"),
    "org-variety-documents": Route("org", ("get", "post"), kind="variety"),
    "org-technical-data-set-list": Route("org", ("get", "post")),
    "org-technical-data-set-detail": Route("org", ("get",), kind="data_set"),
    "org-technical-data-set-items": Route("org", ("post",), kind="data_set"),
    "org-technical-data-set-remove-items": Route("org", ("post",), kind="data_set"),
    "org-technical-data-set-validate-items": Route("org", ("post",), kind="data_set"),
    "org-technical-data-set-validate": Route("org", ("post",), kind="data_set"),
    "technical-keys": Route("user", ("get",)),
    "farm-campaign-list": Route("farm", ("get", "post")),
    "farm-campaign-detail": Route("farm", ("get", "patch"), kind="campaign"),
    "farm-plan-list": Route("farm", ("get", "post")),
    "farm-plan-detail": Route("farm", ("get",), kind="plan"),
    "farm-plan-new-version": Route("farm", ("post",), kind="plan"),
    "farm-plan-compare": Route("farm", ("get",), kind="plan"),
    "farm-plan-version-list": Route("farm", ("get",)),
    "farm-plan-version-detail": Route("farm", ("get", "patch"), kind="plan_version"),
    "farm-plan-version-planting-spec": Route("farm", ("patch",), kind="plan_version"),
    "farm-plan-version-allocations": Route("farm", ("put",), kind="plan_version"),
    "farm-plan-version-phases": Route("farm", ("put",), kind="plan_version"),
    "farm-plan-version-prefill": Route("farm", ("post",), kind="plan_version"),
    "farm-plan-version-compute": Route("farm", ("post",), kind="plan_version"),
    "farm-plan-version-validate": Route("farm", ("post",), kind="plan_version"),
    "farm-crop-cycle-list": Route("farm", ("get",)),
    "farm-crop-cycle-detail": Route("farm", ("get",), kind="crop_cycle"),
    "org-supplier-list": Route("org", ("get", "post")),
    "org-supplier-detail": Route("org", ("get", "patch", "delete"), kind="supplier"),
    "org-catalog-item-list": Route("org", ("get", "post")),
    "org-catalog-item-detail": Route("org", ("get", "patch", "delete"), kind="catalog_item"),
    "org-price-list-list": Route("org", ("get", "post")),
    "org-price-list-detail": Route("org", ("get", "patch"), kind="price_list"),
    "org-price-list-items": Route("org", ("put",), kind="price_list"),
    "farm-irrigation-design-list": Route("farm", ("get", "post")),
    "farm-irrigation-design-detail": Route("farm", ("get", "patch"), kind="design"),
    "farm-irrigation-design-compute": Route("farm", ("post",), kind="design"),
    "farm-irrigation-design-validate": Route("farm", ("post",), kind="design"),
    "farm-irrigation-design-new-version": Route("farm", ("post",), kind="design"),
    "farm-irrigation-design-bom-lines": Route("farm", ("post",), kind="design"),
    "farm-irrigation-design-link": Route("farm", ("post",), kind="design"),
    "farm-quote-list": Route("farm", ("get", "post")),
    "farm-quote-detail": Route("farm", ("get", "patch"), kind="quote"),
    "farm-quote-issue": Route("farm", ("post",), kind="quote"),
    "farm-quote-decide": Route("farm", ("post",), kind="quote"),
    "org-input-product-list": Route("org", ("get", "post")),
    "org-input-product-detail": Route("org", ("get", "patch"), kind="input_product"),
    "farm-plan-program-detail": Route("farm", ("get",), kind="plan_version"),
    "farm-plan-program-fertilizations": Route("farm", ("post",), kind="plan_version"),
    "farm-plan-program-phyto": Route("farm", ("post",), kind="plan_version"),
    "farm-plan-program-irrigation": Route("farm", ("put",), kind="plan_version"),
    "farm-plan-program-remove": Route("farm", ("post",), kind="plan_version"),
    "farm-plan-program-recompute": Route("farm", ("post",), kind="plan_version"),
    "farm-observation-list": Route("farm", ("get", "post")),
    "farm-observation-detail": Route("farm", ("get",), kind="observation"),
    "farm-task-list": Route("farm", ("get", "post")),
    "farm-task-detail": Route("farm", ("get", "patch"), kind="task"),
    "farm-task-generate": Route("farm", ("post",)),
    "farm-task-status": Route("farm", ("post",), kind="task"),
    "farm-task-assign": Route("farm", ("post",), kind="task"),
    "farm-task-history": Route("farm", ("get",), kind="task"),
    "farm-task-mine": Route("farm", ("get",)),
    "farm-task-report-list": Route("farm", ("get", "post")),
    "farm-task-report-detail": Route("farm", ("get",), kind="task_report"),
    "farm-team-list": Route("farm", ("get", "post")),
    "farm-team-detail": Route("farm", ("get",), kind="team"),
    "farm-treasury-account-list": Route("farm", ("get", "post")),
    "farm-treasury-account-detail": Route("farm", ("get", "patch"), kind="treasury_account"),
    "farm-treasury-account-balances": Route("farm", ("get",)),
    "farm-treasury-account-opening": Route("farm", ("post",)),
    "farm-treasury-account-mine": Route("farm", ("post",)),
    "farm-treasury-account-members": Route("farm", ("get",)),
    "farm-treasury-account-set-main": Route("farm", ("post",), kind="treasury_account"),
    "farm-loan-list": Route("farm", ("get", "post")),
    "farm-loan-detail": Route("farm", ("get",), kind="loan"),
    "farm-loan-positions": Route("farm", ("get",)),
    "farm-transaction-list": Route("farm", ("get", "post")),
    "farm-transaction-detail": Route("farm", ("get", "patch"), kind="transaction"),
    "farm-transaction-validate": Route("farm", ("post",), kind="transaction"),
    "farm-transaction-reject": Route("farm", ("post",), kind="transaction"),
    "farm-transaction-reverse": Route("farm", ("post",), kind="transaction"),
    "farm-transaction-correct": Route("farm", ("post",), kind="transaction"),
    "farm-transaction-allocate": Route("farm", ("post",), kind="transaction"),
    "farm-transaction-revisions": Route("farm", ("get",), kind="transaction"),
    "farm-transaction-treasury": Route("farm", ("get",)),
    "farm-budget-line-list": Route("farm", ("get", "post")),
    "farm-budget-line-detail": Route("farm", ("get",), kind="budget_line"),
    "farm-budget-line-from-quote": Route("farm", ("post",)),
    "farm-budget-line-report": Route("farm", ("get",)),
    "org-finance-category-list": Route("org", ("get", "post")),
    "org-finance-category-detail": Route("org", ("get",), kind="finance_category"),
    "farm-unit-conversion-list": Route("farm", ("get", "post")),
    "farm-harvest-list": Route("farm", ("get", "post")),
    "farm-harvest-detail": Route("farm", ("get",), kind="harvest_record"),
    "farm-harvest-void": Route("farm", ("post",), kind="harvest_record"),
    "farm-harvest-results-detail": Route("farm", ("get",), kind="crop_cycle"),
    "farm-harvest-results-campaign": Route("farm", ("get",)),
    "ai-status": Route("user", ("get",)),
    "org-ai-extraction-list": Route("org", ("get", "post")),
    "org-ai-extraction-detail": Route("org", ("get",), kind="ai_extraction"),
    "farm-ai-plan-draft-list": Route("farm", ("get", "post")),
    "farm-ai-plan-draft-detail": Route("farm", ("get",), kind="ai_plan_draft"),
    "farm-ai-suggestion-detail": Route("farm", ("get",), kind="ai_suggestion"),
    "farm-ai-suggestion-decide": Route("farm", ("post",), kind="ai_suggestion"),
}


def _collect(patterns, prefix=""):
    for entry in patterns:
        if isinstance(entry, URLResolver):
            yield from _collect(entry.url_patterns, prefix + str(entry.pattern))
        elif isinstance(entry, URLPattern):
            yield prefix + str(entry.pattern), entry.name


def api_route_names() -> set[str]:
    names = set()
    for route, name in _collect(get_resolver().url_patterns):
        if route.startswith("api/v1/") and name:
            names.add(name)
    return names


def test_every_route_is_declared():
    undeclared = api_route_names() - set(ROUTES)
    assert not undeclared, f"Routes sans politique de tenant : {sorted(undeclared)}"
    stale = set(ROUTES) - api_route_names()
    assert not stale, f"Routes déclarées mais absentes : {sorted(stale)}"


def _objects_of_org_a(world: World) -> dict[str, object]:
    variety = make_variety(world.org_a)
    invitation = Invitation.objects.create(
        organization=world.org_a,
        email="i@example.test",
        token_hash="x" * 64,
        expires_at="2099-01-01T00:00:00Z",
        invited_by=world.admin_a,
    )
    return {
        "organization": world.org_a,
        "role": Role.objects.get(organization=world.org_a, code="worker"),
        "org_member": OrganizationMembership.objects.get(
            organization=world.org_a, user=world.worker_a1
        ),
        "invitation": invitation,
        "farm_member": FarmMembership.objects.get(farm=world.farm_a1, user=world.worker_a1),
        "field": make_field(world.farm_a1),
        "parcel": make_parcel(world.farm_a1),
        "conflict": SyncConflict.objects.create(
            id=uuid.uuid4(),
            organization_id=world.org_a.id,
            farm=world.farm_a1,
            raised_for=world.manager_a1,
            entity_type="fields.parcel",
            entity_id=uuid.uuid4(),
            conflict_type="field_conflict",
        ),
        "org_file": make_sheet(world.org_a, world.admin_a),
        "farm_file": _farm_receipt(world),
        "crop": variety.crop,
        "variety": variety,
        "data_set": make_data_set(variety),
        **_plan_objects(world, variety),
    }


def _plan_objects(world: World, variety) -> dict[str, object]:
    import datetime

    from apps.farms.access import resolve_farm_context
    from apps.production_plans import services as plans
    from apps.production_plans.models import CropCycle

    ctx = resolve_farm_context(world.admin_a, world.farm_a1.id)
    campaign = plans.create_campaign(
        ctx,
        data={
            "name": "C",
            "start_date": datetime.date(2026, 1, 1),
            "end_date": datetime.date(2026, 2, 1),
        },
    )
    plan = plans.create_plan(ctx, campaign_id=campaign.id, variety_id=variety.id, name="P")
    version = plan.versions.get()
    cycle = CropCycle.objects.create(
        organization=world.org_a,
        farm=world.farm_a1,
        plan=plan,
        plan_version=version,
        parcel=make_parcel(world.farm_a1),
        area_m2=10,
        start_date=datetime.date(2026, 1, 1),
        end_date=datetime.date(2026, 1, 2),
    )
    from apps.inventory.models import CatalogItem, PriceList, Supplier
    from apps.irrigation.models import IrrigationDesign, Quote

    supplier = Supplier.objects.create(organization=world.org_a, name="S")
    design = IrrigationDesign.objects.create(
        organization=world.org_a,
        farm=world.farm_a1,
        parcel=cycle.parcel,
        name="D",
        number=1,
        system_type="drip",
    )
    return {
        "campaign": campaign,
        "plan": plan,
        "plan_version": version,
        "crop_cycle": cycle,
        "supplier": supplier,
        "catalog_item": CatalogItem.objects.create(
            organization=world.org_a, category="valve", name="V", base_unit="piece"
        ),
        "price_list": PriceList.objects.create(
            organization=world.org_a,
            supplier=supplier,
            name="T",
            currency="XAF",
            valid_from=datetime.date(2026, 1, 1),
        ),
        "design": design,
        "quote": Quote.objects.create(
            organization=world.org_a, farm=world.farm_a1, design=design, number=1, currency="XAF"
        ),
        **_task_objects(world, cycle),
        "harvest_record": _harvest(world, cycle),
        **_ai_objects(world, version),
    }


def _ai_objects(world: World, version) -> dict[str, object]:
    from apps.ai_assistant.models import AIRun, AISuggestion

    def run(kind, farm=None):
        return AIRun.objects.create(
            organization=world.org_a,
            farm=farm,
            kind=kind,
            provider="fake",
            prompt_version="t",
            schema_version="t",
            requested_by=world.admin_a,
        )

    draft_run = run("plan_draft", world.farm_a1)
    return {
        "ai_extraction": run("extraction"),
        "ai_plan_draft": draft_run,
        "ai_suggestion": AISuggestion.objects.create(
            run=draft_run, plan_version=version, field_path="planting_spec.row_spacing_m"
        ),
    }


def _harvest(world: World, cycle):
    import datetime

    from apps.harvest.models import HarvestRecord

    return HarvestRecord.objects.create(
        organization=world.org_a,
        farm=world.farm_a1,
        crop_cycle=cycle,
        parcel=cycle.parcel,
        harvested_on=datetime.date(2026, 1, 2),
        quantity=1,
        unit="kg",
        quantity_kg=1,
        conversion_factor_used=1,
        quality_grade="grade_1",
        responsible=world.admin_a,
    )


def _task_objects(world: World, cycle) -> dict[str, object]:
    import datetime

    from apps.agronomy.models import InputProduct, Observation
    from apps.tasks.models import Task, TaskReport, Team

    task = Task.objects.create(
        organization=world.org_a,
        farm=world.farm_a1,
        task_type="other",
        title="T",
        planned_start_date=datetime.date(2026, 1, 1),
        planned_end_date=datetime.date(2026, 1, 2),
    )
    return {
        "input_product": InputProduct.objects.create(
            organization=world.org_a, kind="fertilizer", name="F"
        ),
        "observation": Observation.objects.create(
            organization=world.org_a,
            farm=world.farm_a1,
            parcel=cycle.parcel,
            observed_at="2026-01-01T00:00:00Z",
            kind="pest",
            author=world.admin_a,
        ),
        "task": task,
        "task_report": TaskReport.objects.create(
            organization=world.org_a,
            farm=world.farm_a1,
            task=task,
            reported_by=world.admin_a,
            actual_start="2026-01-01T00:00:00Z",
            completion="partial",
        ),
        "team": Team.objects.create(organization=world.org_a, farm=world.farm_a1, name="E"),
        **_finance_objects(world),
    }


def _finance_objects(world: World) -> dict[str, object]:
    from apps.farms.access import resolve_farm_context
    from apps.finance import services as finance
    from apps.finance.models import BudgetLine, FinanceCategory, TreasuryAccount

    category = FinanceCategory.objects.create(
        organization=world.org_a, kind="expense", code="c", name="C"
    )
    account = TreasuryAccount.objects.create(
        organization=world.org_a, farm=world.farm_a1, name="Caisse", kind="cash", currency="XAF"
    )
    ctx = resolve_farm_context(world.admin_a, world.farm_a1.id)
    tx, _ = finance.record_transaction(
        ctx,
        data={
            "kind": "expense",
            "business_date": datetime_today(),
            "amount": Decimal(1000),
            "account": account,
            "category": category,
            "idempotency_key": uuid.uuid4(),
        },
    )
    loan = finance.create_loan(
        ctx,
        data={
            "lender": "Banque fictive",
            "principal": Decimal(100000),
            "currency": "XAF",
            "started_on": datetime_today(),
        },
    )
    return {
        "finance_category": category,
        "treasury_account": account,
        "transaction": tx,
        "loan": loan,
        "budget_line": BudgetLine.objects.create(
            organization=world.org_a,
            farm=world.farm_a1,
            category=category,
            label="B",
            planned_amount=10,
            currency="XAF",
        ),
    }


def datetime_today():
    from django.utils import timezone

    return timezone.localdate()


def _farm_receipt(world: World):
    import io

    from apps.farms.access import resolve_farm_context
    from apps.files.services import upload_file

    stored, _ = upload_file(
        resolve_farm_context(world.admin_a, world.farm_a1.id),
        stream=io.BytesIO(PDF_BYTES),
        original_name="recu.pdf",
        purpose="receipt",
    )
    return stored


def _url(name: str, route: Route, world: World, objects: dict, farm=None) -> str:
    kwargs: dict[str, object] = {}
    if route.scope == "org":
        if name == "organization-detail":
            kwargs["pk"] = world.org_a.id
        else:
            kwargs["organization_id"] = world.org_a.id
    if route.scope == "farm":
        kwargs["farm_id"] = (farm or world.farm_a1).id
    if route.kind and name != "organization-detail":
        kwargs["pk"] = objects[route.kind].pk
    return reverse(name, kwargs=kwargs)


def _call(client, method: str, url: str):
    return getattr(client, method)(url, {}, format="json", HTTP_IF_MATCH="1")


SCOPED = [(n, r) for n, r in ROUTES.items() if r.scope in {"org", "farm"}]


@pytest.mark.parametrize("name,route", SCOPED, ids=[n for n, _ in SCOPED])
def test_other_organization_gets_404_on_every_method(world, client_for, name, route):
    objects = _objects_of_org_a(world)
    url = _url(name, route, world, objects)
    intruder = client_for(world.admin_b)
    for method in route.methods:
        response = _call(intruder, method, url)
        assert response.status_code == 404, (method, url, response.status_code)


FARM_SCOPED = [(n, r) for n, r in ROUTES.items() if r.scope == "farm"]


@pytest.mark.parametrize("name,route", FARM_SCOPED, ids=[n for n, _ in FARM_SCOPED])
def test_same_org_user_without_farm_membership_gets_404(world, client_for, name, route):
    objects = _objects_of_org_a(world)
    # manager_a1 has no membership on farm A2; objects of A1 accessed through A2's URL
    # must not resolve either.
    url = _url(name, route, world, objects, farm=world.farm_a2)
    for user in (world.manager_a1, world.outsider):
        client = client_for(user)
        for method in route.methods:
            response = _call(client, method, url)
            assert response.status_code == 404, (user, method, url, response.status_code)


def test_object_of_farm_a1_is_not_reachable_through_farm_a2_url(world, client_for):
    parcel = make_parcel(world.farm_a1)
    client = client_for(world.admin_a)  # admin of both farms
    url = reverse("farm-parcel-detail", kwargs={"farm_id": world.farm_a2.id, "pk": parcel.id})
    assert client.get(url).status_code == 404
    assert client.patch(url, {"name": "x"}, format="json", HTTP_IF_MATCH="1").status_code == 404
    assert client.delete(url, HTTP_IF_MATCH="1").status_code == 404


NON_PUBLIC = [(n, r) for n, r in ROUTES.items() if r.scope != "public"]


@pytest.mark.parametrize("name,route", NON_PUBLIC, ids=[n for n, _ in NON_PUBLIC])
def test_anonymous_gets_401(world, api, name, route):
    objects = {**_objects_of_org_a(world), "device": None}
    if route.kind == "device":
        from apps.users.models import Device

        objects["device"] = Device.objects.create(user=world.admin_a)
    url = _url(name, route, world, objects)
    for method in route.methods:
        assert _call(api, method, url).status_code == 401, (method, url)


def test_listings_never_expose_other_tenant_ids(world, client_for):
    make_parcel(world.farm_b1)
    client = client_for(world.admin_a)
    payloads = [
        client.get("/api/v1/farms/").content,
        client.get("/api/v1/organizations/").content,
        client.get("/api/v1/me/").content,
        client.get(f"/api/v1/farms/{world.farm_a1.id}/parcels/").content,
        client.get(f"/api/v1/organizations/{world.org_a.id}/members/").content,
    ]
    forbidden = [str(world.org_b.id), str(world.farm_b1.id), str(world.admin_b.id)]
    for payload in payloads:
        for identifier in forbidden:
            assert identifier.encode() not in payload


def test_role_without_permission_gets_403_inside_own_farm(world, client_for):
    finance = client_for(world.finance_a1)  # finance manager: no fields.view
    assert finance.get(f"/api/v1/farms/{world.farm_a1.id}/parcels/").status_code == 403
    worker = client_for(world.worker_a1)
    assert worker.get(f"/api/v1/farms/{world.farm_a1.id}/members/").status_code == 403
