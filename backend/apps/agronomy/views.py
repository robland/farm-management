from typing import Any

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.agronomy import services
from apps.agronomy.models import InputProduct, Observation
from apps.agronomy.serializers import (
    InputProductSerializer,
    IrrigationScheduleSerializer,
    ObservationSerializer,
    PlannedFertilizationSerializer,
    PlannedIrrigationSerializer,
    PlannedPhytoSerializer,
    ProgramSerializer,
)
from apps.core.versioning import parse_if_match
from apps.farms.viewsets import FarmScopedGenericViewSet
from apps.organizations.viewsets import OrgScopedGenericViewSet
from apps.production_plans.models import PlanVersion


class InputProductViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, OrgScopedGenericViewSet
):
    serializer_class = InputProductSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]
    permission_map = {
        "list": "inventory.view",
        "retrieve": "inventory.view",
        "create": "inventory.edit",
        "partial_update": "inventory.edit",
    }
    filterset_fields = ["kind"]

    def get_queryset(self) -> QuerySet[InputProduct]:
        return InputProduct.objects.filter(
            organization_id=self.tenant.organization_id, deleted_at__isnull=True
        )

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product = services.create_product(self.tenant, data=dict(serializer.validated_data))
        return Response(self.get_serializer(product).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        product = self.get_object()
        serializer = self.get_serializer(product, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        product = services.update_product(
            self.tenant,
            product_id=product.id,
            expected_version=parse_if_match(request),
            changes=dict(serializer.validated_data),
        )
        return Response(self.get_serializer(product).data)


class RemoveItemSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=list(services.PLANNED_MODELS))
    id = serializers.UUIDField()


class PlanProgramViewSet(mixins.RetrieveModelMixin, FarmScopedGenericViewSet):
    """Agronomic programme of a plan version (lookup = plan version id)."""

    serializer_class = ProgramSerializer
    permission_map = {
        "retrieve": "plans.view",
        "fertilizations": "plans.edit",
        "phyto": "plans.edit",
        "irrigation": "plans.edit",
        "remove": "plans.edit",
        "recompute": "plans.edit",
    }

    def get_queryset(self) -> QuerySet[PlanVersion]:
        return PlanVersion.objects.filter(farm_id=self.farm_id)

    def _program(self, version: PlanVersion, **extra: Any) -> Response:
        data = ProgramSerializer(
            {
                "fertilizations": version.fertilizations.all(),
                "phyto_interventions": version.phyto_interventions.all(),
                "irrigation_schedule": version.irrigation_schedule.all(),
            }
        ).data
        return Response(
            {
                **data,
                "plan_version": str(version.id),
                "version": PlanVersion.objects.get(id=version.id).version,
                "phyto_warning": services.PHYTO_WARNING,
                **extra,
            }
        )

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._program(self.get_object())

    @extend_schema(request=PlannedFertilizationSerializer)
    @action(detail=True, methods=["post"])
    def fertilizations(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        version = self.get_object()
        serializer = PlannedFertilizationSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        _, missing = services.add_fertilization(
            self.tenant,
            version_id=version.id,
            expected_version=parse_if_match(request),
            data=dict(serializer.validated_data),
        )
        return self._program(version, missing=missing)

    @extend_schema(request=PlannedPhytoSerializer)
    @action(detail=True, methods=["post"])
    def phyto(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        version = self.get_object()
        serializer = PlannedPhytoSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        _, warnings = services.add_phyto(
            self.tenant,
            version_id=version.id,
            expected_version=parse_if_match(request),
            data=dict(serializer.validated_data),
        )
        return self._program(version, warnings=warnings)

    @extend_schema(
        request=IrrigationScheduleSerializer, responses=PlannedIrrigationSerializer(many=True)
    )
    @action(detail=True, methods=["put"])
    def irrigation(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        version = self.get_object()
        serializer = IrrigationScheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.set_irrigation_schedule(
            self.tenant,
            version_id=version.id,
            expected_version=parse_if_match(request),
            items=[dict(i) for i in serializer.validated_data["items"]],
        )
        return self._program(version)

    @extend_schema(request=RemoveItemSerializer)
    @action(detail=True, methods=["post"])
    def remove(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        version = self.get_object()
        serializer = RemoveItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.remove_program_item(
            self.tenant,
            version_id=version.id,
            expected_version=parse_if_match(request),
            kind=serializer.validated_data["kind"],
            item_id=serializer.validated_data["id"],
        )
        return self._program(version)

    @extend_schema(request=None)
    @action(detail=True, methods=["post"])
    def recompute(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        version = self.get_object()
        report = services.recompute_program(self.tenant, version_id=version.id)
        return self._program(version, **report)


class ObservationViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, FarmScopedGenericViewSet
):
    serializer_class = ObservationSerializer
    permission_map = {
        "list": "observations.view",
        "retrieve": "observations.view",
        "create": "observations.create",
    }
    filterset_fields = ["parcel", "kind", "crop_cycle"]

    def get_queryset(self) -> QuerySet[Observation]:
        return Observation.objects.filter(farm_id=self.farm_id).prefetch_related("photos")

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        observation, created = services.create_observation(
            self.tenant, data=dict(serializer.validated_data)
        )
        return Response(
            self.get_serializer(observation).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
