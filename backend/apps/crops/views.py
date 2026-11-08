from typing import Any

from django.db.models import QuerySet
from rest_framework import mixins, status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.versioning import parse_if_match
from apps.crops import services
from apps.crops.models import Crop
from apps.crops.serializers import CropSerializer
from apps.organizations.viewsets import OrgScopedGenericViewSet


class CropViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, OrgScopedGenericViewSet):
    serializer_class = CropSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    permission_map = {
        "list": services.VIEW,
        "retrieve": services.VIEW,
        "create": services.EDIT,
        "partial_update": services.EDIT,
        "destroy": services.EDIT,
    }
    filterset_fields = ["category"]

    def get_queryset(self) -> QuerySet[Crop]:
        return services.visible_crops(self.tenant)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        crop = services.create_crop(self.tenant, data=serializer.validated_data)
        return Response(self.get_serializer(crop).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        crop = self.get_object()
        serializer = self.get_serializer(crop, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        crop = services.update_crop(
            self.tenant,
            crop_id=crop.id,
            expected_version=parse_if_match(request),
            changes=serializer.validated_data,
        )
        return Response(self.get_serializer(crop).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        services.delete_crop(self.tenant, crop_id=self.get_object().id)
        return Response(status=status.HTTP_204_NO_CONTENT)
