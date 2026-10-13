from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from core import services
from core.models import Event, EventSeat, Reservation, Seat, Venue
from core.permissions import AdminWriteAuthenticatedRead
from core.serializers import (
    EventSeatSerializer,
    EventSerializer,
    ReservationSerializer,
    SeatSerializer,
    VenueSerializer,
)


class VenueViewSet(viewsets.ModelViewSet):
    queryset = Venue.objects.order_by("id")
    serializer_class = VenueSerializer
    permission_classes = [AdminWriteAuthenticatedRead]


class SeatViewSet(viewsets.ModelViewSet):
    queryset = Seat.objects.select_related("venue").order_by("id")
    serializer_class = SeatSerializer
    permission_classes = [AdminWriteAuthenticatedRead]


class EventViewSet(viewsets.ModelViewSet):
    serializer_class = EventSerializer
    permission_classes = [AdminWriteAuthenticatedRead]
    queryset = Event.objects.all()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Event.objects.none()
        queryset = Event.objects.select_related("venue").order_by("starts_at", "id")
        if not self.request.user.is_staff:
            queryset = queryset.filter(status=Event.Status.PUBLISHED)
        return queryset


class EventSeatViewSet(viewsets.ModelViewSet):
    serializer_class = EventSeatSerializer
    permission_classes = [AdminWriteAuthenticatedRead]
    queryset = EventSeat.objects.all()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return EventSeat.objects.none()
        queryset = EventSeat.objects.select_related("event", "seat").order_by("id")
        if not self.request.user.is_staff:
            queryset = queryset.filter(event__status=Event.Status.PUBLISHED)
        if self.action == "list" and "event" in self.request.query_params:
            event_id = self.request.query_params["event"]
            if not event_id.isdecimal():
                raise ValidationError({"event": "Must be a positive event ID."})
            queryset = queryset.filter(event_id=event_id)
        return queryset

    def perform_destroy(self, instance):
        services.delete_event_seat(instance.pk)


@extend_schema_view(
    list=extend_schema(parameters=[OpenApiParameter("status", str, enum=Reservation.Status.values)])
)
class ReservationViewSet(viewsets.ModelViewSet):
    serializer_class = ReservationSerializer
    queryset = Reservation.objects.all()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Reservation.objects.none()
        queryset = (
            Reservation.objects.select_related("owner", "event")
            .prefetch_related("items")
            .order_by("-created_at", "-id")
        )
        if not self.request.user.is_staff:
            queryset = queryset.filter(owner=self.request.user)
        if self.action == "list" and "status" in self.request.query_params:
            status = self.request.query_params["status"]
            if status not in Reservation.Status.values:
                raise ValidationError({"status": "Invalid reservation status."})
            queryset = queryset.filter(status=status)
        return queryset

    def perform_destroy(self, instance):
        services.delete_reservation(instance.pk)

    def change_status(self, target):
        reservation = self.get_object()
        if self.request.data:
            raise ValidationError("This action accepts an empty request body.")
        reservation = services.transition_reservation(reservation.pk, target)
        return Response(self.get_serializer(reservation).data)

    @extend_schema(request=None, responses={200: ReservationSerializer})
    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        return self.change_status(Reservation.Status.CONFIRMED)

    @extend_schema(request=None, responses={200: ReservationSerializer})
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self.change_status(Reservation.Status.CANCELLED)
