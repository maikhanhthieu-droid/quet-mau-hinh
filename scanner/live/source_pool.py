"""Quota-aware multi-source request scheduling.

The pool assigns each symbol to one source and only fails over after an error.
Aliases are canonicalized before states are created, so ``VIETFIN`` and
``DNSE`` always share a single quota/circuit.
"""

from __future__ import annotations

import email.utils
import logging
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Generic, Iterable, TypeVar

from .config import LiveScanConfig, canonical_source


LOGGER = logging.getLogger(__name__)
T = TypeVar("T")


class SourcePoolError(RuntimeError):
    """Base class for source-pool errors."""


class AllSourcesFailed(SourcePoolError):
    """Raised when no configured source can complete an operation."""


class SourceDisabled(SourcePoolError):
    """Raised when a source is not usable for this run."""


class SourceNeutralError(RuntimeError):
    """Symbol/data error that should not open a provider-wide circuit."""


def _root_exception(exc: BaseException) -> BaseException:
    """Unwrap Tenacity RetryError without importing Tenacity directly."""

    last_attempt = getattr(exc, "last_attempt", None)
    exception_method = getattr(last_attempt, "exception", None)
    if callable(exception_method):
        nested = exception_method()
        if isinstance(nested, BaseException):
            return nested
    return exc


def _retry_after_seconds(exc: BaseException, *, now_epoch: float | None = None) -> float | None:
    exc = _root_exception(exc)
    direct = getattr(exc, "retry_after", None)
    if direct is not None:
        try:
            return max(0.0, float(direct))
        except (TypeError, ValueError):
            pass
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(str(raw))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    now_epoch = time.time() if now_epoch is None else now_epoch
    return max(0.0, parsed.timestamp() - now_epoch)


def _status_code(exc: BaseException) -> int | None:
    exc = _root_exception(exc)
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def safe_exception_summary(exc: BaseException) -> str:
    """Return a metadata-safe error label with no URL/body/header text."""

    root = _root_exception(exc)
    name = type(root).__name__
    status = _status_code(root)
    return f"{name} (HTTP {status})" if status is not None else name


@dataclass
class SlidingWindowLimiter:
    """Thread-safe rolling one-minute request budget."""

    requests_per_minute: int
    jitter_min_sec: float
    jitter_max_sec: float
    monotonic: Callable[[], float] = time.monotonic
    sleeper: Callable[[float], None] = time.sleep
    rng: random.Random = field(default_factory=random.Random)
    window_sec: float = 60.0
    _requests: deque[float] = field(default_factory=deque, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def acquire(self) -> None:
        # Jitter happens before every outbound request, including retries.
        delay = self.rng.uniform(self.jitter_min_sec, self.jitter_max_sec)
        if delay > 0:
            self.sleeper(delay)

        while True:
            with self._lock:
                now = self.monotonic()
                cutoff = now - self.window_sec
                while self._requests and self._requests[0] <= cutoff:
                    self._requests.popleft()
                if len(self._requests) < self.requests_per_minute:
                    self._requests.append(now)
                    return
                wait_for = max(
                    0.001, self.window_sec - (now - self._requests[0]) + 0.001
                )
            self.sleeper(wait_for)


@dataclass
class SourceState:
    name: str
    limiter: SlidingWindowLimiter
    cooldown_min_sec: float
    cooldown_max_sec: float
    recover_after_sec: float
    retry_after_max_sec: float
    monotonic: Callable[[], float] = time.monotonic
    rng: random.Random = field(default_factory=random.Random)
    calls: int = 0
    successes: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    disabled_reason: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self.disabled_reason is None

    def ready_in(self) -> float:
        with self._lock:
            if self.disabled_reason is not None:
                return float("inf")
            return max(0.0, self.cooldown_until - self.monotonic())

    def before_request(self) -> None:
        with self._lock:
            if self.disabled_reason is not None:
                raise SourceDisabled(f"{self.name}: {self.disabled_reason}")
            wait_for = max(0.0, self.cooldown_until - self.monotonic())
        if wait_for > 0:
            raise SourceDisabled(
                f"{self.name}: cooldown còn {wait_for:.1f} giây"
            )
        self.limiter.acquire()
        with self._lock:
            self.calls += 1

    def mark_success(self) -> None:
        with self._lock:
            self.successes += 1
            self.consecutive_failures = 0
            self.cooldown_until = 0.0

    def mark_failure(self, exc: BaseException) -> None:
        status = _status_code(exc)
        retry_after = _retry_after_seconds(exc)
        with self._lock:
            self.failures += 1
            self.consecutive_failures += 1
            now = self.monotonic()
            if status in {401, 403}:
                self.disabled_reason = f"HTTP {status}: lỗi xác thực/ủy quyền"
                return

            random_cooldown = self.rng.uniform(
                self.cooldown_min_sec, self.cooldown_max_sec
            )
            cooldown = random_cooldown
            if self.consecutive_failures >= 2:
                cooldown = max(cooldown, self.recover_after_sec)
            if retry_after is not None:
                # Never retry this provider earlier than its Retry-After.
                # ``retry_after_max_sec`` caps how long a worker may block
                # waiting; longer delays quarantine this source while another
                # source handles work.
                cooldown = max(cooldown, retry_after)
            self.cooldown_until = max(self.cooldown_until, now + cooldown)

    def disable(self, reason: str) -> None:
        with self._lock:
            self.disabled_reason = reason

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "source": self.name,
                "calls": self.calls,
                "successes": self.successes,
                "failures": self.failures,
                "consecutive_failures": self.consecutive_failures,
                "ready_in_sec": (
                    None
                    if self.disabled_reason is not None
                    else round(max(0.0, self.cooldown_until - self.monotonic()), 3)
                ),
                "disabled_reason": self.disabled_reason,
                "requests_per_minute": self.limiter.requests_per_minute,
            }


