"""End-to-end MVP scenario through the public API (REQUIREMENTS.md §15, criteria 1 to 20).

A farm manager creates an organization and farms, registers a variety from a technical
sheet extracted by the AI (fake deterministic provider), validates the data, gets an AI
plan draft, completes and validates it, sizes the irrigation and quotes it, generates
tasks, and field users work OFFLINE (sync push) on tasks, expenses and harvests.
Values are fictitious test data.
"""

import io
import uuid
from decimal import Decimal as D

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.ai_assistant import services as ai_services
from apps.ai_assistant.providers import LLMResponse, LLMUsage
from apps.ai_assistant.tests.test_ai import make_text_pdf
from apps.audit.models import AuditEvent
from apps.finance.models import FinancialTransaction
from apps.users.models import User

pytestmark = pytest.mark.django_db

PASSWORD = "Mvp-scenario-passw0rd"
TODAY = timezone.localdate().isoformat()


class ScriptedProvider:
    """Deterministic stand-in for the AI provider: answers per request kind."""

    name, model = "fake", "claude-opus-5-5"

    def generate_json(self, request):
        if "fiche" in request.text:
            data = {
                "items": [
                    {
                        "key": k,
                        "value": v,
                        "value_min": None,
                        "value_max": None,
                        "value_text": None,
                        "unit": u,
                        "page": 1,
                        "quote": q,
                        "confidence": "0.9",
                    }
                    for k, v, u, q in [
                        ("row_spacing", "1.5", "m", "Ecartement entre rangs : 1,5 m"),
                        ("plant_spacing", "0.5", "m", "Ecartement sur le rang : 0,5 m"),
                        ("germination_rate", "0.8", "ratio", "Germination : 80 %"),
                        ("seeds_per_gram", "25", "count/g", "25 graines par gramme"),
                        ("phase.sowing.duration_days", "1", "days", "Semis : 1 jour"),
                        ("phase.vegetative.duration_days", "30", "days", "Vegetation : 30 jours"),
                        ("phase.harvest.duration_days", "20", "days", "Recolte : 20 jours"),
                    ]
                ],
                "missing": ["thousand_seed_weight"],
                "notes": "",
            }
        else:
            planting = [
                ("row_spacing_m", "1.5", "document", "row_spacing"),
                ("plant_spacing_m", "0.5", "document", "plant_spacing"),
                ("germination_rate", "0.8", "document", "germination_rate"),
                ("seeds_per_gram", "25", "document", "seeds_per_gram"),
                ("plants_per_hole", "1", "ai_suggestion", None),
                ("seeds_per_hole", "2", "ai_suggestion", None),
                ("planting_method", "direct_seeding", "ai_suggestion", None),
            ]
            data = {
                "planting": [
                    {"field": f, "value": v, "source": s, "technical_key": k, "rationale": "test"}
                    for f, v, s, k in planting
                ],
                "phases": [
                    {
                        "phase_code": c,
                        "duration_days": d,
                        "source": "document",
                        "technical_key": f"phase.{c}.duration_days",
                        "rationale": "",
                    }
                    for c, d in (("sowing", 1), ("vegetative", 30), ("harvest", 20))
                ],
                "missing_info": [
                    {"field": "safety_margin_rate", "question": "Quelle marge de sécurité ?"}
                ],
                "remarks": "",
            }
        return LLMResponse(
            data=data, usage=LLMUsage(model=self.model, input_tokens=800, output_tokens=400)
        )


def login(identifier: str) -> APIClient:
    client = APIClient()
    tokens = client.post(
        "/api/v1/auth/login/", {"identifier": identifier, "password": PASSWORD}, format="json"
    )
    assert tokens.status_code == 200, tokens.json()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens.json()['access']}")
    return client


def ok(response, status=(200, 201)):
    assert response.status_code in ((status,) if isinstance(status, int) else status), (
        response.status_code,
        response.content[:500],
    )
    return response.json() if response.content else None


def push(client, farm_id, *operations):
    body = {
        "operations": [{"op_id": str(uuid.uuid4()), "farm_id": farm_id, **op} for op in operations]
    }
    return ok(client.post("/api/v1/sync/push/", body, format="json"))["results"]


