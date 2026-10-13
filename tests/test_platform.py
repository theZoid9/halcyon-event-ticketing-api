from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError
from django.test import RequestFactory
from rest_framework.exceptions import PermissionDenied
from rest_framework.authtoken.models import Token

from core import errors
from core.health import HealthView

pytestmark = pytest.mark.django_db


def test_login_logout(client, user):
    response = client.post(
        "/api/auth/login/", {"username": user.username, "password": "Secure-example-1782!"}
    )
    assert response.status_code == 200
    client.credentials(HTTP_AUTHORIZATION=f"Token {response.data['token']}")
    assert client.post("/api/auth/logout/").status_code == 204
    assert client.post("/api/auth/logout/").status_code == 401


def test_bad_login_and_throttling(client, user):
    for _ in range(10):
        response = client.post("/api/auth/login/", {"username": user.username, "password": "wrong"})
        assert response.status_code == 401
        assert response.data["error"]["code"] == "authentication_failed"
    assert client.post("/api/auth/login/", {}).status_code == 429


def test_user_crud(admin_client):
    payload = {
        "username": "newperson",
        "email": "person@example.com",
        "password": "Long-and-random-8782!",
    }
    response = admin_client.post("/api/users/", payload)
    assert response.status_code == 201
    assert "password" not in response.data
    uid = response.data["id"]
    person = get_user_model().objects.get(pk=uid)
    assert person.check_password(payload["password"])
    assert admin_client.get("/api/users/").data["count"] == 2
    url = f"/api/users/{uid}/"
    assert admin_client.get(url).status_code == 200
    assert admin_client.patch(url, {"email": "changed@example.com"}).status_code == 200
    payload["password"] = "Different-password-9827!"
    assert admin_client.put(url, payload).status_code == 200
    person.refresh_from_db()
    assert person.check_password(payload["password"])
    assert admin_client.delete(url).status_code == 204
    assert admin_client.get(url).status_code == 404


def test_user_authorization_and_validation(client, auth_client, admin_client):
    assert client.get("/api/users/").status_code == 401
    assert auth_client.get("/api/users/").status_code == 403
    response = admin_client.post("/api/users/", {"username": "weak", "password": "123"})
    assert response.status_code == 400
    assert response.data["error"]["code"] == "validation_error"
    assert response.data["error"]["request_id"] == response["X-Request-ID"]


def test_health(client):
    response = client.get("/health/")
    assert response.status_code == 200
    assert response.data["database"] == "connected"
    assert response.data["uptime_seconds"] >= 0
    with patch("core.health.connection.cursor", side_effect=DatabaseError("secret details")):
        response = HealthView.as_view()(RequestFactory().get("/health/"))
    assert response.status_code == 503
    assert response.data["database"] == "unavailable"
    assert "secret" not in str(response.data)


def test_docs_and_unknown_route(client):
    assert client.get("/api/schema/").status_code == 200
    assert client.get("/api/docs/").status_code == 200
    response = client.get("/unknown/")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_error_handlers():
    request = RequestFactory().get("/")
    for exc, code in [
        (IntegrityError("private"), 409),
        (RuntimeError("private"), 500),
        (PermissionDenied(), 403),
    ]:
        response = errors.exception_handler(exc, {"request": request})
        assert response.status_code == code
        assert "private" not in str(response.data)
    assert errors.bad_request(request, None).status_code == 400
    assert errors.permission_denied(request, None).status_code == 403
    assert errors.server_error(request).status_code == 500


def test_password_change_and_deactivation_revoke_tokens(admin_client, user, client):
    token = Token.objects.create(user=user)
    response = admin_client.patch(f"/api/users/{user.pk}/", {"password": "New-long-password-1782!"})
    assert response.status_code == 200
    assert not Token.objects.filter(key=token.key).exists()
    token = Token.objects.create(user=user)
    assert admin_client.patch(f"/api/users/{user.pk}/", {"is_active": False}).status_code == 200
    assert not Token.objects.filter(key=token.key).exists()
    assert (
        client.post(
            "/api/auth/login/", {"username": user.username, "password": "New-long-password-1782!"}
        ).status_code
        == 401
    )


def test_method_and_malformed_json_errors(auth_client):
    response = auth_client.get("/api/auth/logout/")
    assert response.status_code == 405
    assert response.data["error"]["code"] == "method_not_allowed"
    response = auth_client.post("/api/reservations/", "{invalid", content_type="application/json")
    assert response.status_code == 400
    assert response.data["error"]["code"] == "parse_error"
