from typing import Any

from django.contrib import admin
from django.forms import ModelForm
from django.http import HttpRequest

from apps.audit.services import record_event
from apps.crops.models import Crop


@admin.register(Crop)
class CropAdmin(admin.ModelAdmin):
    """The shared crop catalogue (`organization` empty) is maintained here by the platform.

    No API can create a global crop. Crops owned by an organization stay read-only:
    they belong to that organization and are edited through the API.
    """

    list_display = ["common_name", "scientific_name", "family", "category", "organization"]
    list_select_related = ["organization"]
    list_filter = ["category", ("organization", admin.EmptyFieldListFilter)]
    search_fields = ["common_name", "scientific_name", "family", "=id"]
    fields = [
        "id",
        "common_name",
        "scientific_name",
        "family",
        "category",
        "organization",
        "version",
        "created_at",
        "updated_at",
    ]
    readonly_fields = ["id", "organization", "version", "created_at", "updated_at"]

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        if obj is not None and obj.organization_id is not None:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        # Varieties and plans reference crops (PROTECT): never deleted from here.
        return False

    def save_model(self, request: HttpRequest, obj: Crop, form: ModelForm, change: bool) -> None:
        before = {name: form.initial.get(name) for name in form.changed_data}
        obj.organization = None
        obj.updated_by = request.user  # type: ignore[assignment]
        if change:
            if not form.changed_data:
                return
            obj.version += 1
        else:
            obj.created_by = request.user  # type: ignore[assignment]
        super().save_model(request, obj, form, change)
        record_event(
            action="crop.updated" if change else "crop.created",
            actor=request.user,
            entity_type="crops.crop",
            entity_id=obj.id,
            before=before if change else None,
            after={name: form.cleaned_data.get(name) for name in form.changed_data},
        )
