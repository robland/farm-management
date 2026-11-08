from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from apps.audit.services import record_event
from apps.core.admin_services import ServiceAdmin, platform_context
from apps.core.exceptions import VersionConflictError
from apps.core.tenancy import TenantContext
from apps.crops import services
from apps.crops.models import Crop

CROP_FIELDS = ["common_name", "scientific_name", "family", "category"]


@admin.register(Crop)
class CropAdmin(ServiceAdmin):
    """Organization crops go through the services; the shared catalogue is maintained here.

    Leaving `organization` empty creates a crop of the shared catalogue (no API can):
    it is saved directly, with an audit event and a version increment.
    """

    list_display = ["common_name", "scientific_name", "family", "category", "organization"]
    list_select_related = ["organization"]
    list_filter = ["category", ("organization", admin.EmptyFieldListFilter)]
    search_fields = ["common_name", "scientific_name", "family", "=id"]
    scope = "organization"
    add_fields = CROP_FIELDS
    change_fields = CROP_FIELDS

    def get_form(
        self, request: HttpRequest, obj: Any = None, change: bool = False, **kwargs: Any
    ) -> Any:
        form = super().get_form(request, obj, change=change, **kwargs)
        if obj is None:
            form.base_fields["organization"].required = False
            form.base_fields["organization"].help_text = "Vide : référentiel commun des cultures."
        return form

    def context_for(self, request: HttpRequest, obj: Any) -> TenantContext:
        if obj.organization_id is None:
            return platform_context(request, organization_id=obj.id)  # unused by global crops
        return super().context_for(request, obj)

    def run_form_service(self, request: HttpRequest, form: Any) -> Any:
        adding = form.instance._state.adding
        if (adding and form.cleaned_data.get("organization") is None) or (
            not adding and form.instance.organization_id is None
        ):
            return self._save_global(request, form, adding)
        return super().run_form_service(request, form)

    def _save_global(self, request: HttpRequest, form: Any, adding: bool) -> Crop | None:
        changed = [name for name in form.changed_data if name in CROP_FIELDS]
        if not adding and not changed:
            return None
        crop = Crop() if adding else Crop.objects.select_for_update().get(pk=form.instance.pk)
        if not adding and crop.version != (
            form.cleaned_data.get("expected_version") or crop.version
        ):
            raise VersionConflictError(crop.version)
        before = {name: getattr(crop, name) for name in changed}
        for name in CROP_FIELDS:
            setattr(crop, name, form.cleaned_data.get(name, getattr(crop, name)))
        crop.updated_by = request.user  # type: ignore[assignment]
        if adding:
            crop.created_by = request.user  # type: ignore[assignment]
        else:
            crop.version += 1
        crop.full_clean()
        crop.save()
        record_event(
            action="crop.created" if adding else "crop.updated",
            actor=request.user,
            entity_type="crops.crop",
            entity_id=crop.id,
            before=None if adding else before,
            after={name: getattr(crop, name) for name in changed},
        )
        return crop

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> Crop:
        return services.create_crop(ctx, data=data)

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        return services.update_crop(
            ctx, crop_id=obj.id, expected_version=expected_version, changes=changes
        )

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        if obj is not None and obj.organization_id is None:
            return False  # the shared catalogue is referenced by every organization
        return super().has_delete_permission(request, obj)

    def perform_delete(self, ctx: TenantContext, obj: Any) -> None:
        services.delete_crop(ctx, crop_id=obj.id)
