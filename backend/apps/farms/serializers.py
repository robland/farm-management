from typing import Any

from rest_framework import serializers

from apps.farms.models import Farm, FarmMembership, validate_farm_settings
from apps.organizations.serializers import validate_timezone
from apps.users.serializers import UserPublicSerializer, UserSerializer


class FarmSerializer(serializers.ModelSerializer):
    timezone = serializers.CharField(validators=[validate_timezone])

    class Meta:
        model = Farm
        fields = [
            "id",
            "organization",
            "name",
            "code",
            "country",
            "region",
            "locality",
            "latitude",
            "longitude",
            "timezone",
            "currency",
            "locale",
            "declared_area_m2",
            "settings",
            "status",
            "version",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "organization", "version", "created_at", "updated_at"]

    def validate_settings(self, value: Any) -> Any:
        from django.core.exceptions import ValidationError

        try:
            validate_farm_settings(value)
        except ValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return value


class FarmMembershipSerializer(serializers.ModelSerializer):
    user = UserPublicSerializer(read_only=True)
    role_code = serializers.CharField(source="role.code", read_only=True)

    class Meta:
        model = FarmMembership
        fields = [
            "id",
            "user",
            "role",
            "role_code",
            "status",
            "valid_from",
            "valid_to",
            "version",
            "created_at",
        ]
        read_only_fields = ["id", "user", "role", "role_code", "version", "created_at"]


class FarmMembershipCreateSerializer(serializers.Serializer):
    user = serializers.UUIDField()
    role = serializers.UUIDField()
    valid_from = serializers.DateField(required=False, allow_null=True)
    valid_to = serializers.DateField(required=False, allow_null=True)


class FarmMembershipUpdateSerializer(serializers.Serializer):
    role = serializers.UUIDField(required=False)
    status = serializers.ChoiceField(choices=FarmMembership.Status.choices, required=False)
    valid_from = serializers.DateField(required=False, allow_null=True)
    valid_to = serializers.DateField(required=False, allow_null=True)


class AccessibleFarmSerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(source="organization.name", read_only=True)

    class Meta:
        model = Farm
        fields = [
            "id",
            "organization",
            "organization_name",
            "name",
            "code",
            "timezone",
            "currency",
            "locale",
            "status",
            "version",
        ]
        read_only_fields = fields


class MeFarmSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    organization_id = serializers.UUIDField()
    role = serializers.CharField(allow_null=True)
    is_org_admin = serializers.BooleanField()
    permissions = serializers.ListField(child=serializers.CharField())


class MeOrganizationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    is_org_admin = serializers.BooleanField()


class MeSerializer(serializers.Serializer):
    user = UserSerializer()
    organizations = MeOrganizationSerializer(many=True)
    farms = MeFarmSerializer(many=True)
