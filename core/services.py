from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.errors import Conflict
from core.models import Event, EventSeat, Reservation, ReservationSeat

HOLD_MINUTES = 15
MAX_SEATS_PER_RESERVATION = 8


def _lock_event(event_id):
    return Event.objects.select_for_update().get(pk=event_id)


def _expire_holds(event):
    expired_ids = list(
        Reservation.objects.filter(
            event=event, status=Reservation.Status.HELD, hold_expires_at__lte=timezone.now()
        ).values_list("id", flat=True)
    )
    if expired_ids:
        EventSeat.objects.filter(event=event, reservation_id__in=expired_ids).update(
            reservation=None
        )
        Reservation.objects.filter(id__in=expired_ids).update(status=Reservation.Status.EXPIRED)


@transaction.atomic
def expire_event_holds(event_id):
    """Commit expiry independently, even if a later user action is rejected."""
    event = _lock_event(event_id)
    _expire_holds(event)


def _check_bookable(event):
    if event.status != Event.Status.PUBLISHED or event.starts_at <= timezone.now():
        raise Conflict("This event is not open for reservations.")


def _claim_seats(event, reservation, seat_ids):
    if not 1 <= len(seat_ids) <= MAX_SEATS_PER_RESERVATION or len(set(seat_ids)) != len(seat_ids):
        raise ValidationError({"seats": "Select 1 to 8 distinct event seats."})
    seats = list(
        EventSeat.objects.select_for_update()
        .select_related("seat")
        .filter(event=event, pk__in=seat_ids)
        .order_by("pk")
    )
    if len(seats) != len(seat_ids):
        raise ValidationError({"seats": "Every selected seat must belong to the event."})
    for seat in seats:
        if not seat.is_available or not seat.seat.is_active or seat.reservation_id is not None:
            raise Conflict(f"Event seat {seat.pk} is unavailable.")
    ReservationSeat.objects.bulk_create(
        [
            ReservationSeat(reservation=reservation, event_seat=seat, unit_price=seat.price)
            for seat in seats
        ]
    )
    EventSeat.objects.filter(pk__in=seat_ids).update(reservation=reservation)


@transaction.atomic
def create_reservation(owner, data):
    event = _lock_event(data["event"].pk)
    _expire_holds(event)
    _check_bookable(event)
    seat_ids = [seat.pk for seat in data.pop("seats")]
    reservation = Reservation.objects.create(
        owner=owner,
        event=event,
        hold_expires_at=timezone.now() + timedelta(minutes=HOLD_MINUTES),
        reference=data.get("reference", ""),
    )
    _claim_seats(event, reservation, seat_ids)
    return reservation


def update_reservation(reservation_id, data):
    event_id = Reservation.objects.only("event_id").get(pk=reservation_id).event_id
    expire_event_holds(event_id)
    return _update_reservation_locked(reservation_id, event_id, data)


@transaction.atomic
def _update_reservation_locked(reservation_id, event_id, data):
    event = _lock_event(event_id)
    _expire_holds(event)
    reservation = Reservation.objects.select_for_update().get(pk=reservation_id)
    if reservation.status != Reservation.Status.HELD:
        raise Conflict("Only an active hold can be edited.")
    _check_bookable(event)
    if "event" in data and data["event"].pk != event.pk:
        raise ValidationError({"event": "The event cannot be changed."})
    if "seats" in data:
        seat_ids = [seat.pk for seat in data["seats"]]
        EventSeat.objects.filter(event=event, reservation=reservation).update(reservation=None)
        reservation.items.all().delete()
        _claim_seats(event, reservation, seat_ids)
    reservation.reference = data.get("reference", reservation.reference)
    reservation.save(update_fields=["reference", "updated_at"])
    return reservation


def transition_reservation(reservation_id, target):
    event_id = Reservation.objects.only("event_id").get(pk=reservation_id).event_id
    expire_event_holds(event_id)
    return _transition_reservation_locked(reservation_id, event_id, target)


