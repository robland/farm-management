"""Django admin: every model is consultable; writes never bypass the services (Q34)."""

import uuid

import pytest
from django.apps import apps
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.crops.models import Crop
from apps.fields.models import Parcel
from apps.finance.models import FinancialTransaction
from apps.organizations.models import Invitation
from apps.users.models import Device, User
from tests.factories import World, make_user
from tests.factories_catalog import make_crop
from tests.tenancy.test_isolation import _objects_of_org_a

pytestmark = pytest.mark.django_db

PROJECT_MODELS = [m for m in apps.get_models() if m.__module__.startswith("apps.")]


def _admin_url(model: type, view: str, *args: object) -> str:
    return reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_{view}", args=args)


@pytest.fixture
def superuser_client() -> Client:
    client = Client()
    client.force_login(make_user(is_staff=True, is_superuser=True))
    return client


@pytest.fixture
def populated(world: World) -> World:
    _objects_of_org_a(world)
    return world


def test_every_project_model_is_registered() -> None:
    missing = [m._meta.label for m in PROJECT_MODELS if m not in admin.site._registry]
    assert missing == []


@pytest.mark.parametrize("model", PROJECT_MODELS, ids=lambda m: m._meta.label)
def test_changelist_search_and_detail_render(populated, superuser_client, model) -> None:
    assert superuser_client.get(_admin_url(model, "changelist")).status_code == 200
    # A free-text term must not break the exact-id search (non-UUID input).
    assert superuser_client.get(_admin_url(model, "changelist"), {"q": "abc"}).status_code == 200
    obj = model._default_manager.first()
    if obj is not None:
        assert superuser_client.get(_admin_url(model, "change", obj.pk)).status_code == 200


@pytest.mark.parametrize("model", PROJECT_MODELS, ids=lambda m: m._meta.label)
def test_add_page_renders_when_creation_is_offered(populated, superuser_client, model) -> None:
    model_admin = admin.site._registry[model]
    request = superuser_client.get(_admin_url(model, "changelist")).wsgi_request
    expected = 200 if model_admin.has_add_permission(request) else 403
    assert superuser_client.get(_admin_url(model, "add")).status_code == expected


def test_derived_admin_searches_by_exact_id(populated, superuser_client) -> None:
    parcels = list(Parcel.objects.all()[:2])
    assert len(parcels) == 2
    response = superuser_client.get(_admin_url(Parcel, "changelist"), {"q": str(parcels[0].id)})
    assert list(response.context["cl"].result_list) == [parcels[0]]


def test_most_models_have_a_rendered_detail_page(populated) -> None:
    # Guards the test above against silently checking empty tables only.
    with_objects = [m for m in PROJECT_MODELS if m._default_manager.exists()]
    assert len(with_objects) >= len(PROJECT_MODELS) // 2


def test_validated_transactions_cannot_be_changed_or_deleted(populated, superuser_client) -> None:
    tx = FinancialTransaction.objects.filter(status=FinancialTransaction.Status.VALIDATED).first()
    assert tx is not None
    # Recording goes through the service (see test_admin_flows); deletion never exists.
    assert superuser_client.get(_admin_url(FinancialTransaction, "add")).status_code == 200
    assert (
        superuser_client.get(_admin_url(FinancialTransaction, "delete", tx.pk)).status_code == 403
    )
    before = (tx.amount, tx.status, tx.version)
    response = superuser_client.post(
        _admin_url(FinancialTransaction, "change", tx.pk), {"amount": "1", "status": "rejected"}
    )
    assert response.status_code == 403
    tx.refresh_from_db()
    assert (tx.amount, tx.status, tx.version) == before


def test_secrets_are_never_displayed(populated, superuser_client) -> None:
    invitation = Invitation.objects.first()
    assert invitation is not None
    page = superuser_client.get(_admin_url(Invitation, "change", invitation.pk))
    assert invitation.token_hash not in page.content.decode()
    user = User.objects.first()
    page = superuser_client.get(_admin_url(User, "change", user.pk))
    assert user.password not in page.content.decode()


