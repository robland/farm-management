from typing import Any

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.versioning import parse_if_match
from apps.farms.viewsets import FarmScopedGenericViewSet
from apps.production_plans import services
from apps.production_plans.models import Campaign, CropCycle, PlanVersion, ProductionPlan
from apps.production_plans.serializers import (
    AllocationsInputSerializer,
    CampaignSerializer,
    CompareQuerySerializer,
    CropCycleSerializer,
    NewVersionSerializer,
    PhasesInputSerializer,
    PlantingSpecSerializer,
    PlanVersionHeaderSerializer,
    PlanVersionSerializer,
    ProductionPlanCreateSerializer,
    ProductionPlanSerializer,
)

V, E, VAL = services.VIEW, services.EDIT, services.VALIDATE


class CampaignViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, FarmScopedGenericViewSet):
    serializer_class = CampaignSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]
    permission_map = {"list": V, "retrieve": V, "create": E, "partial_update": E}
    filterset_fields = ["status"]

    def get_queryset(self) -> QuerySet[Campaign]:
        return Campaign.objects.filter(farm_id=self.farm_id, deleted_at__isnull=True)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        campaign = services.create_campaign(self.tenant, data=serializer.validated_data)
        return Response(self.get_serializer(campaign).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        campaign = self.get_object()
        serializer = self.get_serializer(campaign, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        campaign = services.update_campaign(
            self.tenant,
            campaign_id=campaign.id,
            expected_version=parse_if_match(request),
            changes=serializer.validated_data,
        )
        return Response(self.get_serializer(campaign).data)


class ProductionPlanViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, FarmScopedGenericViewSet
):
    serializer_class = ProductionPlanSerializer
    permission_map = {"list": V, "retrieve": V, "create": E, "new_version": E, "compare": V}
    filterset_fields = ["campaign", "status", "variety"]

    def get_queryset(self) -> QuerySet[ProductionPlan]:
        return ProductionPlan.objects.filter(farm_id=self.farm_id).select_related("variety")

    @extend_schema(
        request=ProductionPlanCreateSerializer, responses={201: ProductionPlanSerializer}
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = ProductionPlanCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        plan = services.create_plan(
            self.tenant, campaign_id=data["campaign"], variety_id=data["variety"], name=data["name"]
        )
        return Response(self.get_serializer(plan).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=NewVersionSerializer, responses={201: PlanVersionSerializer})
    @action(detail=True, methods=["post"], url_path="new-version")
    def new_version(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = NewVersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        draft = services.create_new_version(
            self.tenant,
            plan_id=self.get_object().id,
            based_on_id=serializer.validated_data.get("based_on"),
            change_note=serializer.validated_data.get("change_note", ""),
        )
        return Response(PlanVersionSerializer(draft).data, status=status.HTTP_201_CREATED)

    @extend_schema(parameters=[CompareQuerySerializer])
    @action(detail=True, methods=["get"])
    def compare(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        plan = self.get_object()
        query = CompareQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        for key in ("a", "b"):
            if not plan.versions.filter(id=query.validated_data[key]).exists():
                return Response(
                    {
                        "code": "not_found",
                        "message": "Version introuvable.",
                        "details": {},
                        "field_errors": {},
                    },
                    status=404,
                )
        return Response(
            services.compare_versions(
                self.tenant,
                version_a_id=query.validated_data["a"],
                version_b_id=query.validated_data["b"],
            )
        )


class PlanVersionViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, FarmScopedGenericViewSet
):
    serializer_class = PlanVersionSerializer
    http_method_names = ["get", "post", "put", "patch", "head", "options"]
    permission_map = {
        "list": V,
        "retrieve": V,
        "partial_update": E,
        "planting_spec": E,
        "allocations": E,
        "phases": E,
        "prefill": E,
        "compute": E,
        "validate": VAL,
    }
    filterset_fields = ["plan", "status"]

    def get_queryset(self) -> QuerySet[PlanVersion]:
        return (
            PlanVersion.objects.filter(farm_id=self.farm_id)
            .select_related("planting_spec")
            .prefetch_related("allocations", "phases", "provenances", "calculations")
        )

    def _fresh(self, version_id: Any) -> Any:
        return PlanVersionSerializer(self.get_queryset().get(id=version_id)).data

    @extend_schema(request=PlanVersionHeaderSerializer, responses=PlanVersionSerializer)
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        version = self.get_object()
        serializer = PlanVersionHeaderSerializer(
            data=request.data, partial=True, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        services.update_header(
            self.tenant,
            version_id=version.id,
            expected_version=parse_if_match(request),
            changes=serializer.validated_data,
        )
        return Response(self._fresh(version.id))

    @extend_schema(request=PlantingSpecSerializer, responses=PlanVersionSerializer)
    @action(detail=True, methods=["patch"], url_path="planting-spec")
    def planting_spec(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        version = self.get_object()
        serializer = PlantingSpecSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_planting_spec(
            self.tenant,
            version_id=version.id,
            expected_version=parse_if_match(request),
            changes=serializer.validated_data,
        )
        return Response(self._fresh(version.id))

    @extend_schema(request=AllocationsInputSerializer, responses=PlanVersionSerializer)
    @action(detail=True, methods=["put"])
    def allocations(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        version = self.get_object()
        serializer = AllocationsInputSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        services.set_allocations(
            self.tenant,
            version_id=version.id,
            expected_version=parse_if_match(request),
            allocations=serializer.validated_data["allocations"],
        )
        return Response(self._fresh(version.id))

    @extend_schema(request=PhasesInputSerializer, responses=PlanVersionSerializer)
    @action(detail=True, methods=["put"])
    def phases(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        version = self.get_object()
        serializer = PhasesInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.set_phases(
            self.tenant,
            version_id=version.id,
            expected_version=parse_if_match(request),
            phases=serializer.validated_data["phases"],
        )
        return Response(self._fresh(version.id))

    @extend_schema(request=None)
    @action(detail=True, methods=["post"])
    def prefill(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        version = self.get_object()
        report = services.prefill_from_technical_data(
            self.tenant, version_id=version.id, expected_version=parse_if_match(request)
        )
        return Response({**report, "version": self._fresh(version.id)})

    @extend_schema(request=None)
    @action(detail=True, methods=["post"])
    def compute(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        outcome = services.compute_version(self.tenant, version_id=self.get_object().id)
        return Response(outcome.to_dict())

    @extend_schema(request=None, responses=PlanVersionSerializer)
    @action(detail=True, methods=["post"])
    def validate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        version = services.validate_version(
            self.tenant, version_id=self.get_object().id, expected_version=parse_if_match(request)
        )
        return Response(self._fresh(version.id))


class CropCycleViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, FarmScopedGenericViewSet):
    serializer_class = CropCycleSerializer
    permission_map = {"list": V, "retrieve": V}
    filterset_fields = ["parcel", "plan", "status"]

    def get_queryset(self) -> QuerySet[CropCycle]:
        return CropCycle.objects.filter(farm_id=self.farm_id).order_by("start_date")
