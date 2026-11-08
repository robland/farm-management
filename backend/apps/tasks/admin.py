from typing import Any

from django import forms
from django.contrib import admin
from django.http import HttpRequest

from apps.core.admin import ReadOnlyTabularInline, register_read_only
from apps.core.admin_services import ServiceAdmin, platform_context, service_action
from apps.core.tenancy import TenantContext
from apps.tasks import services
from apps.tasks.models import InputConsumption, Task, TaskReport, TaskStatusEvent, Team
from apps.users.models import User

TASK_FIELDS = [
    "parcel",
    "task_type",
    "title",
    "description",
    "planned_start_date",
    "planned_end_date",
]


@admin.register(Team)
class TeamAdmin(ServiceAdmin):
    add_fields = ["name", "members"]

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> Team:
        return services.create_team(
            ctx, name=data["name"], member_ids=[user.id for user in data.get("members", [])]
        )


class TaskStatusEventInline(ReadOnlyTabularInline):
    model = TaskStatusEvent
    show_change_link = False


class StatusForm(forms.Form):
    to_status = forms.ChoiceField(label="Nouveau statut", choices=Task.Status.choices)
    reason = forms.CharField(label="Motif (annulation, réouverture)", required=False)


class AssignForm(forms.Form):
    users = forms.ModelMultipleChoiceField(
        label="Personnes",
        queryset=User.objects.filter(is_active=True),
        required=False,
        help_text="Membres actifs de l'exploitation uniquement (vérifié par le service).",
    )
    teams = forms.ModelMultipleChoiceField(
        label="Équipes", queryset=Team.objects.all(), required=False
    )


@admin.register(Task)
class TaskAdmin(ServiceAdmin):
    """Task workflow: create or generate from a validated plan → assign → statuses → report."""

    list_display = [
        "title",
        "task_type",
        "status",
        "planned_start_date",
        "planned_end_date",
        "parcel",
        "farm",
    ]
    list_select_related = ["parcel", "farm"]
    list_filter = ["status", "task_type", "origin"]
    inlines = [TaskStatusEventInline]
    add_fields = TASK_FIELDS
    change_fields = TASK_FIELDS
    actions = ["change_status", "assign"]

    def can_change(self, obj: Any) -> bool:
        return obj.status not in (Task.Status.DONE, Task.Status.CANCELLED)

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> Task:
        return services.create_task(ctx, data=data)

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        return services.update_task(
            ctx, task_id=obj.id, expected_version=expected_version, changes=changes
        )

    @service_action("Changer le statut (transitions autorisées uniquement)", form=StatusForm)
    def change_status(self, ctx: TenantContext, obj: Task, to_status: str, reason: str) -> None:
        services.change_status(
            ctx, task_id=obj.id, to_status=to_status, expected_from=obj.status, reason=reason
        )

    @service_action("Affecter", form=AssignForm)
    def assign(self, ctx: TenantContext, obj: Task, users: Any, teams: Any) -> None:
        services.assign_task(
            ctx,
            task_id=obj.id,
            user_ids=[u.id for u in users],
            team_ids=[t.id for t in teams if t.farm_id == obj.farm_id],
        )


class InputConsumptionInline(ReadOnlyTabularInline):
    model = InputConsumption


@admin.register(TaskReport)
class TaskReportAdmin(ServiceAdmin):
    """A report is entered for its task; consumptions are recorded through the API."""

    scope = "task"
    replay_by_id = True
    add_fields = [
        "actual_start",
        "actual_end",
        "duration_minutes",
        "completion",
        "notes",
        "deviation_notes",
    ]
    inlines = [InputConsumptionInline]

    def context_for(self, request: HttpRequest, obj: Any) -> TenantContext:
        return platform_context(request, organization_id=obj.organization_id, farm_id=obj.farm_id)

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> TaskReport:
        return services.create_report(ctx, data={**data, "consumptions": []})[0]


register_read_only(TaskStatusEvent, InputConsumption)
