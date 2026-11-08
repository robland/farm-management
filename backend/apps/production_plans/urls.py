from rest_framework.routers import SimpleRouter

from apps.production_plans import views

FARM = r"farms/(?P<farm_id>[^/.]+)"

router = SimpleRouter()
router.register(f"{FARM}/campaigns", views.CampaignViewSet, basename="farm-campaign")
router.register(f"{FARM}/plans", views.ProductionPlanViewSet, basename="farm-plan")
router.register(f"{FARM}/plan-versions", views.PlanVersionViewSet, basename="farm-plan-version")
router.register(f"{FARM}/crop-cycles", views.CropCycleViewSet, basename="farm-crop-cycle")

urlpatterns = router.urls
