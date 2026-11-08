from typing import Any

from django.db.models import QuerySet
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.farms.viewsets import FarmScopedGenericViewSet
from apps.harvest import services
from apps.harvest.models import HarvestRecord, UnitConversion
from apps.harvest.serializers import (
    CampaignQuerySerializer,
    HarvestRecordSerializer,
    UnitConversionSerializer,
    VoidSerializer,
)
from apps.production_plans.models import CropCycle
from apps.production_plans.serializers import CropCycleSerializer

V, R = services.VIEW, services.RECORD


class UnitConversionViewSet(mixins.ListModelMixin, FarmScopedGenericViewSet):
    serializer_class = UnitConversionSerializer
    permission_map = {"list": V, "create": R}

    def get_queryset(self) -> QuerySet[UnitConversion]:
        return UnitConversion.objects.filter(farm_id=self.farm_id)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversion = services.set_unit_conversion(self.tenant, data=dict(serializer.validated_data))
        return Response(self.get_serializer(conversion).data, status=status.HTTP_201_CREATED)


class HarvestRecordViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, FarmScopedGenericViewSet
):
    serializer_class = HarvestRecordSerializer
    permission_map = {"list": V, "retrieve": V, "create": R, "void": "farm.manage"}
    filterset_fields = ["crop_cycle", "parcel", "quality_grade"]

    def get_queryset(self) -> QuerySet[HarvestRecord]:
        return HarvestRecord.objects.filter(farm_id=self.farm_id)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record, created = services.record_harvest(self.tenant, data=dict(serializer.validated_data))
        return Response(
            self.get_serializer(record).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(request=VoidSerializer, responses=HarvestRecordSerializer)
    @action(detail=True, methods=["post"])
    def void(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = VoidSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = services.void_harvest(
            self.tenant, record_id=self.get_object().id, reason=serializer.validated_data["reason"]
        )
        return Response(self.get_serializer(record).data)


class HarvestResultsViewSet(mixins.RetrieveModelMixin, FarmScopedGenericViewSet):
    """Objectives vs results per crop cycle (lookup = crop cycle id) or per campaign."""

    permission_map = {"retrieve": V, "campaign": V}
    serializer_class = CropCycleSerializer  # lookup model; responses are documented below

    def get_queryset(self) -> QuerySet[CropCycle]:
        return CropCycle.objects.filter(farm_id=self.farm_id)

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(services.cycle_results(self.tenant, cycle_id=self.get_object().id))

    @extend_schema(parameters=[CampaignQuerySerializer], responses=OpenApiTypes.OBJECT)
    @action(detail=False, methods=["get"])
    def campaign(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query = CampaignQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(
            services.campaign_results(self.tenant, campaign_id=query.validated_data["campaign"])
        )
