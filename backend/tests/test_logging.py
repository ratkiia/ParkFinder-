"""Traceability: request ids, access log, upstream-call log and JSON log files."""

import json
import logging
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import Settings
from app.logging_config import JsonFormatter, configure_logging, redact
from app.main import create_app
from app.request_context import REQUEST_ID_PATTERN, resolve_request_id
from tests.conftest import FakePrimary, build_service


def read_log(settings: Settings) -> list[dict]:
    for handler in logging.getLogger().handlers:
        handler.flush()
    path = settings.log_dir / settings.log_file_name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(autouse=True)
def _reset_logging():
    yield
    # Close our file handlers so tmp directories can be removed (Windows keeps files locked).
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_parkfinder_handler", False):
            root.removeHandler(handler)
            handler.close()


class TestRequestId:
    def test_generated_when_missing(self):
        rid = resolve_request_id(None)
        assert REQUEST_ID_PATTERN.match(rid)

    def test_valid_incoming_is_reused(self):
        assert resolve_request_id("frontend-1234abcd") == "frontend-1234abcd"

    @pytest.mark.parametrize("bad", ["short", "x" * 65, "has space 12345", "inject\nline12345", "<script>abc"])
    def test_invalid_incoming_is_replaced(self, bad):
        assert resolve_request_id(bad) != bad


def test_redact_masks_credentials():
    assert redact({"q": "Austin", "api_key": "s3cret", "Token": "t", "access_token": "x"}) == {
        "q": "Austin", "api_key": "***", "Token": "***", "access_token": "***"}
    assert redact(None) is None


def test_json_formatter_includes_event_fields_and_exception():
    record = logging.LogRecord("parkfinder.test", logging.ERROR, __file__, 1, "boom %s", ("x",), None)
    record.request_id = "abc12345"
    record.event = {"event": "unit", "status": 500, "message": "must not override"}
    try:
        raise ValueError("bad")
    except ValueError:
        import sys
        record.exc_info = sys.exc_info()
    line = json.loads(JsonFormatter().format(record))
    assert line["message"] == "boom x"
    assert line["request_id"] == "abc12345"
    assert line["event"] == "unit" and line["status"] == 500
    assert "ValueError: bad" in line["exception"]


def test_configure_logging_is_idempotent(settings):
    configure_logging(settings)
    configure_logging(settings)
    owned = [h for h in logging.getLogger().handlers if getattr(h, "_parkfinder_handler", False)]
    assert len(owned) == 2  # console + file, not duplicated


def test_file_logging_can_be_disabled(settings):
    settings.log_to_file = False
    configure_logging(settings)
    owned = [h for h in logging.getLogger().handlers if getattr(h, "_parkfinder_handler", False)]
    assert len(owned) == 1


def test_response_carries_request_id_and_access_log_is_written(settings):
    with TestClient(create_app(settings, park_service=build_service(settings))) as client:
        response = client.get("/api/v1/parks/prospect-park", headers={"X-Request-ID": "trace-test-0001"})
    assert response.headers["X-Request-ID"] == "trace-test-0001"

    access = [e for e in read_log(settings) if e.get("event") == "http_request"]
    assert access, "expected an access-log entry"
    entry = access[-1]
    assert entry["request_id"] == "trace-test-0001"
    assert entry["method"] == "GET" and entry["path"] == "/api/v1/parks/prospect-park"
    assert entry["status"] == 200 and entry["duration_ms"] >= 0
    assert entry["level"] == "INFO"


def test_cors_allows_and_exposes_request_id_header(settings):
    with TestClient(create_app(settings, park_service=build_service(settings))) as client:
        preflight = client.options("/api/v1/parks/by-city", headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-request-id",
        })
        actual = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert preflight.status_code == 200
    assert "x-request-id" in preflight.headers["access-control-allow-headers"].lower()
    assert "x-request-id" in actual.headers["access-control-expose-headers"].lower()


def test_error_body_contains_request_id(settings):
    with TestClient(create_app(settings, park_service=build_service(settings))) as client:
        response = client.get("/api/v1/parks/by-city", params={"city": "1"})
    body = response.json()
    assert response.status_code == 422
    assert body["error"]["request_id"] == response.headers["X-Request-ID"]
    entry = [e for e in read_log(settings) if e.get("event") == "http_request"][-1]
    assert entry["status"] == 422 and entry["level"] == "WARNING"


