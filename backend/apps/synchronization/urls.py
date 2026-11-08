from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.synchronization import views

router = SimpleRouter()
router.register(
    r"farms/(?P<farm_id>[^/.]+)/sync/conflicts", views.ConflictViewSet, basename="sync-conflict"
)

urlpatterns = [
    path("sync/push/", views.PushView.as_view(), name="sync-push"),
    path("sync/pull/", views.PullView.as_view(), name="sync-pull"),
    *router.urls,
]
