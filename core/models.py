from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models

code_validator = RegexValidator(r"^[A-Z0-9][A-Z0-9_-]*$", "Use uppercase letters, digits, _ or -.")


class Supplier(models.Model):
    name = models.CharField(max_length=120, unique=True)
    email = models.EmailField()

    def __str__(self):
        return self.name


class Product(models.Model):
    sku = models.CharField(max_length=64, unique=True, validators=[code_validator])
    name = models.CharField(max_length=160)
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    is_active = models.BooleanField(default=True)
    suppliers = models.ManyToManyField(Supplier, related_name="products", blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(unit_price__gt=0), name="product_price_positive"
            )
        ]

    def __str__(self):
        return self.sku


class Warehouse(models.Model):
    code = models.CharField(max_length=32, unique=True, validators=[code_validator])
    name = models.CharField(max_length=120)
    address = models.CharField(max_length=500)

    def __str__(self):
        return self.code


class Stock(models.Model):
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="stock")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="stock")
    quantity = models.PositiveIntegerField(default=0)
    reserved = models.PositiveIntegerField(default=0, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["warehouse", "product"], name="stock_warehouse_product_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(reserved__lte=models.F("quantity")),
                name="stock_reserved_within_quantity",
            ),
        ]

    @property
    def available(self):
        return self.quantity - self.reserved

    def __str__(self):
        return f"{self.warehouse_id}:{self.product_id}"


class Order(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ALLOCATED = "allocated", "Allocated"
        FULFILLED = "fulfilled", "Fulfilled"
        CANCELLED = "cancelled", "Cancelled"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders"
    )
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="orders")
    products = models.ManyToManyField(Product, through="OrderLine", related_name="orders")
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.DRAFT, editable=False
    )
    reference = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["owner", "-created_at", "-id"], name="order_owner_recent_idx"),
            models.Index(fields=["status", "-created_at", "-id"], name="order_status_recent_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["draft", "allocated", "fulfilled", "cancelled"]),
                name="order_status_valid",
            )
        ]

    def __str__(self):
        return f"Order {self.pk} ({self.status})"


class OrderLine(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_items")
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["order", "product"], name="order_product_unique"),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="order_line_quantity_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gt=0), name="order_line_price_positive"
            ),
        ]

    def __str__(self):
        return f"{self.order_id}:{self.product_id} x {self.quantity}"
