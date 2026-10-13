from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q


class Venue(models.Model):
    name = models.CharField(max_length=160)
    city = models.CharField(max_length=100)
    address = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.name} ({self.city})"


class Seat(models.Model):
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name="seats")
    section = models.CharField(max_length=50)
    row = models.CharField(max_length=20)
    number = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["venue", "section", "row", "number"], name="unique_venue_seat"
            ),
            models.CheckConstraint(condition=Q(number__gte=1), name="positive_seat_number"),
        ]

    def __str__(self):
        return f"{self.venue_id}:{self.section}-{self.row}-{self.number}"


class Event(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft"
        PUBLISHED = "published"
        CANCELLED = "cancelled"

    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name="events")
    title = models.CharField(max_length=180)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    description = models.TextField(blank=True)
    seats = models.ManyToManyField(Seat, through="EventSeat", related_name="events")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "starts_at", "id"], name="event_public_schedule_idx")
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")), name="event_end_after_start"
            )
        ]

    def __str__(self):
        return self.title


class EventSeat(models.Model):
    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name="event_seats")
    seat = models.ForeignKey(Seat, on_delete=models.PROTECT, related_name="event_seats")
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    is_available = models.BooleanField(default=True)
    reservation = models.ForeignKey(
        "Reservation",
        on_delete=models.SET_NULL,
        related_name="claimed_seats",
        null=True,
        blank=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["event", "seat"], name="unique_event_seat"),
            models.CheckConstraint(condition=Q(price__gte=0), name="nonnegative_event_seat_price"),
        ]

    def __str__(self):
        return f"{self.event_id}:{self.seat_id}"


class Reservation(models.Model):
    class Status(models.TextChoices):
        HELD = "held"
        CONFIRMED = "confirmed"
        CANCELLED = "cancelled"
        EXPIRED = "expired"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reservations"
    )
    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name="reservations")
    seats = models.ManyToManyField(
        EventSeat, through="ReservationSeat", related_name="reservations"
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.HELD)
    hold_expires_at = models.DateTimeField()
    reference = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["owner", "-created_at", "-id"], name="reservation_owner_feed_idx"),
            models.Index(
                fields=["event", "status", "hold_expires_at"], name="reservation_expiry_idx"
            ),
        ]

    def __str__(self):
        return f"Reservation {self.pk} ({self.status})"


class ReservationSeat(models.Model):
    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, related_name="items")
    event_seat = models.ForeignKey(EventSeat, on_delete=models.PROTECT, related_name="items")
    unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0)]
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["reservation", "event_seat"], name="unique_reservation_seat"
            ),
            models.CheckConstraint(condition=Q(unit_price__gte=0), name="nonnegative_ticket_price"),
        ]
