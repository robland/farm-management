from typing import Any

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.versioning import parse_if_match
from apps.farms.viewsets import FarmScopedGenericViewSet
from apps.irrigation import services
from apps.irrigation.models import IrrigationDesign, Quote
from apps.irrigation.serializers import (
    BomLineInputSerializer,
    BomLineSerializer,
    BomLinkSerializer,
    IrrigationDesignSerializer,
    QuoteCreateSerializer,
    QuoteSerializer,
    QuoteStatusSerializer,
    QuoteUpdateSerializer,
)

V, E = services.VIEW, services.EDIT


class IrrigationDesignViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, FarmScopedGenericViewSet
):
    serializer_class = IrrigationDesignSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]
    permission_map = {
        "list": V,
        "retrieve": V,
        "create": E,
        "partial_update": E,
        "compute": E,
        "validate": E,
        "new_version": E,
        "bom_lines": E,
        "link": E,
    }
    filterset_fields = ["parcel", "plan_version", "status", "system_type"]

    def get_queryset(self) -> QuerySet[IrrigationDesign]:
        return IrrigationDesign.objects.filter(farm_id=self.farm_id).prefetch_related("bom_lines")

    def _fresh(self, pk: Any) -> Any:
        return IrrigationDesignSerializer(
            self.get_queryset().get(id=pk), context=self.get_serializer_context()
        ).data

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        design = services.create_design(self.tenant, data=serializer.validated_data)
        return Response(self._fresh(design.id), status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        design = self.get_object()
        serializer = self.get_serializer(design, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_design(
            self.tenant,
            design_id=design.id,
            expected_version=parse_if_match(request),
            changes=serializer.validated_data,
        )
        return Response(self._fresh(design.id))

    @extend_schema(request=None)
    @action(detail=True, methods=["post"])
    def compute(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        outcome = services.compute_design(self.tenant, design_id=self.get_object().id)
        return Response(outcome)

    @extend_schema(request=None, responses=IrrigationDesignSerializer)
    @action(detail=True, methods=["post"])
    def validate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        design = services.validate_design(
            self.tenant, design_id=self.get_object().id, expected_version=parse_if_match(request)
        )
        return Response(self._fresh(design.id))

    @extend_schema(request=None, responses={201: IrrigationDesignSerializer})
    @action(detail=True, methods=["post"], url_path="new-version")
    def new_version(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        draft = services.new_design_version(self.tenant, design_id=self.get_object().id)
        return Response(self._fresh(draft.id), status=status.HTTP_201_CREATED)

    @extend_schema(request=BomLineInputSerializer, responses={201: BomLineSerializer})
    @action(detail=True, methods=["post"], url_path="bom-lines")
    def bom_lines(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = BomLineInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        line = services.add_manual_bom_line(
            self.tenant, design_id=self.get_object().id, data=dict(serializer.validated_data)
        )
        return Response(BomLineSerializer(line).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=BomLinkSerializer, responses=BomLineSerializer)
    @action(detail=True, methods=["post"])
    def link(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = BomLinkSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        line = services.link_bom_line(
            self.tenant,
            design_id=self.get_object().id,
            bom_line_id=serializer.validated_data["bom_line"],
            catalog_item=serializer.validated_data["catalog_item"],
        )
        return Response(BomLineSerializer(line).data)


class QuoteViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, FarmScopedGenericViewSet):
    serializer_class = QuoteSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]
    permission_map = {
        "list": V,
        "retrieve": V,
        "create": E,
        "partial_update": E,
        "issue": E,
        "decide": E,
    }
    filterset_fields = ["design", "status", "supplier"]

    def get_queryset(self) -> QuerySet[Quote]:
        return Quote.objects.filter(farm_id=self.farm_id).prefetch_related("lines")

    def _fresh(self, pk: Any) -> Any:
        return QuoteSerializer(self.get_queryset().get(id=pk)).data

    @extend_schema(request=QuoteCreateSerializer, responses={201: QuoteSerializer})
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = QuoteCreateSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        quote = services.create_quote(
            self.tenant,
            design_id=data["design"],
            price_list=data.get("price_list"),
            currency=data.get("currency"),
            notes=data.get("notes", ""),
        )
        return Response(self._fresh(quote.id), status=status.HTTP_201_CREATED)

    @extend_schema(request=QuoteUpdateSerializer, responses=QuoteSerializer)
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        quote = self.get_object()
        serializer = QuoteUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.update_quote(
            self.tenant,
            quote_id=quote.id,
            expected_version=parse_if_match(request),
            data=serializer.validated_data,
        )
        return Response(self._fresh(quote.id))

    @extend_schema(request=None, responses=QuoteSerializer)
    @action(detail=True, methods=["post"])
    def issue(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        quote = services.issue_quote(
            self.tenant, quote_id=self.get_object().id, expected_version=parse_if_match(request)
        )
        return Response(self._fresh(quote.id))

    @extend_schema(request=QuoteStatusSerializer, responses=QuoteSerializer)
    @action(detail=True, methods=["post"])
    def decide(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = QuoteStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        quote = services.decide_quote(
            self.tenant,
            quote_id=self.get_object().id,
            expected_version=parse_if_match(request),
            status=serializer.validated_data["status"],
        )
        return Response(self._fresh(quote.id))
