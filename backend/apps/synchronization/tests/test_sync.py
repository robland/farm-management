"""Synchronization protocol tests (OFFLINE_SYNC.md §10)."""

import threading
import uuid
from decimal import Decimal

import pytest
from django.db import connection

from apps.fields.models import Parcel
from apps.organizations.models import Role
from apps.synchronization.models import (
    ChangeLog,
    FarmSyncState,
    SyncConflict,
    SyncOperationReceipt,
)
from apps.synchronization.push import IncomingOperation, process_operation
from tests.factories import make_parcel

pytestmark = pytest.mark.django_db

PUSH = "/api/v1/sync/push/"
PULL = "/api/v1/sync/pull/"


def op(farm, op_type="create", entity_type="fields.parcel", entity_id=None, **extra):
    return {
        "op_id": str(uuid.uuid4()),
        "farm_id": str(farm.id),
        "op_type": op_type,
        "entity_type": entity_type,
        "entity_id": str(entity_id or uuid.uuid4()),
        **extra,
    }


def create_parcel_op(farm, code="SYNC-1", **payload):
    return op(
        farm, payload={"name": "Parcelle hors ligne", "code": code, "area_m2": "250", **payload}
    )


def push(client, *operations):
    response = client.post(PUSH, {"operations": list(operations)}, format="json")
    assert response.status_code == 200, response.content
    return response.json()["results"]


# --- Push: create, replay, idempotency ----------------------------------------


def test_offline_create_is_applied_once_and_replay_returns_same_result(world, client_for):
    client = client_for(world.manager_a1)
    operation = create_parcel_op(world.farm_a1)
    first = push(client, operation)[0]
    assert first["status"] == "applied", first
    assert first["entity_version"] == 1
    replay = push(client, operation)[0]
    assert replay["replayed"] is True
    assert {k: v for k, v in replay.items() if k != "replayed"} == first
    assert Parcel.objects.filter(id=operation["entity_id"]).count() == 1
    assert ChangeLog.objects.filter(entity_id=operation["entity_id"]).count() == 1
    change = ChangeLog.objects.get(entity_id=operation["entity_id"])
    assert str(change.origin_op_id) == operation["op_id"]


def test_same_op_id_with_different_payload_is_rejected(world, client_for):
    client = client_for(world.manager_a1)
    operation = create_parcel_op(world.farm_a1)
    push(client, operation)
    tampered = {**operation, "payload": {**operation["payload"], "area_m2": "999"}}
    result = push(client, tampered)[0]
    assert result["status"] == "rejected"
    assert result["error"]["code"] == "idempotency_key_reused"


def test_op_id_of_another_user_cannot_be_replayed(world, client_for):
    operation = create_parcel_op(world.farm_a1)
    push(client_for(world.manager_a1), operation)
    result = push(client_for(world.admin_a), operation)[0]
    assert result["error"]["code"] == "idempotency_key_reused"


def test_same_entity_created_twice_with_new_op_id_converges(world, client_for):
    client = client_for(world.manager_a1)
    first = create_parcel_op(world.farm_a1)
    second = {**first, "op_id": str(uuid.uuid4())}
    push(client, first)
    result = push(client, second)[0]
    assert result["status"] == "applied"
    assert result["created"] is False
    assert Parcel.objects.filter(id=first["entity_id"]).count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_push_of_same_op_applies_once(world):
    operation = IncomingOperation(
        op_id=uuid.uuid4(),
        farm_id=world.farm_a1.id,
        op_type="create",
        entity_type="fields.parcel",
        entity_id=uuid.uuid4(),
        payload={"name": "Concurrente", "code": "CONC-1", "area_m2": "10"},
    )
    results: list[dict] = []

    def worker() -> None:
        try:
            results.append(process_operation(world.manager_a1, None, operation))
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 4
    assert all(r["status"] == "applied" for r in results), results
    assert Parcel.objects.filter(id=operation.entity_id).count() == 1
    assert SyncOperationReceipt.objects.filter(op_id=operation.op_id).count() == 1


def test_partial_batch_failure_does_not_block_independent_operations(world, client_for):
    client = client_for(world.manager_a1)
    good1 = create_parcel_op(world.farm_a1, code="OK-1")
    invalid = create_parcel_op(world.farm_a1, code="BAD", area_m2="-3")
    good2 = create_parcel_op(world.farm_a1, code="OK-2")
    dependent = op(
        world.farm_a1,
        "update",
        entity_id=invalid["entity_id"],
        base_version=1,
        payload={"name": "x"},
        depends_on=[invalid["op_id"]],
    )
    results = push(client, good1, invalid, good2, dependent)
    assert [r["status"] for r in results] == ["applied", "rejected", "applied", "rejected"]
    assert results[1]["error"]["code"] == "validation_error"
    assert results[3]["error"]["code"] == "dependency_failed"
    # Rejections leave no receipt: they can be retried once fixed.
    assert not SyncOperationReceipt.objects.filter(op_id=invalid["op_id"]).exists()


