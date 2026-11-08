import pytest
from django.core.exceptions import ValidationError

from apps.core.geojson import validate_geometry

pytestmark = pytest.mark.django_db


def test_health_ok(api):
    response = api.get("/api/v1/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
    assert response.headers["X-Request-ID"]


def test_request_id_is_propagated(api):
    response = api.get("/api/v1/health/", HTTP_X_REQUEST_ID="abc12345-trace")
    assert response.headers["X-Request-ID"] == "abc12345-trace"


def test_unauthenticated_error_uses_uniform_format(api):
    response = api.get("/api/v1/farms/")
    assert response.status_code == 401
    body = response.json()
    assert set(body) == {"code", "message", "details", "field_errors"}


def test_openapi_schema_generates(api):
    response = api.get("/api/v1/schema/")
    assert response.status_code == 200
    assert b"/api/v1/farms/{farm_id}/parcels/" in response.content


SQUARE = [[[15.0, -4.0], [15.001, -4.0], [15.001, -4.001], [15.0, -4.0]]]


def test_geojson_valid_polygon():
    validate_geometry({"type": "Polygon", "coordinates": SQUARE})
    validate_geometry({"type": "MultiPolygon", "coordinates": [SQUARE]})
    validate_geometry(None)


@pytest.mark.parametrize(
    "geometry",
    [
        {"type": "Point", "coordinates": [15, -4]},
        {"type": "Polygon", "coordinates": []},
        {"type": "Polygon", "coordinates": [[[15, -4], [16, -4], [16, -5]]]},
        {"type": "Polygon", "coordinates": [[[15, -4], [16, -4], [16, -5], [15, -5]]]},
        {"type": "Polygon", "coordinates": [[[200, -4], [16, -4], [16, -5], [200, -4]]]},
        {"type": "Polygon", "coordinates": [[["a", -4], [16, -4], [16, -5], ["a", -4]]]},
        "not-an-object",
    ],
)
def test_geojson_invalid(geometry):
    with pytest.raises(ValidationError):
        validate_geometry(geometry)
