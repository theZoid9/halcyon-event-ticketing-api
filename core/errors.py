import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from django.http import JsonResponse
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


class Conflict(APIException):
    status_code = 409
    default_detail = "The request conflicts with the current resource state."
    default_code = "conflict"


def envelope(code, message, details, request):
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": getattr(request, "request_id", None),
        }
    }


def exception_handler(exc, context):
    request = context.get("request")
    if isinstance(exc, DjangoValidationError):
        exc = ValidationError(getattr(exc, "message_dict", exc.messages))
    if isinstance(exc, (ProtectedError, IntegrityError)):
        exc = Conflict("A uniqueness or relationship constraint prevented this change.")
    response = drf_exception_handler(exc, context)
    if response is None:
        logger.exception("Unhandled API error request_id=%s", getattr(request, "request_id", None))
        return Response(
            envelope("internal_error", "An internal error occurred.", {}, request), status=500
        )
    code = (
        "validation_error"
        if isinstance(exc, ValidationError)
        else getattr(exc, "default_code", "request_error")
    )
    message = (
        str(response.data.get("detail", "Request validation failed."))
        if isinstance(response.data, dict)
        else "Request validation failed."
    )
    response.data = envelope(code, message, response.data, request)
    return response


def bad_request(request, exception):
    return JsonResponse(envelope("bad_request", "Invalid request.", {}, request), status=400)


def permission_denied(request, exception):
    return JsonResponse(
        envelope("permission_denied", "Permission denied.", {}, request), status=403
    )


def not_found(request, exception):
    return JsonResponse(envelope("not_found", "Resource not found.", {}, request), status=404)


def server_error(request):
    return JsonResponse(
        envelope("internal_error", "An internal error occurred.", {}, request), status=500
    )
