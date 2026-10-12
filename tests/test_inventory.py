from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from core import services
from core.errors import Conflict
from core.models import Order, OrderLine, Product, Stock, Supplier, Warehouse

pytestmark = pytest.mark.django_db


@pytest.fixture
def catalog():
    supplier = Supplier.objects.create(name="Acme", email="supply@example.com")
    warehouse = Warehouse.objects.create(code="JHB", name="Johannesburg", address="1 Main Road")
    product = Product.objects.create(sku="WIDGET-1", name="Widget", unit_price="12.50")
    product.suppliers.add(supplier)
    stock = Stock.objects.create(warehouse=warehouse, product=product, quantity=10)
    return supplier, warehouse, product, stock


def payload(catalog, quantity=3):
    return {
        "warehouse": catalog[1].pk,
        "reference": "CLIENT-001",
        "items": [{"product": catalog[2].pk, "quantity": quantity}],
    }


def create_order(client, catalog, quantity=3):
    response = client.post("/api/orders/", payload(catalog, quantity))
    assert response.status_code == 201, response.data
    return response.data["id"]


@pytest.mark.parametrize(
    "resource,data,change",
    [
        (
            "suppliers",
            {"name": "Vendor", "email": "vendor@example.com"},
            {"name": "Vendor Updated"},
        ),
        (
            "products",
            {"sku": "SKU-2", "name": "Thing", "unit_price": "20.00", "suppliers": []},
            {"name": "Thing Updated"},
        ),
        (
            "warehouses",
            {"code": "CPT", "name": "Cape Town", "address": "2 Main Road"},
            {"name": "Cape Town Updated"},
        ),
    ],
)
def test_catalog_full_crud(admin_client, auth_client, client, resource, data, change):
    url = f"/api/{resource}/"
    assert client.get(url).status_code == 401
    assert auth_client.post(url, data).status_code == 403
    response = admin_client.post(url, data)
    assert response.status_code == 201, response.data
    detail = f"{url}{response.data['id']}/"
    assert auth_client.get(url).data["count"] == 1
    assert auth_client.get(detail).status_code == 200
    assert auth_client.patch(detail, change).status_code == 403
    assert auth_client.put(detail, data).status_code == 403
    assert auth_client.delete(detail).status_code == 403
    assert admin_client.patch(detail, change).status_code == 200
    assert admin_client.put(detail, data).status_code == 200
    assert admin_client.delete(detail).status_code == 204
    assert admin_client.get(detail).status_code == 404


def test_stock_crud_and_immutable_identity(admin_client, auth_client, client, catalog):
    _, warehouse, product, stock = catalog
    url = f"/api/stock/{stock.pk}/"
    assert client.get("/api/stock/").status_code == 401
    assert auth_client.get("/api/stock/").data["count"] == 1
    assert auth_client.get(url).data["available"] == 10
    for method in ["post", "patch", "put", "delete"]:
        assert (
            getattr(auth_client, method)("/api/stock/" if method == "post" else url, {}).status_code
            == 403
        )
    assert admin_client.patch(url, {"quantity": 20}).data["quantity"] == 20
    data = {"warehouse": warehouse.pk, "product": product.pk, "quantity": 8}
    assert admin_client.put(url, data).status_code == 200
    new_product = Product.objects.create(sku="OTHER", name="Other", unit_price=1)
    assert admin_client.patch(url, {"product": new_product.pk}).status_code == 400
    assert admin_client.patch(url, {"reserved": 5}).status_code == 400
    assert admin_client.patch(url, {"quantity": -1}).status_code == 400
    assert admin_client.post("/api/stock/", data).status_code == 400
    assert admin_client.delete(url).status_code == 204
    assert admin_client.post("/api/stock/", data).status_code == 201


