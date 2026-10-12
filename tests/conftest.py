import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient


@pytest.fixture(autouse=True)
def reset_throttles():
    cache.clear()


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="alice", password="Secure-example-1782!")


@pytest.fixture
def other_user(db):
    return get_user_model().objects.create_user(username="bob", password="Secure-example-1782!")


@pytest.fixture
def admin(db):
    return get_user_model().objects.create_user(
        username="admin", password="Secure-example-1782!", is_staff=True
    )


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def auth_client(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=user).key}")
    return client


@pytest.fixture
def admin_client(admin):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=admin).key}")
    return client
