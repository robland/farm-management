from typing import Any

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.versioning import parse_if_match
from apps.inventory import services
from apps.inventory.models import CatalogItem, PriceList, Supplier
from apps.inventory.serializers import (
    CatalogItemSerializer,
    PriceItemsInputSerializer,
    PriceListSerializer,
    SupplierSerializer,
)
from apps.organizations.viewsets import OrgScopedGenericViewSet

_PERMS = {
    "list": services.VIEW,
    "retrieve": services.VIEW,
    "create": services.EDIT,
    "partial_update": services.EDIT,
    "destroy": services.EDIT,
}


class _OrgCrudViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, OrgScopedGenericViewSet):
    model: type[Any]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    permission_map = _PERMS

    def get_queryset(self) -> QuerySet[Any]:
        queryset = self.model.objects.filter(organization_id=self.tenant.organization_id)
        if hasattr(self.model, "deleted_at"):
            queryset = queryset.filter(deleted_at__isnull=True)
        return queryset

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = services.create_org_object(self.tenant, self.model, serializer.validated_data)
        return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        instance = services.update_org_object(
            self.tenant, self.model, instance.pk, parse_if_match(request), serializer.validated_data
        )
        return Response(self.get_serializer(instance).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        services.delete_org_object(
            self.tenant, self.model, self.get_object().pk, parse_if_match(request)
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class SupplierViewSet(_OrgCrudViewSet):
    model = Supplier
    serializer_class = SupplierSerializer
    filterset_fields = ["kind"]


class CatalogItemViewSet(_OrgCrudViewSet):
    model = CatalogItem
    serializer_class = CatalogItemSerializer
    filterset_fields = ["category"]


class PriceListViewSet(_OrgCrudViewSet):
    model = PriceList
    serializer_class = PriceListSerializer
    http_method_names = ["get", "post", "patch", "put", "head", "options"]
    permission_map = {**_PERMS, "items": services.EDIT}
    filterset_fields = ["supplier", "status", "currency"]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        price_list = services.create_price_list(self.tenant, serializer.validated_data)
        return Response(self.get_serializer(price_list).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=PriceItemsInputSerializer, responses=PriceListSerializer)
    @action(detail=True, methods=["put"])
    def items(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        price_list = self.get_object()
        serializer = PriceItemsInputSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        price_list = services.set_price_items(
            self.tenant,
            price_list_id=price_list.id,
            expected_version=parse_if_match(request),
            items=serializer.validated_data["items"],
        )
        return Response(self.get_serializer(price_list).data)
