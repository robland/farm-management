"""Django admin for platform staff (OPEN_QUESTIONS Q34): consultation building blocks.

A plain model admin form would bypass the services (permissions, optimistic versions,
audit trail, synchronisation change log). `ReadOnlyAdmin` is therefore view-only;
writes are added by `apps.core.admin_services.ServiceAdmin`, which delegates every
creation, change, deletion and workflow action to the business services.

`ReadOnlyAdmin` derives a sensible change list from the model when an attribute
is not set explicitly: title/status columns, organisation and farm scope,
choice filters, a search on names and on the exact id, and `select_related` on
the displayed foreign keys (no N+1 on the change list).
"""

from typing import Any

from django.contrib import admin
from django.db import models
from django.http import HttpRequest

# Never displayed, even read-only: credentials and secrets stay out of the admin.
SECRET_FIELDS = frozenset({"password", "token_hash", "key_hash", "secret"})

_TITLE_FIELDS = ("name", "title", "full_name", "common_name", "label", "code", "reference")
_STATUS_FIELDS = ("status", "kind", "category", "op_type", "action", "entity_type", "purpose")
_SCOPE_FIELDS = ("organization", "farm")
_DATE_FIELDS = ("business_date", "occurred_at", "created_at")
_FILTER_LIMIT = 4


def _concrete_names(model: type[models.Model]) -> "dict[str, models.Field[Any, Any]]":
    return {
        f.name: f
        for f in model._meta.get_fields()
        if isinstance(f, models.Field) and f.concrete and not f.many_to_many
    }


def _exact_pk_search(model: type[models.Model]) -> str:
    pk = model._meta.pk
    if pk is not None and pk.is_relation:
        # A one-to-one primary key (e.g. PlantingSpec) is searched on the related id.
        return f"={pk.name}__id"
    return "=pk"


def _derive_list_display(fields: "dict[str, models.Field[Any, Any]]") -> list[str]:
    title = next((name for name in _TITLE_FIELDS if name in fields), "__str__")
    columns = [title]
    columns += [name for name in _STATUS_FIELDS if name in fields and name != title]
    columns += [name for name in _SCOPE_FIELDS if name in fields]
    columns += [name for name in ("version", "deleted_at") if name in fields]
    columns += next(([name] for name in _DATE_FIELDS if name in fields), [])
    return columns


class ReadOnlyAdmin(admin.ModelAdmin):
    """View-only admin; change-list options are derived from the model when not declared.

    Derivation goes through the `get_*` hooks, so a declared class attribute always wins.
    """

    def __init__(self, model: type[models.Model], admin_site: admin.AdminSite) -> None:
        super().__init__(model, admin_site)
        self._fields = _concrete_names(model)
        self._secrets = [name for name in self._fields if name in SECRET_FIELDS]

    def get_list_display(self, request: HttpRequest) -> Any:
        if tuple(self.list_display) != ("__str__",):  # Django's default: not declared
            return self.list_display
        return _derive_list_display(self._fields)

    def get_search_fields(self, request: HttpRequest) -> Any:
        if self.search_fields:
            return self.search_fields
        text_types = models.CharField | models.EmailField
        names = [n for n in _TITLE_FIELDS if isinstance(self._fields.get(n), text_types)]
        return [*names, _exact_pk_search(self.model)]

    def get_list_filter(self, request: HttpRequest) -> Any:
        if self.list_filter:
            return self.list_filter
        filters: list[Any] = [
            n for n in _STATUS_FIELDS if n in self._fields and self._fields[n].choices
        ][:_FILTER_LIMIT]
        if "deleted_at" in self._fields:
            filters.append(("deleted_at", admin.EmptyFieldListFilter))
        return filters

    def get_list_select_related(self, request: HttpRequest) -> Any:
        if self.list_select_related is not False:
            return self.list_select_related
        return [
            name
            for name in self.get_list_display(request)
            if isinstance(name, str) and isinstance(self._fields.get(name), models.ForeignKey)
        ]

    def get_ordering(self, request: HttpRequest) -> Any:
        if self.ordering:
            return self.ordering
        return next(([f"-{n}"] for n in _DATE_FIELDS if n in self._fields), [])

    def get_exclude(self, request: HttpRequest, obj: Any = None) -> Any:
        return [*(super().get_exclude(request, obj) or []), *self._secrets] or None

    def get_readonly_fields(self, request: HttpRequest, obj: Any = None) -> Any:
        if self.readonly_fields:
            return self.readonly_fields
        # Non-editable fields (id, timestamps) are not form fields: list them explicitly
        # so that the detail page shows them too.
        return [n for n, f in self._fields.items() if not f.editable and n not in self._secrets]

    def has_add_permission(self, request: HttpRequest, *args: Any) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


class ReadOnlyTabularInline(admin.TabularInline):
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


class ReadOnlyStackedInline(admin.StackedInline):
    extra = 0
    can_delete = False

    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


def register_read_only(*models_: type[models.Model]) -> None:
    """Register models with the derived read-only admin."""
    for model in models_:
        admin.site.register(model, ReadOnlyAdmin)
