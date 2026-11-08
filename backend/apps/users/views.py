from typing import cast

from django.contrib.auth.password_validation import validate_password
from django.db.models import QuerySet
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from apps.audit.services import record_event
from apps.users.models import Device, User
from apps.users.serializers import (
    ChangePasswordSerializer,
    DeviceAwareTokenRefreshSerializer,
    DeviceSerializer,
    LoginResponseSerializer,
    LoginSerializer,
    LogoutSerializer,
)


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list[type] = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    @extend_schema(request=LoginSerializer, responses=LoginResponseSerializer)
    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.save()
        record_event(
            action="auth.login",
            actor=serializer.validated_data["user"],
            entity_type="users.device",
            entity_id=data["device_id"],
        )
        return Response(LoginResponseSerializer(data).data)


class RefreshView(TokenRefreshView):
    serializer_class = DeviceAwareTokenRefreshSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"


class LogoutView(APIView):
    @extend_schema(request=LogoutSerializer, responses={204: None})
    def post(self, request: Request) -> Response:
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            token = RefreshToken(serializer.validated_data["refresh"])
            if str(token.get("user_id")) != str(request.user.pk):
                raise ValidationError({"refresh": ["Jeton invalide."]})
            token.blacklist()
        except TokenError as exc:
            raise ValidationError({"refresh": ["Jeton invalide."]}) from exc
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChangePasswordView(APIView):
    @extend_schema(request=ChangePasswordSerializer, responses={204: None})
    def post(self, request: Request) -> Response:
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = cast(User, request.user)
        if not user.check_password(serializer.validated_data["current_password"]):
            raise ValidationError({"current_password": ["Mot de passe incorrect."]})
        new_password = serializer.validated_data["new_password"]
        validate_password(new_password, user)
        user.set_password(new_password)
        user.save(update_fields=["password"])
        record_event(
            action="auth.password_changed", actor=user, entity_type="users.user", entity_id=user.id
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyDeviceViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = DeviceSerializer
    queryset = Device.objects.none()  # model hint for OpenAPI; see get_queryset

    def get_queryset(self) -> QuerySet[Device]:
        return Device.objects.filter(user=cast(User, self.request.user)).order_by("-created_at")

    @extend_schema(request=None, responses=DeviceSerializer)
    @action(detail=True, methods=["post"])
    def revoke(self, request: Request, pk: str | None = None) -> Response:
        device = self.get_object()
        if device.revoked_at is None:
            device.revoked_at = timezone.now()
            device.save(update_fields=["revoked_at"])
            record_event(
                action="auth.device_revoked",
                actor=request.user,
                entity_type="users.device",
                entity_id=device.id,
            )
        return Response(DeviceSerializer(device).data)
