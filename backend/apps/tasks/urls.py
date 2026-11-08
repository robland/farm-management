from rest_framework.routers import SimpleRouter

from apps.tasks import views

FARM = r"farms/(?P<farm_id>[^/.]+)"

router = SimpleRouter()
router.register(f"{FARM}/tasks", views.TaskViewSet, basename="farm-task")
router.register(f"{FARM}/task-reports", views.TaskReportViewSet, basename="farm-task-report")
router.register(f"{FARM}/teams", views.TeamViewSet, basename="farm-team")

urlpatterns = router.urls
