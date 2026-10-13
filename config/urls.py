from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from core.auth import LoginView, LogoutView, UserViewSet
from core.health import HealthView
from core.views import EventSeatViewSet, EventViewSet, ReservationViewSet, SeatViewSet, VenueViewSet

router = DefaultRouter()
router.register("users", UserViewSet)
router.register("venues", VenueViewSet)
router.register("seats", SeatViewSet)
router.register("events", EventViewSet)
router.register("event-seats", EventSeatViewSet)
router.register("reservations", ReservationViewSet)

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
