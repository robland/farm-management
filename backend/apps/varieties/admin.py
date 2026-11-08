from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin, ReadOnlyTabularInline, register_read_only
from apps.varieties.models import TechnicalDataItem, TechnicalDataSet, TechnicalDocument, Variety


class TechnicalDataItemInline(ReadOnlyTabularInline):
    model = TechnicalDataItem


@admin.register(TechnicalDataSet)
class TechnicalDataSetAdmin(ReadOnlyAdmin):
    inlines = [TechnicalDataItemInline]


register_read_only(Variety, TechnicalDocument, TechnicalDataItem)
