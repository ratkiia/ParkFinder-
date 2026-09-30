from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest
import respx

from app.errors import UpstreamError, UpstreamRateLimitedError, UpstreamTimeoutError
from app.http_client import parse_retry_after, request_json

URL = "https://upstream.test/data"


async def no_sleep(_: float) -> None:
    return None


async def call(client: httpx.AsyncClient, retries: int = 2, sleep=no_sleep):
    return await request_json(client, "GET", URL, provider="Upstream", max_retries=retries, sleep=sleep)


@pytest.fixture
async def client():
    async with httpx.AsyncClient() as c:
        yield c


class TestParseRetryAfter:
    def test_seconds(self):
        assert parse_retry_after("12") == 12

    def test_http_date(self):
        future = datetime.now(timezone.utc) + timedelta(seconds=30)
        assert 25 <= parse_retry_after(format_datetime(future, usegmt=True)) <= 31

    @pytest.mark.parametrize("value", [None, "", "soon", "-5"])
    def test_invalid_or_negative(self, value):
        result = parse_retry_after(value)
        assert result is None or result == 0


@respx.mock
async def test_success_returns_json(client):
    respx.get(URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    assert await call(client) == {"ok": True}


@respx.mock
async def test_429_is_retried_then_succeeds(client):
    route = respx.get(URL).mock(side_effect=[httpx.Response(429, headers={"Retry-After": "1"}),
                                             httpx.Response(200, json=[1])])
    sleeps: list[float] = []

    async def record(seconds: float) -> None:
        sleeps.append(seconds)

    assert await call(client, sleep=record) == [1]
    assert route.call_count == 2
    assert sleeps == [1.0]


@respx.mock
async def test_429_exhausted_raises_rate_limited_with_retry_after(client):
    route = respx.get(URL).mock(return_value=httpx.Response(429, headers={"Retry-After": "30"}))
    with pytest.raises(UpstreamRateLimitedError) as info:
        await call(client, retries=2)
    assert route.call_count == 3
    assert info.value.retry_after == 30


@respx.mock
async def test_retry_after_is_capped(client):
    respx.get(URL).mock(side_effect=[httpx.Response(503, headers={"Retry-After": "3600"}),
                                     httpx.Response(200, json={})])
    sleeps: list[float] = []

    async def record(seconds: float) -> None:
        sleeps.append(seconds)

    await request_json(client, "GET", URL, provider="U", max_retry_after_seconds=5, sleep=record)
    assert sleeps == [5]


@respx.mock
async def test_500_is_not_retried(client):
    route = respx.get(URL).mock(return_value=httpx.Response(500))
    with pytest.raises(UpstreamError, match="HTTP 500"):
        await call(client)
    assert route.call_count == 1


@respx.mock
async def test_504_exhausted_raises_timeout(client):
    respx.get(URL).mock(return_value=httpx.Response(504))
    with pytest.raises(UpstreamTimeoutError):
        await call(client, retries=1)


@respx.mock
async def test_400_raises_upstream_error(client):
    respx.get(URL).mock(return_value=httpx.Response(400, text="bad query"))
    with pytest.raises(UpstreamError, match="HTTP 400"):
        await call(client)


@respx.mock
async def test_network_timeout_retried_then_raises(client):
    route = respx.get(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(UpstreamTimeoutError):
        await call(client, retries=2)
    assert route.call_count == 3


@respx.mock
async def test_timeout_then_success(client):
    respx.get(URL).mock(side_effect=[httpx.ConnectTimeout("slow"), httpx.Response(200, json={"a": 1})])
    assert await call(client) == {"a": 1}


@respx.mock
async def test_connection_error_raises_upstream_error(client):
    respx.get(URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(UpstreamError, match="Could not reach"):
        await call(client, retries=0)


@respx.mock
async def test_invalid_json_raises_upstream_error(client):
    respx.get(URL).mock(return_value=httpx.Response(200, text="<html>not json</html>"))
    with pytest.raises(UpstreamError, match="invalid response"):
        await call(client)
