from rest_framework.routers import SimpleRouter

from apps.files import views

router = SimpleRouter()
router.register(
    r"organizations/(?P<organization_id>[^/.]+)/files",
    views.OrganizationFileViewSet,
    basename="org-file",
)
router.register(r"farms/(?P<farm_id>[^/.]+)/files", views.FarmFileViewSet, basename="farm-file")

urlpatterns = router.urls