class SourcePool(Generic[T]):
    """Balanced, failover-capable collection of canonical source states."""

    def __init__(
        self,
        config: LiveScanConfig,
        sources: Iterable[str] | None = None,
        *,
        rng: random.Random | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.rng = rng or random.Random(config.random_seed)
        self.monotonic = monotonic
        self.sleeper = sleeper
        self._selection_lock = threading.Lock()

        canonical_names: list[str] = []
        for raw in sources or config.sources:
            name = canonical_source(raw)
            if name not in canonical_names:
                canonical_names.append(name)

        self.states: dict[str, SourceState] = {}
        for name in canonical_names:
            # Request jitter/cooldowns must vary between retries/runs even when
            # symbol order is made reproducible by a daily seed.
            child_rng = random.SystemRandom()
            limiter = SlidingWindowLimiter(
                requests_per_minute=config.effective_limit(name),
                jitter_min_sec=config.jitter_min_sec,
                jitter_max_sec=config.jitter_max_sec,
                monotonic=monotonic,
                sleeper=sleeper,
                rng=child_rng,
            )
            self.states[name] = SourceState(
                name=name,
                limiter=limiter,
                cooldown_min_sec=config.error_cooldown_min_sec,
                cooldown_max_sec=config.error_cooldown_max_sec,
                recover_after_sec=config.recover_after_sec,
                retry_after_max_sec=config.retry_after_max_sec,
                monotonic=monotonic,
                rng=child_rng,
            )

    def disable(self, source: str, reason: str) -> None:
        name = canonical_source(source)
        if name in self.states:
            self.states[name].disable(reason)

    def healthy_sources(self) -> list[str]:
        return [
            name
            for name, state in self.states.items()
            if state.enabled and state.ready_in() != float("inf")
        ]

    def _ordered_candidates(self, preferred: str | None = None) -> list[SourceState]:
        preferred = canonical_source(preferred) if preferred else None
        with self._selection_lock:
            candidates = [state for state in self.states.values() if state.enabled]
            self.rng.shuffle(candidates)
            # Prefer ready and less-used sources; shuffled order breaks ties.
            candidates.sort(
                key=lambda s: (
                    s.ready_in() > 0,
                    0 if preferred and s.name == preferred else 1,
                    s.ready_in(),
                    s.calls,
                )
            )
            return candidates

    def call(
        self,
        operation: Callable[[str], T],
        *,
        preferred: str | None = None,
    ) -> tuple[T, str]:
        """Run once on a balanced source, failing over only after an error."""

        errors: list[str] = []
        attempted_round: set[str] = set()
        permanently_excluded: set[str] = set()
        max_attempts = max(
            self.config.request_attempts, len(self.states)
        )
        attempts_made = 0

        while attempts_made < max_attempts:
            candidates = [
                state
                for state in self._ordered_candidates(preferred)
                if state.name not in permanently_excluded
                and state.name not in attempted_round
                and state.ready_in() <= 0
            ]
            if not candidates:
                eligible = [
                    state
                    for state in self.states.values()
                    if state.enabled and state.name not in permanently_excluded
                ]
                if not eligible:
                    break

                ready = [state for state in eligible if state.ready_in() <= 0]
                if ready and all(
                    state.name in attempted_round for state in ready
                ):
                    # A new retry round is allowed while the total outbound
                    # request count remains below SCAN_REQUEST_ATTEMPTS.
                    attempted_round.clear()
                    continue

                # Do not make every worker sleep through a long circuit-open
                # interval. A short wait is acceptable; a longer one leaves
                # this source quarantined for other calls and fails this symbol.
                finite = [
                    state.ready_in()
                    for state in eligible
                    if state.ready_in() != float("inf")
                ]
                if finite and min(finite) <= self.config.retry_after_max_sec:
                    self.sleeper(max(0.001, min(finite)))
                    attempted_round.clear()
                    continue
                break

            state = candidates[0]
            attempted_round.add(state.name)
            try:
                state.before_request()
                attempts_made += 1
                result = operation(state.name)
            except SourceDisabled as exc:
                errors.append(str(exc))
                continue
            except SourceNeutralError as exc:
                permanently_excluded.add(state.name)
                errors.append(f"{state.name}: {type(exc).__name__}")
                continue
            except Exception as exc:  # noqa: BLE001 - provider exceptions vary
                state.mark_failure(exc)
                status = _status_code(exc)
                suffix = f"HTTP {status}" if status is not None else type(exc).__name__
                errors.append(f"{state.name}: {suffix}")
                LOGGER.warning("Nguồn %s lỗi (%s); chuyển nguồn", state.name, suffix)
                continue
            state.mark_success()
            return result, state.name

        details = "; ".join(errors) if errors else "không có nguồn sẵn sàng"
        raise AllSourcesFailed(details)

    def snapshots(self) -> list[dict[str, object]]:
        return [self.states[name].snapshot() for name in sorted(self.states)]