def test_unknown_fields_and_types_are_rejected(world, client_for):
    client = client_for(world.manager_a1)
    unknown_field = create_parcel_op(world.farm_a1)
    unknown_field["payload"]["organization"] = str(world.org_b.id)
    unknown_type = op(world.farm_a1, entity_type="finance.secret", payload={})
    results = push(client, unknown_field, unknown_type)
    assert results[0]["error"]["code"] == "validation_error"
    assert results[1]["error"]["code"] == "unknown_entity_type"


def test_batch_validation(world, client_for):
    client = client_for(world.manager_a1)
    operation = create_parcel_op(world.farm_a1)
    duplicate = client.post(PUSH, {"operations": [operation, operation]}, format="json")
    assert duplicate.status_code == 400
    too_many = [create_parcel_op(world.farm_a1, code=f"M{i}") for i in range(101)]
    assert client.post(PUSH, {"operations": too_many}, format="json").status_code == 400


# --- Permissions and tenancy ---------------------------------------------------


def test_push_to_other_organization_farm_is_rejected_as_not_found(world, client_for):
    result = push(client_for(world.admin_a), create_parcel_op(world.farm_b1))[0]
    assert result["error"]["code"] == "not_found"
    assert not Parcel.objects.filter(farm=world.farm_b1).exists()


def test_push_without_write_permission_is_rejected(world, client_for):
    parcel = make_parcel(world.farm_a1)
    update = op(
        world.farm_a1, "update", entity_id=parcel.id, base_version=99, payload={"name": "x"}
    )
    result = push(client_for(world.worker_a1), update)[0]
    # Stale version, but permission is checked first: no conflict and no snapshot leak.
    assert result["error"]["code"] == "permission_denied"
    assert "server" not in result
    assert not SyncConflict.objects.exists()


def test_update_of_entity_of_other_farm_is_not_found(world, client_for):
    foreign = make_parcel(world.farm_a2)
    update = op(
        world.farm_a1, "update", entity_id=foreign.id, base_version=1, payload={"name": "x"}
    )
    result = push(client_for(world.admin_a), update)[0]
    assert result["error"]["code"] == "not_found"


def test_author_must_be_the_authenticated_user(world, client_for):
    operation = create_parcel_op(world.farm_a1) | {"author_id": str(world.admin_a.id)}
    result = push(client_for(world.manager_a1), operation)[0]
    assert result["error"]["code"] == "author_mismatch"


def test_rejected_operation_can_be_retried_after_permission_granted(world, client_for):
    operation = create_parcel_op(world.farm_a1)
    client = client_for(world.worker_a1)
    assert push(client, operation)[0]["status"] == "rejected"
    from apps.farms.models import FarmMembership

    FarmMembership.objects.filter(user=world.worker_a1, farm=world.farm_a1).update(
        role=Role.objects.get(organization=world.org_a, code="farm_manager")
    )
    assert push(client, operation)[0]["status"] == "applied"


# --- Concurrent modifications ----------------------------------------------------


def _update(farm, parcel, base_version, base_values, payload):
    return op(
        farm,
        "update",
        entity_id=parcel.id,
        base_version=base_version,
        base_values=base_values,
        payload=payload,
    )


def test_update_with_current_version(world, client_for):
    parcel = make_parcel(world.farm_a1, name="Avant")
    result = push(
        client_for(world.manager_a1),
        _update(world.farm_a1, parcel, 1, {"name": "Avant"}, {"name": "Après"}),
    )[0]
    assert result["status"] == "applied" and result["merged"] is False
    parcel.refresh_from_db()
    assert parcel.name == "Après" and parcel.version == 2


def test_concurrent_edits_on_disjoint_fields_are_merged(world, client_for):
    parcel = make_parcel(world.farm_a1, name="Nord", soil_type="argileux")
    client = client_for(world.manager_a1)
    # Device A changes the name, device B (offline, based on v1) changes soil type.
    push(client, _update(world.farm_a1, parcel, 1, {"name": "Nord"}, {"name": "Nord-Est"}))
    result = push(
        client,
        _update(world.farm_a1, parcel, 1, {"soil_type": "argileux"}, {"soil_type": "sableux"}),
    )[0]
    assert result["status"] == "applied" and result["merged"] is True
    parcel.refresh_from_db()
    assert (parcel.name, parcel.soil_type, parcel.version) == ("Nord-Est", "sableux", 3)


