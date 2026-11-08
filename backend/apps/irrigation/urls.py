from rest_framework.routers import SimpleRouter

from apps.irrigation import views

FARM = r"farms/(?P<farm_id>[^/.]+)"

router = SimpleRouter()
router.register(
    f"{FARM}/irrigation-designs", views.IrrigationDesignViewSet, basename="farm-irrigation-design"
)
router.register(f"{FARM}/quotes", views.QuoteViewSet, basename="farm-quote")

urlpatterns = router.urls
