from __future__ import annotations

import random

from scanner.live.config import LiveScanConfig
from scanner.live.source_pool import SlidingWindowLimiter, SourcePool


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeResponse:
    status_code = 429
    headers = {"Retry-After": "120"}


class FakeRateLimit(Exception):
    def __init__(self) -> None:
        self.response = FakeResponse()


def test_sliding_window_enforces_actual_cap() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(
        requests_per_minute=2,
        jitter_min_sec=0,
        jitter_max_sec=0,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
        rng=random.Random(1),
    )

    limiter.acquire()
    limiter.acquire()
    assert clock.now == 0
    limiter.acquire()
    assert clock.now >= 60


def test_pool_fails_over_and_honors_retry_after_without_early_retry() -> None:
    clock = FakeClock()
    config = LiveScanConfig.from_env(
        {
            "SCAN_API_SOURCES": "KBS,VCI",
            "SCAN_SOURCE_REQUESTS_PER_MINUTE": "20",
            "SCAN_SOURCE_LIMITS": "KBS=20,VCI=20",
            "SCAN_SOURCE_USAGE_RATIO": "1",
            "SCAN_REQUEST_JITTER_MIN_SEC": "0",
            "SCAN_REQUEST_JITTER_MAX_SEC": "0",
            "SCAN_SOURCE_ERROR_COOLDOWN_MIN_SEC": "1",
            "SCAN_SOURCE_ERROR_COOLDOWN_MAX_SEC": "1",
            "SCAN_SOURCE_RECOVER_AFTER_SEC": "5",
            "SCAN_RETRY_AFTER_MAX_SEC": "10",
        }
    )
    pool: SourcePool[str] = SourcePool(
        config,
        rng=random.Random(2),
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
    )

    def operation(source: str) -> str:
        if source == "KBS":
            raise FakeRateLimit()
        return "ok"

    value, source = pool.call(operation, preferred="KBS")

    assert value == "ok"
    assert source == "VCI"
    assert pool.states["KBS"].ready_in() >= 120
    assert clock.now == 0


def test_alias_and_canonical_name_share_one_circuit() -> None:
    config = LiveScanConfig.from_env(
        {
            "SCAN_API_SOURCES": "VIETFIN,DNSE",
            "SCAN_REQUEST_JITTER_MIN_SEC": "0",
            "SCAN_REQUEST_JITTER_MAX_SEC": "0",
        }
    )
    pool: SourcePool[str] = SourcePool(config)
    assert list(pool.states) == ["DNSE"]


def test_request_attempts_retries_same_source_after_short_cooldown() -> None:
    clock = FakeClock()
    config = LiveScanConfig.from_env(
        {
            "SCAN_API_SOURCES": "KBS",
            "SCAN_REQUEST_ATTEMPTS": "3",
            "SCAN_REQUEST_JITTER_MIN_SEC": "0",
            "SCAN_REQUEST_JITTER_MAX_SEC": "0",
            "SCAN_SOURCE_ERROR_COOLDOWN_MIN_SEC": "1",
            "SCAN_SOURCE_ERROR_COOLDOWN_MAX_SEC": "1",
            "SCAN_SOURCE_RECOVER_AFTER_SEC": "5",
            "SCAN_RETRY_AFTER_MAX_SEC": "10",
        }
    )
    pool: SourcePool[str] = SourcePool(
        config,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
    )
    calls = 0

    def operation(source: str) -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ConnectionError("temporary")
        return source

    value, source = pool.call(operation)
    assert value == source == "KBS"
    assert calls == 3
    assert clock.now >= 6
