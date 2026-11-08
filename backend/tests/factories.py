"""Test data builders. All data is fictitious and for tests only."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from apps.farms.models import Farm, FarmMembership
from apps.farms.services import create_farm
from apps.fields.models import Field, Parcel
from apps.organizations.access import resolve_org_context
from apps.organizations.models import Organization, OrganizationMembership, Role
from apps.organizations.services import create_organization
from apps.users.models import User

PASSWORD = "Test-passw0rd!x"
_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


def make_user(**kwargs: Any) -> User:
    n = _next()
    kwargs.setdefault("email", f"user{n}@example.test")
    kwargs.setdefault("full_name", f"Utilisateur {n}")
    return User.objects.create_user(password=PASSWORD, **kwargs)


def make_org(admin: User, name: str | None = None) -> Organization:
    return create_organization(
        user=admin,
        name=name or f"Organisation {_next()}",
        country="CG",
        default_currency="XAF",
        default_timezone="Africa/Brazzaville",
    )


def make_farm(org: Organization, admin: User, **kwargs: Any) -> Farm:
    n = _next()
    data = {
        "name": f"Exploitation {n}",
        "code": f"farm-{n}",
        "country": "CG",
        "timezone": "Africa/Brazzaville",
        "currency": "XAF",
        **kwargs,
    }
    return create_farm(resolve_org_context(admin, org.id), data=data)


def add_member(org: Organization, farm: Farm | None, user: User, role_code: str | None) -> None:
    OrganizationMembership.objects.get_or_create(organization=org, user=user)
    if farm is not None and role_code is not None:
        FarmMembership.objects.create(
            organization=org,
            farm=farm,
            user=user,
            role=Role.objects.get(organization=org, code=role_code),
        )


def make_field(farm: Farm, **kwargs: Any) -> Field:
    n = _next()
    return Field.objects.create(
        organization_id=farm.organization_id,
        farm=farm,
        name=kwargs.pop("name", f"Champ {n}"),
        code=kwargs.pop("code", f"C{n}"),
        **kwargs,
    )


def make_parcel(farm: Farm, **kwargs: Any) -> Parcel:
    n = _next()
    return Parcel.objects.create(
        organization_id=farm.organization_id,
        farm=farm,
        name=kwargs.pop("name", f"Parcelle {n}"),
        code=kwargs.pop("code", f"P{n}"),
        area_m2=kwargs.pop("area_m2", Decimal("1000")),
        **kwargs,
    )


@dataclass
class World:
    """Two organizations; org A has two farms. Used by tenancy tests."""

    org_a: Organization
    org_b: Organization
    farm_a1: Farm
    farm_a2: Farm
    farm_b1: Farm
    admin_a: User
    admin_b: User
    manager_a1: User
    worker_a1: User  # worker on A1, technician on A2
    finance_a1: User
    outsider: User  # member of org A without any farm role


def make_world() -> World:
    admin_a, admin_b = make_user(full_name="Admin A"), make_user(full_name="Admin B")
    org_a, org_b = make_org(admin_a, "Org A"), make_org(admin_b, "Org B")
    farm_a1, farm_a2 = make_farm(org_a, admin_a), make_farm(org_a, admin_a)
    farm_b1 = make_farm(org_b, admin_b)
    manager_a1, worker_a1 = make_user(), make_user(phone="+242061234567")
    finance_a1, outsider = make_user(), make_user()
    add_member(org_a, farm_a1, manager_a1, "farm_manager")
    add_member(org_a, farm_a1, worker_a1, "worker")
    add_member(org_a, farm_a2, worker_a1, "technician")
    add_member(org_a, farm_a1, finance_a1, "finance_manager")
    add_member(org_a, None, outsider, None)
    return World(
        org_a,
        org_b,
        farm_a1,
        farm_a2,
        farm_b1,
        admin_a,
        admin_b,
        manager_a1,
        worker_a1,
        finance_a1,
        outsider,
    )
