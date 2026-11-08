from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin, ReadOnlyTabularInline, register_read_only
from apps.tasks.models import InputConsumption, Task, TaskReport, TaskStatusEvent, Team


class TaskStatusEventInline(ReadOnlyTabularInline):
    model = TaskStatusEvent
    show_change_link = False


@admin.register(Task)
class TaskAdmin(ReadOnlyAdmin):
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


class InputConsumptionInline(ReadOnlyTabularInline):
    model = InputConsumption


@admin.register(TaskReport)
class TaskReportAdmin(ReadOnlyAdmin):
    inlines = [InputConsumptionInline]


register_read_only(Team, TaskStatusEvent, InputConsumption)