def test_order_crud_owner_isolation_and_price_snapshot(
    auth_client, admin_client, client, user, other_user, catalog
):
    assert client.get("/api/orders/").status_code == 401
    assert client.post("/api/orders/", payload(catalog)).status_code == 401
    oid = create_order(auth_client, catalog)
    url = f"/api/orders/{oid}/"
    order = Order.objects.get(pk=oid)
    assert order.owner == user
    assert list(order.products.all()) == [catalog[2]]
    assert auth_client.get(url).data["total"] == "37.50"
    assert auth_client.get("/api/orders/?status=draft").data["count"] == 1
    assert auth_client.get("/api/orders/?status=unknown").status_code == 400
    assert admin_client.get("/api/orders/").data["count"] == 1
    assert admin_client.get(url).status_code == 200
    catalog[2].unit_price = Decimal("99.00")
    catalog[2].save()
    assert auth_client.get(url).data["total"] == "37.50"
    assert auth_client.patch(url, {"reference": "UPDATED"}).data["reference"] == "UPDATED"
    assert auth_client.put(url, payload(catalog, 2)).data["total"] == "198.00"
    assert (
        auth_client.patch(url, {"items": [{"product": catalog[2].pk, "quantity": 1}]}).status_code
        == 200
    )
    hidden = services.create_order(
        other_user, {"warehouse": catalog[1], "items": [{"product": catalog[2], "quantity": 1}]}
    )
    hidden_url = f"/api/orders/{hidden.pk}/"
    for method in ["get", "patch", "put", "delete"]:
        assert getattr(auth_client, method)(hidden_url).status_code == 404
    for action in ["allocate", "cancel"]:
        assert auth_client.post(f"{hidden_url}{action}/").status_code == 404
    assert auth_client.get("/api/orders/").data["count"] == 1
    assert auth_client.delete(url).status_code == 204
    assert not OrderLine.objects.filter(order_id=oid).exists()


@pytest.mark.parametrize(
    "mutation",
    [
        {"items": []},
        {"items": [{"product": 999999, "quantity": 1}]},
        {"status": "fulfilled"},
        {"owner": 999},
        {"total": "0.00"},
        {"unknown": True},
    ],
)
def test_invalid_order_payload(auth_client, catalog, mutation):
    data = payload(catalog)
    data.update(mutation)
    response = auth_client.post("/api/orders/", data)
    assert response.status_code == 400, response.data
    assert response.data["error"]["code"] == "validation_error"
    assert Order.objects.count() == 0


@pytest.mark.parametrize("quantity", [0, -1, 1.5, 2147483648])
def test_invalid_quantities(auth_client, catalog, quantity):
    assert auth_client.post("/api/orders/", payload(catalog, quantity)).status_code == 400


def test_duplicate_inactive_and_read_only_items(auth_client, catalog):
    data = payload(catalog)
    data["items"] *= 2
    assert auth_client.post("/api/orders/", data).status_code == 400
    data = payload(catalog)
    data["items"][0]["unit_price"] = "0.01"
    assert auth_client.post("/api/orders/", data).status_code == 400
    catalog[2].is_active = False
    catalog[2].save()
    assert auth_client.post("/api/orders/", payload(catalog)).status_code == 400


def test_allocate_fulfil_and_retry(auth_client, admin_client, catalog):
    oid = create_order(auth_client, catalog, 4)
    url = f"/api/orders/{oid}/"
    assert admin_client.post(f"{url}fulfil/").status_code == 409
    assert auth_client.post(f"{url}allocate/", {"quantity": 1}).status_code == 400
    for _ in range(2):
        assert auth_client.post(f"{url}allocate/").data["status"] == "allocated"
    stock = catalog[3]
    stock.refresh_from_db()
    assert (stock.quantity, stock.reserved, stock.available) == (10, 4, 6)
    assert auth_client.patch(url, {"reference": "forbidden"}).status_code == 409
    assert auth_client.delete(url).status_code == 409
    assert auth_client.post(f"{url}fulfil/").status_code == 403
    assert admin_client.patch(f"/api/stock/{stock.pk}/", {"quantity": 3}).status_code == 409
    assert admin_client.delete(f"/api/stock/{stock.pk}/").status_code == 409
    for _ in range(2):
        assert admin_client.post(f"{url}fulfil/").data["status"] == "fulfilled"
    stock.refresh_from_db()
    assert (stock.quantity, stock.reserved, stock.available) == (6, 0, 6)
    assert auth_client.post(f"{url}cancel/").status_code == 409
    assert auth_client.post(f"{url}allocate/").status_code == 409


@pytest.mark.parametrize("allocate", [False, True])
def test_cancel_releases_only_once(auth_client, catalog, allocate):
    oid = create_order(auth_client, catalog)
    url = f"/api/orders/{oid}/"
    if allocate:
        assert auth_client.post(f"{url}allocate/").status_code == 200
    for _ in range(2):
        assert auth_client.post(f"{url}cancel/").data["status"] == "cancelled"
    catalog[3].refresh_from_db()
    assert (catalog[3].quantity, catalog[3].reserved) == (10, 0)
    assert auth_client.post(f"{url}allocate/").status_code == 409
    assert auth_client.delete(url).status_code == 409


