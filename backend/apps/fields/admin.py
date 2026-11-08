from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin, ReadOnlyTabularInline, register_read_only
from apps.fields.models import Field, Parcel, ParcelHistoryEntry


class ParcelInline(ReadOnlyTabularInline):
    model = Parcel
    fields = ["name", "status", "version", "deleted_at"]


@admin.register(Field)
class FieldAdmin(ReadOnlyAdmin):
    inlines = [ParcelInline]


register_read_only(Parcel, ParcelHistoryEntry)
