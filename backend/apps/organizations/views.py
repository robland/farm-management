from typing import Any

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.versioning import parse_if_match
from apps.core.viewsets import request_user
from apps.organizations import services
from apps.organizations.access import resolve_org_context
from apps.organizations.models import Invitation, Organization, OrganizationMembership, Role
from apps.organizations.permissions_catalog import PERMISSIONS
from apps.organizations.serializers import (
    InvitationAcceptSerializer,
    InvitationCreatedSerializer,
    InvitationCreateSerializer,
    InvitationSerializer,
    OrganizationMembershipSerializer,
    OrganizationMembershipUpdateSerializer,
    OrganizationSerializer,
    PermissionSerializer,
    RoleSerializer,
    RoleUpdateSerializer,
)
from apps.organizations.services import ORG_MANAGE
from apps.organizations.viewsets import OrgScopedGenericViewSet


class OrganizationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Organizations the current user belongs to. Any user may create one (FR-001)."""

    serializer_class = OrganizationSerializer
    queryset = Organization.objects.none()  # model hint for OpenAPI; see get_queryset
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self) -> QuerySet[Organization]:
        return Organization.objects.filter(
            memberships__user=request_user(self.request),
            memberships__status=OrganizationMembership.Status.ACTIVE,
            status=Organization.Status.ACTIVE,
        ).order_by("name")

    def get_object(self) -> Organization:
        ctx = resolve_org_context(request_user(self.request), self.kwargs["pk"])
        return Organization.objects.get(id=ctx.organization_id)

    def perform_create(self, serializer: Any) -> None:
        serializer.instance = services.create_organization(
            user=request_user(self.request), **serializer.validated_data
        )

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        ctx = resolve_org_context(request_user(request), kwargs["pk"])
        serializer = self.get_serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        organization = services.update_organization(
            ctx, expected_version=parse_if_match(request), changes=serializer.validated_data
        )
        return Response(self.get_serializer(organization).data)


class RoleViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    OrgScopedGenericViewSet,
):
    serializer_class = RoleSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    permission_map = {
        "list": "members.view",
        "retrieve": "members.view",
        "create": ORG_MANAGE,
        "partial_update": ORG_MANAGE,
        "destroy": ORG_MANAGE,
    }

    def get_queryset(self) -> QuerySet[Role]:
        return (
            Role.objects.filter(organization_id=self.tenant.organization_id)
            .prefetch_related("permissions")
            .order_by("name")
        )

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        role = services.create_role(
            self.tenant,
            code=data["code"],
            name=data["name"],
            description=data.get("description", ""),
            permissions=data.get("permissions", []),
        )
        return Response(self.get_serializer(role).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=RoleUpdateSerializer, responses=RoleSerializer)
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        role = self.get_object()
        serializer = RoleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        permissions = data.pop("permissions", None)
        role = services.update_role(
            self.tenant,
            role_id=role.id,
            expected_version=parse_if_match(request),
            changes=data,
            permissions=permissions,
        )
        return Response(self.get_serializer(role).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        role = self.get_object()
        services.delete_role(self.tenant, role_id=role.id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class OrganizationMemberViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    OrgScopedGenericViewSet,
):
    serializer_class = OrganizationMembershipSerializer
    http_method_names = ["get", "patch", "head", "options"]
    permission_map = {
        "list": "members.view",
        "retrieve": "members.view",
        "partial_update": ORG_MANAGE,
    }

    def get_queryset(self) -> QuerySet[OrganizationMembership]:
        return (
            OrganizationMembership.objects.filter(organization_id=self.tenant.organization_id)
            .select_related("user")
            .order_by("user__full_name")
        )

    @extend_schema(
        request=OrganizationMembershipUpdateSerializer, responses=OrganizationMembershipSerializer
    )
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        membership = self.get_object()
        serializer = OrganizationMembershipUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = services.update_org_membership(
            self.tenant,
            membership_id=membership.id,
            expected_version=parse_if_match(request),
            changes=serializer.validated_data,
        )
        return Response(self.get_serializer(membership).data)


class InvitationViewSet(mixins.ListModelMixin, OrgScopedGenericViewSet):
    serializer_class = InvitationSerializer
    permission_map = {
        "list": ORG_MANAGE,
        "create": "members.manage",
        "revoke": ORG_MANAGE,
    }

    def get_queryset(self) -> QuerySet[Invitation]:
        return Invitation.objects.filter(organization_id=self.tenant.organization_id).order_by(
            "-created_at"
        )

    @extend_schema(request=InvitationCreateSerializer, responses={201: InvitationCreatedSerializer})
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = InvitationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        invitation, token = services.create_invitation(
            self.tenant,
            email=data.get("email"),
            phone=data.get("phone"),
            farm_id=data.get("farm"),
            role_id=data.get("role"),
            make_org_admin=data["make_org_admin"],
        )
        payload = InvitationSerializer(invitation).data
        payload["token"] = token
        return Response(payload, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=InvitationSerializer)
    @action(detail=True, methods=["post"])
    def revoke(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        invitation = services.revoke_invitation(self.tenant, invitation_id=self.get_object().id)
        return Response(InvitationSerializer(invitation).data)


class AcceptInvitationView(APIView):
    """Accept an invitation, either as the logged-in user or by creating an account."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    @extend_schema(request=InvitationAcceptSerializer, responses={200: None})
    def post(self, request: Request) -> Response:
        serializer = InvitationAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        current = request_user(request) if request.user.is_authenticated else None
        invitation, user = services.accept_invitation(
            token=data["token"],
            user=current,
            full_name=data.get("full_name", ""),
            password=data.get("password", ""),
        )
        return Response(
            {
                "organization_id": invitation.organization_id,
                "farm_id": invitation.farm_id,
                "user_id": user.id,
            }
        )


class PermissionCatalogView(APIView):
    @extend_schema(responses=PermissionSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response([{"code": c, "description": d} for c, d in PERMISSIONS.items()])
