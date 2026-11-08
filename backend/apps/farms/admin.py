from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin, ReadOnlyTabularInline
from apps.farms.models import Farm, FarmMembership


class FarmMembershipInline(ReadOnlyTabularInline):
    model = FarmMembership
    fields = ["user", "role", "status", "valid_from", "valid_to"]


@admin.register(Farm)
class FarmAdmin(ReadOnlyAdmin):
    inlines = [FarmMembershipInline]


@admin.register(FarmMembership)
class FarmMembershipAdmin(ReadOnlyAdmin):
    list_display = ["user", "farm", "role", "status", "valid_from", "valid_to"]
    list_select_related = ["user", "farm", "role"]
    search_fields = ["user__full_name", "user__email", "user__phone", "farm__name"]
    list_filter = ["status"]