def test_staff_without_view_permission_is_refused(populated) -> None:
    client = Client()
    client.force_login(make_user(is_staff=True))
    assert client.get(_admin_url(FinancialTransaction, "changelist")).status_code == 403


def test_non_staff_users_are_redirected_to_login(populated) -> None:
    client = Client()
    client.force_login(populated.admin_a)  # organization admin, not platform staff
    response = client.get(_admin_url(FinancialTransaction, "changelist"))
    assert response.status_code == 302
    assert reverse("admin:login") in response["Location"]


def test_global_crop_is_created_and_edited_with_audit(superuser_client) -> None:
    response = superuser_client.post(
        _admin_url(Crop, "add"),
        {
            "common_name": "Gombo",
            "scientific_name": "Abelmoschus esculentus",
            "category": "vegetable",
        },
    )
    assert response.status_code == 302
    crop = Crop.objects.get(common_name="Gombo")
    assert crop.organization_id is None and crop.version == 1
    assert AuditEvent.objects.filter(action="crop.created", entity_id=crop.id).exists()

    response = superuser_client.post(
        _admin_url(Crop, "change", crop.pk),
        {"common_name": "Gombo", "family": "Malvaceae", "category": "vegetable"},
    )
    assert response.status_code == 302
    crop.refresh_from_db()
    assert crop.family == "Malvaceae" and crop.version == 2
    event = AuditEvent.objects.get(action="crop.updated", entity_id=crop.id)
    assert event.after == {"family": "Malvaceae", "scientific_name": ""}


def test_organization_crop_is_edited_through_the_service(world, superuser_client) -> None:
    crop = make_crop(world.org_a, name="Culture privée")
    response = superuser_client.post(
        _admin_url(Crop, "change", crop.pk),
        {"common_name": "Renommée", "category": "other", "expected_version": crop.version},
    )
    assert response.status_code == 302
    crop.refresh_from_db()
    assert crop.common_name == "Renommée" and crop.version == 2
    assert crop.organization_id == world.org_a.id
    assert AuditEvent.objects.filter(action="crop.updated", entity_id=crop.id).exists()
    # Shared catalogue crops cannot be deleted; an organization's crop can (service rules).
    assert superuser_client.get(_admin_url(Crop, "delete", crop.pk)).status_code == 200


def test_user_deactivation_is_audited(world, superuser_client) -> None:
    target = world.worker_a1
    response = superuser_client.post(
        _admin_url(User, "change", target.pk),
        {
            "full_name": target.full_name,
            "locale": target.locale,
            "is_staff": "",
            "is_superuser": "",
        },
    )
    assert response.status_code == 302
    target.refresh_from_db()
    assert target.is_active is False
    event = AuditEvent.objects.get(action="admin.user_updated", entity_id=target.id)
    assert event.after == {"is_active": False}


def test_only_superuser_may_grant_staff_rights(world) -> None:
    staff = make_user(is_staff=True)
    staff.user_permissions.add(
        *Permission.objects.filter(codename__in=["view_user", "change_user"])
    )
    client = Client()
    client.force_login(staff)
    target = world.worker_a1
    response = client.post(
        _admin_url(User, "change", target.pk),
        {"full_name": target.full_name, "locale": "fr", "is_active": "on", "is_staff": "on"},
    )
    assert response.status_code == 302
    target.refresh_from_db()
    assert target.is_staff is False


def test_device_revocation_action_is_audited(world, superuser_client) -> None:
    device = Device.objects.create(id=uuid.uuid4(), user=world.worker_a1, label="Téléphone perdu")
    response = superuser_client.post(
        _admin_url(Device, "changelist"),
        {"action": "revoke_devices", "_selected_action": [str(device.pk)]},
    )
    assert response.status_code == 302
    device.refresh_from_db()
    assert device.revoked_at is not None
    assert AuditEvent.objects.filter(action="auth.device_revoked", entity_id=device.id).exists()
