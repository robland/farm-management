from django import forms
from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin
from apps.core.admin_services import ServiceAdmin, service_action
from apps.core.tenancy import TenantContext
from apps.synchronization import services
from apps.synchronization.models import ChangeLog, FarmSyncState, SyncConflict, SyncOperationReceipt


@admin.register(FarmSyncState)
class FarmSyncStateAdmin(ReadOnlyAdmin):
    list_display = ["farm", "last_seq", "compacted_before_seq"]
    list_select_related = ["farm"]
    search_fields = ["farm__name"]


@admin.register(ChangeLog)
class ChangeLogAdmin(ReadOnlyAdmin):
    list_display = ["farm", "seq", "entity_type", "entity_id", "operation", "changed_at"]
    list_select_related = ["farm"]
    search_fields = ["entity_type", "=entity_id", "=origin_op_id"]
    list_filter = ["operation", "entity_type"]
    ordering = ["-changed_at"]
    show_full_result_count = False


@admin.register(SyncOperationReceipt)
class SyncOperationReceiptAdmin(ReadOnlyAdmin):
    list_display = ["op_id", "entity_type", "op_type", "status", "user", "farm", "received_at"]
    list_select_related = ["user", "farm"]
    search_fields = ["=op_id", "=entity_id", "entity_type"]
    list_filter = ["status", "op_type"]
    ordering = ["-received_at"]
    show_full_result_count = False


class ResolveForm(forms.Form):
    resolution = forms.ChoiceField(
        label="Résolution",
        choices=[*SyncConflict.Resolution.choices, ("dismiss", "Ignorer")],
    )
    note = forms.CharField(label="Note", required=False)


@admin.register(SyncConflict)
class SyncConflictAdmin(ServiceAdmin):
    """Conflicts are shown explicitly and resolved by a person (CLAUDE.md §8)."""

    list_display = ["entity_type", "entity_id", "conflict_type", "status", "farm", "created_at"]
    list_select_related = ["farm"]
    search_fields = ["=entity_id", "entity_type"]
    list_filter = ["status", "conflict_type", "resolution"]
    actions = ["resolve"]

    @service_action("Résoudre les conflits", form=ResolveForm)
    def resolve(self, ctx: TenantContext, obj: SyncConflict, resolution: str, note: str) -> None:
        services.resolve_conflict(ctx, conflict_id=obj.id, resolution=resolution, note=note)
