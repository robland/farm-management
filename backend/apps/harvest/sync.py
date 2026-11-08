"""Harvests are field events: created offline, append-only."""

from apps.harvest import services
from apps.harvest.models import HarvestRecord
from apps.harvest.serializers import HarvestRecordSerializer
from apps.synchronization.registry import EntityHandler, MergeStrategy, register

register(
    EntityHandler(
        entity_type=services.HARVEST_ENTITY,
        model=HarvestRecord,
        serializer_class=HarvestRecordSerializer,
        read_permission=services.VIEW,
        write_permission=services.RECORD,
        strategy=MergeStrategy.APPEND_ONLY,
        create=services.record_harvest,
    )
)
