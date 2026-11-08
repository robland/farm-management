from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.organizations import views

router = SimpleRouter()
router.register("organizations", views.OrganizationViewSet, basename="organization")
router.register(
    r"organizations/(?P<organization_id>[^/.]+)/roles", views.RoleViewSet, basename="org-role"
)
router.register(
    r"organizations/(?P<organization_id>[^/.]+)/members",
    views.OrganizationMemberViewSet,
    basename="org-member",
)
router.register(
    r"organizations/(?P<organization_id>[^/.]+)/invitations",
    views.InvitationViewSet,
    basename="org-invitation",
)

urlpatterns = [
    path("permissions/", views.PermissionCatalogView.as_view(), name="permission-catalog"),
    path("invitations/accept/", views.AcceptInvitationView.as_view(), name="invitation-accept"),
    *router.urls,
]