def test_mvp_scenario(monkeypatch):
    monkeypatch.setattr(ai_services, "get_provider", lambda: ScriptedProvider())
    for email in ("manager@a.test", "manager@b.test"):
        User.objects.create_user(email, PASSWORD, full_name=email)
    manager = login("manager@a.test")
    other = login("manager@b.test")

    # 1-2. Two organizations; organization A manages two farms.
    org_payload = {
        "country": "CG",
        "default_currency": "XAF",
        "default_timezone": "Africa/Brazzaville",
    }
    org = ok(
        manager.post("/api/v1/organizations/", {"name": "Coop A", **org_payload}, format="json")
    )
    org_b = ok(
        other.post("/api/v1/organizations/", {"name": "Coop B", **org_payload}, format="json")
    )
    farm_payload = {"country": "CG", "timezone": "Africa/Brazzaville", "currency": "XAF"}
    farm = ok(
        manager.post(
            f"/api/v1/organizations/{org['id']}/farms/",
            {"name": "Ferme Nord", "code": "nord", **farm_payload},
            format="json",
        )
    )
    farm2 = ok(
        manager.post(
            f"/api/v1/organizations/{org['id']}/farms/",
            {"name": "Ferme Sud", "code": "sud", **farm_payload},
            format="json",
        )
    )
    F = f"/api/v1/farms/{farm['id']}"
    ORG = f"/api/v1/organizations/{org['id']}"

    # 3. A field worker invited with a phone number gets roles on both farms.
    roles = {r["code"]: r["id"] for r in ok(manager.get(f"{ORG}/roles/"))["results"]}
    invite = ok(
        manager.post(
            f"{ORG}/invitations/",
            {"phone": "+242060000001", "farm": farm["id"], "role": roles["worker"]},
            format="json",
        )
    )
    ok(
        APIClient().post(
            "/api/v1/invitations/accept/",
            {"token": invite["token"], "full_name": "Ouvrier", "password": PASSWORD},
            format="json",
        )
    )
    worker_user = User.objects.get(phone="+242060000001")
    ok(
        manager.post(
            f"/api/v1/farms/{farm2['id']}/members/",
            {"user": str(worker_user.id), "role": roles["technician"]},
            format="json",
        )
    )
    worker = login("+242060000001")
    assert {f["id"] for f in ok(worker.get("/api/v1/me/"))["farms"]} == {farm["id"], farm2["id"]}

    # 4. Parcel created and configured.
    parcel = ok(
        manager.post(
            f"{F}/parcels/",
            {
                "name": "Parcelle 1",
                "code": "P1",
                "area_m2": "1000",
                "length_m": "50",
                "width_m": "20",
                "soil_ph": "6.2",
            },
            format="json",
        )
    )

    # 5-6. Variety with its technical sheet; AI extraction into a DRAFT, human validation.
    crop = ok(
        manager.post(
            f"{ORG}/crops/", {"common_name": "Pastèque", "category": "fruit"}, format="json"
        )
    )
    variety = ok(
        manager.post(
            f"{ORG}/varieties/",
            {"crop": crop["id"], "name": "Variété A", "seed_company": "Semencier"},
            format="json",
        )
    )
    pdf = make_text_pdf(
        [
            "Ecartement entre rangs : 1,5 m",
            "Ecartement sur le rang : 0,5 m",
            "Germination : 80 %",
            "25 graines par gramme",
            "Semis : 1 jour",
            "Vegetation : 30 jours",
            "Recolte : 20 jours",
        ]
    )
    sheet = ok(
        manager.post(
            f"{ORG}/files/",
            {"purpose": "technical_sheet", "file": io.BytesIO(pdf)},
            format="multipart",
        )
    )
    document = ok(
        manager.post(
            f"{ORG}/varieties/{variety['id']}/documents/",
            {"file": sheet["id"], "supplier": "Semencier"},
            format="json",
        )
    )
    run = ok(manager.post(f"{ORG}/ai/extractions/", {"document": document["id"]}, format="json"))
    data_set = ok(manager.get(f"{ORG}/technical-data-sets/{run['data_set']}/"))
    assert data_set["status"] == "draft"
    assert all(item["provenance"] == "document" for item in data_set["items"])  # quotes verified
    ok(
        manager.post(
            f"{ORG}/technical-data-sets/{data_set['id']}/validate-items/",
            {"keys": [i["key"] for i in data_set["items"]]},
            format="json",
        )
    )
    ok(manager.post(f"{ORG}/technical-data-sets/{data_set['id']}/validate/"))

    # 6-8. AI plan draft, human decisions, completion and validation; planting computed.
    campaign = ok(
        manager.post(
            f"{F}/campaigns/",
            {"name": "Saison 2026", "start_date": TODAY, "end_date": "2027-12-31"},
            format="json",
        )
    )
    draft = ok(
        manager.post(
            f"{F}/ai/plan-drafts/",
            {
                "campaign": campaign["id"],
                "variety": variety["id"],
                "parcel": parcel["id"],
                "allocated_area_m2": "1000",
                "non_plantable_area_m2": "0",
                "planned_start_date": TODAY,
            },
            format="json",
        )
    )
    version_id = draft["plan_version"]
    for suggestion in draft["suggestions"]:
        ok(
            manager.post(
                f"{F}/ai/suggestions/{suggestion['id']}/decide/",
                {"decision": "accept"},
                format="json",
            )
        )
    version = ok(manager.get(f"{F}/plan-versions/{version_id}/"))
    version = ok(
        manager.patch(
            f"{F}/plan-versions/{version_id}/planting-spec/",
            {"safety_margin_rate": "0.1"},
            format="json",
            HTTP_IF_MATCH=str(version["version"]),
        )
    )
    product = ok(
        manager.post(
            f"{ORG}/input-products/",
            {"kind": "fertilizer", "name": "Urée", "composition": {"N": 46}},
            format="json",
        )
    )
    ok(
        manager.post(
            f"{F}/plan-programs/{version_id}/fertilizations/",
            {
                "product": product["id"],
                "phase_code": "vegetative",
                "day_offset": 5,
                "mode": "nutrient_target",
                "target_nutrient": "N",
                "nutrient_dose_kg_per_ha": "100",
                "source_kind": "user_input",
            },
            format="json",
            HTTP_IF_MATCH=str(version["version"]),
        )
    )
    computed = ok(manager.post(f"{F}/plan-versions/{version_id}/compute/"))
    # No plot dimensions on the allocation: theoretical count floor(1000 / (1.5 × 0.5)).
    assert computed["complete"] and computed["totals"]["plant_count"] == 1333
    version = ok(manager.get(f"{F}/plan-versions/{version_id}/"))
    validated = ok(
        manager.post(
            f"{F}/plan-versions/{version_id}/validate/", HTTP_IF_MATCH=str(version["version"])
        )
    )
    assert validated["status"] == "validated"

    # 9. Irrigation sizing, BOM and quote.
    design = ok(
        manager.post(
            f"{F}/irrigation-designs/",
            {
                "parcel": parcel["id"],
                "plan_version": version_id,
                "name": "Goutte-à-goutte",
                "system_type": "drip",
                "parameters": {
                    "lateral_count": 14,
                    "lateral_length_m": "50",
                    "lateral_spacing_m": "1.5",
                    "emitter_spacing_m": "0.3",
                    "emitter_flow_lph": "2",
                    "operating_pressure_bar": "1",
                    "source_max_flow_m3h": "2.5",
                },
                "bom_parameters": {"installation_waste_rate": "0.05"},
            },
            format="json",
        )
    )
    assert ok(manager.post(f"{F}/irrigation-designs/{design['id']}/compute/"))["complete"]
    quote = ok(manager.post(f"{F}/quotes/", {"design": design["id"]}, format="json"))
    line = quote["lines"][0]
    quote = ok(
        manager.patch(
            f"{F}/quotes/{quote['id']}/",
            {"lines": [{"id": line["id"], "unit_price": "100"}]},
            format="json",
            HTTP_IF_MATCH=str(quote["version"]),
        )
    )
    quote = ok(
        manager.post(f"{F}/quotes/{quote['id']}/issue/", HTTP_IF_MATCH=str(quote["version"]))
    )
    assert D(quote["total"]) > 0

    # 10. Tasks generated from the validated plan only.
    summary = ok(manager.post(f"{F}/tasks/generate/", {"plan_version": version_id}, format="json"))
    assert summary["created"] == 3  # sowing, harvest, fertilization
    tasks = {t["source_ref"]: t for t in ok(worker.get(f"{F}/tasks/"))["results"]}

    # 11 + 16. The worker reports OFFLINE (sync push), with input consumption.
    sowing = tasks["phase:sowing"]
    results = push(
        worker,
        farm["id"],
        {
            "op_type": "command",
            "command": "task.change_status",
            "entity_type": "tasks.task",
            "entity_id": sowing["id"],
            "payload": {"from": "todo", "to": "in_progress"},
        },
        {
            "op_type": "create",
            "entity_type": "tasks.task_report",
            "entity_id": str(uuid.uuid4()),
            "payload": {
                "task": tasks["fertilization:1"]["id"],
                "actual_start": timezone.now().isoformat(),
                "completion": "complete",
                "consumptions": [{"product": product["id"], "quantity": "21", "unit": "kg"}],
            },
        },
    )
    assert [r["status"] for r in results] == ["applied", "applied"]

    # 12-13 + 16-17. Treasury: expense recorded offline and replayed, income, balance.
    account = ok(
        manager.post(
            f"{F}/treasury-accounts/",
            {"name": "Caisse", "kind": "cash", "currency": "XAF"},
            format="json",
        )
    )
    spend = ok(
        manager.post(
            f"{ORG}/finance-categories/",
            {"kind": "expense", "code": "intrants", "name": "Intrants"},
            format="json",
        )
    )
    sell = ok(
        manager.post(
            f"{ORG}/finance-categories/",
            {"kind": "income", "code": "ventes", "name": "Ventes"},
            format="json",
        )
    )
    expense_id = str(uuid.uuid4())
    expense_op = {
        "op_type": "create",
        "entity_type": "finance.transaction",
        "entity_id": expense_id,
        "payload": {
            "kind": "expense",
            "business_date": TODAY,
            "amount": "45000",
            "account": account["id"],
            "category": spend["id"],
            "currency": "XAF",
            "plan": validated["plan"],
        },
    }
    op_id = str(uuid.uuid4())
    for _ in range(2):  # same op re-sent (lost response): applied once
        results = ok(
            manager.post(
                "/api/v1/sync/push/",
                {"operations": [{"op_id": op_id, "farm_id": farm["id"], **expense_op}]},
                format="json",
            )
        )["results"]
        assert results[0]["status"] == "applied"
    assert FinancialTransaction.objects.filter(id=expense_id).count() == 1
    ok(
        manager.post(
            f"{F}/transactions/",
            {
                "kind": "income",
                "business_date": TODAY,
                "amount": "120000",
                "account": account["id"],
                "category": sell["id"],
                "plan": validated["plan"],
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
    )
    balances = {
        b["name"]: D(b["balance"]) for b in ok(manager.get(f"{F}/treasury-accounts/balances/"))
    }
    assert balances["Caisse"] == D(75000)

    # 14. Budget from the irrigation quote vs actual through an explicit allocation.
    budget = ok(
        manager.post(
            f"{F}/budget-lines/from-quote/",
            {"quote": quote["id"], "category": spend["id"]},
            format="json",
        )
    )
    ok(
        manager.post(
            f"{F}/transactions/{expense_id}/allocate/",
            {"budget_line": budget["id"], "amount": "45000"},
            format="json",
        )
    )
    report = ok(manager.get(f"{F}/budget-lines/report/"))[0]
    assert D(report["actual"]) == D(45000)

    # 15 + 16. Harvest recorded offline, yields computed.
    cycle = ok(manager.get(f"{F}/crop-cycles/"))["results"][0]
    results = push(
        worker,
        farm["id"],
        {
            "op_type": "create",
            "entity_type": "harvest.harvest_record",
            "entity_id": str(uuid.uuid4()),
            "payload": {
                "crop_cycle": cycle["id"],
                "harvested_on": TODAY,
                "quantity": "1500",
                "unit": "kg",
                "quality_grade": "grade_1",
            },
        },
    )
    assert results[0]["status"] == "applied"
    outcome = ok(manager.get(f"{F}/harvest-results/{cycle['id']}/"))
    assert outcome["yield"]["outputs"]["gross_yield_kg_per_ha"]["value"] == "15000.00"
    assert D(outcome["finance"]["margin"]) == D(75000)

    # 18. Concurrent edits of the same parcel field are detected as a conflict.
    base = {
        "op_type": "update",
        "entity_type": "fields.parcel",
        "entity_id": parcel["id"],
        "base_version": 1,
        "base_values": {"name": "Parcelle 1"},
    }
    assert (
        push(manager, farm["id"], {**base, "payload": {"name": "Nord-Est"}})[0]["status"]
        == "applied"
    )
    assert (
        push(manager, farm["id"], {**base, "payload": {"name": "Nord-Ouest"}})[0]["status"]
        == "conflict"
    )

    # 19. Financial traceability: reversal instead of deletion, audit trail.
    ok(
        manager.post(
            f"{F}/transactions/{expense_id}/reverse/", {"reason": "Erreur de saisie"}, format="json"
        )
    )
    assert FinancialTransaction.objects.get(id=expense_id).status == "reversed"
    assert AuditEvent.objects.filter(action="transaction.reversed", entity_id=expense_id).exists()

    # 1 + 20. The other organization sees none of it.
    for path in (
        f"{F}/parcels/",
        f"{F}/transactions/",
        f"{ORG}/varieties/",
        f"{F}/harvest-results/{cycle['id']}/",
        f"/api/v1/organizations/{org['id']}/",
    ):
        assert other.get(path).status_code == 404, path
    assert other.get("/api/v1/sync/pull/", {"farm_id": farm["id"]}).status_code == 404
    leaked = other.get(f"/api/v1/organizations/{org_b['id']}/varieties/").content
    assert variety["id"].encode() not in leaked
