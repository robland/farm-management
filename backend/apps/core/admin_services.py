"""Service-backed Django admin: create, edit, delete and run workflows through the services.

An admin form never writes a model directly. It validates its fields, then
calls the same business service as the API, inside a *platform context*:
the staff member acts with every permission of the target organization
(`is_org_admin=True`). The gate is the Django admin itself: `is_staff` plus
the model permissions (`add_`, `change_`, `delete_`). Services therefore keep
enforcing their invariants: optimistic versions (the form carries the version
it was displayed with), tenant consistency of references, audit trail (the
actor is the staff member), synchronisation change log, immutable finance.

Workflow actions (validate, reverse, compute…) are change-list actions that
call one service per selected object; those that need input (a reason, a
target status) display an intermediate form first.
"""

import functools
import uuid
from collections.abc import Callable, Sequence
from typing import Any, cast

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models, transaction
from django.db.models import Q, QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

from apps.core.admin import SECRET_FIELDS, ReadOnlyAdmin
from apps.core.exceptions import DomainError
from apps.core.tenancy import TenantContext
from apps.users.models import User

PROTECTED_FROM_EDIT = frozenset({"id", "organization", "farm", "version"})


def platform_context(
    request: HttpRequest, *, organization_id: uuid.UUID, farm_id: uuid.UUID | None = None
) -> TenantContext:
    """Context of a staff member acting through the admin (see module docstring)."""
    return TenantContext(
        user=cast(User, request.user),
        organization_id=organization_id,
        farm_id=farm_id,
        is_org_admin=True,
    )


def scope_of(obj: Any) -> tuple[uuid.UUID, uuid.UUID | None]:
    """(organization, farm) owning `obj`: an organization, a farm or a tenant-owned row."""
    label = obj._meta.label
    if label == "organizations.Organization":
        return obj.id, None
    if label == "farms.Farm":
        return obj.organization_id, obj.id
    return obj.organization_id, getattr(obj, "farm_id", None)


def error_messages(exc: Exception) -> list[str]:
    if isinstance(exc, DomainError):
        details = [f"{field} : {' '.join(msgs)}" for field, msgs in exc.field_errors.items()]
        return [exc.message, *details]
    if isinstance(exc, DjangoValidationError):
        return list(exc.messages)
    return [str(exc)]


def _add_errors(form: forms.BaseForm, exc: Exception) -> None:
    if isinstance(exc, DomainError) and exc.field_errors:
        for field, msgs in exc.field_errors.items():
            form.add_error(field if field in form.fields else None, msgs)
        if exc.message and exc.message != exc.code:
            form.add_error(None, exc.message)
        return
    if isinstance(exc, DjangoValidationError) and hasattr(exc, "error_dict"):
        for field, errors in exc.error_dict.items():
            form.add_error(field if field in form.fields else None, errors)
        return
    form.add_error(None, error_messages(exc))


def _same_scope(value: Any, organization_id: uuid.UUID, farm_id: uuid.UUID | None) -> bool:
    values = list(value) if isinstance(value, QuerySet | list | tuple) else [value]
    for item in values:
        if not isinstance(item, models.Model):
            continue
        item_farm = getattr(item, "farm_id", None)
        if farm_id is not None and item_farm is not None and item_farm != farm_id:
            return False
        item_org = getattr(item, "organization_id", None)
        if item_org is not None and item_org != organization_id:
            return False
    return True


