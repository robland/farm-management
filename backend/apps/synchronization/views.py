from typing import Any

from django.db.models import QuerySet
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.viewsets import request_user
from apps.farms.access import resolve_farm_context
from apps.farms.viewsets import FarmScopedGenericViewSet
from apps.synchronization import services
from apps.synchronization.models import SyncConflict
from apps.synchronization.pull import pull_changes
from apps.synchronization.push import IncomingOperation, process_batch
from apps.synchronization.serializers import (
    ConflictResolveSerializer,
    PullQuerySerializer,
    PullResponseSerializer,
    PushRequestSerializer,
    PushResponseSerializer,
    SyncConflictSerializer,
)
from apps.users.models import Device


class PushView(APIView):
    """Apply a batch of offline operations. Always 200: each operation has its own result."""

    @extend_schema(request=PushRequestSerializer, responses=PushResponseSerializer)
    def post(self, request: Request) -> Response:
        serializer = PushRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = request_user(request)

        device = None
        auth: Any = request.auth
        token_device = auth.get("device_id") if auth is not None else None
        device_id = token_device or data.get("device_id")
        if device_id is not None:
            device = Device.objects.filter(id=device_id, user=user, revoked_at__isnull=True).first()

        operations = [IncomingOperation(**op) for op in data["operations"]]
        results = process_batch(user, device, operations)
        return Response({"results": results, "server_time": timezone.now()})


class PullView(APIView):
    @extend_schema(parameters=[PullQuerySerializer], responses=PullResponseSerializer)
    def get(self, request: Request) -> Response:
        query = PullQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        params = query.validated_data
        ctx = resolve_farm_context(request_user(request), params["farm_id"])
        return Response(pull_changes(ctx, cursor=params["cursor"], limit=params["limit"]))


class ConflictViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, FarmScopedGenericViewSet):
    serializer_class = SyncConflictSerializer
    queryset = SyncConflict.objects.none()  # model hint for OpenAPI; see get_queryset
    permission_map = {"list": "farm.view", "retrieve": "farm.view", "resolve": "farm.view"}
    filterset_fields = ["status", "conflict_type", "entity_type"]

    def get_queryset(self) -> QuerySet[SyncConflict]:
        return services.visible_conflicts(self.tenant).order_by("-created_at")

    @extend_schema(request=ConflictResolveSerializer, responses=SyncConflictSerializer)
    @action(detail=True, methods=["post"])
    def resolve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = ConflictResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conflict = services.resolve_conflict(
            self.tenant,
            conflict_id=self.get_object().id,
            resolution=serializer.validated_data["resolution"],
            note=serializer.validated_data.get("note", ""),
        )
        return Response(SyncConflictSerializer(conflict).data)
