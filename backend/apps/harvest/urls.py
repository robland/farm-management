from rest_framework.routers import SimpleRouter

from apps.harvest import views

FARM = r"farms/(?P<farm_id>[^/.]+)"

router = SimpleRouter()
router.register(
    f"{FARM}/unit-conversions", views.UnitConversionViewSet, basename="farm-unit-conversion"
)
router.register(f"{FARM}/harvests", views.HarvestRecordViewSet, basename="farm-harvest")
router.register(
    f"{FARM}/harvest-results", views.HarvestResultsViewSet, basename="farm-harvest-results"
)

urlpatterns = router.urls
