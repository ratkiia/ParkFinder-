"""End-to-end tests of the HTTP layer: status codes, error envelope, validation, security headers."""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.errors import UpstreamRateLimitedError
from app.main import create_app
from tests.conftest import FakeGeocoder, FakePrimary, build_service, make_park


@pytest.fixture
def client(settings):
    service = build_service(settings, primary=FakePrimary([make_park("osm-way-1", "Pease Park")]))
    with TestClient(create_app(settings, park_service=service), raise_server_exceptions=False) as c:
        yield c


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200 and response.json()["status"] == "ok"


def test_parks_by_city_ok(client):
    response = client.get("/api/v1/parks/by-city", params={"city": "Austin, TX"})
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1 and body["parks"][0]["name"] == "Pease Park"
    assert body["degraded"] is False and "OpenStreetMap" in body["attribution"]
    # Missing data is returned as null/empty, never invented.
    park = body["parks"][0]
    assert park["description"] is None and park["hours"] is None and park["images"] == []


@pytest.mark.parametrize("params", [
    {},
    {"city": "A"},
    {"city": "x" * 101},
    {"city": "<script>alert(1)</script>"},
    {"city": "Austin; DROP TABLE"},
    {"city": "12345"},
])
def test_parks_by_city_validation_422(client, params):
    response = client.get("/api/v1/parks/by-city", params=params)
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"][0]["field"].startswith("query")
    assert "<script>" not in response.text  # raw input is not echoed back


@pytest.mark.parametrize("city", ["St. Louis, MO", "Coeur d'Alene", "Winston-Salem", "Cañon City"])
def test_parks_by_city_accepts_real_city_names(client, city):
    assert client.get("/api/v1/parks/by-city", params={"city": city}).status_code == 200


def test_parks_by_city_404(settings):
    from app.errors import CityNotFoundError

    service = build_service(settings, FakeGeocoder(exc=CityNotFoundError("No US city matching 'Atlantis'.")))
    with TestClient(create_app(settings, park_service=service)) as c:
        response = c.get("/api/v1/parks/by-city", params={"city": "Atlantis"})
    assert response.status_code == 404 and response.json()["error"]["code"] == "city_not_found"


def test_upstream_throttling_returns_503_with_retry_after(settings):
    service = build_service(settings, FakeGeocoder(exc=UpstreamRateLimitedError("slow down", retry_after=17)))
    with TestClient(create_app(settings, park_service=service)) as c:
        response = c.get("/api/v1/parks/by-city", params={"city": "Denver"})
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "17"
    assert response.json()["error"]["code"] == "service_unavailable"


def test_in_bounds_ok(client):
    response = client.get("/api/v1/parks/in-bounds",
                          params={"south": 30.2, "west": -97.8, "north": 30.3, "east": -97.7})
    assert response.status_code == 200 and response.json()["area"]["label"] == "Current map area"


@pytest.mark.parametrize("params,code", [
    ({"south": 30.2, "west": -97.8, "north": 30.3}, "validation_error"),  # missing
    ({"south": "abc", "west": -97.8, "north": 30.3, "east": -97.7}, "validation_error"),
    ({"south": 95, "west": -97.8, "north": 96, "east": -97.7}, "validation_error"),
    ({"south": 30.3, "west": -97.8, "north": 30.2, "east": -97.7}, "invalid_request"),  # inverted
    ({"south": 30, "west": -100, "north": 35, "east": -95}, "invalid_request"),  # too large
    ({"south": "nan", "west": -97.8, "north": 30.3, "east": -97.7}, "validation_error"),
])
def test_in_bounds_validation_422(client, params, code):
    response = client.get("/api/v1/parks/in-bounds", params=params)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


def test_park_details(client):
    assert client.get("/api/v1/parks/prospect-park").json()["name"] == "Prospect Park"


def test_park_details_404(client):
    response = client.get("/api/v1/parks/does-not-exist")
    assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("park_id", ["UPPER", "has_underscore", "-leading-dash", "a" * 121])
def test_park_details_invalid_id_422(client, park_id):
    assert client.get(f"/api/v1/parks/{park_id}").status_code == 422


def test_unknown_route_uses_error_envelope(client):
    response = client.get("/api/v1/nope")
    assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"


def test_only_get_is_allowed(client):
    assert client.post("/api/v1/parks/by-city").status_code == 405


def test_unexpected_error_returns_generic_500(settings):
    class ExplodingPrimary(FakePrimary):
        async def parks_in_bbox(self, bbox):
            raise RuntimeError("secret internal detail")

    service = build_service(settings, primary=ExplodingPrimary())
    with TestClient(create_app(settings, park_service=service), raise_server_exceptions=False) as c:
        response = c.get("/api/v1/parks/by-city", params={"city": "Austin"})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret" not in response.text


def test_own_rate_limit_returns_429(settings):
    settings.rate_limit_burst = 2
    settings.rate_limit_per_minute = 1
    with TestClient(create_app(settings, park_service=build_service(settings))) as c:
        statuses = [c.get("/api/v1/parks/prospect-park").status_code for _ in range(3)]
        limited = c.get("/api/v1/parks/prospect-park")
        health = c.get("/api/health")
    assert statuses == [200, 200, 429]
    assert limited.json()["error"]["code"] == "rate_limited"
    assert int(limited.headers["Retry-After"]) >= 1
    assert health.status_code == 200  # health checks are not rate limited


def test_security_headers(client):
    response = client.get("/api/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_cors_allows_configured_origin_only(client):
    ok = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    evil = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in evil.headers


def test_cors_preflight(client):
    response = client.options("/api/v1/parks/by-city", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert response.status_code == 200


@respx.mock
def test_full_stack_with_mocked_upstreams_and_overpass_500_fallback(settings):
    """Real providers + HTTPX; Nominatim works, Overpass returns 500 -> sample fallback for Brooklyn."""
    respx.get(settings.nominatim_url).mock(return_value=httpx.Response(200, json=[{
        "lat": "40.65", "lon": "-73.95", "addresstype": "borough", "display_name": "Brooklyn, New York",
        "boundingbox": ["40.57", "40.74", "-74.05", "-73.83"],
    }]))
    respx.post(settings.overpass_url).mock(return_value=httpx.Response(500))
    with TestClient(create_app(settings)) as c:
        response = c.get("/api/v1/parks/by-city", params={"city": "Brooklyn, NY"})
    assert response.status_code == 200
    body = response.json()
    assert body["degraded"] is True and body["sources"] == ["sample"]
    assert [p["id"] for p in body["parks"]] == ["prospect-park"]
