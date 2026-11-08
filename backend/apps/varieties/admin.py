from typing import Any

from django import forms
from django.contrib import admin
from django.http import HttpRequest

from apps.core.admin import ReadOnlyTabularInline
from apps.core.admin_services import ServiceAdmin, ServiceForm, platform_context, service_action
from apps.core.tenancy import TenantContext
from apps.files import services as files
from apps.files.models import StoredFile
from apps.varieties import services
from apps.varieties.models import TechnicalDataItem, TechnicalDataSet, TechnicalDocument, Variety

VARIETY_FIELDS = ["crop", "name", "seed_company", "description", "is_hybrid"]
ITEM_VALUE_FIELDS = [
    "value_numeric",
    "value_min",
    "value_max",
    "value_text",
    "unit",
    "provenance",
    "source_page",
    "source_section",
    "source_quote",
    "confidence",
    "notes",
]


@admin.register(Variety)
class VarietyAdmin(ServiceAdmin):
    scope = "organization"
    add_fields = VARIETY_FIELDS
    change_fields = VARIETY_FIELDS

    def can_change(self, obj: Any) -> bool:
        return obj.deleted_at is None

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> Variety:
        return services.create_variety(ctx, data=data)

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        return services.update_variety(
            ctx, variety_id=obj.id, expected_version=expected_version, changes=changes
        )

    def perform_delete(self, ctx: TenantContext, obj: Any) -> None:
        services.delete_variety(ctx, variety_id=obj.id, expected_version=obj.version)


class TechnicalDocumentForm(ServiceForm):
    upload = forms.FileField(label="Fiche technique (PDF)")


@admin.register(TechnicalDocument)
class TechnicalDocumentAdmin(ServiceAdmin):
    """Upload a technical sheet: stored by the file service (type and size checks)."""

    form = TechnicalDocumentForm
    scope = "variety"
    add_fields = ["upload", "title", "supplier", "document_date", "language"]
    actions = ["extract"]

    @service_action("Extraire les données par l'assistant IA (brouillon à valider)")
    def extract(self, ctx: TenantContext, obj: TechnicalDocument) -> str | None:
        from apps.ai_assistant import services as ai  # optional module, loaded on use

        run = ai.run_extraction(ctx, document_id=obj.id)
        if run.status != run.Status.SUCCEEDED:
            # Not an exception: the failed run stays recorded (cost, error) for follow-up.
            return f"{obj} : {run.error_message or 'assistant IA indisponible'} (saisie manuelle)."
        return None

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> TechnicalDocument:
        upload = data.pop("upload")
        variety = data.pop("variety")
        stored, _ = files.upload_file(
            ctx,
            stream=upload,
            original_name=upload.name,
            purpose=StoredFile.Purpose.TECHNICAL_SHEET,
            declared_mime=getattr(upload, "content_type", "") or "",
        )
        return services.add_document(ctx, variety_id=variety.id, file_id=stored.id, data=data)


class TechnicalDataItemInline(ReadOnlyTabularInline):
    model = TechnicalDataItem


@admin.register(TechnicalDataSet)
class TechnicalDataSetAdmin(ServiceAdmin):
    scope = "variety"
    add_fields = ["source_document", "based_on", "notes"]
    inlines = [TechnicalDataItemInline]
    actions = ["validate"]

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> TechnicalDataSet:
        source, based_on = data.get("source_document"), data.get("based_on")
        return services.create_data_set(
            ctx,
            variety_id=data["variety"].id,
            source_document_id=source.id if source else None,
            based_on_id=based_on.id if based_on else None,
            notes=data.get("notes", ""),
        )

    @service_action("Valider les jeux de données (tous les éléments doivent être validés)")
    def validate(self, ctx: TenantContext, obj: TechnicalDataSet) -> None:
        services.validate_data_set(ctx, data_set_id=obj.id)


@admin.register(TechnicalDataItem)
class TechnicalDataItemAdmin(ServiceAdmin):
    """Items of a draft data set; a changed value must be validated again."""

    list_display = [
        "key",
        "value_numeric",
        "value_text",
        "unit",
        "provenance",
        "validated",
        "data_set",
    ]
    list_select_related = ["data_set"]
    list_filter = ["provenance", "validated"]
    search_fields = ["key", "=data_set__id"]
    scope = "data_set"
    add_fields = ["key", *ITEM_VALUE_FIELDS]
    change_fields = ITEM_VALUE_FIELDS
    actions = ["validate_items"]

    def context_for(self, request: HttpRequest, obj: Any) -> TenantContext:
        return platform_context(request, organization_id=obj.data_set.organization_id)

    def can_change(self, obj: Any) -> bool:
        return obj.data_set.status == TechnicalDataSet.Status.DRAFT

    def _item(self, obj: Any, changes: dict[str, Any]) -> dict[str, Any]:
        values = {name: getattr(obj, name) for name in ITEM_VALUE_FIELDS}
        return {"key": obj.key, **values, **changes}

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> TechnicalDataItem:
        data_set = data.pop("data_set")
        services.upsert_items(ctx, data_set_id=data_set.id, items=[data])
        return TechnicalDataItem.objects.get(data_set=data_set, key=data["key"])

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        services.upsert_items(ctx, data_set_id=obj.data_set_id, items=[self._item(obj, changes)])
        return TechnicalDataItem.objects.get(pk=obj.pk)

    def perform_delete(self, ctx: TenantContext, obj: Any) -> None:
        services.remove_items(ctx, data_set_id=obj.data_set_id, keys=[obj.key])

    @service_action("Valider les éléments sélectionnés")
    def validate_items(self, ctx: TenantContext, obj: TechnicalDataItem) -> None:
        services.validate_items(ctx, data_set_id=obj.data_set_id, keys=[obj.key])