def test_unhandled_error_is_logged_with_traceback_and_request_id(settings):
    class ExplodingPrimary(FakePrimary):
        async def parks_in_bbox(self, bbox):
            raise RuntimeError("kaboom")

    service = build_service(settings, primary=ExplodingPrimary())
    with TestClient(create_app(settings, park_service=service), raise_server_exceptions=False) as client:
        response = client.get("/api/v1/parks/by-city", params={"city": "Austin"})
    assert response.status_code == 500
    rid = response.headers["X-Request-ID"]
    assert response.json()["error"]["request_id"] == rid
    assert "kaboom" not in response.text

    entries = [e for e in read_log(settings) if e["request_id"] == rid]
    crash = next(e for e in entries if e.get("event") == "unhandled_error")
    assert "RuntimeError: kaboom" in crash["exception"]
    assert any(e.get("event") == "http_request" and e["status"] == 500 and e["level"] == "ERROR" for e in entries)


def test_rate_limited_request_is_logged(settings):
    settings.rate_limit_burst = 1
    settings.rate_limit_per_minute = 1
    with TestClient(create_app(settings, park_service=build_service(settings))) as client:
        client.get("/api/v1/parks/prospect-park")
        limited = client.get("/api/v1/parks/prospect-park")
    assert limited.status_code == 429 and "X-Request-ID" in limited.headers
    entry = [e for e in read_log(settings) if e.get("event") == "http_request"][-1]
    assert entry["rate_limited"] is True and entry["status"] == 429


@respx.mock
def test_one_request_id_traces_the_whole_call_chain(settings):
    """Access log, cache lookup, every upstream attempt (incl. retries) and the search summary share one id."""
    respx.get(settings.nominatim_url).mock(return_value=httpx.Response(200, json=[{
        "lat": "30.27", "lon": "-97.74", "addresstype": "city", "display_name": "Austin, Texas",
        "boundingbox": ["30.1", "30.5", "-97.9", "-97.6"],
    }]))
    respx.post(settings.overpass_url).mock(side_effect=[
        httpx.Response(503),
        httpx.Response(200, json={"elements": [
            {"type": "way", "id": 1, "center": {"lat": 30.26, "lon": -97.77}, "tags": {"name": "Zilker Park"}}]}),
    ])
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/parks/by-city", params={"city": "Austin, TX"},
                              headers={"X-Request-ID": "chain-trace-42"})
    assert response.status_code == 200

    entries = [e for e in read_log(settings) if e["request_id"] == "chain-trace-42"]
    events = [e.get("event") for e in entries]
    assert events.count("upstream_call") == 3  # Nominatim + Overpass retry + Overpass success
    upstream = [e for e in entries if e.get("event") == "upstream_call"]
    assert [(e["provider"], e["status"], e["outcome"]) for e in upstream] == [
        ("Nominatim", 200, "success"), ("Overpass", 503, "retry"), ("Overpass", 200, "success")]
    assert upstream[0]["params"]["q"] == "Austin, TX"
    assert "cache_lookup" in events
    search = next(e for e in entries if e.get("event") == "park_search")
    assert search["count"] == 1 and search["degraded"] is False
    assert events[-1] == "http_request"


@respx.mock
def test_upstream_timeout_is_logged(settings):
    respx.get(settings.nominatim_url).mock(side_effect=httpx.ReadTimeout("slow"))
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/parks/by-city", params={"city": "Denver"})
    assert response.status_code == 503
    upstream = [e for e in read_log(settings) if e.get("event") == "upstream_call"]
    assert [e["outcome"] for e in upstream] == ["retry", "failed"]
    assert all(e["error"] == "ReadTimeout" and e["level"] == "WARNING" for e in upstream)
    assert any(e.get("event") == "provider_failure" for e in read_log(settings))


def test_log_directory_is_created(tmp_path: Path, sample_path: Path):
    settings = Settings(sample_data_path=sample_path, log_dir=tmp_path / "nested" / "logs", log_to_file=True)
    configure_logging(settings)
    logging.getLogger("parkfinder.test").warning("hello")
    assert (tmp_path / "nested" / "logs" / "api.log").exists()
