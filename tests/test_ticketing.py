from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import Event, EventSeat, Reservation, ReservationSeat, Seat, Venue

pytestmark = pytest.mark.django_db


@pytest.fixture
def catalogue():
    venue = Venue.objects.create(name="Grand Hall", city="Johannesburg", address="1 Main Road")
    seats = [Seat.objects.create(venue=venue, section="A", row="1", number=n) for n in range(1, 4)]
    start = timezone.now() + timedelta(days=5)
    event = Event.objects.create(
        venue=venue,
        title="Spring Concert",
        starts_at=start,
        ends_at=start + timedelta(hours=2),
        status=Event.Status.PUBLISHED,
    )
    event_seats = [
        EventSeat.objects.create(event=event, seat=seat, price="50.00") for seat in seats
    ]
    return venue, seats, event, event_seats


def reserve(client, event, seats, reference="TEST-1"):
    return client.post(
        "/api/reservations/",
        {"event": event.pk, "seats": [seat.pk for seat in seats], "reference": reference},
    )


def test_catalogue_crud_and_visibility(client, auth_client, admin_client):
    assert client.get("/api/events/").status_code == 401
    assert auth_client.post("/api/venues/", {}).status_code == 403
    venue = admin_client.post(
        "/api/venues/", {"name": "Hall", "city": "Cape Town", "address": "1 Street"}
    )
    assert venue.status_code == 201
    vid = venue.data["id"]
    assert admin_client.get(f"/api/venues/{vid}/").status_code == 200
    assert (
        admin_client.put(
            f"/api/venues/{vid}/", {"name": "Main Hall", "city": "Cape Town", "address": "1 Street"}
        ).status_code
        == 200
    )
    assert admin_client.patch(f"/api/venues/{vid}/", {"city": "Durban"}).status_code == 200
    assert auth_client.get("/api/venues/").data["count"] == 1

    seat = admin_client.post("/api/seats/", {"venue": vid, "section": "A", "row": "1", "number": 1})
    assert seat.status_code == 201
    sid = seat.data["id"]
    assert auth_client.get(f"/api/seats/{sid}/").status_code == 200
    assert admin_client.patch(f"/api/seats/{sid}/", {"section": "B"}).status_code == 200
    assert (
        admin_client.put(
            f"/api/seats/{sid}/", {"venue": vid, "section": "A", "row": "1", "number": 1}
        ).status_code
        == 200
    )
    assert admin_client.post(
        "/api/seats/", {"venue": vid, "section": "A", "row": "1", "number": 1}
    ).status_code in (400, 409)

    start = timezone.now() + timedelta(days=2)
    event = admin_client.post(
        "/api/events/",
        {
            "venue": vid,
            "title": "Show",
            "starts_at": start.isoformat(),
            "ends_at": (start + timedelta(hours=2)).isoformat(),
        },
    )
    assert event.status_code == 201
    eid = event.data["id"]
    assert auth_client.get(f"/api/events/{eid}/").status_code == 404
    assert admin_client.get(f"/api/events/{eid}/").status_code == 200
    assert admin_client.patch(f"/api/events/{eid}/", {"status": "published"}).status_code == 409
    event_seat = admin_client.post(
        "/api/event-seats/", {"event": eid, "seat": sid, "price": "75.00"}
    )
    assert event_seat.status_code == 201
    esid = event_seat.data["id"]
    assert (
        admin_client.put(
            f"/api/event-seats/{esid}/",
            {"event": eid, "seat": sid, "price": "80.00", "is_available": True},
        ).status_code
        == 200
    )
    assert admin_client.patch(f"/api/events/{eid}/", {"status": "published"}).status_code == 200
    assert auth_client.get("/api/events/").data["count"] == 1
    assert auth_client.get(f"/api/event-seats/?event={eid}").data["count"] == 1
    assert auth_client.get(f"/api/event-seats/{esid}/").data["is_claimed"] is False
    assert admin_client.delete(f"/api/event-seats/{esid}/").status_code == 204
    assert admin_client.delete(f"/api/events/{eid}/").status_code == 204
    assert admin_client.delete(f"/api/seats/{sid}/").status_code == 204
    assert admin_client.delete(f"/api/venues/{vid}/").status_code == 204


