"""Admin CRUD and workflows go through the business services (Q34)."""

from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.crops.models import Crop
from apps.fields.models import Parcel
from apps.inventory.models import CatalogItem, PriceList, PriceListItem, Supplier
from apps.organizations.models import Invitation, Organization, OrganizationMembership, Role
from apps.synchronization.models import ChangeLog
from apps.varieties.models import TechnicalDataItem, TechnicalDataSet
from tests.factories import World, make_field, make_parcel, make_user
from tests.factories_catalog import make_variety

pytestmark = pytest.mark.django_db


def url(model: type, view: str, *args: object) -> str:
    return reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_{view}", args=args)


def form_errors(response: Any) -> Any:
    context = getattr(response, "context", None)
    if not context or "adminform" not in context:
        return None
    form = context["adminform"].form
    return {"fields": dict(form.errors), "non_field": list(form.non_field_errors())}


def assert_saved(response: Any) -> None:
    assert response.status_code == 302, form_errors(response)


@pytest.fixture
def staff() -> Any:
    return make_user(is_staff=True, is_superuser=True, full_name="Support")


@pytest.fixture
def client(staff: Any) -> Client:
    c = Client()
    c.force_login(staff)
    return c


PARCEL = {
    "name": "Parcelle admin",
    "code": "ADM-1",
    "area_m2": "500",
    "water_availability": "unknown",
    "status": "active",
}


def test_parcel_created_through_service_with_change_log_and_audit(world: World, client, staff):
    response = client.post(url(Parcel, "add"), {"farm": world.farm_a1.pk, **PARCEL})
    assert_saved(response)
    parcel = Parcel.objects.get(code="ADM-1")
    assert parcel.farm_id == world.farm_a1.id and parcel.organization_id == world.org_a.id
    assert parcel.version == 1 and parcel.created_by == staff
    # Offline clients will receive it: the service wrote the synchronisation change log.
    assert ChangeLog.objects.filter(entity_id=parcel.id, farm=world.farm_a1).exists()
    assert AuditEvent.objects.filter(entity_id=parcel.id, actor=staff).exists()


def test_parcel_update_increments_version_and_detects_concurrent_edit(world: World, client):
    parcel = make_parcel(world.farm_a1)
    data = {**PARCEL, "code": parcel.code, "expected_version": parcel.version}
    assert_saved(client.post(url(Parcel, "change", parcel.pk), {**data, "name": "Renommée"}))
    parcel.refresh_from_db()
    assert parcel.name == "Renommée" and parcel.version == 2
    # A form displayed before that change (version 1) is refused, nothing is overwritten.
    stale = client.post(url(Parcel, "change", parcel.pk), {**data, "name": "Écrasée"})
    assert stale.status_code == 200
    assert "modifiée entre-temps" in str(form_errors(stale))
    parcel.refresh_from_db()
    assert parcel.name == "Renommée" and parcel.version == 2


def test_references_of_another_farm_are_refused(world: World, client):
    foreign_field = make_field(world.farm_b1)
    response = client.post(
        url(Parcel, "add"), {"farm": world.farm_a1.pk, "field": foreign_field.pk, **PARCEL}
    )
    assert response.status_code == 200
    assert not Parcel.objects.filter(code="ADM-1").exists()


def test_add_form_scoped_by_query_string_only_offers_that_farm(world: World, client):
    own, foreign = make_field(world.farm_a1), make_field(world.farm_b1)
    response = client.get(url(Parcel, "add"), {"farm": str(world.farm_a1.pk)})
    choices = list(response.context["adminform"].form.fields["field"].queryset)
    assert own in choices and foreign not in choices


def test_parcel_delete_is_a_tombstone_through_the_service(world: World, client):
    parcel = make_parcel(world.farm_a1)
    assert_saved(client.post(url(Parcel, "delete", parcel.pk), {"post": "yes"}))
    parcel.refresh_from_db()
    assert parcel.deleted_at is not None
    assert ChangeLog.objects.filter(entity_id=parcel.id, operation="delete").exists()


def test_bulk_delete_action_is_not_offered(world: World, client):
    make_parcel(world.farm_a1)
    response = client.get(url(Parcel, "changelist"))
    assert "delete_selected" not in response.content.decode()


def test_staff_needs_the_django_add_permission(world: World):
    viewer = make_user(is_staff=True)
    viewer.user_permissions.add(Permission.objects.get(codename="view_parcel"))
    c = Client()
    c.force_login(viewer)
    assert c.get(url(Parcel, "add")).status_code == 403
    response = c.post(url(Parcel, "add"), {"farm": world.farm_a1.pk, **PARCEL})
    assert response.status_code == 403
    assert not Parcel.objects.filter(code="ADM-1").exists()


def test_organization_created_with_its_owner_and_default_roles(client):
    owner = make_user(full_name="Nouvelle gérante")
    response = client.post(
        url(Organization, "add"),
        {
            "owner": owner.pk,
            "name": "Coopérative du Pool",
            "country": "CG",
            "default_currency": "XAF",
            "default_timezone": "Africa/Brazzaville",
            "default_locale": "fr",
        },
    )
    assert_saved(response)
    org = Organization.objects.get(name="Coopérative du Pool")
    assert OrganizationMembership.objects.get(organization=org, user=owner).is_org_admin
    assert Role.objects.filter(organization=org).exists()


