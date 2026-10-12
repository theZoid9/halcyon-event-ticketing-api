import time

from django.db import DatabaseError, connection
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

STARTED_AT = time.monotonic()


class HealthSerializer(serializers.Serializer):
    status = serializers.CharField()
    database = serializers.CharField()
    uptime_seconds = serializers.FloatField()


class HealthView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(responses={200: HealthSerializer, 503: HealthSerializer})
    def get(self, request):
        connected = True
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                connected = cursor.fetchone() == (1,)
        except DatabaseError:
            connected = False
        return Response(
            {
                "status": "ok" if connected else "degraded",
                "database": "connected" if connected else "unavailable",
                "uptime_seconds": round(time.monotonic() - STARTED_AT, 3),
            },
            status=200 if connected else 503,
        )
