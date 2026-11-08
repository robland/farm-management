from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.farms import views

router = SimpleRouter()
router.register(
    r"organizations/(?P<organization_id>[^/.]+)/farms",
    views.OrganizationFarmViewSet,
    basename="org-farm",
)
router.register(
    r"farms/(?P<farm_id>[^/.]+)/members", views.FarmMemberViewSet, basename="farm-member"
)

urlpatterns = [
    path("me/", views.MeView.as_view(), name="me"),
    path("farms/", views.FarmViewSet.as_view({"get": "list"}), name="farm-list"),
    path(
        "farms/<str:farm_id>/",
        views.FarmViewSet.as_view({"get": "retrieve", "patch": "partial_update"}),
        name="farm-detail",
    ),
    *router.urls,
]