class ServiceForm(forms.ModelForm):
    """Model form whose saving is delegated to the admin's service hooks."""

    expected_version = forms.IntegerField(required=False, widget=forms.HiddenInput)
    # Generated when the add form is displayed: a second submission is a replay, not a copy.
    client_id = forms.UUIDField(required=False, widget=forms.HiddenInput, initial=uuid.uuid4)

    service_admin: "ServiceAdmin"
    request: HttpRequest

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Declared extra fields belong to one form only (add or change): keep those shown.
        shown = set(self._meta.fields or ())
        for name in list(self.declared_fields):
            if name not in shown and name not in ("expected_version", "client_id"):
                del self.fields[name]
        if not self.instance._state.adding:
            self.fields["expected_version"].initial = self.service_admin.version_of(self.instance)
        self.service_admin.limit_choices(self.request, self)

    def _post_clean(self) -> None:
        # Replaces ModelForm's model validation: the service validates and saves.
        if self.errors:
            return
        try:
            with transaction.atomic():
                result = self.service_admin.run_form_service(self.request, self)
        except (DomainError, DjangoValidationError) as exc:
            _add_errors(self, exc)
            return
        if result is not None:
            self.instance = result


class ServiceAdmin(ReadOnlyAdmin):
    """Admin whose writes go through services. Subclasses implement the `perform_*` hooks.

    `scope` names the field chosen on the add form to locate the tenant (`farm` or
    `organization`); `add_fields` and `change_fields` are the editable fields.
    Everything else is displayed read-only.
    """

    form = ServiceForm
    scope: str | None = "farm"
    add_fields: Sequence[str] = ()
    change_fields: Sequence[str] = ()
    # The create service replays a known `data["id"]` (field data entered offline too).
    replay_by_id = False

    # --- service hooks ---------------------------------------------------------------

    def perform_create(self, ctx: TenantContext, data: dict[str, Any]) -> Any:
        raise NotImplementedError

    def perform_update(
        self, ctx: TenantContext, obj: Any, changes: dict[str, Any], expected_version: int
    ) -> Any:
        raise NotImplementedError

    def perform_delete(self, ctx: TenantContext, obj: Any) -> None:
        raise NotImplementedError

    def can_change(self, obj: Any) -> bool:
        """Object-level rule (e.g. only drafts are editable)."""
        return True

    def version_of(self, obj: Any) -> int | None:
        """Optimistic version checked by the service: a child row uses its parent's."""
        return getattr(obj, "version", None)

    def context_for(self, request: HttpRequest, obj: Any) -> TenantContext:
        return platform_context(
            request,
            organization_id=obj.organization_id,
            farm_id=getattr(obj, "farm_id", None),
        )

    def scope_ids(
        self, request: HttpRequest, form: Any
    ) -> tuple[uuid.UUID, uuid.UUID | None] | None:
        """(organization, farm) of the edited object, or of the scope chosen on add."""
        if not form.instance._state.adding:
            ctx = self.context_for(request, form.instance)
            return ctx.organization_id, ctx.farm_id
        if self.scope is None:
            return None
        chosen = (getattr(form, "cleaned_data", None) or {}).get(self.scope)
        if chosen is None:
            chosen = self._scope_from_query(request)
        if chosen is None:
            return None
        return scope_of(chosen)

    def _scope_from_query(self, request: HttpRequest) -> Any:
        raw = request.GET.get(self.scope or "")
        if not raw or self.scope is None:
            return None
        related = self.model._meta.get_field(self.scope).related_model
        try:
            return related._default_manager.filter(pk=raw).first()
        except DjangoValidationError:
            return None

    # --- permissions -----------------------------------------------------------------

    def _implements(self, hook: str) -> bool:
        return getattr(type(self), hook) is not getattr(ServiceAdmin, hook)

    def has_add_permission(self, request: HttpRequest, *args: Any) -> bool:
        return self._implements("perform_create") and admin.ModelAdmin.has_add_permission(
            self, request
        )

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        if not self._implements("perform_update"):
            return False
        if obj is not None and not self.can_change(obj):
            return False
        return admin.ModelAdmin.has_change_permission(self, request, obj)

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return self._implements("perform_delete") and admin.ModelAdmin.has_delete_permission(
            self, request, obj
        )

    def has_workflow_permission(self, request: HttpRequest) -> bool:
        opts = self.model._meta
        return request.user.has_perm(f"{opts.app_label}.change_{opts.model_name}")

    # --- form layout -----------------------------------------------------------------

    def _editing(self, request: HttpRequest, obj: Any) -> bool:
        return obj is not None and self.has_change_permission(request, obj)

    def get_fields(self, request: HttpRequest, obj: Any = None) -> Any:
        if obj is None:
            replay = ["client_id"] if self.replay_by_id else []
            return [*([self.scope] if self.scope else []), *self.add_fields, *replay]
        if not self._editing(request, obj):
            return super().get_fields(request, obj)
        return [*self.change_fields, "expected_version", *self.get_readonly_fields(request, obj)]

    def get_readonly_fields(self, request: HttpRequest, obj: Any = None) -> Any:
        if obj is None:
            return []
        if not self._editing(request, obj):
            return super().get_readonly_fields(request, obj)
        editable = set(self.change_fields)
        return [name for name in self._fields if name not in editable and name not in SECRET_FIELDS]

    def get_form(
        self, request: HttpRequest, obj: Any = None, change: bool = False, **kwargs: Any
    ) -> Any:
        form = super().get_form(request, obj, change=change, **kwargs)
        return type(form.__name__, (form,), {"service_admin": self, "request": request})

    def get_changeform_initial_data(self, request: HttpRequest) -> dict[str, Any]:
        initial = dict(super().get_changeform_initial_data(request))
        chosen = self._scope_from_query(request)
        if chosen is not None and self.scope:
            initial[self.scope] = chosen
        return initial

    def limit_choices(self, request: HttpRequest, form: Any) -> None:
        """Offer only the references of the object's organization and farm."""
        if not form.instance._state.adding and not self._implements("perform_update"):
            return  # view-only page: no choice is offered
        scope = self.scope_ids(request, form)
        if scope is None:
            return
        organization_id, farm_id = scope
        for name, field in form.fields.items():
            if name == self.scope or not isinstance(field, forms.ModelChoiceField):
                continue
            queryset = cast(QuerySet[Any], field.queryset)
            names = {f.name: f for f in queryset.model._meta.concrete_fields}
            if farm_id is not None and "farm" in names:
                field.queryset = queryset.filter(farm_id=farm_id)
            elif "organization" in names:
                own = Q(organization_id=organization_id)
                if names["organization"].null:  # shared catalogue entries (global crops)
                    own |= Q(organization__isnull=True)
                field.queryset = queryset.filter(own)

    # --- saving ----------------------------------------------------------------------

    def run_form_service(self, request: HttpRequest, form: Any) -> Any:
        cleaned = form.cleaned_data
        if form.instance._state.adding:
            data = {k: cleaned[k] for k in self.add_fields if k in cleaned}
            if self.replay_by_id and cleaned.get("client_id"):
                data["id"] = cleaned["client_id"]
            if self.scope is None:  # tenant-free creation (an organization)
                return self.perform_create(None, data)  # type: ignore[arg-type]
            scope = self.scope_ids(request, form)
            if scope is None:
                raise DjangoValidationError({self.scope: "Champ obligatoire."})
            ctx = platform_context(request, organization_id=scope[0], farm_id=scope[1])
            self._check_scope(cleaned, ctx)
            if self.scope not in ("farm", "organization"):
                data[self.scope] = cleaned[self.scope]
            return self.perform_create(ctx, data)
        ctx = self.context_for(request, form.instance)
        self._check_scope(cleaned, ctx)
        changes = {k: cleaned[k] for k in form.changed_data if k in self.change_fields}
        if not changes:
            return None
        version = cleaned.get("expected_version") or self.version_of(form.instance) or 0
        return self.perform_update(ctx, form.instance, changes, version)

    def _check_scope(self, cleaned: dict[str, Any], ctx: TenantContext) -> None:
        errors = {
            name: "Cet élément appartient à une autre organisation ou exploitation."
            for name, value in cleaned.items()
            if name != self.scope and not _same_scope(value, ctx.organization_id, ctx.farm_id)
        }
        if errors:
            raise DjangoValidationError(errors)

    def save_model(self, request: HttpRequest, obj: Any, form: Any, change: bool) -> None:
        """Already saved by the service during form validation."""

    def save_related(self, request: HttpRequest, form: Any, formsets: Any, change: bool) -> None:
        """Relations are written by the services (inlines are read-only)."""

    def get_deleted_objects(self, objs: Any, request: HttpRequest) -> Any:
        # The service decides (soft delete, or refusal while the object is referenced):
        # Django's cascade preview does not apply.
        return [str(obj) for obj in objs], {}, set(), []

    def delete_model(self, request: HttpRequest, obj: Any) -> None:
        self.perform_delete(self.context_for(request, obj), obj)

    def delete_view(self, request: HttpRequest, object_id: str, extra_context: Any = None) -> Any:
        try:
            return super().delete_view(request, object_id, extra_context)
        except DomainError as exc:
            self.message_user(request, " ".join(error_messages(exc)), messages.ERROR)
            opts = self.model._meta
            return HttpResponseRedirect(
                reverse(f"admin:{opts.app_label}_{opts.model_name}_change", args=[object_id])
            )

    def get_inline_instances(self, request: HttpRequest, obj: Any = None) -> Any:
        # Inlines are read-only displays: nothing to show on add, nothing to submit.
        if obj is None or request.method == "POST":
            return []
        return super().get_inline_instances(request, obj)

    def get_actions(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        actions = super().get_actions(request, *args, **kwargs)
        # Bulk deletion would bypass the services (QuerySet.delete()).
        actions.pop("delete_selected", None)
        return actions


class ReasonForm(forms.Form):
    reason = forms.CharField(label="Motif", widget=forms.Textarea(attrs={"rows": 3}))


ActionFn = Callable[..., Any]


def service_action(
    description: str, *, form: type[forms.Form] | None = None
) -> Callable[[ActionFn], ActionFn]:
    """Change-list action calling `fn(admin, ctx, obj, **form_data)` for each object.

    `fn` may return a message: the step completed but its outcome needs attention.

    With `form`, an intermediate page collects the input first. Each object runs
    in its own transaction: one failure does not cancel the others, and every
    failure is reported with its reason.
    """

    def decorator(fn: ActionFn) -> ActionFn:
        @admin.action(description=description, permissions=["workflow"])
        @functools.wraps(fn)
        def action(
            modeladmin: ServiceAdmin, request: HttpRequest, queryset: QuerySet[Any]
        ) -> HttpResponse | None:
            values: dict[str, Any] = {}
            if form is not None:
                bound = form(request.POST) if "apply" in request.POST else form()
                if not bound.is_bound or not bound.is_valid():
                    return render(
                        request,
                        "admin/fms/action_form.html",
                        {
                            **modeladmin.admin_site.each_context(request),
                            "title": description,
                            "form": bound,
                            "objects": queryset,
                            "action": fn.__name__,
                            "opts": modeladmin.model._meta,
                        },
                    )
                values = bound.cleaned_data
            done, failures, warnings = 0, [], []
            for obj in queryset:
                try:
                    with transaction.atomic():
                        warning = fn(
                            modeladmin, modeladmin.context_for(request, obj), obj, **values
                        )
                except (DomainError, DjangoValidationError) as exc:
                    failures.append(f"{obj} : {' '.join(error_messages(exc))}")
                    continue
                if isinstance(warning, str):  # completed, but the outcome needs attention
                    warnings.append(warning)
                else:
                    done += 1
            if done:
                modeladmin.message_user(
                    request, f"{description} : {done} élément(s).", messages.SUCCESS
                )
            for warning in warnings:
                modeladmin.message_user(request, warning, messages.WARNING)
            for failure in failures:
                modeladmin.message_user(request, failure, messages.ERROR)
            return None

        return action

    return decorator
