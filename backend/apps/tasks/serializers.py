from typing import Any

from rest_framework import serializers

from apps.agronomy.models import InputProduct
from apps.core.serializers import FarmScopedPrimaryKeyRelatedField
from apps.fields.models import Parcel
from apps.files.models import StoredFile
from apps.inventory.serializers import OrgScopedRelatedField
from apps.tasks.models import InputConsumption, Task, TaskReport, TaskStatusEvent, Team
from apps.tasks.services import is_late


class TaskSerializer(serializers.ModelSerializer):
    parcel = FarmScopedPrimaryKeyRelatedField(
        queryset=Parcel.objects.all(), required=False, allow_null=True
    )
    is_late = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "id",
            "plan",
            "plan_version",
            "crop_cycle",
            "parcel",
            "task_type",
            "title",
            "description",
            "planned_start_date",
            "planned_end_date",
            "status",
            "is_late",
            "origin",
            "source_ref",
            "superseded_by",
            "assignees",
            "teams",
            "version",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "plan",
            "plan_version",
            "crop_cycle",
            "status",
            "is_late",
            "origin",
            "source_ref",
            "superseded_by",
            "assignees",
            "teams",
            "version",
            "created_at",
            "updated_at",
        ]

    def get_is_late(self, task: Task) -> bool:
        today = self.context.get("today")
        return bool(today and is_late(task, today))


class TaskStatusEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskStatusEvent
        fields = ["from_status", "to_status", "actor", "reason", "occurred_at"]
        read_only_fields = fields


class StatusChangeSerializer(serializers.Serializer):
    to = serializers.ChoiceField(choices=Task.Status.choices)
    reason = serializers.CharField(required=False, allow_blank=True)


class AssignSerializer(serializers.Serializer):
    users = serializers.ListField(child=serializers.UUIDField(), default=list)
    teams = serializers.ListField(child=serializers.UUIDField(), default=list)


class ConsumptionSerializer(serializers.ModelSerializer):
    product = OrgScopedRelatedField(queryset=InputProduct.objects.all())

    class Meta:
        model = InputConsumption
        fields = ["product", "quantity", "unit", "lot_number", "quantity_base", "base_unit"]
        read_only_fields = ["quantity_base", "base_unit"]


class TaskReportSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(required=False)
    task = FarmScopedPrimaryKeyRelatedField(queryset=Task.objects.all())
    consumptions = ConsumptionSerializer(many=True, required=False)
    photos = OrgScopedRelatedField(queryset=StoredFile.objects.all(), many=True, required=False)

    class Meta:
        model = TaskReport
        fields = [
            "id",
            "task",
            "reported_by",
            "actual_start",
            "actual_end",
            "duration_minutes",
            "completion",
            "notes",
            "deviation_notes",
            "photos",
            "consumptions",
            "created_at",
            "version",
        ]
        read_only_fields = ["reported_by", "created_at", "version"]

    def to_representation(self, instance: TaskReport) -> dict[str, Any]:
        data = super().to_representation(instance)
        data["consumptions"] = ConsumptionSerializer(instance.consumptions.all(), many=True).data
        return data


class TeamSerializer(serializers.ModelSerializer):
    members = serializers.ListField(child=serializers.UUIDField(), write_only=True, default=list)

    class Meta:
        model = Team
        fields = ["id", "name", "members", "version"]
        read_only_fields = ["id", "version"]

    def to_representation(self, instance: Team) -> dict[str, Any]:
        data = super().to_representation(instance)
        data["members"] = [str(pk) for pk in instance.members.values_list("id", flat=True)]
        return data


class GenerateSerializer(serializers.Serializer):
    plan_version = serializers.UUIDField()
