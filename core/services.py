"""Transactional writes. Lock order: order, warehouse, then stock by product ID.

Warehouse locking intentionally serializes stock mutations within a warehouse,
including insertion/deletion of stock rows. All API stock writes use this module.
"""

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError

from core.errors import Conflict
from core.models import Order, OrderLine, Stock, Warehouse


def lock_order(order_id):
    return get_object_or_404(Order.objects.select_for_update(), pk=order_id)


def lock_warehouse(warehouse_id):
    return get_object_or_404(Warehouse.objects.select_for_update(), pk=warehouse_id)


def require_draft(order):
    if order.status != Order.Status.DRAFT:
        raise Conflict("Only draft orders may be edited or deleted.")


def write_items(order, items):
    OrderLine.objects.bulk_create(
        [
            OrderLine(
                order=order,
                product=item["product"],
                quantity=item["quantity"],
                unit_price=item["product"].unit_price,
            )
            for item in items
        ]
    )


@transaction.atomic
def create_order(owner, data):
    items = data.pop("items")
    order = Order.objects.create(owner=owner, **data)
    write_items(order, items)
    return order


@transaction.atomic
def update_order(order_id, data):
    order = lock_order(order_id)
    require_draft(order)
    items = data.pop("items", None)
    for name, value in data.items():
        setattr(order, name, value)
    order.save()
    if items is not None:
        order.items.all().delete()
        write_items(order, items)
    return order


@transaction.atomic
def delete_order(order_id):
    order = lock_order(order_id)
    require_draft(order)
    order.delete()


@transaction.atomic
def transition_order(order_id, target):
    order = lock_order(order_id)
    if order.status == target:
        return order
    allowed = {
        Order.Status.ALLOCATED: [Order.Status.DRAFT],
        Order.Status.FULFILLED: [Order.Status.ALLOCATED],
        Order.Status.CANCELLED: [Order.Status.DRAFT, Order.Status.ALLOCATED],
    }
    if order.status not in allowed.get(target, []):
        raise Conflict(f"Cannot change {order.status} to {target}.")
    lock_warehouse(order.warehouse_id)
    items = list(order.items.select_related("product").order_by("product_id"))
    if not items:
        raise Conflict("An order must contain at least one item.")
    stocks = {
        stock.product_id: stock
        for stock in Stock.objects.select_for_update()
        .filter(warehouse_id=order.warehouse_id, product_id__in=[item.product_id for item in items])
        .order_by("product_id")
    }
    for item in items:
        stock = stocks.get(item.product_id)
        if target == Order.Status.ALLOCATED:
            if not item.product.is_active:
                raise Conflict(f"Product {item.product_id} is inactive.")
            if stock is None or stock.available < item.quantity:
                raise Conflict(f"Insufficient available stock for product {item.product_id}.")
            stock.reserved += item.quantity
        elif order.status == Order.Status.ALLOCATED:
            if stock is None or stock.reserved < item.quantity:
                raise Conflict("Reserved stock is inconsistent; contact an administrator.")
            stock.reserved -= item.quantity
            if target == Order.Status.FULFILLED:
                stock.quantity -= item.quantity
        else:
            continue  # Cancelling a draft does not touch stock.
        stock.save(update_fields=["quantity", "reserved"])
    order.status = target
    order.save(update_fields=["status", "updated_at"])
    return order


@transaction.atomic
def create_stock(data):
    lock_warehouse(data["warehouse"].pk)
    return Stock.objects.create(**data)


@transaction.atomic
def update_stock(stock_id, data):
    current = get_object_or_404(Stock, pk=stock_id)
    lock_warehouse(current.warehouse_id)
    stock = get_object_or_404(Stock.objects.select_for_update(), pk=stock_id)
    for field in ["warehouse", "product"]:
        if field in data and data[field].pk != getattr(stock, f"{field}_id"):
            raise ValidationError({field: "Stock warehouse and product cannot be changed."})
    quantity = data.get("quantity", stock.quantity)
    if quantity < stock.reserved:
        raise Conflict("Quantity cannot be less than reserved stock.")
    stock.quantity = quantity
    stock.save(update_fields=["quantity"])
    return stock


@transaction.atomic
def delete_stock(stock_id):
    current = get_object_or_404(Stock, pk=stock_id)
    lock_warehouse(current.warehouse_id)
    stock = get_object_or_404(Stock.objects.select_for_update(), pk=stock_id)
    if stock.reserved:
        raise Conflict("Stock with active reservations cannot be deleted.")
    stock.delete()
