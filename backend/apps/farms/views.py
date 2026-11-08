from typing import Any

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.versioning import parse_if_match
from apps.core.viewsets import request_user
from apps.farms import services
from apps.farms.access import accessible_farms, resolve_farm_context
from apps.farms.models import Farm, FarmMembership
from apps.farms.serializers import (
    AccessibleFarmSerializer,
    FarmMembershipCreateSerializer,
    FarmMembershipSerializer,
    FarmMembershipUpdateSerializer,
    FarmSerializer,
    MeSerializer,
)
from apps.farms.viewsets import FarmScopedGenericViewSet
from apps.organizations.models import OrganizationMembership
from apps.organizations.permissions_catalog import PERMISSIONS
from apps.organizations.services import ORG_MANAGE
from apps.organizations.viewsets import OrgScopedGenericViewSet
from apps.users.serializers import UserSerializer


class OrganizationFarmViewSet(mixins.ListModelMixin, OrgScopedGenericViewSet):
    """`/organizations/{id}/farms/`: list accessible farms of the organization, create (admin)."""

    serializer_class = FarmSerializer
    queryset = Farm.objects.none()  # model hint for OpenAPI; see get_queryset
    permission_map = {"list": "farm.view", "create": ORG_MANAGE}

    def get_queryset(self) -> QuerySet[Farm]:
        return accessible_farms(request_user(self.request)).filter(
            organization_id=self.tenant.organization_id
        )

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        farm = services.create_farm(self.tenant, data=serializer.validated_data)
        return Response(self.get_serializer(farm).data, status=status.HTTP_201_CREATED)


class FarmViewSet(viewsets.GenericViewSet):
    """`/farms/`: bootstrap list across organizations; detail and update of one farm."""

    serializer_class = FarmSerializer
    queryset = Farm.objects.none()  # model hint for OpenAPI; see get_queryset
    lookup_url_kwarg = "farm_id"

    def get_queryset(self) -> QuerySet[Farm]:
        return accessible_farms(request_user(self.request))

    @extend_schema(responses=AccessibleFarmSerializer(many=True))
    def list(self, request: Request) -> Response:
        page = self.paginate_queryset(self.get_queryset())
        data = AccessibleFarmSerializer(page, many=True).data
        return self.get_paginated_response(data)

    def retrieve(self, request: Request, farm_id: str) -> Response:
        ctx = resolve_farm_context(request_user(request), farm_id)
        ctx.require("farm.view")
        return Response(FarmSerializer(Farm.objects.get(id=ctx.require_farm_id)).data)

    def partial_update(self, request: Request, farm_id: str) -> Response:
        ctx = resolve_farm_context(request_user(request), farm_id)
        serializer = FarmSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        farm = services.update_farm(
            ctx, expected_version=parse_if_match(request), changes=serializer.validated_data
        )
        return Response(FarmSerializer(farm).data)


class FarmMemberViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, FarmScopedGenericViewSet):
    serializer_class = FarmMembershipSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]
    permission_map = {
        "list": "members.view",
        "retrieve": "members.view",
        "create": "members.manage",
        "partial_update": "members.manage",
    }

    def get_queryset(self) -> QuerySet[FarmMembership]:
        return (
            FarmMembership.objects.filter(farm_id=self.farm_id)
            .select_related("user", "role")
            .order_by("user__full_name")
        )

    @extend_schema(
        request=FarmMembershipCreateSerializer, responses={201: FarmMembershipSerializer}
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = FarmMembershipCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        membership = services.add_farm_member(
            self.tenant, user_id=data.pop("user"), role_id=data.pop("role"), **data
        )
        return Response(self.get_serializer(membership).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=FarmMembershipUpdateSerializer, responses=FarmMembershipSerializer)
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        membership = self.get_object()
        serializer = FarmMembershipUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = services.update_farm_member(
            self.tenant,
            membership_id=membership.id,
            expected_version=parse_if_match(request),
            changes=serializer.validated_data,
        )
        return Response(self.get_serializer(membership).data)


class MeView(APIView):
    """Profile, organizations and effective farm permissions of the current user."""

    @extend_schema(responses=MeSerializer)
    def get(self, request: Request) -> Response:
        user = request_user(request)
        org_memberships = list(
            OrganizationMembership.objects.filter(user=user, status="active")
            .select_related("organization")
            .filter(organization__status="active")
        )
        admin_orgs = {m.organization_id for m in org_memberships if m.is_org_admin}
        memberships = {
            m.farm_id: m
            for m in FarmMembership.objects.filter(user=user, status="active").select_related(
                "role"
            )
        }
        farms = []
        for farm in accessible_farms(user):
            ctx = resolve_farm_context(user, farm.id)
            membership = memberships.get(farm.id)
            farms.append(
                {
                    "id": farm.id,
                    "name": farm.name,
                    "organization_id": farm.organization_id,
                    "role": membership.role.code if membership else None,
                    "is_org_admin": farm.organization_id in admin_orgs,
                    "permissions": sorted(PERMISSIONS if ctx.is_org_admin else ctx.permissions),
                }
            )
        return Response(
            {
                "user": UserSerializer(user).data,
                "organizations": [
                    {
                        "id": m.organization_id,
                        "name": m.organization.name,
                        "is_org_admin": m.is_org_admin,
                    }
                    for m in org_memberships
                ],
                "farms": farms,
            }
        )

    @extend_schema(request=UserSerializer, responses=UserSerializer)
    def patch(self, request: Request) -> Response:
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
