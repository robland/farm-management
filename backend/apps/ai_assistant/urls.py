from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.ai_assistant import views

router = SimpleRouter()
router.register(
    r"organizations/(?P<organization_id>[^/.]+)/ai/extractions",
    views.ExtractionViewSet,
    basename="org-ai-extraction",
)
router.register(
    r"farms/(?P<farm_id>[^/.]+)/ai/plan-drafts",
    views.PlanDraftViewSet,
    basename="farm-ai-plan-draft",
)
router.register(
    r"farms/(?P<farm_id>[^/.]+)/ai/suggestions",
    views.SuggestionViewSet,
    basename="farm-ai-suggestion",
)

urlpatterns = [
    path("ai/status/", views.AIStatusView.as_view(), name="ai-status"),
    *router.urls,
]
