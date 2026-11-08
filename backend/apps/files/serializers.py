from rest_framework import serializers

from apps.files.models import StoredFile


class StoredFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = StoredFile
        fields = [
            "id",
            "original_name",
            "detected_mime",
            "size_bytes",
            "sha256",
            "purpose",
            "status",
            "uploaded_by",
            "created_at",
        ]
        read_only_fields = fields


class FileUploadSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False, help_text="UUID client (file d'attente hors ligne).")
    purpose = serializers.ChoiceField(choices=StoredFile.Purpose.choices)
    file = serializers.FileField()
