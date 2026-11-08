"""The farm itself is pulled by clients (settings, currency, timezone) but not written offline."""

from apps.farms.models import Farm
from apps.farms.serializers import FarmSerializer
from apps.farms.services import FARM_ENTITY
from apps.synchronization.registry import EntityHandler, MergeStrategy, register

register(
    EntityHandler(
        entity_type=FARM_ENTITY,
        model=Farm,
        serializer_class=FarmSerializer,
        read_permission="farm.view",
        write_permission="farm.manage",
        strategy=MergeStrategy.STRICT,
        farm_attr="id",
    )
)
