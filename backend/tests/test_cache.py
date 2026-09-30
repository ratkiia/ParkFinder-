import asyncio

import pytest

from app.cache import TTLCache


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_get_set_and_expiry():
    clock = FakeClock()
    cache: TTLCache[str] = TTLCache(max_entries=10, default_ttl=5, clock=clock)
    cache.set("a", "1")
    assert cache.get("a") == "1"
    clock.now = 4.99
    assert cache.get("a") == "1"
    clock.now = 5
    assert cache.get("a") is None
    assert len(cache) == 0


def test_custom_ttl():
    clock = FakeClock()
    cache: TTLCache[str] = TTLCache(max_entries=10, default_ttl=5, clock=clock)
    cache.set("a", "1", ttl=100)
    clock.now = 50
    assert cache.get("a") == "1"


def test_lru_eviction_respects_max_size():
    cache: TTLCache[int] = TTLCache(max_entries=2, default_ttl=60)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.get("a")  # 'a' becomes most recently used
    cache.set("c", 3)
    assert cache.get("b") is None
    assert cache.get("a") == 1 and cache.get("c") == 3
    assert len(cache) == 2


def test_invalidate():
    cache: TTLCache[int] = TTLCache(max_entries=5, default_ttl=60)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.invalidate("a")
    assert cache.get("a") is None and cache.get("b") == 2
    cache.invalidate()
    assert len(cache) == 0


def test_rejects_invalid_size():
    with pytest.raises(ValueError):
        TTLCache(max_entries=0, default_ttl=1)


async def test_get_or_set_caches_result():
    cache: TTLCache[int] = TTLCache(max_entries=5, default_ttl=60)
    calls = 0

    async def factory() -> int:
        nonlocal calls
        calls += 1
        return 42

    assert await cache.get_or_set("k", factory) == 42
    assert await cache.get_or_set("k", factory) == 42
    assert calls == 1


async def test_get_or_set_coalesces_concurrent_requests():
    cache: TTLCache[int] = TTLCache(max_entries=5, default_ttl=60)
    calls = 0
    gate = asyncio.Event()

    async def factory() -> int:
        nonlocal calls
        calls += 1
        await gate.wait()
        return 7

    waiters = [asyncio.create_task(cache.get_or_set("k", factory)) for _ in range(5)]
    await asyncio.sleep(0)
    gate.set()
    assert await asyncio.gather(*waiters) == [7] * 5
    assert calls == 1


async def test_get_or_set_does_not_cache_failures():
    cache: TTLCache[int] = TTLCache(max_entries=5, default_ttl=60)
    attempts = 0

    async def flaky() -> int:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("boom")
        return 1

    with pytest.raises(RuntimeError):
        await cache.get_or_set("k", flaky)
    assert await cache.get_or_set("k", flaky) == 1


async def test_cancelled_caller_does_not_cancel_shared_fetch():
    cache: TTLCache[int] = TTLCache(max_entries=5, default_ttl=60)
    gate = asyncio.Event()

    async def factory() -> int:
        await gate.wait()
        return 9

    first = asyncio.create_task(cache.get_or_set("k", factory))
    second = asyncio.create_task(cache.get_or_set("k", factory))
    await asyncio.sleep(0)
    first.cancel()
    gate.set()
    assert await second == 9
    await asyncio.sleep(0)
    assert cache.get("k") == 9
