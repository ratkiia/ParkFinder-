import pytest

from app.rate_limit import MinIntervalLimiter, TokenBucketLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_token_bucket_allows_burst_then_limits():
    clock = FakeClock()
    limiter = TokenBucketLimiter(rate_per_minute=60, burst=3, clock=clock)
    assert [limiter.check("ip")[0] for _ in range(3)] == [True, True, True]
    allowed, retry_after = limiter.check("ip")
    assert not allowed
    assert retry_after == pytest.approx(1.0)


def test_token_bucket_refills_over_time():
    clock = FakeClock()
    limiter = TokenBucketLimiter(rate_per_minute=60, burst=1, clock=clock)
    assert limiter.check("ip")[0]
    assert not limiter.check("ip")[0]
    clock.now = 1.0
    assert limiter.check("ip")[0]


def test_token_bucket_is_per_client():
    limiter = TokenBucketLimiter(rate_per_minute=60, burst=1, clock=FakeClock())
    assert limiter.check("a")[0]
    assert not limiter.check("a")[0]
    assert limiter.check("b")[0]


def test_token_bucket_bounds_memory():
    limiter = TokenBucketLimiter(rate_per_minute=60, burst=1, max_clients=2, clock=FakeClock())
    for key in ("a", "b", "c"):
        limiter.check(key)
    assert len(limiter._buckets) == 2


async def test_min_interval_limiter_spaces_calls():
    clock = FakeClock()
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.now += seconds

    limiter = MinIntervalLimiter(1.0, clock=clock, sleep=fake_sleep)
    await limiter.wait()
    await limiter.wait()
    clock.now += 0.25
    await limiter.wait()
    assert sleeps == [pytest.approx(1.0), pytest.approx(0.75)]
