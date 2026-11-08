from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.users import views

router = SimpleRouter()
router.register("me/devices", views.MyDeviceViewSet, basename="my-device")

urlpatterns = [
    path("auth/login/", views.LoginView.as_view(), name="auth-login"),
    path("auth/refresh/", views.RefreshView.as_view(), name="auth-refresh"),
    path("auth/logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("auth/password/", views.ChangePasswordView.as_view(), name="auth-password"),
    *router.urls,
]
