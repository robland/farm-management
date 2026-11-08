from django.contrib import admin

from apps.audit.models import AuditEvent
from apps.core.admin import ReadOnlyAdmin


@admin.register(AuditEvent)
class AuditEventAdmin(ReadOnlyAdmin):
    """Append-only journal: consultation only (also enforced by a database trigger)."""

    list_display = ["created_at", "action", "entity_type", "entity_id", "actor", "organization_id"]
    list_select_related = ["actor"]
    search_fields = ["action", "entity_type", "=entity_id", "=organization_id", "=request_id"]
    list_filter = ["entity_type"]
    date_hierarchy = "created_at"
    show_full_result_count = False
