from rest_framework.routers import SimpleRouter

from apps.agronomy import views

router = SimpleRouter()
router.register(
    r"organizations/(?P<organization_id>[^/.]+)/input-products",
    views.InputProductViewSet,
    basename="org-input-product",
)
router.register(
    r"farms/(?P<farm_id>[^/.]+)/plan-programs",
    views.PlanProgramViewSet,
    basename="farm-plan-program",
)
router.register(
    r"farms/(?P<farm_id>[^/.]+)/observations", views.ObservationViewSet, basename="farm-observation"
)

urlpatterns = router.urls
