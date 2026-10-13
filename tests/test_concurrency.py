"""PostgreSQL tests use independent connections and competing requests."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.utils import timezone

from core import services
from core.errors import Conflict
from core.models import Event, EventSeat, Reservation, Seat, Venue

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def setup_event():
    if connection.vendor != "postgresql":
        pytest.skip("Row-lock concurrency requires PostgreSQL; CI runs this test.")
    users = [get_user_model().objects.create_user(username=f"buyer{i}") for i in range(2)]
    venue = Venue.objects.create(name="Test", city="Test", address="Test")
    seat = Seat.objects.create(venue=venue, section="A", row="1", number=1)
    starts = timezone.now() + timedelta(days=1)
    event = Event.objects.create(
        venue=venue,
        title="Test",
        starts_at=starts,
        ends_at=starts + timedelta(hours=1),
        status=Event.Status.PUBLISHED,
    )
    event_seat = EventSeat.objects.create(event=event, seat=seat, price="10.00")
    return users, event, event_seat


def parallel(calls):
    barrier = Barrier(len(calls))

    def invoke(call):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
            barrier.wait(timeout=10)
            try:
                call()
                return "ok"
            except Conflict:
                return "conflict"
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return list(pool.map(invoke, calls))


def test_competing_buyers_cannot_claim_same_seat(setup_event):
    users, event, seat = setup_event
    results = parallel(
        [
            lambda user=user: services.create_reservation(
                user, {"event": event, "seats": [seat], "reference": ""}
            )
            for user in users
        ]
    )
    assert sorted(results) == ["conflict", "ok"]
    seat.refresh_from_db()
    assert seat.reservation_id is not None
    assert Reservation.objects.count() == 1


def test_cancel_racing_new_hold_is_consistent(setup_event):
    users, event, seat = setup_event
    old = services.create_reservation(users[0], {"event": event, "seats": [seat]})
    results = parallel(
        [
            lambda: services.transition_reservation(old.pk, Reservation.Status.CANCELLED),
            lambda: services.create_reservation(users[1], {"event": event, "seats": [seat]}),
        ]
    )
    assert results[0] == "ok"
    assert results[1] in ("ok", "conflict")
    seat.refresh_from_db()
    old.refresh_from_db()
    assert old.status == Reservation.Status.CANCELLED
    assert seat.reservation_id in (
        [None]
        if results[1] == "conflict"
        else list(Reservation.objects.exclude(pk=old.pk).values_list("pk", flat=True))
    )