def test_concurrent_edits_on_same_field_raise_conflict_without_write(world, client_for):
    parcel = make_parcel(world.farm_a1, area_m2=Decimal("1000"))
    client = client_for(world.manager_a1)
    push(client, _update(world.farm_a1, parcel, 1, {"area_m2": "1000"}, {"area_m2": "1200"}))
    result = push(
        client, _update(world.farm_a1, parcel, 1, {"area_m2": "1000.0000"}, {"area_m2": "900"})
    )[0]
    assert result["status"] == "conflict"
    assert result["conflict_type"] == "field_conflict"
    assert result["fields"] == ["area_m2"]
    assert Decimal(result["server"]["area_m2"]) == Decimal("1200")
    parcel.refresh_from_db()
    assert parcel.area_m2 == Decimal("1200") and parcel.version == 2
    conflict = SyncConflict.objects.get(id=result["conflict_id"])
    assert conflict.raised_for == world.manager_a1 and conflict.status == "open"


def test_converging_edits_are_not_conflicts(world, client_for):
    parcel = make_parcel(world.farm_a1, name="A")
    client = client_for(world.manager_a1)
    push(client, _update(world.farm_a1, parcel, 1, {"name": "A"}, {"name": "B"}))
    result = push(client, _update(world.farm_a1, parcel, 1, {"name": "A"}, {"name": "B"}))[0]
    assert result["status"] == "applied"
    parcel.refresh_from_db()
    assert parcel.version == 2


def test_stale_update_without_base_values_is_a_conflict(world, client_for):
    parcel = make_parcel(world.farm_a1)
    client = client_for(world.manager_a1)
    push(client, _update(world.farm_a1, parcel, 1, {}, {"name": "X"}))
    result = push(client, _update(world.farm_a1, parcel, 1, {}, {"notes": "Y"}))[0]
    assert result["status"] == "conflict"


def test_update_of_deleted_entity_is_a_conflict(world, client_for):
    parcel = make_parcel(world.farm_a1)
    client = client_for(world.manager_a1)
    assert (
        push(client, op(world.farm_a1, "delete", entity_id=parcel.id, base_version=1))[0]["status"]
        == "applied"
    )
    result = push(client, _update(world.farm_a1, parcel, 1, {"name": parcel.name}, {"name": "Z"}))[
        0
    ]
    assert result["status"] == "conflict"
    assert result["server"]["deleted"] is True


def test_delete_is_idempotent_and_stale_delete_conflicts(world, client_for):
    parcel = make_parcel(world.farm_a1)
    client = client_for(world.manager_a1)
    push(client, _update(world.farm_a1, parcel, 1, {"name": parcel.name}, {"name": "v2"}))
    stale = push(client, op(world.farm_a1, "delete", entity_id=parcel.id, base_version=1))[0]
    assert stale["status"] == "conflict"
    ok = push(client, op(world.farm_a1, "delete", entity_id=parcel.id, base_version=2))[0]
    assert ok["status"] == "applied"
    again = push(client, op(world.farm_a1, "delete", entity_id=parcel.id, base_version=2))[0]
    assert again["status"] == "applied" and again["already_deleted"] is True