@transaction.atomic
def _transition_reservation_locked(reservation_id, event_id, target):
    event = _lock_event(event_id)
    _expire_holds(event)
    reservation = Reservation.objects.select_for_update().get(pk=reservation_id)
    if reservation.status == target:
        return reservation
    if target == Reservation.Status.CONFIRMED:
        _check_bookable(event)
        if reservation.status != Reservation.Status.HELD:
            raise Conflict("Only an active hold can be confirmed.")
    elif target == Reservation.Status.CANCELLED:
        if reservation.status not in (Reservation.Status.HELD, Reservation.Status.CONFIRMED):
            raise Conflict("This reservation cannot be cancelled.")
        if event.starts_at <= timezone.now():
            raise Conflict("The event has already started.")
        EventSeat.objects.filter(event=event, reservation=reservation).update(reservation=None)
    else:
        raise ValueError("Unsupported transition")
    reservation.status = target
    reservation.save(update_fields=["status", "updated_at"])
    return reservation


def delete_reservation(reservation_id):
    event_id = Reservation.objects.only("event_id").get(pk=reservation_id).event_id
    expire_event_holds(event_id)
    _delete_reservation_locked(reservation_id, event_id)


@transaction.atomic
def _delete_reservation_locked(reservation_id, event_id):
    event = _lock_event(event_id)
    _expire_holds(event)
    reservation = Reservation.objects.select_for_update().get(pk=reservation_id)
    if reservation.status != Reservation.Status.HELD:
        raise Conflict("Only an active hold can be deleted; cancel a confirmed reservation.")
    EventSeat.objects.filter(event=event, reservation=reservation).update(reservation=None)
    reservation.delete()


@transaction.atomic
def update_event(event_id, data):
    event = _lock_event(event_id)
    if "venue" in data and data["venue"].pk != event.venue_id:
        if event.event_seats.exists() or event.reservations.exists():
            raise Conflict("The venue cannot change after seats or reservations exist.")
    new_status = data.get("status", event.status)
    if new_status != event.status:
        if event.status == Event.Status.CANCELLED or new_status == Event.Status.DRAFT:
            raise Conflict("This event status transition is not allowed.")
        if new_status == Event.Status.PUBLISHED:
            if event.status != Event.Status.DRAFT or not event.event_seats.exists():
                raise Conflict("Add event seats before publishing.")
        if new_status == Event.Status.CANCELLED:
            if event.status != Event.Status.PUBLISHED:
                raise Conflict("Only a published event can be cancelled.")
            EventSeat.objects.filter(event=event).update(reservation=None)
            Reservation.objects.filter(
                event=event, status__in=[Reservation.Status.HELD, Reservation.Status.CONFIRMED]
            ).update(status=Reservation.Status.CANCELLED)
    for key, value in data.items():
        setattr(event, key, value)
    if event.ends_at <= event.starts_at:
        raise ValidationError({"ends_at": "Must be after starts_at."})
    event.save()
    return event


@transaction.atomic
def create_event_seat(data):
    event = _lock_event(data["event"].pk)
    if data["seat"].venue_id != event.venue_id:
        raise ValidationError({"seat": "Seat must belong to the event venue."})
    return EventSeat.objects.create(**data)


@transaction.atomic
def update_event_seat(event_seat_id, data):
    event_id = EventSeat.objects.only("event_id").get(pk=event_seat_id).event_id
    _lock_event(event_id)
    seat = EventSeat.objects.select_for_update().get(pk=event_seat_id)
    if any(key in data and data[key].pk != getattr(seat, f"{key}_id") for key in ("event", "seat")):
        raise ValidationError("Event and seat identity cannot change.")
    if seat.reservation_id and data.get("is_available") is False:
        raise Conflict("A claimed seat cannot be disabled.")
    for key in ("price", "is_available"):
        if key in data:
            setattr(seat, key, data[key])
    seat.save(update_fields=["price", "is_available"])
    return seat


@transaction.atomic
def delete_event_seat(event_seat_id):
    event_id = EventSeat.objects.only("event_id").get(pk=event_seat_id).event_id
    _lock_event(event_id)
    seat = EventSeat.objects.select_for_update().get(pk=event_seat_id)
    if seat.reservation_id:
        raise Conflict("A claimed seat cannot be deleted.")
    seat.delete()
