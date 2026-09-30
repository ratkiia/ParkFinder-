"""Rate limiting primitives.

* ``TokenBucketLimiter`` protects our public endpoints (per client key).
* ``MinIntervalLimiter`` spaces out calls to an upstream with a strict usage policy
  (Nominatim allows at most one request per second).
"""

import asyncio
import time
from collections import OrderedDict
from typing import Awaitable, Callable


class TokenBucketLimiter:
    def __init__(
        self,
        *,
        rate_per_minute: int,
        burst: int,
        max_clients: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._rate_per_second = rate_per_minute / 60.0
        self._capacity = float(burst)
        self._max_clients = max_clients
        self._clock = clock
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()  # key -> (tokens, updated_at)

    def check(self, key: str) -> tuple[bool, float]:
        """Consume one token. Returns ``(allowed, retry_after_seconds)``."""
        now = self._clock()
        tokens, updated = self._buckets.get(key, (self._capacity, now))
        tokens = min(self._capacity, tokens + (now - updated) * self._rate_per_second)

        if tokens >= 1:
            allowed, tokens, retry_after = True, tokens - 1, 0.0
        else:
            allowed, retry_after = False, (1 - tokens) / self._rate_per_second

        self._buckets[key] = (tokens, now)
        self._buckets.move_to_end(key)
        while len(self._buckets) > self._max_clients:  # bound memory under many distinct clients
            self._buckets.popitem(last=False)
        return allowed, retry_after


class MinIntervalLimiter:
    def __init__(
        self,
        interval_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._interval = interval_seconds
        self._clock = clock
        self._sleep = sleep
        self._next_allowed = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            delay = self._next_allowed - self._clock()
            if delay > 0:
                await self._sleep(delay)
            self._next_allowed = self._clock() + self._interval
