from typing import Any

from django.db.models import Q, QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.versioning import parse_if_match
from apps.farms.viewsets import FarmScopedGenericViewSet
from apps.tasks import services
from apps.tasks.models import Task, TaskReport, Team
from apps.tasks.serializers import (
    AssignSerializer,
    GenerateSerializer,
    StatusChangeSerializer,
    TaskReportSerializer,
    TaskSerializer,
    TaskStatusEventSerializer,
    TeamSerializer,
)

V, E = services.VIEW, services.EDIT


class TaskViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, FarmScopedGenericViewSet):
    serializer_class = TaskSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]
    permission_map = {
        "list": V,
        "retrieve": V,
        "create": E,
        "partial_update": E,
        "generate": E,
        "status": services.REPORT,
        "assign": services.ASSIGN,
        "history": V,
        "mine": V,
    }
    filterset_fields = ["status", "parcel", "plan", "task_type", "crop_cycle"]

    def get_queryset(self) -> QuerySet[Task]:
        queryset = Task.objects.filter(farm_id=self.farm_id).prefetch_related("assignees", "teams")
        late = self.request.query_params.get("late")
        if late in {"true", "1"}:
            queryset = queryset.filter(
                status__in=["todo", "in_progress"],
                planned_end_date__lt=services.farm_today(self.farm_id),
            )
        return queryset

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        if not getattr(self, "swagger_fake_view", False):
            context["today"] = services.farm_today(self.farm_id)
        return context

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = services.create_task(self.tenant, data=dict(serializer.validated_data))
        return Response(self.get_serializer(task).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        task = self.get_object()
        serializer = self.get_serializer(task, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        task = services.update_task(
            self.tenant,
            task_id=task.id,
            expected_version=parse_if_match(request),
            changes=dict(serializer.validated_data),
        )
        return Response(self.get_serializer(task).data)

    @extend_schema(request=GenerateSerializer)
    @action(detail=False, methods=["post"])
    def generate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = GenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        summary = services.generate_tasks(
            self.tenant, version_id=serializer.validated_data["plan_version"]
        )
        return Response(summary)

    @extend_schema(request=StatusChangeSerializer, responses=TaskSerializer)
    @action(detail=True, methods=["post"])
    def status(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = StatusChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = self.get_object()
        services.change_status(
            self.tenant,
            task_id=task.id,
            to_status=serializer.validated_data["to"],
            reason=serializer.validated_data.get("reason", ""),
        )
        return Response(self.get_serializer(Task.objects.get(id=task.id)).data)

    @extend_schema(request=AssignSerializer, responses=TaskSerializer)
    @action(detail=True, methods=["post"])
    def assign(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = AssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = services.assign_task(
            self.tenant,
            task_id=self.get_object().id,
            user_ids=serializer.validated_data["users"],
            team_ids=serializer.validated_data["teams"],
        )
        return Response(self.get_serializer(task).data)

    @extend_schema(responses=TaskStatusEventSerializer(many=True))
    @action(detail=True, methods=["get"])
    def history(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        events = self.get_object().status_events.all()
        return Response(TaskStatusEventSerializer(events, many=True).data)

    @action(detail=False, methods=["get"])
    def mine(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        user = request.user
        queryset = self.get_queryset().filter(Q(assignees=user) | Q(teams__members=user)).distinct()
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(self.get_serializer(page, many=True).data)


class TaskReportViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, FarmScopedGenericViewSet):
    serializer_class = TaskReportSerializer
    permission_map = {"list": V, "retrieve": V, "create": services.REPORT}
    filterset_fields = ["task", "reported_by", "completion"]

    def get_queryset(self) -> QuerySet[TaskReport]:
        return TaskReport.objects.filter(farm_id=self.farm_id).prefetch_related(
            "consumptions", "photos"
        )

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        report, created = services.create_report(self.tenant, data=dict(serializer.validated_data))
        return Response(
            self.get_serializer(report).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class TeamViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, FarmScopedGenericViewSet):
    serializer_class = TeamSerializer
    permission_map = {"list": V, "retrieve": V, "create": services.ASSIGN}

    def get_queryset(self) -> QuerySet[Team]:
        return Team.objects.filter(farm_id=self.farm_id).prefetch_related("members")

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        team = services.create_team(
            self.tenant,
            name=serializer.validated_data["name"],
            member_ids=serializer.validated_data["members"],
        )
        return Response(self.get_serializer(team).data, status=status.HTTP_201_CREATED)
