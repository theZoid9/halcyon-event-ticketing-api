from decimal import Decimal

from rest_framework import serializers

from core import services
from core.models import Order, OrderLine, Product, Stock, Supplier, Warehouse


class StrictModelSerializer(serializers.ModelSerializer):
    """Reject unknown/read-only input instead of silently ignoring state overrides."""

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


class SupplierSerializer(StrictModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "name", "email"]


class ProductSerializer(StrictModelSerializer):
    class Meta:
        model = Product
        fields = ["id", "sku", "name", "unit_price", "is_active", "suppliers"]


class WarehouseSerializer(StrictModelSerializer):
    class Meta:
        model = Warehouse
        fields = ["id", "code", "name", "address"]


class StockSerializer(StrictModelSerializer):
    available = serializers.IntegerField(read_only=True)
    quantity = serializers.IntegerField(min_value=0, max_value=2147483647)

    class Meta:
        model = Stock
        fields = ["id", "warehouse", "product", "quantity", "reserved", "available"]
        read_only_fields = ["reserved"]

    def create(self, validated_data):
        return services.create_stock(validated_data)

    def update(self, instance, validated_data):
        return services.update_stock(instance.pk, validated_data)


class OrderLineSerializer(StrictModelSerializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True))
    quantity = serializers.IntegerField(min_value=1, max_value=2147483647)

    class Meta:
        model = OrderLine
        fields = ["id", "product", "quantity", "unit_price"]
        read_only_fields = ["id", "unit_price"]


class OrderSerializer(StrictModelSerializer):
    items = OrderLineSerializer(many=True, allow_empty=False, max_length=100)
    total = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "owner",
            "warehouse",
            "status",
            "reference",
            "items",
            "total",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["owner", "status", "created_at", "updated_at"]

    def get_total(self, obj) -> str:
        return str(
            sum((item.quantity * item.unit_price for item in obj.items.all()), Decimal("0.00"))
        )

    def validate_items(self, items):
        ids = [item["product"].pk for item in items]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("Each product may appear only once.")
        return items

    def create(self, validated_data):
        return services.create_order(self.context["request"].user, validated_data)

    def update(self, instance, validated_data):
        return services.update_order(instance.pk, validated_data)
