from rest_framework import serializers

from apps.crops.models import Crop


class CropSerializer(serializers.ModelSerializer):
    is_global = serializers.BooleanField(read_only=True)

    class Meta:
        model = Crop
        fields = [
            "id",
            "common_name",
            "scientific_name",
            "family",
            "category",
            "is_global",
            "version",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_global", "version", "created_at", "updated_at"]
