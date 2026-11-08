import zoneinfo
from typing import Any

from rest_framework import serializers

from apps.organizations.models import Invitation, Organization, OrganizationMembership, Role
from apps.users.serializers import UserPublicSerializer


def validate_timezone(value: str) -> None:
    try:
        zoneinfo.ZoneInfo(value)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as exc:
        raise serializers.ValidationError("Fuseau horaire inconnu.") from exc


class OrganizationSerializer(serializers.ModelSerializer):
    default_timezone = serializers.CharField(validators=[validate_timezone])

    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
            "slug",
            "country",
            "default_currency",
            "default_timezone",
            "default_locale",
            "status",
            "version",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "slug", "status", "version", "created_at", "updated_at"]


class RoleSerializer(serializers.ModelSerializer):
    # Output is added in to_representation from the related RolePermission rows.
    permissions = serializers.ListField(
        child=serializers.CharField(), required=False, write_only=True
    )

    class Meta:
        model = Role
        fields = ["id", "code", "name", "description", "is_system", "permissions", "version"]
        read_only_fields = ["id", "is_system", "version"]

    def to_representation(self, instance: Role) -> dict[str, Any]:
        data = super().to_representation(instance)
        data["permissions"] = sorted(instance.permission_codes())
        return data


class RoleUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    permissions = serializers.ListField(child=serializers.CharField(), required=False)


class OrganizationMembershipSerializer(serializers.ModelSerializer):
    user = UserPublicSerializer(read_only=True)

    class Meta:
        model = OrganizationMembership
        fields = ["id", "user", "is_org_admin", "status", "version", "created_at"]
        read_only_fields = ["id", "user", "version", "created_at"]


class OrganizationMembershipUpdateSerializer(serializers.Serializer):
    is_org_admin = serializers.BooleanField(required=False)
    status = serializers.ChoiceField(choices=OrganizationMembership.Status.choices, required=False)


class InvitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invitation
        fields = [
            "id",
            "email",
            "phone",
            "farm",
            "role",
            "make_org_admin",
            "expires_at",
            "accepted_at",
            "revoked_at",
            "created_at",
        ]
        read_only_fields = fields


class InvitationCreateSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_null=True)
    phone = serializers.CharField(required=False, allow_null=True, max_length=20)
    farm = serializers.UUIDField(required=False, allow_null=True)
    role = serializers.UUIDField(required=False, allow_null=True)
    make_org_admin = serializers.BooleanField(default=False)


class InvitationCreatedSerializer(InvitationSerializer):
    token = serializers.CharField(read_only=True, help_text="Affiché une seule fois.")

    class Meta(InvitationSerializer.Meta):
        fields = [*InvitationSerializer.Meta.fields, "token"]
        read_only_fields = fields


class InvitationAcceptSerializer(serializers.Serializer):
    token = serializers.CharField()
    full_name = serializers.CharField(required=False, allow_blank=True, max_length=200)
    password = serializers.CharField(
        required=False, allow_blank=True, write_only=True, trim_whitespace=False
    )


class PermissionSerializer(serializers.Serializer):
    code = serializers.CharField()
    description = serializers.CharField()
