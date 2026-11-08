"""Irrigation API tests. Prices and parameters are fictitious test values."""

from decimal import Decimal as D

import pytest

from apps.irrigation.models import Quote
from tests.factories import make_parcel

pytestmark = pytest.mark.django_db

DRIP_PARAMS = {
    "lateral_count": 14,
    "lateral_length_m": "50",
    "lateral_spacing_m": "1.5",
    "emitter_spacing_m": "0.3",
    "emitter_flow_lph": "2",
    "operating_pressure_bar": "1",
    "source_max_flow_m3h": "2.5",
    "irrigated_area_m2": "1000",
    "et0_mm_per_day": "5",
    "kc": "1",
    "application_efficiency_rate": "0.9",
    "segments": [
        {"role": "main", "length_m": "80", "inner_diameter_mm": "50", "hazen_williams_c": "140"}
    ],
}
BOM_PARAMS = {"installation_waste_rate": "0.05", "dripline_roll_length_m": "400", "filter_count": 1}


def farm_url(world, path):
    return f"/api/v1/farms/{world.farm_a1.id}/{path}"


def org_url(world, path):
    return f"/api/v1/organizations/{world.org_a.id}/{path}"


def make_design(client, world, parcel, **overrides):
    response = client.post(
        farm_url(world, "irrigation-designs/"),
        {
            "parcel": str(parcel.id),
            "name": "Goutte-à-goutte P1",
            "system_type": "drip",
            "parameters": DRIP_PARAMS,
            "bom_parameters": BOM_PARAMS,
            **overrides,
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    return response.json()


def make_price_list(client, world, prices, supplier_name="Fournisseur A"):
    supplier = client.post(
        org_url(world, "suppliers/"), {"name": supplier_name}, format="json"
    ).json()
    price_list = client.post(
        org_url(world, "price-lists/"),
        {
            "supplier": supplier["id"],
            "name": "Tarif",
            "currency": "XAF",
            "valid_from": "2026-01-01",
        },
        format="json",
    )
    assert price_list.status_code == 201, price_list.json()
    pl = price_list.json()
    items = client.put(
        org_url(world, f"price-lists/{pl['id']}/items/"),
        {
            "items": [
                {"catalog_item": item_id, "unit": unit, "unit_price": price}
                for item_id, unit, price in prices
            ]
        },
        format="json",
        HTTP_IF_MATCH=str(pl["version"]),
    )
    assert items.status_code == 200, items.json()
    activated = client.patch(
        org_url(world, f"price-lists/{pl['id']}/"),
        {"status": "active"},
        format="json",
        HTTP_IF_MATCH=str(items.json()["version"]),
    )
    assert activated.status_code == 200, activated.json()
    return activated.json()


def test_drip_design_compute_validate(world, client_for):
    client = client_for(world.manager_a1)
    design = make_design(client, world, make_parcel(world.farm_a1))
    outcome = client.post(farm_url(world, f"irrigation-designs/{design['id']}/compute/")).json()
    assert outcome["complete"] is True, outcome
    drip = next(r for r in outcome["results"] if r["calc_type"] == "irrigation.drip")
    assert drip["outputs"]["total_flow_m3h"] == {"value": "4.6480", "unit": "m3/h"}
    assert drip["outputs"]["gross_daily_volume_m3"]["unit"] == "m3/j"
    assert "Dénivelé" in drip["details"]["not_considered"]

    detail = client.get(farm_url(world, f"irrigation-designs/{design['id']}/")).json()
    types = [line["component_type"] for line in detail["bom_lines"]]
    assert types.count("dripline") == 1 and "valve" in types and "filter" in types
    validated = client.post(
        farm_url(world, f"irrigation-designs/{design['id']}/validate/"),
        HTTP_IF_MATCH=str(detail["version"]),
    )
    assert validated.status_code == 200, validated.json()
    assert validated.json()["status"] == "validated"
    refused = client.patch(
        farm_url(world, f"irrigation-designs/{design['id']}/"),
        {"name": "x"},
        format="json",
        HTTP_IF_MATCH=str(validated.json()["version"]),
    )
    assert refused.status_code == 400


def test_invalid_parameters_and_missing_inputs(world, client_for):
    client = client_for(world.manager_a1)
    parcel = make_parcel(world.farm_a1)
    bad = client.post(
        farm_url(world, "irrigation-designs/"),
        {
            "parcel": str(parcel.id),
            "name": "x",
            "system_type": "drip",
            "parameters": {"lateral_count": 0},
        },
        format="json",
    )
    assert bad.status_code == 400
    design = make_design(client, world, parcel, parameters={"lateral_count": 4}, bom_parameters={})
    outcome = client.post(farm_url(world, f"irrigation-designs/{design['id']}/compute/")).json()
    assert outcome["complete"] is False
    assert "emitter_flow_lph" in outcome["missing"]
    assert (
        client.post(
            farm_url(world, f"irrigation-designs/{design['id']}/validate/"), HTTP_IF_MATCH="2"
        ).status_code
        == 400
    )


def test_waste_rate_must_be_explicit(world, client_for):
    client = client_for(world.manager_a1)
    design = make_design(client, world, make_parcel(world.farm_a1), bom_parameters={})
    outcome = client.post(farm_url(world, f"irrigation-designs/{design['id']}/compute/")).json()
    assert outcome["missing"] == ["installation_waste_rate"]


def test_quote_copies_prices_and_supports_several_suppliers(world, client_for):
    client = client_for(world.admin_a)
    design = make_design(client, world, make_parcel(world.farm_a1))
    client.post(farm_url(world, f"irrigation-designs/{design['id']}/compute/"))
    detail = client.get(farm_url(world, f"irrigation-designs/{design['id']}/")).json()
    dripline = next(line for line in detail["bom_lines"] if line["component_type"] == "dripline")
    item = client.post(
        org_url(world, "catalog-items/"),
        {"category": "dripline", "name": "Rampe 16 mm", "base_unit": "roll"},
        format="json",
    ).json()
    linked = client.post(
        farm_url(world, f"irrigation-designs/{design['id']}/link/"),
        {"bom_line": dripline["id"], "catalog_item": item["id"]},
        format="json",
    )
    assert linked.status_code == 200, linked.json()

    supplier_a = make_price_list(client, world, [(item["id"], "roll", "45000")], "Fournisseur A")
    supplier_b = make_price_list(client, world, [(item["id"], "roll", "41000")], "Fournisseur B")
    quote_a = client.post(
        farm_url(world, "quotes/"),
        {"design": design["id"], "price_list": supplier_a["id"]},
        format="json",
    )
    assert quote_a.status_code == 201, quote_a.json()
    quote_b = client.post(
        farm_url(world, "quotes/"),
        {"design": design["id"], "price_list": supplier_b["id"]},
        format="json",
    ).json()
    qa = quote_a.json()
    priced = next(line for line in qa["lines"] if line["unit_price"] is not None)
    assert D(priced["unit_price"]) == D(45000) and D(priced["line_total"]) == D(90000)
    assert D(qa["total"]) == D(90000) and qa["warnings"]  # other lines are unpriced
    assert D(quote_b["total"]) == D(82000)
    assert (qa["number"], quote_b["number"]) == (1, 2)

    # Manual price on an unpriced line, then issue: the quote becomes immutable.
    valve = next(line for line in qa["lines"] if line["description"] == "Vannes de secteur")
    updated = client.patch(
        farm_url(world, f"quotes/{qa['id']}/"),
        {"lines": [{"id": valve["id"], "unit_price": "12500"}]},
        format="json",
        HTTP_IF_MATCH=str(qa["version"]),
    ).json()
    assert D(updated["total"]) == D(90000 + 2 * 12500)
    issued = client.post(
        farm_url(world, f"quotes/{qa['id']}/issue/"), HTTP_IF_MATCH=str(updated["version"])
    ).json()
    assert issued["status"] == "issued"
    assert (
        client.patch(
            farm_url(world, f"quotes/{qa['id']}/"),
            {"tax_rate": "0.1"},
            format="json",
            HTTP_IF_MATCH=str(issued["version"]),
        ).status_code
        == 400
    )
    accepted = client.post(
        farm_url(world, f"quotes/{qa['id']}/decide/"),
        {"status": "accepted"},
        format="json",
        HTTP_IF_MATCH=str(issued["version"]),
    )
    assert accepted.json()["status"] == "accepted"
    # Archiving the price list does not change existing quotes.
    client.patch(
        org_url(world, f"price-lists/{supplier_a['id']}/"),
        {"status": "archived"},
        format="json",
        HTTP_IF_MATCH=str(supplier_a["version"]),
    )
    assert Quote.objects.get(id=qa["id"]).total == D(115000)


def test_active_price_list_is_immutable_and_precision_checked(world, client_for):
    client = client_for(world.admin_a)
    item = client.post(
        org_url(world, "catalog-items/"),
        {"category": "valve", "name": "Vanne", "base_unit": "piece"},
        format="json",
    ).json()
    price_list = make_price_list(client, world, [(item["id"], "piece", "1000")])
    refused = client.put(
        org_url(world, f"price-lists/{price_list['id']}/items/"),
        {"items": []},
        format="json",
        HTTP_IF_MATCH=str(price_list["version"]),
    )
    assert refused.status_code == 400
    supplier = client.post(org_url(world, "suppliers/"), {"name": "S2"}, format="json").json()
    draft = client.post(
        org_url(world, "price-lists/"),
        {"supplier": supplier["id"], "name": "T", "currency": "XAF", "valid_from": "2026-01-01"},
        format="json",
    ).json()
    precise = client.put(
        org_url(world, f"price-lists/{draft['id']}/items/"),
        {"items": [{"catalog_item": item["id"], "unit": "piece", "unit_price": "10.5"}]},
        format="json",
        HTTP_IF_MATCH=str(draft["version"]),
    )
    assert precise.status_code == 400  # XAF has no minor unit


def test_quote_requires_bom_and_active_price_list(world, client_for):
    client = client_for(world.admin_a)
    design = make_design(client, world, make_parcel(world.farm_a1))
    assert (
        client.post(farm_url(world, "quotes/"), {"design": design["id"]}, format="json").status_code
        == 400
    )
    client.post(farm_url(world, f"irrigation-designs/{design['id']}/compute/"))
    without_prices = client.post(
        farm_url(world, "quotes/"), {"design": design["id"]}, format="json"
    ).json()
    assert without_prices["currency"] == "XAF" and D(without_prices["total"]) == 0


def test_cross_tenant_links_are_refused(world, client_for):
    client = client_for(world.admin_a)
    other_farm_parcel = make_parcel(world.farm_a2)
    response = client.post(
        farm_url(world, "irrigation-designs/"),
        {"parcel": str(other_farm_parcel.id), "name": "x", "system_type": "drip"},
        format="json",
    )
    assert response.status_code == 400
    admin_b = client_for(world.admin_b)
    supplier_b = admin_b.post(
        f"/api/v1/organizations/{world.org_b.id}/suppliers/", {"name": "B"}, format="json"
    ).json()
    leak = client.post(
        org_url(world, "price-lists/"),
        {"supplier": supplier_b["id"], "name": "x", "currency": "XAF", "valid_from": "2026-01-01"},
        format="json",
    )
    assert leak.status_code == 400


def test_irrigation_permissions(world, client_for):
    worker = client_for(world.worker_a1)
    assert worker.get(farm_url(world, "irrigation-designs/")).status_code == 403
    finance = client_for(world.finance_a1)  # irrigation.view only
    assert finance.get(farm_url(world, "irrigation-designs/")).status_code == 200
    assert (
        finance.post(farm_url(world, "irrigation-designs/"), {}, format="json").status_code == 403
    )
