from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from core.auth import LoginView, LogoutView, UserViewSet
from core.health import HealthView
from core.views import OrderViewSet, ProductViewSet, StockViewSet, SupplierViewSet, WarehouseViewSet

router = DefaultRouter()
router.register("users", UserViewSet)
router.register("suppliers", SupplierViewSet)
router.register("products", ProductViewSet)
router.register("warehouses", WarehouseViewSet)
router.register("stock", StockViewSet)
router.register("orders", OrderViewSet)

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("api/auth/login/", LoginView.as_view(), name="login"),
    path("api/auth/logout/", LogoutView.as_view(), name="logout"),
    path("api/", include(router.urls)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]
handler400 = "core.errors.bad_request"
handler403 = "core.errors.permission_denied"
handler404 = "core.errors.not_found"
handler500 = "core.errors.server_error"
