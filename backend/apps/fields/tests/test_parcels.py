import threading
import uuid
from decimal import Decimal

import pytest
from django.db import DatabaseError, connection, transaction

from apps.audit.models import AuditEvent
from apps.fields.models import Parcel
from apps.synchronization.models import ChangeLog
from tests.factories import make_field, make_parcel

pytestmark = pytest.mark.django_db


def parcels_url(farm):
    return f"/api/v1/farms/{farm.id}/parcels/"


PARCEL = {"name": "Parcelle Nord", "code": "PN-1", "area_m2": "1000.0000", "soil_ph": "6.5"}


def test_create_and_configure_parcel(world, client_for):
    client = client_for(world.manager_a1)
    field = make_field(world.farm_a1, area_m2=Decimal("5000"))
    response = client.post(
        parcels_url(world.farm_a1),
        {
            **PARCEL,
            "field": str(field.id),
            "length_m": "50",
            "width_m": "20",
            "water_availability": "medium",
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["version"] == 1
    assert body["warnings"] == []
    parcel = Parcel.objects.get(id=body["id"])
    assert parcel.created_by == world.manager_a1
    assert AuditEvent.objects.filter(action="parcel.created", entity_id=parcel.id).exists()
    change = ChangeLog.objects.get(entity_id=parcel.id)
    assert change.entity_type == "fields.parcel"
    assert change.required_permission == "fields.view"


def test_dimension_mismatch_produces_warning(world, client_for):
    response = client_for(world.manager_a1).post(
        parcels_url(world.farm_a1), {**PARCEL, "length_m": "10", "width_m": "10"}, format="json"
    )
    assert response.status_code == 201
    assert response.json()["warnings"]


@pytest.mark.parametrize(
    "override",
    [
        {"area_m2": "0"},
        {"area_m2": "-5"},
        {"soil_ph": "15"},
        {"latitude": "95"},
        {"geometry": {"type": "Point", "coordinates": [1, 2]}},
        {"water_availability": "lots"},
    ],
)
def test_parcel_validation(world, client_for, override):
    response = client_for(world.manager_a1).post(
        parcels_url(world.farm_a1), {**PARCEL, **override}, format="json"
    )
    assert response.status_code == 400


def test_code_unique_per_farm_but_reusable_elsewhere(world, client_for):
    client = client_for(world.admin_a)
    assert client.post(parcels_url(world.farm_a1), PARCEL, format="json").status_code == 201
    assert client.post(parcels_url(world.farm_a1), PARCEL, format="json").status_code == 400
    assert client.post(parcels_url(world.farm_a2), PARCEL, format="json").status_code == 201


def test_parcels_cannot_exceed_field_area(world, client_for):
    client = client_for(world.manager_a1)
    field = make_field(world.farm_a1, area_m2=Decimal("1500"))
    first = client.post(
        parcels_url(world.farm_a1), {**PARCEL, "field": str(field.id)}, format="json"
    )
    assert first.status_code == 201
    second = client.post(
        parcels_url(world.farm_a1),
        {**PARCEL, "code": "PN-2", "field": str(field.id)},
        format="json",
    )
    assert second.status_code == 400
    assert second.json()["code"] == "business_rule_violation"
    small = client.post(
        parcels_url(world.farm_a1),
        {**PARCEL, "code": "PN-3", "area_m2": "500", "field": str(field.id)},
        format="json",
    )
    assert small.status_code == 201
    # Shrinking the field below its parcels is refused.
    shrink = client.patch(
        f"/api/v1/farms/{world.farm_a1.id}/fields/{field.id}/",
        {"area_m2": "1000"},
        format="json",
        HTTP_IF_MATCH="1",
    )
    assert shrink.status_code == 400


def test_area_tolerance_setting(world, client_for):
    world.farm_a1.settings = {"area_tolerance_pct": 10}
    world.farm_a1.save()
    field = make_field(world.farm_a1, area_m2=Decimal("1000"))
    response = client_for(world.manager_a1).post(
        parcels_url(world.farm_a1),
        {**PARCEL, "area_m2": "1100", "field": str(field.id)},
        format="json",
    )
    assert response.status_code == 201


def test_cannot_attach_parcel_to_field_of_other_farm(world, client_for):
    foreign_field = make_field(world.farm_a2)
    response = client_for(world.admin_a).post(
        parcels_url(world.farm_a1), {**PARCEL, "field": str(foreign_field.id)}, format="json"
    )
    assert response.status_code == 400
    assert "field" in response.json()["field_errors"]


def test_update_with_optimistic_concurrency(world, client_for):
    parcel = make_parcel(world.farm_a1)
    client = client_for(world.manager_a1)
    url = f"{parcels_url(world.farm_a1)}{parcel.id}/"
    assert client.patch(url, {"name": "A"}, format="json").status_code == 428
    first = client.patch(url, {"name": "A"}, format="json", HTTP_IF_MATCH="1")
    assert first.status_code == 200
    assert first.json()["version"] == 2
    stale = client.patch(url, {"name": "B"}, format="json", HTTP_IF_MATCH="1")
    assert stale.status_code == 409
    assert stale.json()["details"]["current_version"] == 2
    assert ChangeLog.objects.filter(entity_id=parcel.id).count() == 1


def test_noop_update_does_not_bump_version(world, client_for):
    parcel = make_parcel(world.farm_a1, name="Same")
    response = client_for(world.manager_a1).patch(
        f"{parcels_url(world.farm_a1)}{parcel.id}/",
        {"name": "Same"},
        format="json",
        HTTP_IF_MATCH="1",
    )
    assert response.json()["version"] == 1


def test_client_generated_id_create_is_idempotent(world, client_for):
    client = client_for(world.manager_a1)
    client_id = str(uuid.uuid4())
    first = client.post(parcels_url(world.farm_a1), {**PARCEL, "id": client_id}, format="json")
    replay = client.post(parcels_url(world.farm_a1), {**PARCEL, "id": client_id}, format="json")
    assert first.status_code == 201
    assert replay.status_code == 200
    assert Parcel.objects.filter(id=client_id).count() == 1
    assert ChangeLog.objects.filter(entity_id=client_id).count() == 1


def test_client_id_of_other_tenant_is_rejected_without_leak(world, client_for):
    foreign = make_parcel(world.farm_b1)
    response = client_for(world.admin_a).post(
        parcels_url(world.farm_a1), {**PARCEL, "id": str(foreign.id)}, format="json"
    )
    assert response.status_code == 409
    assert "farm" not in str(response.json()["details"])
    foreign.refresh_from_db()
    assert foreign.farm_id == world.farm_b1.id


def test_soft_delete_hides_parcel_and_frees_code(world, client_for):
    client = client_for(world.manager_a1)
    parcel = make_parcel(world.farm_a1, code="DEL-1")
    url = f"{parcels_url(world.farm_a1)}{parcel.id}/"
    assert client.delete(url).status_code == 428
    assert client.delete(url, HTTP_IF_MATCH="1").status_code == 204
    assert client.get(url).status_code == 404
    parcel.refresh_from_db()
    assert parcel.deleted_at is not None and parcel.version == 2
    assert ChangeLog.objects.get(entity_id=parcel.id).operation == "delete"
    again = client.post(parcels_url(world.farm_a1), {**PARCEL, "code": "DEL-1"}, format="json")
    assert again.status_code == 201


def test_field_with_parcels_cannot_be_deleted(world, client_for):
    field = make_field(world.farm_a1)
    make_parcel(world.farm_a1, field=field)
    response = client_for(world.manager_a1).delete(
        f"/api/v1/farms/{world.farm_a1.id}/fields/{field.id}/", HTTP_IF_MATCH="1"
    )
    assert response.status_code == 400


def test_parcel_history(world, client_for):
    parcel = make_parcel(world.farm_a1)
    url = f"{parcels_url(world.farm_a1)}{parcel.id}/history/"
    entry = {"period_start": "2025-03-01", "period_end": "2025-06-30", "crop_label": "Maïs"}
    assert client_for(world.worker_a1).post(url, entry, format="json").status_code == 403
    created = client_for(world.manager_a1).post(url, entry, format="json")
    assert created.status_code == 201
    listed = client_for(world.worker_a1).get(url)
    assert listed.status_code == 200
    assert listed.json()[0]["crop_label"] == "Maïs"
    invalid = client_for(world.manager_a1).post(
        url, {**entry, "period_end": "2024-01-01"}, format="json"
    )
    assert invalid.status_code == 400


def test_worker_reads_but_cannot_write(world, client_for):
    make_parcel(world.farm_a1)
    client = client_for(world.worker_a1)
    assert client.get(parcels_url(world.farm_a1)).status_code == 200
    assert client.post(parcels_url(world.farm_a1), PARCEL, format="json").status_code == 403


def test_filter_by_field(world, client_for):
    field = make_field(world.farm_a1)
    make_parcel(world.farm_a1, field=field)
    make_parcel(world.farm_a1)
    response = client_for(world.manager_a1).get(
        parcels_url(world.farm_a1), {"field": str(field.id)}
    )
    assert response.json()["count"] == 1


def test_audit_log_is_append_only(world):
    event = AuditEvent.objects.first()
    with pytest.raises(DatabaseError), transaction.atomic():
        AuditEvent.objects.filter(id=event.id).update(action="tampered")
    with pytest.raises(DatabaseError), transaction.atomic():
        AuditEvent.objects.filter(id=event.id).delete()


@pytest.mark.django_db(transaction=True)
def test_change_sequence_is_gapless_under_concurrency(world):
    from apps.farms.access import resolve_farm_context
    from apps.fields.services import create_parcel

    ctx = resolve_farm_context(world.manager_a1, world.farm_a1.id)
    errors: list[Exception] = []

    def worker(i: int) -> None:
        try:
            create_parcel(ctx, data={"name": f"P{i}", "code": f"CC-{i}", "area_m2": Decimal(10)})
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    seqs = sorted(ChangeLog.objects.filter(farm=world.farm_a1).values_list("seq", flat=True))
    assert seqs == list(range(1, len(seqs) + 1))
