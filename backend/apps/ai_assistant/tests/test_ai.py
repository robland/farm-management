"""AI assistant tests with a deterministic fake provider. No real AI call is made."""

import io
from decimal import Decimal as D

import pytest

from apps.ai_assistant import services
from apps.ai_assistant.models import AIRequestLog, AIRun, AISuggestion
from apps.ai_assistant.providers import LLMResponse, LLMUsage, ProviderError
from apps.farms.access import resolve_farm_context
from apps.files.models import StoredFile
from apps.files.services import upload_file
from apps.organizations.access import resolve_org_context
from apps.production_plans import services as plans
from apps.production_plans.models import FieldProvenance, PlanVersion
from apps.varieties.models import TechnicalDataItem, TechnicalDocument
from tests.factories import make_parcel
from tests.factories_catalog import make_variety
from tests.factories_plans import make_validated_variety

pytestmark = pytest.mark.django_db


def make_text_pdf(lines: list[str]) -> bytes:
    """Build a one-page PDF containing the given text lines (valid xref table)."""
    stream = "BT /F1 12 Tf 50 750 Td 14 TL " + " ".join(f"({line}) Tj T*" for line in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


class FakeProvider:
    name = "fake"
    model = "claude-opus-5-5"

    def __init__(self, data=None, error=None):
        self.data, self.error, self.requests = data, error, []

    def generate_json(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return LLMResponse(
            data=self.data,
            usage=LLMUsage(model=self.model, input_tokens=1000, output_tokens=500, latency_ms=12),
        )


@pytest.fixture
def use_provider(monkeypatch):
    def _install(provider):
        monkeypatch.setattr(services, "get_provider", lambda: provider)
        return provider

    return _install


def org_url(world, path):
    return f"/api/v1/organizations/{world.org_a.id}/{path}"


def farm_url(world, path):
    return f"/api/v1/farms/{world.farm_a1.id}/{path}"


@pytest.fixture
def sheet(world):
    variety = make_variety(world.org_a, name="Pastèque test")
    pdf = make_text_pdf(
        ["Fiche technique variete test", "Ecartement entre rangs : 1,5 m", "Cycle : 75 jours"]
    )
    stored, _ = upload_file(
        resolve_org_context(world.admin_a, world.org_a.id),
        stream=io.BytesIO(pdf),
        original_name="fiche.pdf",
        purpose=StoredFile.Purpose.TECHNICAL_SHEET,
    )
    return TechnicalDocument.objects.create(organization=world.org_a, variety=variety, file=stored)


def extraction_item(key, value=None, page=1, quote="", **extra):
    base = {
        "key": key,
        "value": value,
        "value_min": None,
        "value_max": None,
        "value_text": None,
        "unit": "",
        "page": page,
        "quote": quote,
        "confidence": "0.9",
    }
    return {**base, **extra}


EXTRACTION_OUTPUT = {
    "items": [
        extraction_item("row_spacing", "1.5", quote="Ecartement entre rangs : 1,5 m", unit="m"),
        # Quote not present in the document: cannot be classified as documentary.
        extraction_item("plant_spacing", "0.5", quote="Espacement sur le rang 50 cm", unit="m"),
        extraction_item("cycle_duration", "75", quote="cycle : 75 jours", unit="days"),
        extraction_item("unknown_magic_key", "3"),
        extraction_item("germination_rate", "85", quote="x", unit="ratio"),  # out of range
    ],
    "missing": ["seeds_per_gram"],
    "notes": "",
}


def test_without_provider_the_assistant_is_unavailable_and_manual_mode_works(
    world, client_for, sheet
):
    client = client_for(world.admin_a)
    assert client.get("/api/v1/ai/status/").json()["available"] is False
    response = client.post(
        org_url(world, "ai/extractions/"), {"document": str(sheet.id)}, format="json"
    )
    assert response.status_code == 503
    assert AIRun.objects.get().status == "unavailable"
    # FR-106: manual creation of a plan remains possible.
    campaign = client.post(
        farm_url(world, "campaigns/"),
        {"name": "C", "start_date": "2026-01-01", "end_date": "2026-06-30"},
        format="json",
    ).json()
    plan = client.post(
        farm_url(world, "plans/"),
        {"campaign": campaign["id"], "variety": str(sheet.variety_id), "name": "Manuel"},
        format="json",
    )
    assert plan.status_code == 201


def test_extraction_creates_a_draft_with_verified_citations(world, client_for, sheet, use_provider):
    provider = use_provider(FakeProvider(EXTRACTION_OUTPUT))
    response = client_for(world.admin_a).post(
        org_url(world, "ai/extractions/"), {"document": str(sheet.id)}, format="json"
    )
    assert response.status_code == 201, response.json()
    run = response.json()
    assert run["status"] == "succeeded"
    assert provider.requests[0].documents[0].media_type == "application/pdf"
    items = {i.key: i for i in TechnicalDataItem.objects.filter(data_set_id=run["data_set"])}
    assert set(items) == {"row_spacing", "plant_spacing", "cycle_duration"}
    assert items["row_spacing"].provenance == "document"  # quote found on page 1
    assert items["cycle_duration"].provenance == "document"  # case-insensitive match
    assert items["plant_spacing"].provenance == "ai_extraction"  # unverifiable quote
    assert not any(i.validated for i in items.values())  # FR-023: human validation needed
    assert {r["item"]["key"] for r in run["rejected_items"]} == {
        "unknown_magic_key",
        "germination_rate",
    }
    assert run["missing_info"] == [{"field": "seeds_per_gram", "question": "Absent de la fiche"}]
    sheet.refresh_from_db()
    assert sheet.status == "extracted"
    log = AIRequestLog.objects.get()
    # 1000 × 4 / 1e6 + 500 × 20 / 1e6 = 0.014 USD (FR-107)
    assert log.estimated_cost == D("0.014") and log.status == "ok"
    assert run["usage"][0]["input_tokens"] == 1000


def test_non_conforming_output_is_rejected(world, client_for, sheet, use_provider):
    use_provider(FakeProvider({"items": "not a list"}))
    response = client_for(world.admin_a).post(
        org_url(world, "ai/extractions/"), {"document": str(sheet.id)}, format="json"
    )
    assert response.status_code == 502
    assert AIRun.objects.get().error_code == "schema_mismatch"
    assert AIRequestLog.objects.get().status == "invalid_output"
    assert not TechnicalDataItem.objects.exists()


def test_provider_errors_are_logged(world, client_for, sheet, use_provider):
    use_provider(
        FakeProvider(
            error=ProviderError(
                "refusal", "Refus", usage=LLMUsage(model="claude-opus-5-5", input_tokens=10)
            )
        )
    )
    response = client_for(world.admin_a).post(
        org_url(world, "ai/extractions/"), {"document": str(sheet.id)}, format="json"
    )
    assert response.status_code == 502
    log = AIRequestLog.objects.get()
    assert (log.status, log.error_code, log.input_tokens) == ("error", "refusal", 10)


def test_monthly_quota(world, client_for, sheet, use_provider, settings):
    settings.FMS_AI_MONTHLY_REQUEST_LIMIT = 1
    use_provider(FakeProvider(EXTRACTION_OUTPUT))
    client = client_for(world.admin_a)
    assert (
        client.post(
            org_url(world, "ai/extractions/"), {"document": str(sheet.id)}, format="json"
        ).status_code
        == 201
    )
    assert (
        client.post(
            org_url(world, "ai/extractions/"), {"document": str(sheet.id)}, format="json"
        ).status_code
        == 429
    )


def test_ai_requires_permission(world, client_for, sheet, use_provider):
    use_provider(FakeProvider(EXTRACTION_OUTPUT))
    response = client_for(world.finance_a1).post(
        org_url(world, "ai/extractions/"), {"document": str(sheet.id)}, format="json"
    )
    assert response.status_code == 403  # finance manager: no ai.use


def planting(field, value, source="ai_suggestion", key=None):
    return {
        "field": field,
        "value": value,
        "source": source,
        "technical_key": key,
        "rationale": "test",
    }


PLAN_OUTPUT = {
    "planting": [
        planting("row_spacing_m", "1.5", "document", "row_spacing"),  # matches validated data
        planting("plant_spacing_m", "0.4", "document", "plant_spacing"),  # 0.5 validated: no
        planting("planting_method", "direct_seeding"),
        planting("plants_per_hole", "1", "document", "plants_per_hole"),
        planting("seeds_per_hole", "2", "document", "seeds_per_hole"),
        planting("germination_rate", "1.4"),  # invalid fraction -> rejected
        planting("seeds_per_gram", "25", "document", "seeds_per_gram"),
        planting("safety_margin_rate", None),  # unknown -> question to the user
    ],
    "phases": [
        {
            "phase_code": "soil_preparation",
            "duration_days": 7,
            "source": "document",
            "technical_key": "phase.soil_preparation.duration_days",
            "rationale": "",
        },
        {
            "phase_code": "sowing",
            "duration_days": 1,
            "source": "ai_suggestion",
            "technical_key": None,
            "rationale": "Semis en une journée",
        },
        {
            "phase_code": "vegetative",
            "duration_days": 30,
            "source": "document",
            "technical_key": "phase.vegetative.duration_days",
            "rationale": "",
        },
    ],
    "missing_info": [{"field": "objectives", "question": "Quel rendement visez-vous ?"}],
    "remarks": "",
}


def test_plan_draft_classifies_sources_and_requires_human_decisions(
    world, client_for, use_provider
):
    use_provider(FakeProvider(PLAN_OUTPUT))
    variety = make_validated_variety(world.org_a, world.admin_a)
    parcel = make_parcel(world.farm_a1, area_m2=D(1000))
    ctx = resolve_farm_context(world.manager_a1, world.farm_a1.id)
    campaign = plans.create_campaign(
        ctx, data={"name": "C", "start_date": "2026-01-01", "end_date": "2026-12-31"}
    )
    client = client_for(world.manager_a1)
    response = client.post(
        farm_url(world, "ai/plan-drafts/"),
        {
            "campaign": str(campaign.id),
            "variety": str(variety.id),
            "parcel": str(parcel.id),
            "allocated_area_m2": "1000",
            "non_plantable_area_m2": "0",
            "planned_start_date": "2026-01-01",
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    run = response.json()
    version = PlanVersion.objects.get(id=run["plan_version"])
    assert version.status == "draft" and version.origin == "ai_draft"  # never auto-validated
    provenance = dict(
        FieldProvenance.objects.filter(plan_version=version).values_list(
            "field_path", "source_kind"
        )
    )
    assert provenance["planting_spec.row_spacing_m"] == "document"
    assert provenance["planting_spec.plant_spacing_m"] == "ai_suggestion"  # downgraded
    assert provenance["planting_spec.planting_method"] == "ai_suggestion"
    assert provenance["phases.soil_preparation.duration_days"] == "document"
    assert provenance["phases.sowing.duration_days"] == "ai_suggestion"
    assert provenance["allocations"] == "user_input"
    assert [r["item"]["field"] for r in run["rejected_items"]] == ["germination_rate"]
    missing_fields = {m["field"] for m in run["missing_info"]}
    assert {"objectives", "planting_spec.safety_margin_rate"} <= missing_fields
    suggested = {s["field_path"]: s for s in run["suggestions"]}
    assert set(suggested) == {
        "planting_spec.plant_spacing_m",
        "planting_spec.planting_method",
        "phases.sowing.duration_days",
    }
    # Deterministic engine results were computed (not by the AI).
    assert version.calculations.filter(calc_type="planting.density").exists()

    # FR-105: validation is blocked while AI suggestions are undecided.
    blocked = client.post(
        farm_url(world, f"plan-versions/{version.id}/validate/"),
        HTTP_IF_MATCH=str(PlanVersion.objects.get(id=version.id).version),
    )
    assert blocked.status_code == 400
    assert blocked.json()["details"]["blocking"]

    def decide(path, decision, value=None):
        body = {"decision": decision, **({"value": value} if value is not None else {})}
        return client.post(
            farm_url(world, f"ai/suggestions/{suggested[path]['id']}/decide/"), body, format="json"
        )

    assert decide("planting_spec.plant_spacing_m", "modify", "0.5").status_code == 200
    assert decide("planting_spec.planting_method", "accept").status_code == 200
    assert decide("phases.sowing.duration_days", "accept").status_code == 200
    assert decide("phases.sowing.duration_days", "reject").status_code == 400  # already decided
    version.refresh_from_db()
    assert version.planting_spec.plant_spacing_m == D("0.5")
    provenance = dict(
        FieldProvenance.objects.filter(plan_version=version).values_list(
            "field_path", "source_kind"
        )
    )
    assert provenance["planting_spec.plant_spacing_m"] == "user_input"
    # The user completes what the AI could not know, then validates explicitly.
    plans.update_planting_spec(
        ctx,
        version_id=version.id,
        expected_version=version.version,
        changes={"germination_rate": D("0.8"), "safety_margin_rate": D("0.1")},
    )
    version.refresh_from_db()
    validated = client.post(
        farm_url(world, f"plan-versions/{version.id}/validate/"), HTTP_IF_MATCH=str(version.version)
    )
    assert validated.status_code == 200, validated.json()
    assert AISuggestion.objects.filter(status="suggested").count() == 0


def test_plan_draft_without_provider_creates_nothing(world, client_for):
    variety = make_validated_variety(world.org_a, world.admin_a)
    parcel = make_parcel(world.farm_a1, area_m2=D(1000))
    ctx = resolve_farm_context(world.manager_a1, world.farm_a1.id)
    campaign = plans.create_campaign(
        ctx, data={"name": "C", "start_date": "2026-01-01", "end_date": "2026-12-31"}
    )
    response = client_for(world.manager_a1).post(
        farm_url(world, "ai/plan-drafts/"),
        {
            "campaign": str(campaign.id),
            "variety": str(variety.id),
            "parcel": str(parcel.id),
            "allocated_area_m2": "1000",
            "planned_start_date": "2026-01-01",
        },
        format="json",
    )
    assert response.status_code == 503
    assert not PlanVersion.objects.exists()


def test_quote_verification_helpers():
    pages = services.pdf_pages(make_text_pdf(["Densite : 2 plants par m2"]))
    assert services.quote_is_verified(pages, 1, "densite :  2 PLANTS par m2")
    assert not services.quote_is_verified(pages, 2, "densite")
    assert not services.quote_is_verified(pages, 1, "")
    assert services.pdf_pages(b"not a pdf") == []
