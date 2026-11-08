from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin, ReadOnlyTabularInline, register_read_only
from apps.irrigation.models import BomLine, IrrigationDesign, Quote, QuoteLine


class BomLineInline(ReadOnlyTabularInline):
    model = BomLine


@admin.register(IrrigationDesign)
class IrrigationDesignAdmin(ReadOnlyAdmin):
    inlines = [BomLineInline]


class QuoteLineInline(ReadOnlyTabularInline):
    model = QuoteLine


@admin.register(Quote)
class QuoteAdmin(ReadOnlyAdmin):
    inlines = [QuoteLineInline]


register_read_only(BomLine, QuoteLine)
