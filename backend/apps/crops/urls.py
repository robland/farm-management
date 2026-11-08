from rest_framework.routers import SimpleRouter

from apps.crops import views

router = SimpleRouter()
router.register(
    r"organizations/(?P<organization_id>[^/.]+)/crops", views.CropViewSet, basename="org-crop"
)

urlpatterns = router.urls
