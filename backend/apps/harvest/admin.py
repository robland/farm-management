from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin, register_read_only
from apps.harvest.models import HarvestRecord, UnitConversion


@admin.register(HarvestRecord)
class HarvestRecordAdmin(ReadOnlyAdmin):
    list_display = [
        "harvested_on",
        "crop_cycle",
        "parcel",
        "quantity",
        "unit",
        "quantity_kg",
        "quality_grade",
        "voided_at",
        "farm",
    ]
    list_select_related = ["crop_cycle", "parcel", "farm"]
    list_filter = ["quality_grade", ("voided_at", admin.EmptyFieldListFilter)]
    date_hierarchy = "harvested_on"


register_read_only(UnitConversion)
