from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin, ReadOnlyTabularInline, register_read_only
from apps.organizations.models import (
    Invitation,
    Organization,
    OrganizationMembership,
    Role,
    RolePermission,
)


class MembershipInline(ReadOnlyTabularInline):
    model = OrganizationMembership
    fields = ["user", "is_org_admin", "status"]


@admin.register(Organization)
class OrganizationAdmin(ReadOnlyAdmin):
    inlines = [MembershipInline]


class RolePermissionInline(ReadOnlyTabularInline):
    model = RolePermission
    fields = ["permission_code"]
    show_change_link = False


@admin.register(Role)
class RoleAdmin(ReadOnlyAdmin):
    inlines = [RolePermissionInline]


@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(ReadOnlyAdmin):
    list_display = ["user", "organization", "is_org_admin", "status", "created_at"]
    list_select_related = ["user", "organization"]
    search_fields = ["user__full_name", "user__email", "user__phone", "organization__name"]
    list_filter = ["status", "is_org_admin"]


@admin.register(Invitation)
class InvitationAdmin(ReadOnlyAdmin):
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


register_read_only(RolePermission)