def test_conflict_listing_and_resolution(world, client_for):
    parcel = make_parcel(world.farm_a1)
    manager = client_for(world.manager_a1)
    push(manager, _update(world.farm_a1, parcel, 1, {"name": parcel.name}, {"name": "A"}))
    conflict_id = push(
        manager, _update(world.farm_a1, parcel, 1, {"name": parcel.name}, {"name": "B"})
    )[0]["conflict_id"]
    url = f"/api/v1/farms/{world.farm_a1.id}/sync/conflicts/"
    assert [c["id"] for c in manager.get(url).json()["results"]] == [conflict_id]
    # Another member without farm.manage does not see someone else's conflict.
    assert client_for(world.worker_a1).get(url).json()["results"] == []
    resolved = manager.post(
        f"{url}{conflict_id}/resolve/", {"resolution": "keep_server"}, format="json"
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"
    again = manager.post(f"{url}{conflict_id}/resolve/", {"resolution": "dismiss"}, format="json")
    assert again.status_code == 400


# --- Pull ------------------------------------------------------------------------


def pull(client, farm, cursor=0, limit=500):
    response = client.get(PULL, {"farm_id": str(farm.id), "cursor": cursor, "limit": limit})
    assert response.status_code == 200, response.content
    return response.json()


def test_initial_pull_returns_farm_and_parcels(world, client_for):
    client = client_for(world.manager_a1)
    push(client, create_parcel_op(world.farm_a1, code="P-PULL"))
    data = pull(client, world.farm_a1)
    types = [c["entity_type"] for c in data["changes"]]
    assert types == ["farms.farm", "fields.parcel"]
    parcel_change = data["changes"][1]
    assert parcel_change["operation"] == "upsert"
    assert parcel_change["data"]["code"] == "P-PULL"
    assert data["has_more"] is False
    assert data["next_cursor"] == data["server_seq"]


def test_incremental_pull_with_pagination_and_last_state_per_entity(world, client_for):
    client = client_for(world.manager_a1)
    cursor = pull(client, world.farm_a1)["next_cursor"]
    operation = create_parcel_op(world.farm_a1, code="INC")
    push(client, operation)
    for i in range(3):
        push(
            client,
            _update(
                world.farm_a1,
                Parcel.objects.get(id=operation["entity_id"]),
                i + 1,
                {},
                {"notes": f"n{i}"},
            )
            | {"base_values": {"notes": "" if i == 0 else f"n{i - 1}"}},
        )
    page1 = pull(client, world.farm_a1, cursor=cursor, limit=2)
    assert page1["has_more"] is True
    page2 = pull(client, world.farm_a1, cursor=page1["next_cursor"], limit=10)
    assert page2["has_more"] is False
    final = page2["changes"][-1]
    assert final["data"]["notes"] == "n2" and final["version"] == 4
    # Within a page, an entity appears only once.
    ids = [c["entity_id"] for c in page2["changes"]]
    assert len(ids) == len(set(ids))


def test_pull_returns_tombstones(world, client_for):
    client = client_for(world.manager_a1)
    parcel = make_parcel(world.farm_a1)
    cursor = pull(client, world.farm_a1)["next_cursor"]
    push(client, op(world.farm_a1, "delete", entity_id=parcel.id, base_version=1))
    changes = pull(client, world.farm_a1, cursor=cursor)["changes"]
    assert changes == [
        {
            "seq": changes[0]["seq"],
            "entity_type": "fields.parcel",
            "entity_id": str(parcel.id),
            "operation": "delete",
            "version": 2,
        }
    ]


def test_pull_filters_by_permission_and_lists_purge(world, client_for):
    push(client_for(world.manager_a1), create_parcel_op(world.farm_a1))
    data = pull(client_for(world.finance_a1), world.farm_a1)  # no fields.view
    assert {c["entity_type"] for c in data["changes"]} == {"farms.farm"}
    assert "fields.parcel" in data["purge"]
    assert pull(client_for(world.manager_a1), world.farm_a1)["purge"] == []


def test_pull_of_other_tenant_is_404(world, client_for):
    response = client_for(world.admin_a).get(PULL, {"farm_id": str(world.farm_b1.id)})
    assert response.status_code == 404
    response = client_for(world.outsider).get(PULL, {"farm_id": str(world.farm_a1.id)})
    assert response.status_code == 404


def test_pull_never_contains_other_farm_data(world, client_for):
    make_parcel(world.farm_a2, code="OTHER-FARM")
    push(client_for(world.admin_a), create_parcel_op(world.farm_a2, code="OTHER-2"))
    payload = client_for(world.admin_a).get(PULL, {"farm_id": str(world.farm_a1.id)}).content
    assert b"OTHER" not in payload
    assert str(world.farm_a2.id).encode() not in payload


def test_compacted_cursor_returns_410(world, client_for):
    FarmSyncState.objects.filter(farm=world.farm_a1).update(compacted_before_seq=5)
    response = client_for(world.manager_a1).get(
        PULL, {"farm_id": str(world.farm_a1.id), "cursor": 2}
    )
    assert response.status_code == 410
    assert response.json()["details"]["min_cursor"] == 5


def test_revoked_membership_blocks_push_and_pull(world, client_for):
    from apps.farms.models import FarmMembership

    FarmMembership.objects.filter(user=world.manager_a1, farm=world.farm_a1).update(
        status="disabled"
    )
    client = client_for(world.manager_a1)
    assert client.get(PULL, {"farm_id": str(world.farm_a1.id)}).status_code == 404
    assert push(client, create_parcel_op(world.farm_a1))[0]["error"]["code"] == "not_found"


def test_rest_and_sync_writes_share_the_same_journal(world, client_for):
    client = client_for(world.manager_a1)
    cursor = pull(client, world.farm_a1)["next_cursor"]
    client.post(
        f"/api/v1/farms/{world.farm_a1.id}/parcels/",
        {"name": "REST", "code": "REST-1", "area_m2": "10"},
        format="json",
    )
    changes = pull(client, world.farm_a1, cursor=cursor)["changes"]
    assert [c["data"]["code"] for c in changes] == ["REST-1"]
