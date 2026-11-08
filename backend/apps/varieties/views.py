from dataclasses import asdict
from typing import Any

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.versioning import parse_if_match
from apps.organizations.viewsets import OrgScopedGenericViewSet
from apps.varieties import services
from apps.varieties.models import TechnicalDataSet, TechnicalDocument, Variety
from apps.varieties.serializers import (
    ItemsUpsertSerializer,
    KeysSerializer,
    TechnicalDataSetCreateSerializer,
    TechnicalDataSetSerializer,
    TechnicalDocumentCreateSerializer,
    TechnicalDocumentSerializer,
    TechnicalKeySerializer,
    VarietySerializer,
)
from apps.varieties.technical_keys import TECHNICAL_KEYS


class VarietyViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, OrgScopedGenericViewSet):
    serializer_class = VarietySerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    permission_map = {
        "list": services.VIEW,
        "retrieve": services.VIEW,
        "create": services.EDIT,
        "partial_update": services.EDIT,
        "destroy": services.EDIT,
        "documents": services.VIEW,
        "documents:POST": services.EDIT,
    }
    filterset_fields = ["crop"]

    def get_queryset(self) -> QuerySet[Variety]:
        return Variety.objects.filter(
            organization_id=self.tenant.organization_id, deleted_at__isnull=True
        ).select_related("crop")

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        variety = services.create_variety(self.tenant, data=serializer.validated_data)
        return Response(self.get_serializer(variety).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        variety = self.get_object()
        serializer = self.get_serializer(variety, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        variety = services.update_variety(
            self.tenant,
            variety_id=variety.id,
            expected_version=parse_if_match(request),
            changes=serializer.validated_data,
        )
        return Response(self.get_serializer(variety).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        services.delete_variety(
            self.tenant, variety_id=self.get_object().id, expected_version=parse_if_match(request)
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=TechnicalDocumentCreateSerializer,
        responses=TechnicalDocumentSerializer(many=True),
    )
    @action(detail=True, methods=["get", "post"])
    def documents(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        variety = self.get_object()
        if request.method == "POST":
            serializer = TechnicalDocumentCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = dict(serializer.validated_data)
            document = services.add_document(
                self.tenant, variety_id=variety.id, file_id=data.pop("file"), data=data
            )
            return Response(
                TechnicalDocumentSerializer(document).data, status=status.HTTP_201_CREATED
            )
        documents = TechnicalDocument.objects.filter(variety=variety).order_by("-created_at")
        return Response(TechnicalDocumentSerializer(documents, many=True).data)


class TechnicalDataSetViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, OrgScopedGenericViewSet
):
    serializer_class = TechnicalDataSetSerializer
    permission_map = {
        "list": services.VIEW,
        "retrieve": services.VIEW,
        "create": services.EDIT,
        "items": services.EDIT,
        "remove_items": services.EDIT,
        "validate_items": services.VALIDATE,
        "validate": services.VALIDATE,
    }
    filterset_fields = ["variety", "status"]

    def get_queryset(self) -> QuerySet[TechnicalDataSet]:
        return TechnicalDataSet.objects.filter(
            organization_id=self.tenant.organization_id
        ).prefetch_related("items")

    @extend_schema(request=TechnicalDataSetCreateSerializer, responses=TechnicalDataSetSerializer)
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = TechnicalDataSetCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        data_set = services.create_data_set(
            self.tenant,
            variety_id=data["variety"],
            source_document_id=data.get("source_document"),
            based_on_id=data.get("based_on"),
            notes=data.get("notes", ""),
        )
        return Response(self._fresh(data_set.id), status=status.HTTP_201_CREATED)

    def _fresh(self, data_set_id: Any) -> Any:
        return TechnicalDataSetSerializer(self.get_queryset().get(id=data_set_id)).data

    @extend_schema(request=ItemsUpsertSerializer, responses=TechnicalDataSetSerializer)
    @action(detail=True, methods=["post"])
    def items(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        data_set = self.get_object()
        serializer = ItemsUpsertSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.upsert_items(
            self.tenant, data_set_id=data_set.id, items=serializer.validated_data["items"]
        )
        return Response(self._fresh(data_set.id))

    @extend_schema(request=KeysSerializer, responses=TechnicalDataSetSerializer)
    @action(detail=True, methods=["post"], url_path="remove-items")
    def remove_items(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        data_set = self.get_object()
        serializer = KeysSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.remove_items(
            self.tenant, data_set_id=data_set.id, keys=serializer.validated_data["keys"]
        )
        return Response(self._fresh(data_set.id))

    @extend_schema(request=KeysSerializer, responses=TechnicalDataSetSerializer)
    @action(detail=True, methods=["post"], url_path="validate-items")
    def validate_items(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        data_set = self.get_object()
        serializer = KeysSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.validate_items(
            self.tenant, data_set_id=data_set.id, keys=serializer.validated_data["keys"]
        )
        return Response(self._fresh(data_set.id))

    @extend_schema(request=None, responses=TechnicalDataSetSerializer)
    @action(detail=True, methods=["post"])
    def validate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        data_set = services.validate_data_set(self.tenant, data_set_id=self.get_object().id)
        return Response(self._fresh(data_set.id))


class TechnicalKeyCatalogView(APIView):
    @extend_schema(responses=TechnicalKeySerializer(many=True))
    def get(self, request: Request) -> Response:
        catalogue = [{"key": key, **asdict(spec)} for key, spec in TECHNICAL_KEYS.items()]
        catalogue += [
            {
                "key": "phase.<code>.duration_days",
                "name": "Durée d'une phase",
                "unit": "days",
                "kind": "decimal",
                "min_value": None,
                "max_value": None,
            },
            {
                "key": "kc.<code>",
                "name": "Coefficient cultural Kc d'une phase",
                "unit": "ratio",
                "kind": "decimal",
                "min_value": None,
                "max_value": "3",
            },
        ]
        for entry in catalogue:
            entry.pop("min_exclusive", None)
            if "label" in entry:
                entry["name"] = entry.pop("label")
        return Response(catalogue)
