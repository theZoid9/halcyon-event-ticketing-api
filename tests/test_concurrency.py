"""Real PostgreSQL transactions on independent connections, also run in CI."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection

from core import services
from core.errors import Conflict
from core.models import Order, OrderLine, Product, Stock, Warehouse

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def inventory():
    if connection.vendor != "postgresql":
        pytest.skip("Row-lock concurrency requires PostgreSQL; CI runs this test.")
    user = get_user_model().objects.create_user("concurrent")
    warehouse = Warehouse.objects.create(code="TEST", name="Test", address="Test")
    product = Product.objects.create(sku="TEST", name="Test", unit_price=1)
    stock = Stock.objects.create(warehouse=warehouse, product=product, quantity=5)
    orders = []
    for _ in range(2):
        order = Order.objects.create(owner=user, warehouse=warehouse)
        OrderLine.objects.create(order=order, product=product, quantity=4, unit_price=1)
        orders.append(order)
    return stock, orders


def parallel(calls):
    barrier = Barrier(len(calls))

    def invoke(call):
        close_old_connections()
        try:
            # Fail quickly if an implementation change introduces a deadlock.
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


def test_competing_orders_cannot_oversell(inventory):
    stock, orders = inventory
    results = parallel(
        [
            lambda oid=order.pk: services.transition_order(oid, Order.Status.ALLOCATED)
            for order in orders
        ]
    )
    assert sorted(results) == ["conflict", "ok"]
    stock.refresh_from_db()
    assert (stock.quantity, stock.reserved) == (5, 4)
    assert Order.objects.filter(status="allocated").count() == 1


def test_concurrent_retries_reserve_once(inventory):
    stock, orders = inventory

    def call():
        return services.transition_order(orders[0].pk, Order.Status.ALLOCATED)

    assert parallel([call, call]) == ["ok", "ok"]
    stock.refresh_from_db()
    assert stock.reserved == 4


def test_fulfil_racing_cancel_never_double_releases(inventory):
    stock, orders = inventory
    services.transition_order(orders[0].pk, Order.Status.ALLOCATED)
    results = parallel(
        [
            lambda: services.transition_order(orders[0].pk, Order.Status.FULFILLED),
            lambda: services.transition_order(orders[0].pk, Order.Status.CANCELLED),
        ]
    )
    assert sorted(results) == ["conflict", "ok"]
    stock.refresh_from_db()
    orders[0].refresh_from_db()
    assert stock.reserved == 0
    assert stock.quantity == (1 if orders[0].status == "fulfilled" else 5)


def test_stock_adjustment_racing_allocation(inventory):
    stock, orders = inventory
    results = parallel(
        [
            lambda: services.transition_order(orders[0].pk, Order.Status.ALLOCATED),
            lambda: services.update_stock(stock.pk, {"quantity": 2}),
        ]
    )
    assert sorted(results) == ["conflict", "ok"]
    stock.refresh_from_db()
    assert (stock.quantity, stock.reserved) in [(5, 4), (2, 0)]
