from decimal import Decimal

from rest_framework import serializers

from core import services
from core.models import Event, EventSeat, Reservation, ReservationSeat, Seat, Venue


class StrictModelSerializer(serializers.ModelSerializer):
    """Reject unknown and server-controlled fields instead of silently ignoring them."""

    def to_internal_value(self, data):
        if isinstance(data, dict):
            invalid = set(data) - {
                name for name, field in self.fields.items() if not field.read_only
            }
            if invalid:
                raise serializers.ValidationError(
                    {name: "Unknown or read-only field." for name in sorted(invalid)}
                )
        return super().to_internal_value(data)


class VenueSerializer(StrictModelSerializer):
    class Meta:
        model = Venue
        fields = ["id", "name", "city", "address"]


class SeatSerializer(StrictModelSerializer):
    number = serializers.IntegerField(min_value=1)

    class Meta:
        model = Seat
        fields = ["id", "venue", "section", "row", "number", "is_active"]


class EventSerializer(StrictModelSerializer):
    class Meta:
        model = Event
        fields = [
            "id",
            "venue",
            "title",
            "starts_at",
            "ends_at",
            "status",
            "description",
            "created_at",
        ]
        read_only_fields = ["created_at"]

    def validate(self, attrs):
        starts = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
        ends = attrs.get("ends_at", getattr(self.instance, "ends_at", None))
        if starts and ends and ends <= starts:
            raise serializers.ValidationError({"ends_at": "Must be after starts_at."})
        if self.instance is None and attrs.get("status", Event.Status.DRAFT) != Event.Status.DRAFT:
            raise serializers.ValidationError({"status": "Create a draft, then publish it."})
        return attrs

    def update(self, instance, validated_data):
        return services.update_event(instance.pk, validated_data)


class EventSeatSerializer(StrictModelSerializer):
    price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0"))
    is_claimed = serializers.SerializerMethodField()

    class Meta:
        model = EventSeat
        fields = ["id", "event", "seat", "price", "is_available", "is_claimed"]

    def get_is_claimed(self, obj) -> bool:
        return obj.reservation_id is not None

    def validate(self, attrs):
        event = attrs.get("event", getattr(self.instance, "event", None))
        seat = attrs.get("seat", getattr(self.instance, "seat", None))
        if event and seat and event.venue_id != seat.venue_id:
            raise serializers.ValidationError({"seat": "Seat must belong to the event venue."})
        return attrs

    def create(self, validated_data):
        return services.create_event_seat(validated_data)

    def update(self, instance, validated_data):
        return services.update_event_seat(instance.pk, validated_data)


class ReservationSeatSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReservationSeat
        fields = ["event_seat", "unit_price"]
        read_only_fields = fields


class ReservationSerializer(StrictModelSerializer):
    seats = serializers.PrimaryKeyRelatedField(
        many=True, queryset=EventSeat.objects.all(), allow_empty=False
    )
    items = ReservationSeatSerializer(many=True, read_only=True)
    total = serializers.SerializerMethodField()

    class Meta:
        model = Reservation
        fields = [
            "id",
            "owner",
            "event",
            "seats",
            "items",
            "total",
            "status",
            "hold_expires_at",
            "reference",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "owner",
            "items",
            "total",
            "status",
            "hold_expires_at",
            "created_at",
            "updated_at",
        ]

    def validate_seats(self, seats):
        ids = [seat.pk for seat in seats]
        if not 1 <= len(ids) <= services.MAX_SEATS_PER_RESERVATION or len(set(ids)) != len(ids):
            raise serializers.ValidationError("Select 1 to 8 distinct event seats.")
        return seats

    def get_total(self, obj) -> str:
        return str(sum((item.unit_price for item in obj.items.all()), Decimal("0.00")))

    def create(self, validated_data):
        return services.create_reservation(self.context["request"].user, validated_data)

    def update(self, instance, validated_data):
        return services.update_reservation(instance.pk, validated_data)
