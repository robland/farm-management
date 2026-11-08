from typing import Any

from django.http import FileResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.viewsets import CHECKED_IN_SERVICE, TenantGenericViewSet
from apps.farms.viewsets import FarmScopedGenericViewSet
from apps.files import services
from apps.files.models import StoredFile
from apps.files.serializers import FileUploadSerializer, StoredFileSerializer
from apps.organizations.viewsets import OrgScopedGenericViewSet


class _FileViewSetMixin(TenantGenericViewSet):
    serializer_class = StoredFileSerializer
    # Never queried: lookups go through the service; declares the model for OpenAPI.
    queryset = StoredFile.objects.none()
    parser_classes = [MultiPartParser]
    # Read and write permissions depend on the file purpose: enforced by the service.
    permission_map = {
        "create": CHECKED_IN_SERVICE,
        "retrieve": CHECKED_IN_SERVICE,
        "download": CHECKED_IN_SERVICE,
    }

    @extend_schema(request=FileUploadSerializer, responses={201: StoredFileSerializer})
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = FileUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        upload = serializer.validated_data["file"]
        stored, created = services.upload_file(
            self.tenant,
            stream=upload,
            original_name=upload.name,
            purpose=serializer.validated_data["purpose"],
            declared_mime=getattr(upload, "content_type", "") or "",
            file_id=serializer.validated_data.get("id"),
        )
        return Response(
            StoredFileSerializer(stored).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        stored = services.get_file_for_read(self.tenant, kwargs["pk"])
        return Response(StoredFileSerializer(stored).data)

    @extend_schema(responses={(200, "application/octet-stream"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def download(self, request: Request, *args: Any, **kwargs: Any) -> FileResponse:
        stored = services.get_file_for_read(self.tenant, kwargs["pk"])
        response = FileResponse(
            services.open_file(stored),
            as_attachment=True,
            filename=stored.original_name,
            content_type=stored.detected_mime,
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        return response


class OrganizationFileViewSet(_FileViewSetMixin, OrgScopedGenericViewSet):
    """Organization-level files: technical sheets, product labels."""


class FarmFileViewSet(_FileViewSetMixin, FarmScopedGenericViewSet):
    """Farm-level files: receipts, task and observation photos."""
