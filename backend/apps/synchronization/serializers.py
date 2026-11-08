from rest_framework import serializers

from apps.synchronization.models import SyncConflict

MAX_BATCH = 100


class OperationSerializer(serializers.Serializer):
    op_id = serializers.UUIDField()
    farm_id = serializers.UUIDField()
    op_type = serializers.ChoiceField(choices=["create", "update", "delete", "command"])
    entity_type = serializers.CharField(max_length=100)
    entity_id = serializers.UUIDField()
    command = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    payload = serializers.DictField(required=False, default=dict)
    base_version = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    base_values = serializers.DictField(required=False, default=dict)
    created_at = serializers.DateTimeField(required=False, allow_null=True)
    author_id = serializers.UUIDField(required=False, allow_null=True)
    depends_on = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)


class PushRequestSerializer(serializers.Serializer):
    device_id = serializers.UUIDField(required=False, allow_null=True)
    client_version = serializers.CharField(required=False, allow_blank=True, max_length=50)
    protocol_version = serializers.IntegerField(default=1, min_value=1, max_value=1)
    operations = OperationSerializer(many=True, allow_empty=True)

    def validate_operations(self, value: list) -> list:
        if len(value) > MAX_BATCH:
            raise serializers.ValidationError(f"Au plus {MAX_BATCH} opérations par lot.")
        ids = [op["op_id"] for op in value]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("op_id dupliqué dans le lot.")
        return value


class OperationResultSerializer(serializers.Serializer):
    op_id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=["applied", "rejected", "conflict"])
    entity_version = serializers.IntegerField(required=False)
    conflict_id = serializers.UUIDField(required=False)
    error = serializers.DictField(required=False)


class PushResponseSerializer(serializers.Serializer):
    results = OperationResultSerializer(many=True)
    server_time = serializers.DateTimeField()


class PullQuerySerializer(serializers.Serializer):
    farm_id = serializers.UUIDField()
    cursor = serializers.IntegerField(min_value=0, default=0)
    limit = serializers.IntegerField(min_value=1, max_value=500, default=500)


class PullResponseSerializer(serializers.Serializer):
    changes = serializers.ListField(child=serializers.DictField())
    next_cursor = serializers.IntegerField()
    has_more = serializers.BooleanField()
    purge = serializers.ListField(child=serializers.CharField())
    server_seq = serializers.IntegerField()


class SyncConflictSerializer(serializers.ModelSerializer):
    op_id = serializers.UUIDField(source="receipt_id", read_only=True)

    class Meta:
        model = SyncConflict
        fields = [
            "id",
            "op_id",
            "entity_type",
            "entity_id",
            "conflict_type",
            "fields",
            "client_payload",
            "server_snapshot",
            "message",
            "status",
            "resolution",
            "raised_for",
            "resolved_by",
            "resolved_at",
            "created_at",
        ]
        read_only_fields = fields


class ConflictResolveSerializer(serializers.Serializer):
    resolution = serializers.ChoiceField(
        choices=[*SyncConflict.Resolution.values, "dismiss"],
        help_text="keep_server, apply_client (après envoi d'une nouvelle opération), merged, "
        "manual, ou dismiss.",
    )
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)
