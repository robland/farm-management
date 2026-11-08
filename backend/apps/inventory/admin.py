from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin, ReadOnlyTabularInline, register_read_only
from apps.inventory.models import CatalogItem, PriceList, PriceListItem, Supplier


class PriceListItemInline(ReadOnlyTabularInline):
    model = PriceListItem


@admin.register(PriceList)
class PriceListAdmin(ReadOnlyAdmin):
    inlines = [PriceListItemInline]


register_read_only(Supplier, CatalogItem, PriceListItem)