def test_reservation_lifecycle_and_price_snapshot(auth_client, catalogue):
    _, _, event, seats = catalogue
    response = reserve(auth_client, event, seats[:2])
    assert response.status_code == 201
    rid = response.data["id"]
    assert response.data["status"] == "held"
    assert response.data["total"] == "100.00"
    assert len(response.data["items"]) == 2
    assert auth_client.get(f"/api/reservations/{rid}/").status_code == 200
    assert auth_client.get("/api/reservations/?status=held").data["count"] == 1
    assert auth_client.patch(f"/api/reservations/{rid}/", {"reference": "NEW"}).status_code == 200
    assert (
        auth_client.put(
            f"/api/reservations/{rid}/",
            {"event": event.pk, "seats": [seats[1].pk], "reference": "PUT"},
        ).status_code
        == 200
    )
    seats[1].price = Decimal("90.00")
    seats[1].save(update_fields=["price"])
    assert auth_client.get(f"/api/reservations/{rid}/").data["total"] == "50.00"
    assert auth_client.post(f"/api/reservations/{rid}/confirm/").status_code == 200
    assert auth_client.post(f"/api/reservations/{rid}/confirm/").status_code == 200
    assert auth_client.patch(f"/api/reservations/{rid}/", {"reference": "NO"}).status_code == 409
    assert auth_client.delete(f"/api/reservations/{rid}/").status_code == 409
    assert auth_client.post(f"/api/reservations/{rid}/cancel/").status_code == 200
    assert auth_client.post(f"/api/reservations/{rid}/cancel/").status_code == 200
    seats[1].refresh_from_db()
    assert seats[1].reservation_id is None
    new = reserve(auth_client, event, [seats[1]])
    assert new.status_code == 201
    assert new.data["total"] == "90.00"
    assert auth_client.delete(f"/api/reservations/{new.data['id']}/").status_code == 204


def test_double_booking_and_atomicity(auth_client, admin_client, catalogue):
    _, _, event, seats = catalogue
    first = reserve(auth_client, event, [seats[0]])
    assert first.status_code == 201
    second = reserve(auth_client, event, [seats[0], seats[1]])
    assert second.status_code == 409
    assert second.data["error"]["code"] == "conflict"
    seats[1].refresh_from_db()
    assert seats[1].reservation_id is None
    assert Reservation.objects.count() == 1
    assert (
        admin_client.patch(f"/api/event-seats/{seats[0].pk}/", {"is_available": False}).status_code
        == 409
    )
    assert admin_client.delete(f"/api/event-seats/{seats[0].pk}/").status_code == 409
    assert admin_client.delete(f"/api/events/{event.pk}/").status_code == 409


def test_expired_hold_is_released(auth_client, catalogue):
    _, _, event, seats = catalogue
    first = reserve(auth_client, event, [seats[0]])
    Reservation.objects.filter(pk=first.data["id"]).update(
        hold_expires_at=timezone.now() - timedelta(seconds=1)
    )
    assert auth_client.post(f"/api/reservations/{first.data['id']}/confirm/").status_code == 409
    old = Reservation.objects.get(pk=first.data["id"])
    assert old.status == Reservation.Status.EXPIRED
    second = reserve(auth_client, event, [seats[0]])
    assert second.status_code == 201


def test_owner_permissions_and_admin_event_cancellation(
    auth_client, admin_client, client, other_user, catalogue
):
    _, _, event, seats = catalogue
    created = reserve(auth_client, event, [seats[0]])
    rid = created.data["id"]
    from rest_framework.authtoken.models import Token

    client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=other_user).key}")
    assert client.get(f"/api/reservations/{rid}/").status_code == 404
    assert client.post(f"/api/reservations/{rid}/confirm/").status_code == 404
    assert client.get("/api/reservations/").data["count"] == 0
    assert admin_client.get("/api/reservations/").data["count"] == 1
    assert (
        admin_client.patch(f"/api/events/{event.pk}/", {"status": "cancelled"}).status_code == 200
    )
    assert Reservation.objects.get(pk=rid).status == Reservation.Status.CANCELLED
    seats[0].refresh_from_db()
    assert seats[0].reservation_id is None
    assert auth_client.get(f"/api/events/{event.pk}/").status_code == 404
    assert reserve(auth_client, event, [seats[0]]).status_code == 409


