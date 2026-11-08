from typing import Any

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.versioning import parse_if_match
from apps.farms.viewsets import FarmScopedGenericViewSet
from apps.fields import services
from apps.fields.models import Field, Parcel
from apps.fields.serializers import (
    FieldSerializer,
    ParcelHistoryEntrySerializer,
    ParcelSerializer,
)

_PERMS = {
    "list": services.VIEW_PERMISSION,
    "retrieve": services.VIEW_PERMISSION,
    "create": services.EDIT_PERMISSION,
    "partial_update": services.EDIT_PERMISSION,
    "destroy": services.EDIT_PERMISSION,
}


class _VersionedCrudViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, FarmScopedGenericViewSet
):
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def _create(self, request: Request, create_fn: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance, created = create_fn(self.tenant, data=serializer.validated_data)
        return Response(
            self.get_serializer(instance).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def _update(self, request: Request, update_fn: Any, id_kwarg: str) -> Response:
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        instance = update_fn(
            self.tenant,
            **{id_kwarg: instance.id},
            expected_version=parse_if_match(request),
            changes=serializer.validated_data,
        )
        return Response(self.get_serializer(instance).data)


class FieldViewSet(_VersionedCrudViewSet):
    serializer_class = FieldSerializer
    permission_map = _PERMS

    def get_queryset(self) -> QuerySet[Field]:
        return Field.objects.filter(farm_id=self.farm_id, deleted_at__isnull=True).order_by("code")

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._create(request, services.create_field)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._update(request, services.update_field, "field_id")

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        services.delete_field(
            self.tenant, field_id=self.get_object().id, expected_version=parse_if_match(request)
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class ParcelViewSet(_VersionedCrudViewSet):
    serializer_class = ParcelSerializer
    permission_map = {
        **_PERMS,
        "history": services.VIEW_PERMISSION,
        "history:POST": services.EDIT_PERMISSION,
    }
    filterset_fields = ["field", "status", "water_availability"]

    def get_queryset(self) -> QuerySet[Parcel]:
        return Parcel.objects.filter(farm_id=self.farm_id, deleted_at__isnull=True).order_by("code")

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._create(request, services.create_parcel)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._update(request, services.update_parcel, "parcel_id")

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        services.delete_parcel(
            self.tenant, parcel_id=self.get_object().id, expected_version=parse_if_match(request)
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=ParcelHistoryEntrySerializer, responses=ParcelHistoryEntrySerializer(many=True)
    )
    @action(detail=True, methods=["get", "post"], serializer_class=ParcelHistoryEntrySerializer)
    def history(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        parcel = self.get_object()
        if request.method == "POST":
            serializer = ParcelHistoryEntrySerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            entry = services.add_history_entry(
                self.tenant, parcel_id=parcel.id, data=serializer.validated_data
            )
            return Response(
                ParcelHistoryEntrySerializer(entry).data, status=status.HTTP_201_CREATED
            )
        return Response(ParcelHistoryEntrySerializer(parcel.history_entries.all(), many=True).data)
