from typing import Any

from django.contrib.auth import authenticate
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from apps.users.models import Device, User


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField(help_text="E-mail ou numéro de téléphone (+242…).")
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    device_id = serializers.UUIDField(required=False)
    platform = serializers.ChoiceField(choices=Device.Platform.choices, default="other")
    device_label = serializers.CharField(required=False, allow_blank=True, max_length=100)
    client_version = serializers.CharField(required=False, allow_blank=True, max_length=50)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        user = authenticate(
            self.context.get("request"), username=attrs["identifier"], password=attrs["password"]
        )
        if user is None:
            raise serializers.ValidationError("Identifiants invalides.", code="invalid_credentials")
        attrs["user"] = user
        return attrs

    def create(self, validated_data: dict[str, Any]) -> dict[str, Any]:
        user: User = validated_data["user"]
        device = None
        device_id = validated_data.get("device_id")
        if device_id is not None:
            device = Device.objects.filter(id=device_id, user=user).first()
            if device is not None and device.is_revoked:
                raise serializers.ValidationError(
                    {"device_id": ["Appareil révoqué."]}, code="device_revoked"
                )
        if device is None:
            # A device id belonging to another user is never reused.
            device = Device.objects.create(
                user=user,
                platform=validated_data["platform"],
                label=validated_data.get("device_label", ""),
            )
        device.client_version = validated_data.get("client_version", device.client_version)
        device.last_seen_at = timezone.now()
        device.save(update_fields=["client_version", "last_seen_at"])

        refresh = RefreshToken.for_user(user)
        refresh["device_id"] = str(device.id)
        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "device_id": device.id,
            "user_id": user.id,
        }


class LoginResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    device_id = serializers.UUIDField()
    user_id = serializers.UUIDField()


class DeviceAwareTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        token = RefreshToken(attrs["refresh"])
        device_id = token.get("device_id")
        if (
            device_id is not None
            and not Device.objects.filter(
                id=device_id, revoked_at__isnull=True, user__is_active=True
            ).exists()
        ):
            raise serializers.ValidationError("Appareil révoqué.", code="device_revoked")
        return super().validate(attrs)


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "phone", "full_name", "locale", "is_active", "date_joined"]
        read_only_fields = ["id", "email", "phone", "is_active", "date_joined"]


class UserPublicSerializer(serializers.ModelSerializer):
    """Minimal representation exposed to other members of the same tenant."""

    class Meta:
        model = User
        fields = ["id", "full_name", "email", "phone"]
        read_only_fields = fields


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = [
            "id",
            "platform",
            "label",
            "client_version",
            "last_seen_at",
            "revoked_at",
            "created_at",
        ]
        read_only_fields = fields


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)
