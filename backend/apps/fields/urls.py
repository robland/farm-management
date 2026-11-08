from rest_framework.routers import SimpleRouter

from apps.fields import views

router = SimpleRouter()
router.register(r"farms/(?P<farm_id>[^/.]+)/fields", views.FieldViewSet, basename="farm-field")
router.register(r"farms/(?P<farm_id>[^/.]+)/parcels", views.ParcelViewSet, basename="farm-parcel")

urlpatterns = router.urls
