"""Fictitious data for the load tests (backend/loadtest/README.md).

Creates, through the business services, one organization clearly named as fictitious,
one farm, N farm managers sharing the password given in LOAD_TEST_PASSWORD, parcels,
a treasury account and an expense category. Idempotent: re-running it reuses what exists.
Never run it on the pilot database: it is meant for a copy or a test stack.
"""

import os
from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from apps.farms.access import resolve_farm_context
from apps.farms.models import Farm, FarmMembership
from apps.farms.services import add_farm_member, create_farm
from apps.fields import services as fields
from apps.fields.models import Parcel
from apps.finance import services as finance
from apps.finance.models import FinanceCategory, TreasuryAccount
from apps.organizations.access import resolve_org_context
from apps.organizations.models import Organization, OrganizationMembership, Role
from apps.organizations.services import create_organization
from apps.users.models import User

ORG_NAME = "CHARGE — données fictives"
FARM_CODE = "charge"
EMAIL = "charge-{:03d}@example.invalid"


class Command(BaseCommand):
    help = "Prépare des données fictives pour les tests de charge (jamais sur le pilote)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--users", type=int, default=20)
        parser.add_argument("--parcels", type=int, default=50)
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Confirme que la base cible est une copie ou une pile de test.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not options["confirm"]:
            raise CommandError("Ajoutez --confirm : cette commande crée des données fictives.")
        password = os.environ.get("LOAD_TEST_PASSWORD", "")
        if len(password) < 12:
            raise CommandError("LOAD_TEST_PASSWORD (12 caractères au moins) est obligatoire.")
        with transaction.atomic():
            farm = self._prepare(options["users"], options["parcels"], password)
        self.stdout.write(
            f"Exploitation {farm.id} ; comptes {EMAIL.format(1)} à {EMAIL.format(options['users'])}"
        )

    def _user(self, index: int, password: str) -> User:
        email = EMAIL.format(index)
        user = User.objects.filter(email=email).first()
        if user is None:
            user = User.objects.create_user(email, password, full_name=f"Charge {index:03d}")
        return user

    def _prepare(self, users: int, parcels: int, password: str) -> Farm:
        owner = self._user(1, password)
        org = Organization.objects.filter(name=ORG_NAME).first() or create_organization(
            user=owner,
            name=ORG_NAME,
            country="CG",
            default_currency="XAF",
            default_timezone="Africa/Brazzaville",
        )
        farm = Farm.objects.filter(organization=org, code=FARM_CODE).first() or create_farm(
            resolve_org_context(owner, org.id),
            data={
                "name": "Exploitation de charge (fictive)",
                "code": FARM_CODE,
                "country": "CG",
                "timezone": "Africa/Brazzaville",
                "currency": "XAF",
            },
        )
        role = Role.objects.get(organization=org, code="farm_manager")
        org_ctx = resolve_farm_context(owner, farm.id)
        for index in range(1, users + 1):
            user = self._user(index, password)
            OrganizationMembership.objects.get_or_create(organization=org, user=user)
            if not FarmMembership.objects.filter(farm=farm, user=user).exists():
                add_farm_member(org_ctx, user_id=user.id, role_id=role.id)
        existing = Parcel.objects.filter(farm=farm).count()
        for index in range(existing + 1, parcels + 1):
            fields.create_parcel(
                org_ctx,
                data={
                    "name": f"Parcelle fictive {index}",
                    "code": f"CH-{index:03d}",
                    "area_m2": Decimal(500),
                },
            )
        if not TreasuryAccount.objects.filter(farm=farm).exists():
            finance.create_account(
                org_ctx, data={"name": "Caisse fictive", "kind": "cash", "currency": "XAF"}
            )
        if not FinanceCategory.objects.filter(organization=org, kind="expense").exists():
            finance.create_category(
                org_ctx, data={"kind": "expense", "code": "charge", "name": "Dépenses fictives"}
            )
        return farm
