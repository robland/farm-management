from collections.abc import Callable

import pytest
from rest_framework.test import APIClient

from apps.users.models import User
from tests.factories import World, make_world


@pytest.fixture
def api() -> APIClient:
    return APIClient()


@pytest.fixture
def client_for() -> Callable[[User], APIClient]:
    def _make(user: User) -> APIClient:
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    return _make


@pytest.fixture
def world(db: None) -> World:
    return make_world()
