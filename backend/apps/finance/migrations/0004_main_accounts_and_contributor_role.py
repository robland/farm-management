"""Data for the accounts and fundings model (OPEN_QUESTIONS Q35).

1. The oldest account of each farm becomes its main account (the treasury).
2. Existing organizations get the "finance.funding.create" permission on the roles that
   manage finances, and the new "contributor" role. Values are written out here, not
   imported from the catalogue, so that later catalogue changes do not alter history.
"""

from django.db import migrations

FUNDING = "finance.funding.create"
ROLES_GAINING_FUNDING = ("org_admin", "farm_manager", "finance_manager")
CONTRIBUTOR = {
    "code": "contributor",
    "name": "Membre contributeur",
    "permissions": ("farm.view", FUNDING),
}


def forwards(apps, schema_editor):
    TreasuryAccount = apps.get_model("finance", "TreasuryAccount")
    Organization = apps.get_model("organizations", "Organization")
    Role = apps.get_model("organizations", "Role")
    RolePermission = apps.get_model("organizations", "RolePermission")

    seen_farms = set()
    for account in TreasuryAccount.objects.order_by("farm_id", "created_at", "id"):
        if account.farm_id in seen_farms:
            continue
        seen_farms.add(account.farm_id)
        account.role = "main"
        account.save(update_fields=["role"])

    for organization in Organization.objects.all():
        for role in Role.objects.filter(organization=organization, code__in=ROLES_GAINING_FUNDING):
            RolePermission.objects.get_or_create(role=role, permission_code=FUNDING)
        contributor, _ = Role.objects.get_or_create(
            organization=organization,
            code=CONTRIBUTOR["code"],
            defaults={"name": CONTRIBUTOR["name"], "is_system": True},
        )
        for code in CONTRIBUTOR["permissions"]:
            RolePermission.objects.get_or_create(role=contributor, permission_code=code)


def backwards(apps, schema_editor):
    TreasuryAccount = apps.get_model("finance", "TreasuryAccount")
    TreasuryAccount.objects.filter(role="main").update(role="operating")
    RolePermission = apps.get_model("organizations", "RolePermission")
    RolePermission.objects.filter(permission_code=FUNDING).delete()
    # The contributor roles are kept: memberships may already reference them.


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0003_accounts_roles_funding_loans"),
        ("organizations", "0002_initial"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