def test_validation_and_database_constraints(auth_client, admin_client, catalogue):
    venue, physical_seats, event, seats = catalogue
    assert reserve(auth_client, event, []).status_code == 400
    assert reserve(auth_client, event, [seats[0], seats[0]]).status_code == 400
    assert (
        auth_client.post(
            "/api/reservations/", {"event": event.pk, "seats": [seats[0].pk], "owner": 999}
        ).status_code
        == 400
    )
    assert auth_client.get("/api/reservations/?status=invalid").status_code == 400
    assert auth_client.get("/api/event-seats/?event=nope").status_code == 400
    assert (
        admin_client.post(
            "/api/events/",
            {
                "venue": venue.pk,
                "title": "Invalid",
                "starts_at": event.ends_at.isoformat(),
                "ends_at": event.starts_at.isoformat(),
            },
        ).status_code
        == 400
    )
    other_venue = Venue.objects.create(name="Elsewhere", city="Pretoria", address="2 Main")
    other_seat = Seat.objects.create(venue=other_venue, section="A", row="1", number=1)
    assert (
        admin_client.post(
            "/api/event-seats/", {"event": event.pk, "seat": other_seat.pk, "price": "10.00"}
        ).status_code
        == 400
    )
    assert admin_client.post(
        "/api/event-seats/", {"event": event.pk, "seat": physical_seats[0].pk, "price": "2"}
    ).status_code in (400, 409)
    with pytest.raises(IntegrityError), transaction.atomic():
        Seat.objects.create(venue=venue, section="A", row="1", number=1)
    with pytest.raises(IntegrityError), transaction.atomic():
        EventSeat.objects.create(event=event, seat=physical_seats[0], price="-1.00")


def test_unavailable_and_cross_event_seats(auth_client, admin_client, catalogue):
    venue, _, event, seats = catalogue
    start = timezone.now() + timedelta(days=8)
    other = Event.objects.create(
        venue=venue,
        title="Other",
        starts_at=start,
        ends_at=start + timedelta(hours=1),
        status=Event.Status.PUBLISHED,
    )
    assert reserve(auth_client, other, [seats[0]]).status_code == 400
    assert (
        admin_client.patch(f"/api/event-seats/{seats[0].pk}/", {"is_available": False}).status_code
        == 200
    )
    assert reserve(auth_client, event, [seats[0]]).status_code == 409
    assert (
        admin_client.patch(f"/api/seats/{seats[1].seat_id}/", {"is_active": False}).status_code
        == 200
    )
    assert reserve(auth_client, event, [seats[1]]).status_code == 409


def test_invalid_transitions_and_delete_hold(auth_client, admin_client, catalogue):
    _, _, event, seats = catalogue
    response = reserve(auth_client, event, [seats[0]])
    rid = response.data["id"]
    assert auth_client.post(f"/api/reservations/{rid}/confirm/", {"x": 1}).status_code == 400
    assert auth_client.delete(f"/api/reservations/{rid}/").status_code == 204
    assert (
        seats[0].reservation_id is None
        or EventSeat.objects.get(pk=seats[0].pk).reservation_id is None
    )
    response = reserve(auth_client, event, [seats[0]])
    rid = response.data["id"]
    assert auth_client.post(f"/api/reservations/{rid}/cancel/").status_code == 200
    assert auth_client.post(f"/api/reservations/{rid}/confirm/").status_code == 409
    assert admin_client.patch(f"/api/events/{event.pk}/", {"status": "draft"}).status_code == 409
    assert admin_client.patch(f"/api/events/{event.pk}/", {"venue": 999999}).status_code == 400


def test_model_relationships_and_history(auth_client, catalogue):
    venue, physical_seats, event, seats = catalogue
    assert list(event.seats.order_by("id")) == physical_seats
    response = reserve(auth_client, event, [seats[0]])
    reservation = Reservation.objects.get(pk=response.data["id"])
    assert reservation.seats.count() == 1
    assert ReservationSeat.objects.get(reservation=reservation).unit_price == Decimal("50.00")
    assert venue.events.count() == 1
    assert physical_seats[0].event_seats.count() == 1
