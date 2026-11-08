from typing import Any

from django import forms
from django.contrib import admin, messages
from django.http import HttpRequest

from apps.core.admin import ReadOnlyTabularInline, register_read_only
from apps.core.admin_services import ServiceAdmin, ServiceForm, platform_context, service_action
from apps.core.tenancy import TenantContext
from apps.organizations import services
from apps.organizations.models import (
    Invitation,
    Organization,
    OrganizationMembership,
    Role,
    RolePermission,
)
from apps.organizations.permissions_catalog import PERMISSIONS
from apps.users.models import User


class MembershipInline(ReadOnlyTabularInline):
    model = OrganizationMembership
    fields = ["user", "is_org_admin", "status"]


class OrganizationForm(ServiceForm):
    owner = forms.ModelChoiceField(
        label="Administrateur",
        queryset=User.objects.filter(is_active=True),
        required=False,
        help_text="Devient administrateur de l'organisation (création uniquement).",
    )


@admin.register(Organization)
class OrganizationAdmin(ServiceAdmin):
    form = OrganizationForm
    scope = None
    add_fields = [
        "owner",
        "name",
        "country",
        "default_currency",
        "default_timezone",
        "default_locale",
    ]
    change_fields = ["name", "country", "default_currency", "default_timezone", "default_locale"]
    inlines = [MembershipInline]

    def context_for(self, request: HttpRequest, obj: Any) -> TenantContext:
        return platform_context(request, organization_id=obj.id)

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> Organization:
        owner = data.pop("owner")
        if owner is None:
            raise forms.ValidationError({"owner": "Champ obligatoire."})
        return services.create_organization(user=owner, **data)

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        return services.update_organization(ctx, expected_version=expected_version, changes=changes)


class RoleForm(ServiceForm):
    permission_codes = forms.MultipleChoiceField(
        label="Permissions",
        choices=sorted(PERMISSIONS.items()),
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if not self.instance._state.adding:
            self.fields["permission_codes"].initial = sorted(self.instance.permission_codes())


class RolePermissionInline(ReadOnlyTabularInline):
    model = RolePermission
    fields = ["permission_code"]
    show_change_link = False


@admin.register(Role)
class RoleAdmin(ServiceAdmin):
    form = RoleForm
    scope = "organization"
    add_fields = ["code", "name", "description", "permission_codes"]
    change_fields = ["name", "description", "permission_codes"]
    inlines = [RolePermissionInline]

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> Role:
        return services.create_role(
            ctx,
            code=data["code"],
            name=data["name"],
            description=data.get("description", ""),
            permissions=list(data.get("permission_codes", [])),
        )

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        codes = changes.pop("permission_codes", None)
        return services.update_role(
            ctx,
            role_id=obj.id,
            expected_version=expected_version,
            changes=changes,
            permissions=list(codes) if codes is not None else None,
        )

    def perform_delete(self, ctx: TenantContext, obj: Role) -> None:
        services.delete_role(ctx, role_id=obj.id)


@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(ServiceAdmin):
    """Members join through invitations; their admin flag and status are managed here."""

    list_display = ["user", "organization", "is_org_admin", "status", "created_at"]
    list_select_related = ["user", "organization"]
    search_fields = ["user__full_name", "user__email", "user__phone", "organization__name"]
    list_filter = ["status", "is_org_admin"]
    change_fields = ["is_org_admin", "status"]

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        return services.update_org_membership(
            ctx, membership_id=obj.id, expected_version=expected_version, changes=changes
        )


@admin.register(Invitation)
class InvitationAdmin(ServiceAdmin):
    list_display = [
        "email",
        "phone",
        "organization",
        "farm",
        "role",
        "expires_at",
        "accepted_at",
        "revoked_at",
    ]
    list_select_related = ["organization", "farm", "role"]
    search_fields = ["email", "phone", "organization__name"]
    list_filter = [
        ("accepted_at", admin.EmptyFieldListFilter),
        ("revoked_at", admin.EmptyFieldListFilter),
    ]
    scope = "organization"
    add_fields = ["email", "phone", "farm", "role", "make_org_admin"]
    actions = ["revoke"]

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> Invitation:
        invitation, token = services.create_invitation(
            ctx,
            email=data.get("email") or None,
            phone=data.get("phone") or None,
            farm_id=data["farm"].id if data.get("farm") else None,
            role_id=data["role"].id if data.get("role") else None,
            make_org_admin=bool(data.get("make_org_admin")),
        )
        invitation._plain_token = token  # type: ignore[attr-defined]  # never persisted
        return invitation

    def response_add(self, request: HttpRequest, obj: Any, post_url_continue: Any = None) -> Any:
        token = getattr(obj, "_plain_token", None)
        if token:
            # Only the hash is stored: the token is shown once, to be sent to the invitee.
            self.message_user(
                request, f"Jeton d'invitation (affiché une seule fois) : {token}", messages.WARNING
            )
        return super().response_add(request, obj, post_url_continue)

    @service_action("Révoquer les invitations")
    def revoke(self, ctx: TenantContext, obj: Invitation) -> None:
        services.revoke_invitation(ctx, invitation_id=obj.id)


register_read_only(RolePermission)
