"""Resilient JSON-over-HTTP helper used by every provider.

Retries timeouts, connection errors and 429/502/503/504 with exponential backoff
(honouring ``Retry-After`` up to a cap), then maps failures to domain exceptions.
Every attempt is logged as an ``upstream_call`` event tagged with the current request id.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Awaitable, Callable, Mapping

import httpx

from app.errors import UpstreamError, UpstreamRateLimitedError, UpstreamTimeoutError
from app.logging_config import redact

logger = logging.getLogger("parkfinder.upstream")

RETRYABLE_STATUS = frozenset({429, 502, 503, 504})


def parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header given as seconds or an HTTP date."""
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


def _log_attempt(
    level: int,
    *,
    provider: str,
    method: str,
    url: str,
    params: Mapping[str, Any] | None,
    body_bytes: int,
    attempt: int,
    started: float,
    outcome: str,
    status: int | None = None,
    error: str | None = None,
) -> None:
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    logger.log(
        level,
        "%s %s %s -> %s (%.1f ms, attempt %d, %s)",
        provider, method, url, status if status is not None else error, duration_ms, attempt, outcome,
        extra={"event": {
            "event": "upstream_call",
            "provider": provider,
            "method": method,
            "url": url,
            "params": redact(params),
            "body_bytes": body_bytes,
            "status": status,
            "error": error,
            "attempt": attempt,
            "outcome": outcome,
            "duration_ms": duration_ms,
        }},
    )


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    provider: str,
    params: Mapping[str, Any] | None = None,
    data: Mapping[str, Any] | None = None,
    max_retries: int = 2,
    backoff_seconds: float = 0.5,
    max_retry_after_seconds: float = 5.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Any:
    body_bytes = sum(len(str(v)) for v in data.values()) if data else 0
    log = {"provider": provider, "method": method, "url": url, "params": params, "body_bytes": body_bytes}
    attempt = 0
    while True:
        started = time.perf_counter()
        try:
            response = await client.request(method, url, params=params, data=data)
        except httpx.TimeoutException as exc:
            retrying = attempt < max_retries
            # e.g. "ConnectTimeout" vs "ReadTimeout": tells a slow server apart from an unreachable one.
            _log_attempt(logging.WARNING, **log, attempt=attempt + 1, started=started,
                         outcome="retry" if retrying else "failed", error=exc.__class__.__name__)
            if retrying:
                await sleep(backoff_seconds * 2**attempt)
                attempt += 1
                continue
            raise UpstreamTimeoutError(f"{provider} did not respond in time.") from exc
        except httpx.HTTPError as exc:
            retrying = attempt < max_retries
            _log_attempt(logging.WARNING, **log, attempt=attempt + 1, started=started,
                         outcome="retry" if retrying else "failed", error=exc.__class__.__name__)
            if retrying:
                await sleep(backoff_seconds * 2**attempt)
                attempt += 1
                continue
            raise UpstreamError(f"Could not reach {provider}.") from exc

        status = response.status_code
        retry_after = parse_retry_after(response.headers.get("Retry-After"))

        if status in RETRYABLE_STATUS and attempt < max_retries:
            _log_attempt(logging.WARNING, **log, attempt=attempt + 1, started=started, outcome="retry", status=status)
            delay = retry_after if retry_after is not None else backoff_seconds * 2**attempt
            await sleep(min(delay, max_retry_after_seconds))
            attempt += 1
            continue

        if status >= 400:
            _log_attempt(logging.WARNING, **log, attempt=attempt + 1, started=started, outcome="failed", status=status)
            if status == 429:
                raise UpstreamRateLimitedError(f"{provider} is rate limiting requests.", retry_after=retry_after)
            if status == 504:
                raise UpstreamTimeoutError(f"{provider} timed out (HTTP 504).", retry_after=retry_after)
            raise UpstreamError(f"{provider} returned HTTP {status}.", retry_after=retry_after)

        try:
            payload = response.json()
        except ValueError as exc:
            _log_attempt(logging.WARNING, **log, attempt=attempt + 1, started=started, outcome="failed",
                         status=status, error="invalid_json")
            raise UpstreamError(f"{provider} returned an invalid response.") from exc
        _log_attempt(logging.INFO, **log, attempt=attempt + 1, started=started, outcome="success", status=status)
        return payload
