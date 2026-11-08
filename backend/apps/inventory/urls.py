from rest_framework.routers import SimpleRouter

from apps.inventory import views

ORG = r"organizations/(?P<organization_id>[^/.]+)"

router = SimpleRouter()
router.register(f"{ORG}/suppliers", views.SupplierViewSet, basename="org-supplier")
router.register(f"{ORG}/catalog-items", views.CatalogItemViewSet, basename="org-catalog-item")
router.register(f"{ORG}/price-lists", views.PriceListViewSet, basename="org-price-list")

urlpatterns = router.urls
