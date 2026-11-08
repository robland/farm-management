from django.contrib import admin
from django.urls import URLPattern, URLResolver, include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

api_v1: list[URLPattern | URLResolver] = [
    path("", include("apps.core.urls")),
    path("", include("apps.users.urls")),
    path("", include("apps.organizations.urls")),
    path("", include("apps.farms.urls")),
    path("", include("apps.fields.urls")),
    path("", include("apps.synchronization.urls")),
    path("", include("apps.files.urls")),
    path("", include("apps.crops.urls")),
    path("", include("apps.varieties.urls")),
    path("", include("apps.production_plans.urls")),
    path("", include("apps.inventory.urls")),
    path("", include("apps.irrigation.urls")),
    path("", include("apps.agronomy.urls")),
    path("", include("apps.tasks.urls")),
    path("", include("apps.finance.urls")),
    path("", include("apps.harvest.urls")),
    path("", include("apps.ai_assistant.urls")),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include(api_v1)),
]
