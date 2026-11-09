"""Observations are field events: created offline, append-only (OFFLINE_SYNC.md §6.2)."""

from apps.agronomy import services
from apps.agronomy.models import Observation
from apps.agronomy.serializers import ObservationSerializer
from apps.synchronization.registry import EntityHandler, MergeStrategy, register

register(
    EntityHandler(
        entity_type=services.OBSERVATION_ENTITY,
        model=Observation,
        serializer_class=ObservationSerializer,
        read_permission="observations.view",
        write_permission="observations.create",
        strategy=MergeStrategy.APPEND_ONLY,
        create=services.create_observation,
        prefetch=("photos",),
    )
)