def test_shortage_rolls_back_all_items(auth_client, catalog):
    second = Product.objects.create(sku="SECOND", name="Second", unit_price=1)
    data = payload(catalog, 5)
    data["items"].append({"product": second.pk, "quantity": 2})
    oid = auth_client.post("/api/orders/", data).data["id"]
    url = f"/api/orders/{oid}/allocate/"
    assert auth_client.post(url).status_code == 409
    catalog[3].refresh_from_db()
    assert catalog[3].reserved == 0
    assert Order.objects.get(pk=oid).status == "draft"
    Stock.objects.create(warehouse=catalog[1], product=second, quantity=1)
    assert auth_client.post(url).status_code == 409
    catalog[3].refresh_from_db()
    assert catalog[3].reserved == 0


def test_inactive_after_order_creation(auth_client, catalog):
    oid = create_order(auth_client, catalog)
    catalog[2].is_active = False
    catalog[2].save()
    assert auth_client.post(f"/api/orders/{oid}/allocate/").status_code == 409


def test_protected_deletes_and_supplier_relationship(admin_client, auth_client, catalog, user):
    supplier, warehouse, product, _ = catalog
    create_order(auth_client, catalog)
    assert admin_client.delete(f"/api/products/{product.pk}/").status_code == 409
    assert admin_client.delete(f"/api/warehouses/{warehouse.pk}/").status_code == 409
    assert admin_client.delete(f"/api/users/{user.pk}/").status_code == 409
    assert admin_client.get(f"/api/products/{product.pk}/").data["suppliers"] == [supplier.pk]
    assert admin_client.patch(f"/api/products/{product.pk}/", {"suppliers": []}).status_code == 200
    assert not product.suppliers.exists()
    assert admin_client.delete(f"/api/suppliers/{supplier.pk}/").status_code == 204


@pytest.mark.parametrize(
    "resource,data",
    [
        ("products", {"sku": "lowercase!", "name": "Bad", "unit_price": "1.00"}),
        ("products", {"sku": "GOOD", "name": "Bad", "unit_price": "0"}),
        ("suppliers", {"name": "Bad", "email": "not-email"}),
        ("warehouses", {"code": "bad code", "name": "Bad", "address": "x"}),
    ],
)
def test_catalog_validation(admin_client, resource, data):
    assert admin_client.post(f"/api/{resource}/", data).status_code == 400


def test_model_validation_constraints_and_strings(catalog, user):
    supplier, warehouse, product, stock = catalog
    for obj in catalog:
        obj.full_clean()
        assert str(obj)
    product.sku = "bad!"
    with pytest.raises(ValidationError):
        product.full_clean()
    product.refresh_from_db()
    order = services.create_order(
        user, {"warehouse": warehouse, "items": [{"product": product, "quantity": 1}]}
    )
    order.full_clean()
    line = order.items.get()
    line.full_clean()
    assert str(order) and str(line)
    for model, values in [
        (Stock, {"warehouse": warehouse, "product": product, "quantity": 1}),
        (OrderLine, {"order": order, "product": product, "quantity": 1, "unit_price": 1}),
    ]:
        with pytest.raises(IntegrityError), transaction.atomic():
            model.objects.create(**values)
    for queryset, values in [
        (Stock.objects.filter(pk=stock.pk), {"reserved": 11}),
        (Stock.objects.filter(pk=stock.pk), {"quantity": -1}),
        (Product.objects.filter(pk=product.pk), {"unit_price": 0}),
        (OrderLine.objects.filter(pk=line.pk), {"quantity": 0}),
        (OrderLine.objects.filter(pk=line.pk), {"unit_price": 0}),
        (Order.objects.filter(pk=order.pk), {"status": "invalid"}),
    ]:
        with pytest.raises(IntegrityError), transaction.atomic():
            queryset.update(**values)


def test_defensive_inconsistent_and_empty_order(catalog, user):
    order = Order.objects.create(owner=user, warehouse=catalog[1])
    with pytest.raises(Conflict, match="at least one item"):
        services.transition_order(order.pk, Order.Status.ALLOCATED)
    OrderLine.objects.create(order=order, product=catalog[2], quantity=1, unit_price=1)
    Order.objects.filter(pk=order.pk).update(status="allocated")
    with pytest.raises(Conflict, match="inconsistent"):
        services.transition_order(order.pk, Order.Status.FULFILLED)