def test_role_created_and_permissions_replaced(world: World, client):
    response = client.post(
        url(Role, "add"),
        {
            "organization": world.org_a.pk,
            "code": "controleur",
            "name": "Contrôleur",
            "description": "",
            "permission_codes": ["farm.view", "finance.view"],
        },
    )
    assert_saved(response)
    role = Role.objects.get(organization=world.org_a, code="controleur")
    assert role.permission_codes() == {"farm.view", "finance.view"}
    response = client.post(
        url(Role, "change", role.pk),
        {
            "name": "Contrôleur",
            "description": "Lecture seule",
            "permission_codes": ["farm.view"],
            "expected_version": role.version,
        },
    )
    assert_saved(response)
    role.refresh_from_db()
    assert role.permission_codes() == {"farm.view"} and role.description == "Lecture seule"


def test_invitation_token_shown_once_and_revocation_action(world: World, client):
    response = client.post(
        url(Invitation, "add"),
        {"organization": world.org_a.pk, "email": "nouveau@example.test"},
        follow=True,
    )
    shown = [str(m) for m in response.context["messages"]]
    assert any("Jeton d'invitation" in m for m in shown)
    invitation = Invitation.objects.get(email="nouveau@example.test")
    token = next(m for m in shown if "Jeton" in m).rsplit(" ", 1)[-1]
    assert token not in invitation.token_hash  # only the hash is stored
    response = client.post(
        url(Invitation, "changelist"),
        {"action": "revoke", "_selected_action": [str(invitation.pk)]},
    )
    assert response.status_code == 302
    invitation.refresh_from_db()
    assert invitation.revoked_at is not None


def test_organization_crop_goes_through_the_service(world: World, client):
    response = client.post(
        url(Crop, "add"),
        {"organization": world.org_a.pk, "common_name": "Piment local", "category": "vegetable"},
    )
    assert_saved(response)
    crop = Crop.objects.get(common_name="Piment local")
    assert crop.organization_id == world.org_a.id
    assert AuditEvent.objects.filter(action="crop.created", entity_id=crop.id).exists()


def test_technical_data_flow_from_draft_to_validated(world: World, client):
    variety = make_variety(world.org_a)
    assert_saved(client.post(url(TechnicalDataSet, "add"), {"variety": variety.pk, "notes": ""}))
    data_set = TechnicalDataSet.objects.get(variety=variety)
    assert data_set.status == TechnicalDataSet.Status.DRAFT
    response = client.post(
        url(TechnicalDataItem, "add"),
        {
            "data_set": data_set.pk,
            "key": "row_spacing",
            "value_numeric": "1.5",
            "unit": "m",
            "provenance": "user_input",
        },
    )
    assert_saved(response)
    item = TechnicalDataItem.objects.get(data_set=data_set, key="row_spacing")
    assert item.validated is False

    # The data set cannot be validated while an item is not.
    client.post(
        url(TechnicalDataSet, "changelist"),
        {"action": "validate", "_selected_action": [str(data_set.pk)]},
    )
    data_set.refresh_from_db()
    assert data_set.status == TechnicalDataSet.Status.DRAFT

    client.post(
        url(TechnicalDataItem, "changelist"),
        {"action": "validate_items", "_selected_action": [str(item.pk)]},
    )
    client.post(
        url(TechnicalDataSet, "changelist"),
        {"action": "validate", "_selected_action": [str(data_set.pk)]},
    )
    data_set.refresh_from_db()
    assert data_set.status == TechnicalDataSet.Status.VALIDATED
    # A validated data set is immutable: its items are no longer editable.
    item.refresh_from_db()
    assert client.post(url(TechnicalDataItem, "change", item.pk), {}).status_code == 403


def test_price_list_items_added_one_at_a_time(world: World, client):
    item = CatalogItem.objects.create(
        organization=world.org_a, category="pipe", name="Gaine 16 mm", base_unit="m"
    )
    supplier = Supplier.objects.create(organization=world.org_a, name="Agro-Fournitures")
    response = client.post(
        url(PriceList, "add"),
        {
            "organization": world.org_a.pk,
            "supplier": supplier.pk,
            "name": "Tarif 2026",
            "currency": "XAF",
            "valid_from": "2026-01-01",
            "status": "draft",
        },
    )
    assert_saved(response)
    price_list = PriceList.objects.get(name="Tarif 2026")
    response = client.post(
        url(PriceListItem, "add"),
        {"price_list": price_list.pk, "catalog_item": item.pk, "unit": "m", "unit_price": "150"},
    )
    assert_saved(response)
    price = price_list.items.get()
    assert price.unit_price == Decimal("150")

    price_list.refresh_from_db()
    response = client.post(
        url(PriceList, "change", price_list.pk),
        {
            "supplier": supplier.pk,
            "name": "Tarif 2026",
            "currency": "XAF",
            "valid_from": "2026-01-01",
            "status": "active",
            "expected_version": price_list.version,
        },
    )
    assert_saved(response)
    # An active price list is frozen (quotes copy its prices): its items are read-only.
    assert client.post(url(PriceListItem, "change", price.pk), {}).status_code == 403
