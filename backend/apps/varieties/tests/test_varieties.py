import pytest

from apps.crops.models import Crop
from apps.varieties.models import TechnicalDataSet, TechnicalDocument
from apps.varieties.technical_keys import get_key_spec, phase_durations
from tests.factories_catalog import make_crop, make_data_set, make_sheet, make_variety

pytestmark = pytest.mark.django_db


def org_url(world, path):
    return f"/api/v1/organizations/{world.org_a.id}/{path}"


# --- Crops -------------------------------------------------------------------------


def test_crops_list_global_and_own_only(world, client_for):
    make_crop(None, "Espèce commune")
    make_crop(world.org_a, "Espèce A")
    make_crop(world.org_b, "Espèce B")
    names = {
        c["common_name"]
        for c in client_for(world.admin_a).get(org_url(world, "crops/")).json()["results"]
    }
    assert names == {"Espèce commune", "Espèce A"}


def test_global_crop_is_read_only(world, client_for):
    shared = make_crop(None, "Commune")
    response = client_for(world.admin_a).patch(
        org_url(world, f"crops/{shared.id}/"), {"family": "x"}, format="json", HTTP_IF_MATCH="1"
    )
    assert response.status_code == 400


def test_crop_create_unique_and_delete_rules(world, client_for):
    client = client_for(world.admin_a)
    created = client.post(
        org_url(world, "crops/"), {"common_name": "Piment", "category": "vegetable"}, format="json"
    )
    assert created.status_code == 201
    assert (
        client.post(org_url(world, "crops/"), {"common_name": "Piment"}, format="json").status_code
        == 400
    )
    crop = Crop.objects.get(id=created.json()["id"])
    make_variety(world.org_a, crop)
    assert client.delete(org_url(world, f"crops/{crop.id}/")).status_code == 400


# --- Varieties ---------------------------------------------------------------------


def test_create_variety_with_visible_crop_only(world, client_for):
    client = client_for(world.admin_a)
    own = make_crop(world.org_a, "Pastèque")
    ok = client.post(
        org_url(world, "varieties/"),
        {"crop": str(own.id), "name": "V1", "seed_company": "Semencier X"},
        format="json",
    )
    assert ok.status_code == 201, ok.json()
    foreign = make_crop(world.org_b, "Secret B")
    denied = client.post(
        org_url(world, "varieties/"), {"crop": str(foreign.id), "name": "V2"}, format="json"
    )
    assert denied.status_code == 400
    assert denied.json()["field_errors"]["crop"] == ["Culture introuvable."]


def test_technician_cannot_edit_varieties(world, client_for):
    crop = make_crop(world.org_a, "Haricot")
    response = client_for(world.worker_a1).post(
        org_url(world, "varieties/"), {"crop": str(crop.id), "name": "V"}, format="json"
    )
    assert response.status_code == 403  # technician on A2 / worker on A1: no varieties.edit


