"""Synchronization handlers for fields and parcels (descriptive data: three-way merge)."""

from apps.fields import services
from apps.fields.models import Field, Parcel
from apps.fields.serializers import FieldSerializer, ParcelSerializer
from apps.synchronization.registry import EntityHandler, MergeStrategy, register

register(
    EntityHandler(
        entity_type=services.FIELD_ENTITY,
        model=Field,
        serializer_class=FieldSerializer,
        read_permission=services.VIEW_PERMISSION,
        write_permission=services.EDIT_PERMISSION,
        strategy=MergeStrategy.THREE_WAY,
        create=services.create_field,
        update=services.update_field,
        delete=services.delete_field,
        id_kwarg="field_id",
    )
)

register(
    EntityHandler(
        entity_type=services.PARCEL_ENTITY,
        model=Parcel,
        serializer_class=ParcelSerializer,
        read_permission=services.VIEW_PERMISSION,
        write_permission=services.EDIT_PERMISSION,
        strategy=MergeStrategy.THREE_WAY,
        create=services.create_parcel,
        update=services.update_parcel,
        delete=services.delete_parcel,
        id_kwarg="parcel_id",
    )
)
