from typing import Any

from django.contrib import admin, messages
from django.db.models import QuerySet
from django.forms import ModelForm
from django.http import HttpRequest
from django.utils import timezone

from apps.audit.services import record_event
from apps.core.admin import ReadOnlyAdmin
from apps.users.models import Device, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    """Account support: activation and staff flags only, every change is audited.

    Accounts are created through registration or invitation (or `createsuperuser`),
    and identifiers are changed by their owner, so neither is possible here.
    """

    list_display = ["full_name", "email", "phone", "is_active", "is_staff", "date_joined"]
    list_filter = ["is_active", "is_staff", "is_superuser"]
    search_fields = ["full_name", "email", "phone", "=id"]
    ordering = ["full_name"]
    fields = [
        "id",
        "full_name",
        "email",
        "phone",
        "locale",
        "is_active",
        "is_staff",
        "is_superuser",
        "last_login",
        "date_joined",
    ]
    readonly_fields = ["id", "email", "phone", "last_login", "date_joined"]

    def get_readonly_fields(self, request: HttpRequest, obj: Any = None) -> Any:
        readonly = list(super().get_readonly_fields(request, obj))
        # Only a superuser may grant or remove platform staff rights.
        if not getattr(request.user, "is_superuser", False):
            readonly += ["is_staff", "is_superuser"]
        return readonly

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def save_model(self, request: HttpRequest, obj: User, form: ModelForm, change: bool) -> None:
        before = {name: form.initial.get(name) for name in form.changed_data}
        super().save_model(request, obj, form, change)
        if form.changed_data:
            record_event(
                action="admin.user_updated",
                actor=request.user,
                entity_type="users.user",
                entity_id=obj.id,
                before=before,
                after={name: form.cleaned_data.get(name) for name in form.changed_data},
            )


@admin.register(Device)
class DeviceAdmin(ReadOnlyAdmin):
    list_display = ["__str__", "user", "platform", "client_version", "last_seen_at", "revoked_at"]
    list_filter = ["platform", ("revoked_at", admin.EmptyFieldListFilter)]
    search_fields = ["label", "user__full_name", "user__email", "user__phone", "=id"]
    actions = ["revoke_devices"]

    def has_revoke_permission(self, request: HttpRequest) -> bool:
        return request.user.has_perm("users.change_device")

    @admin.action(description="Révoquer les appareils sélectionnés", permissions=["revoke"])
    def revoke_devices(self, request: HttpRequest, queryset: QuerySet[Device]) -> None:
        revoked = 0
        for device in queryset.filter(revoked_at__isnull=True):
            device.revoked_at = timezone.now()
            device.save(update_fields=["revoked_at"])
            record_event(
                action="auth.device_revoked",
                actor=request.user,
                entity_type="users.device",
                entity_id=device.id,
                after={"via": "admin"},
            )
            revoked += 1
        self.message_user(request, f"{revoked} appareil(s) révoqué(s).", messages.SUCCESS)