def test_attach_document_keeps_original_file(world, client_for):
    variety = make_variety(world.org_a)
    sheet = make_sheet(world.org_a, world.admin_a)
    client = client_for(world.admin_a)
    url = org_url(world, f"varieties/{variety.id}/documents/")
    response = client.post(
        url,
        {
            "file": str(sheet.id),
            "supplier": "Semencier X",
            "document_date": "2025-01-15",
            "title": "Fiche",
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    assert client.get(url).json()[0]["file"] == str(sheet.id)
    foreign_sheet = make_sheet(world.org_b, world.admin_b)
    assert client.post(url, {"file": str(foreign_sheet.id)}, format="json").status_code == 400


# --- Technical data ------------------------------------------------------------------


def test_key_catalogue():
    assert get_key_spec("row_spacing").unit == "m"
    assert get_key_spec("phase.flowering.duration_days").unit == "days"
    assert get_key_spec("kc.vegetative").unit == "ratio"
    assert get_key_spec("unknown_key") is None
    assert phase_durations({"phase.sowing.duration_days": 5, "row_spacing": 1}) == {"sowing": 5}


def _setup_set(world, with_document=True):
    variety = make_variety(world.org_a)
    document = None
    if with_document:
        document = TechnicalDocument.objects.create(
            organization=world.org_a, variety=variety, file=make_sheet(world.org_a, world.admin_a)
        )
    payload = {
        "variety": str(variety.id),
        **({"source_document": str(document.id)} if document else {}),
    }
    return variety, document, payload


def test_full_technical_data_workflow(world, client_for):
    client = client_for(world.admin_a)
    variety, document, payload = _setup_set(world)
    created = client.post(org_url(world, "technical-data-sets/"), payload, format="json")
    assert created.status_code == 201, created.json()
    ds_id = created.json()["id"]
    assert created.json()["version_number"] == 1
    base = org_url(world, f"technical-data-sets/{ds_id}/")

    items = {
        "items": [
            {
                "key": "row_spacing",
                "value_numeric": "1.5",
                "provenance": "document",
                "source_page": 2,
                "source_quote": "Écartement entre rangs : 1,5 m",
            },
            {"key": "germination_rate", "value_numeric": "0.85", "provenance": "user_input"},
            {"key": "resistances", "value_text": "Tolérance déclarée", "provenance": "user_input"},
        ]
    }
    upserted = client.post(f"{base}items/", items, format="json")
    assert upserted.status_code == 200, upserted.json()
    units = {i["key"]: i["unit"] for i in upserted.json()["items"]}
    assert units["row_spacing"] == "m"  # unit filled from the catalogue

    early = client.post(f"{base}validate/")
    assert early.status_code == 400
    assert set(early.json()["details"]["pending_keys"]) == {
        "row_spacing",
        "germination_rate",
        "resistances",
    }
    client.post(
        f"{base}validate-items/",
        {"keys": ["row_spacing", "germination_rate", "resistances"]},
        format="json",
    )
    validated = client.post(f"{base}validate/")
    assert validated.status_code == 200
    assert validated.json()["status"] == "validated"
    document.refresh_from_db()
    assert document.status == "reviewed"

    # Immutable once validated.
    assert client.post(f"{base}items/", items, format="json").status_code == 400

    # New version copies items with their validation; changing one resets it.
    v2 = client.post(
        org_url(world, "technical-data-sets/"),
        {"variety": str(variety.id), "based_on": ds_id},
        format="json",
    ).json()
    assert v2["version_number"] == 2 and all(i["validated"] for i in v2["items"])
    v2_base = org_url(world, f"technical-data-sets/{v2['id']}/")
    changed = client.post(
        f"{v2_base}items/",
        {
            "items": [
                {"key": "germination_rate", "value_numeric": "0.9", "provenance": "user_input"}
            ]
        },
        format="json",
    ).json()
    by_key = {i["key"]: i for i in changed["items"]}
    assert by_key["germination_rate"]["validated"] is False
    assert by_key["row_spacing"]["validated"] is True
    client.post(f"{v2_base}validate-items/", {"keys": ["germination_rate"]}, format="json")
    assert client.post(f"{v2_base}validate/").status_code == 200
    statuses = dict(
        TechnicalDataSet.objects.filter(variety=variety).values_list("version_number", "status")
    )
    assert statuses == {1: "superseded", 2: "validated"}


@pytest.mark.parametrize(
    "item,expected_error",
    [
        ({"key": "nope", "value_numeric": "1", "provenance": "user_input"}, "nope"),
        (
            {"key": "row_spacing", "value_numeric": "1", "unit": "cm", "provenance": "user_input"},
            "row_spacing",
        ),
        ({"key": "row_spacing", "value_numeric": "0", "provenance": "user_input"}, "row_spacing"),
        (
            {"key": "germination_rate", "value_numeric": "85", "provenance": "user_input"},
            "germination_rate",
        ),
        ({"key": "row_spacing", "provenance": "user_input"}, "row_spacing"),
        (
            {"key": "row_spacing", "value_min": "2", "value_max": "1", "provenance": "user_input"},
            "row_spacing",
        ),
        (
            {
                "key": "resistances",
                "value_numeric": "1",
                "value_text": "x",
                "provenance": "user_input",
            },
            "resistances",
        ),
        # Document provenance without citation is refused (no assumption shown as documentation).
        ({"key": "row_spacing", "value_numeric": "1", "provenance": "document"}, "row_spacing"),
        (
            {
                "key": "row_spacing",
                "value_numeric": "1",
                "provenance": "document",
                "source_page": 1,
            },
            "row_spacing",
        ),
    ],
)
def test_invalid_items_are_rejected(world, client_for, item, expected_error):
    variety = make_variety(world.org_a)
    data_set = make_data_set(variety)
    response = client_for(world.admin_a).post(
        org_url(world, f"technical-data-sets/{data_set.id}/items/"),
        {"items": [item]},
        format="json",
    )
    assert response.status_code == 400, response.json()
    assert expected_error in response.json()["field_errors"]


def test_document_provenance_requires_source_document(world, client_for):
    data_set = make_data_set(make_variety(world.org_a))
    response = client_for(world.admin_a).post(
        org_url(world, f"technical-data-sets/{data_set.id}/items/"),
        {
            "items": [
                {
                    "key": "row_spacing",
                    "value_numeric": "1",
                    "provenance": "document",
                    "source_page": 1,
                    "source_quote": "1 m",
                }
            ]
        },
        format="json",
    )
    assert response.status_code == 400


def test_validation_requires_validate_permission(world, client_for):
    data_set = make_data_set(make_variety(world.org_a))
    technician_like = client_for(world.worker_a1)
    response = technician_like.post(
        org_url(world, f"technical-data-sets/{data_set.id}/validate-items/"),
        {"keys": ["row_spacing"]},
        format="json",
    )
    assert response.status_code == 403


def test_empty_data_set_cannot_be_validated(world, client_for):
    data_set = make_data_set(make_variety(world.org_a))
    response = client_for(world.admin_a).post(
        org_url(world, f"technical-data-sets/{data_set.id}/validate/")
    )
    assert response.status_code == 400


def test_technical_keys_catalogue_endpoint(world, client_for):
    response = client_for(world.worker_a1).get("/api/v1/technical-keys/")
    assert response.status_code == 200
    keys = {k["key"] for k in response.json()}
    assert {"row_spacing", "germination_rate", "phase.<code>.duration_days"} <= keys
