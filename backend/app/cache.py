"""A small in-memory TTL + LRU cache with request coalescing ("single flight").

Good enough for a single backend instance. For several instances, swap in a shared cache
(e.g. Redis) behind the same ``get`` / ``set`` / ``get_or_set`` interface.
"""

import asyncio
import time
from collections import OrderedDict
from typing import Awaitable, Callable, Generic, TypeVar

V = TypeVar("V")


class TTLCache(Generic[V]):
    def __init__(
        self,
        *,
        max_entries: int,
        default_ttl: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self._max_entries = max_entries
        self._default_ttl = default_ttl
        self._clock = clock
        self._data: OrderedDict[str, tuple[float, V]] = OrderedDict()
        self._inflight: dict[str, asyncio.Task[V]] = {}

    def __len__(self) -> int:
        return len(self._data)

    def get(self, key: str) -> V | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self._clock() >= expires_at:
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: str, value: V, ttl: float | None = None) -> None:
        self._data[key] = (self._clock() + (ttl if ttl is not None else self._default_ttl), value)
        self._data.move_to_end(key)
        while len(self._data) > self._max_entries:
            self._data.popitem(last=False)

    def invalidate(self, key: str | None = None) -> None:
        """Drop one key, or everything when ``key`` is None."""
        if key is None:
            self._data.clear()
        else:
            self._data.pop(key, None)

    async def get_or_set(self, key: str, factory: Callable[[], Awaitable[V]], ttl: float | None = None) -> V:
        """Return a cached value or compute it once, even if many callers ask concurrently.

        Failures are not cached. The upstream call is shielded, so a cancelled caller
        (e.g. a browser that aborted its request) does not abort it for the other waiters.
        """
        cached = self.get(key)
        if cached is not None:
            return cached

        task = self._inflight.get(key)
        if task is None:
            task = asyncio.ensure_future(factory())
            self._inflight[key] = task

            def _on_done(t: asyncio.Task[V]) -> None:
                self._inflight.pop(key, None)
                if not t.cancelled() and t.exception() is None:
                    self.set(key, t.result(), ttl)

            task.add_done_callback(_on_done)

        return await asyncio.shield(task)
