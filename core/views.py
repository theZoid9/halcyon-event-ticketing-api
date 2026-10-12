from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from core import services
from core.models import Order, Product, Stock, Supplier, Warehouse
from core.permissions import AdminWriteAuthenticatedRead
from core.serializers import (
    OrderSerializer,
    ProductSerializer,
    StockSerializer,
    SupplierSerializer,
    WarehouseSerializer,
)


class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.order_by("id")
    serializer_class = SupplierSerializer
    permission_classes = [AdminWriteAuthenticatedRead]


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.prefetch_related("suppliers").order_by("id")
    serializer_class = ProductSerializer
    permission_classes = [AdminWriteAuthenticatedRead]


class WarehouseViewSet(viewsets.ModelViewSet):
    queryset = Warehouse.objects.order_by("id")
    serializer_class = WarehouseSerializer
    permission_classes = [AdminWriteAuthenticatedRead]


class StockViewSet(viewsets.ModelViewSet):
    queryset = Stock.objects.select_related("warehouse", "product").order_by("id")
    serializer_class = StockSerializer
    permission_classes = [AdminWriteAuthenticatedRead]

    def perform_destroy(self, instance):
        services.delete_stock(instance.pk)


@extend_schema_view(
    list=extend_schema(parameters=[OpenApiParameter("status", str, enum=Order.Status.values)])
)
class OrderViewSet(viewsets.ModelViewSet):
    serializer_class = OrderSerializer
    queryset = Order.objects.all()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Order.objects.none()
        queryset = (
            Order.objects.select_related("warehouse", "owner")
            .prefetch_related("items")
            .order_by("-created_at", "-id")
        )
        if not self.request.user.is_staff:
            queryset = queryset.filter(owner=self.request.user)
        if self.action == "list" and "status" in self.request.query_params:
            status = self.request.query_params["status"]
            if status not in Order.Status.values:
                raise ValidationError({"status": "Invalid order status."})
            queryset = queryset.filter(status=status)
        return queryset

    def perform_destroy(self, instance):
        services.delete_order(instance.pk)

    def change_status(self, target):
        # Resolve ownership before obtaining locks; ownership is immutable.
        order = self.get_object()
        if self.request.data:
            raise ValidationError("This action accepts an empty request body.")
        order = services.transition_order(order.pk, target)
        return Response(self.get_serializer(order).data)

    @extend_schema(request=None, responses={200: OrderSerializer})
    @action(detail=True, methods=["post"])
    def allocate(self, request, pk=None):
        return self.change_status(Order.Status.ALLOCATED)

    @extend_schema(request=None, responses={200: OrderSerializer})
    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def fulfil(self, request, pk=None):
        return self.change_status(Order.Status.FULFILLED)

    @extend_schema(request=None, responses={200: OrderSerializer})
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self.change_status(Order.Status.CANCELLED)
