from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin
from apps.files.models import StoredFile


@admin.register(StoredFile)
class StoredFileAdmin(ReadOnlyAdmin):
    """Metadata only: file contents are downloaded through the API permission checks."""

    list_display = [
        "original_name",
        "purpose",
        "status",
        "detected_mime",
        "size_bytes",
        "organization",
        "farm",
        "created_at",
    ]
    search_fields = ["original_name", "=sha256", "=id"]
