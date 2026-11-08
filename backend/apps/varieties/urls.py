from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.varieties import views

router = SimpleRouter()
router.register(
    r"organizations/(?P<organization_id>[^/.]+)/varieties",
    views.VarietyViewSet,
    basename="org-variety",
)
router.register(
    r"organizations/(?P<organization_id>[^/.]+)/technical-data-sets",
    views.TechnicalDataSetViewSet,
    basename="org-technical-data-set",
)

urlpatterns = [
    path("technical-keys/", views.TechnicalKeyCatalogView.as_view(), name="technical-keys"),
    *router.urls,
]
