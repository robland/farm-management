from rest_framework.routers import SimpleRouter

from apps.finance import views

FARM = r"farms/(?P<farm_id>[^/.]+)"

router = SimpleRouter()
router.register(
    f"{FARM}/treasury-accounts", views.TreasuryAccountViewSet, basename="farm-treasury-account"
)
router.register(f"{FARM}/transactions", views.TransactionViewSet, basename="farm-transaction")
router.register(f"{FARM}/budget-lines", views.BudgetLineViewSet, basename="farm-budget-line")
router.register(
    r"organizations/(?P<organization_id>[^/.]+)/finance-categories",
    views.FinanceCategoryViewSet,
    basename="org-finance-category",
)

urlpatterns = router.urls
