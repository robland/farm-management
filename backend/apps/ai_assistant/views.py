from typing import Any

from django.db.models import QuerySet
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ai_assistant import services
from apps.ai_assistant.models import AIRun, AISuggestion
from apps.ai_assistant.serializers import (
    AIRunSerializer,
    AISuggestionSerializer,
    DecisionSerializer,
    ExtractionRequestSerializer,
    PlanDraftRequestSerializer,
)
from apps.farms.viewsets import FarmScopedGenericViewSet
from apps.organizations.viewsets import OrgScopedGenericViewSet

AI = services.AI_USE


class AIStatusView(APIView):
    """Whether the assistant is available (the UI falls back to manual mode otherwise)."""

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request: Request) -> Response:
        return Response(services.provider_status())


class ExtractionViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, OrgScopedGenericViewSet):
    serializer_class = AIRunSerializer
    permission_map = {"list": AI, "retrieve": AI, "create": AI}

    def get_queryset(self) -> QuerySet[AIRun]:
        return AIRun.objects.filter(
            organization_id=self.tenant.organization_id, kind=AIRun.Kind.EXTRACTION
        )

    @extend_schema(request=ExtractionRequestSerializer, responses={201: AIRunSerializer})
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = ExtractionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = services.run_extraction(
            self.tenant, document_id=serializer.validated_data["document"]
        )
        return Response(AIRunSerializer(run).data, status=status.HTTP_201_CREATED)


class PlanDraftViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, FarmScopedGenericViewSet):
    serializer_class = AIRunSerializer
    permission_map = {"list": AI, "retrieve": AI, "create": AI}

    def get_queryset(self) -> QuerySet[AIRun]:
        return AIRun.objects.filter(farm_id=self.farm_id, kind=AIRun.Kind.PLAN_DRAFT)

    @extend_schema(request=PlanDraftRequestSerializer, responses={201: AIRunSerializer})
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = PlanDraftRequestSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        run = services.run_plan_draft(self.tenant, data=dict(serializer.validated_data))
        return Response(AIRunSerializer(run).data, status=status.HTTP_201_CREATED)


@extend_schema(parameters=[OpenApiParameter("farm_id", OpenApiTypes.UUID, OpenApiParameter.PATH)])
class SuggestionViewSet(mixins.RetrieveModelMixin, FarmScopedGenericViewSet):
    serializer_class = AISuggestionSerializer
    permission_map = {"retrieve": "plans.view", "decide": "plans.edit"}

    def get_queryset(self) -> QuerySet[AISuggestion]:
        return AISuggestion.objects.filter(plan_version__farm_id=self.farm_id)

    @extend_schema(request=DecisionSerializer, responses=AISuggestionSerializer)
    @action(detail=True, methods=["post"])
    def decide(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = DecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        suggestion = services.decide_suggestion(
            self.tenant,
            suggestion_id=self.get_object().id,
            decision=serializer.validated_data["decision"],
            value=serializer.validated_data.get("value"),
        )
        return Response(AISuggestionSerializer(suggestion).data)
