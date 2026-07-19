"""Environment-driven configuration for the nightly VN100 scanner."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


SOURCE_ALIASES: dict[str, str] = {
    # VIETFIN is only a spelling alias.  It deliberately resolves to the same
    # DNSE quota bucket and can never create extra capacity.
    "VIETFIN": "DNSE",
}


class ConfigError(ValueError):
    """Raised when live scanner configuration is unsafe or malformed."""


def canonical_source(value: str) -> str:
    name = str(value).strip().upper()
    if not name:
        raise ConfigError("Tên nguồn dữ liệu không được để trống")
    return SOURCE_ALIASES.get(name, name)


def parse_sources(value: str) -> tuple[str, ...]:
    sources: list[str] = []
    for item in str(value).split(","):
        if not item.strip():
            continue
        source = canonical_source(item)
        if source not in sources:
            sources.append(source)
    if not sources:
        raise ConfigError("SCAN_API_SOURCES phải chứa ít nhất một nguồn")
    return tuple(sources)


def parse_source_limits(value: str) -> dict[str, int]:
    limits: dict[str, int] = {}
    for item in str(value or "").split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ConfigError(f"SCAN_SOURCE_LIMITS sai định dạng: {item!r}")
        raw_source, raw_limit = item.split("=", 1)
        source = canonical_source(raw_source)
        try:
            limit = int(raw_limit.strip())
        except ValueError as exc:
            raise ConfigError(f"Quota của {source} phải là số nguyên") from exc
        if limit <= 0:
            raise ConfigError(f"Quota của {source} phải lớn hơn 0")
        # If both DNSE and its VIETFIN alias are provided, keep the safer cap.
        limits[source] = min(limits.get(source, limit), limit)
    return limits


def _env_int(env: Mapping[str, str], name: str, default: int, *, minimum: int = 0) -> int:
    try:
        value = int(env.get(name, str(default)))
    except ValueError as exc:
        raise ConfigError(f"{name} phải là số nguyên") from exc
    if value < minimum:
        raise ConfigError(f"{name} phải >= {minimum}")
    return value


def _env_float(
    env: Mapping[str, str],
    name: str,
    default: float,
    *,
    minimum: float = 0.0,
    maximum: float | None = None,
) -> float:
    try:
        value = float(env.get(name, str(default)))
    except ValueError as exc:
        raise ConfigError(f"{name} phải là số") from exc
    if value < minimum or (maximum is not None and value > maximum):
        upper = f" và <= {maximum}" if maximum is not None else ""
        raise ConfigError(f"{name} phải >= {minimum}{upper}")
    return value


def _env_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = str(env.get(name, "1" if default else "0")).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} phải là true/false hoặc 1/0")


@dataclass(frozen=True)
class LiveScanConfig:
    """Validated runtime settings.

    Secret fields use ``repr=False`` so an accidental config log cannot expose
    credentials.
    """

    sources: tuple[str, ...] = ("KBS", "VCI")
    requests_per_minute: int = 20
    source_limits: Mapping[str, int] = field(default_factory=dict)
    usage_ratio: float = 0.78
    jitter_min_sec: float = 0.8
    jitter_max_sec: float = 2.4
    error_cooldown_min_sec: float = 45.0
    error_cooldown_max_sec: float = 120.0
    recover_after_sec: float = 300.0
    retry_after_max_sec: float = 300.0
    max_workers: int = 2
    request_attempts: int = 3
    startup_jitter_max_sec: float = 180.0

    database_path: Path = Path("data/vn100_ohlcv.sqlite")
    output_dir: Path = Path("artifacts/live_scan/latest")
    bootstrap_calendar_days: int = 900
    overlap_calendar_days: int = 7
    min_bars: int = 120
    min_average_value_vnd: float = 5_000_000_000.0
    max_distance_to_breakout_pct: float = 6.0
    max_results: int = 20
    min_success_ratio: float = 0.85
    timezone: str = "Asia/Ho_Chi_Minh"
    random_seed: int | None = None

    vnstock_api_key: str = field(default="", repr=False)
    telegram_bot_token: str = field(default="", repr=False)
    telegram_chat_id: str = field(default="", repr=False)
    telegram_disable_notification: bool = False
    gemini_api_key: str = field(default="", repr=False)
    gemini_model: str = "gemini-3.1-flash-lite"
    gemini_enabled: bool = True

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "LiveScanConfig":
        env = os.environ if env is None else env
        sources = parse_sources(env.get("SCAN_API_SOURCES", "KBS,VCI"))
        source_limits = parse_source_limits(
            env.get("SCAN_SOURCE_LIMITS", "VCI=20,KBS=20,DNSE=15")
        )

        jitter_min = _env_float(env, "SCAN_REQUEST_JITTER_MIN_SEC", 0.8)
        jitter_max = _env_float(env, "SCAN_REQUEST_JITTER_MAX_SEC", 2.4)
        cooldown_min = _env_float(env, "SCAN_SOURCE_ERROR_COOLDOWN_MIN_SEC", 45.0)
        cooldown_max = _env_float(env, "SCAN_SOURCE_ERROR_COOLDOWN_MAX_SEC", 120.0)
        if jitter_max < jitter_min:
            raise ConfigError(
                "SCAN_REQUEST_JITTER_MAX_SEC phải >= SCAN_REQUEST_JITTER_MIN_SEC"
            )
        if cooldown_max < cooldown_min:
            raise ConfigError(
                "SCAN_SOURCE_ERROR_COOLDOWN_MAX_SEC phải >= "
                "SCAN_SOURCE_ERROR_COOLDOWN_MIN_SEC"
            )

        requested_workers = _env_int(env, "SCAN_MAX_WORKERS", 2, minimum=1)
        # More workers than independent source buckets adds contention without
        # increasing safe throughput.
        max_workers = min(requested_workers, len(sources))

        raw_seed = str(env.get("SCAN_RANDOM_SEED", "")).strip()
        try:
            random_seed = int(raw_seed) if raw_seed else None
        except ValueError as exc:
            raise ConfigError("SCAN_RANDOM_SEED phải là số nguyên") from exc

        return cls(
            sources=sources,
            requests_per_minute=_env_int(
                env, "SCAN_SOURCE_REQUESTS_PER_MINUTE", 20, minimum=1
            ),
            source_limits=source_limits,
            usage_ratio=_env_float(
                env, "SCAN_SOURCE_USAGE_RATIO", 0.78, minimum=0.05, maximum=1.0
            ),
            jitter_min_sec=jitter_min,
            jitter_max_sec=jitter_max,
            error_cooldown_min_sec=cooldown_min,
            error_cooldown_max_sec=cooldown_max,
            recover_after_sec=_env_float(
                env, "SCAN_SOURCE_RECOVER_AFTER_SEC", 300.0
            ),
            retry_after_max_sec=_env_float(
                env, "SCAN_RETRY_AFTER_MAX_SEC", 300.0
            ),
            max_workers=max_workers,
            request_attempts=_env_int(env, "SCAN_REQUEST_ATTEMPTS", 3, minimum=1),
            startup_jitter_max_sec=_env_float(
                env, "SCAN_STARTUP_JITTER_MAX_SEC", 180.0, minimum=0.0
            ),
            database_path=Path(
                env.get("SCAN_DATABASE_PATH", "data/vn100_ohlcv.sqlite")
            ),
            output_dir=Path(
                env.get("SCAN_OUTPUT_DIR", "artifacts/live_scan/latest")
            ),
            bootstrap_calendar_days=_env_int(
                env, "SCAN_BOOTSTRAP_CALENDAR_DAYS", 900, minimum=180
            ),
            overlap_calendar_days=_env_int(
                env, "SCAN_OVERLAP_CALENDAR_DAYS", 7, minimum=1
            ),
            min_bars=_env_int(env, "SCAN_MIN_BARS", 120, minimum=60),
            min_average_value_vnd=_env_float(
                env, "SCAN_MIN_AVERAGE_VALUE_VND", 5_000_000_000.0
            ),
            max_distance_to_breakout_pct=_env_float(
                env,
                "SCAN_MAX_DISTANCE_TO_BREAKOUT_PCT",
                6.0,
                minimum=0.1,
                maximum=20.0,
            ),
            max_results=_env_int(env, "SCAN_MAX_RESULTS", 20, minimum=1),
            min_success_ratio=_env_float(
                env,
                "SCAN_MIN_SUCCESS_RATIO",
                0.85,
                minimum=0.50,
                maximum=1.0,
            ),
            timezone=env.get("SCAN_TIMEZONE", "Asia/Ho_Chi_Minh"),
            random_seed=random_seed,
            vnstock_api_key=env.get("VNSTOCK_API_KEY", "").strip(),
            telegram_bot_token=env.get("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_chat_id=env.get("TELEGRAM_CHAT_ID", "").strip(),
            telegram_disable_notification=_env_bool(
                env, "TELEGRAM_DISABLE_NOTIFICATION", False
            ),
            gemini_api_key=env.get("GEMINI_API_KEY", "").strip(),
            gemini_model=env.get(
                "GEMINI_MODEL", "gemini-3.1-flash-lite"
            ).strip(),
            gemini_enabled=_env_bool(env, "GEMINI_ENABLED", True),
        )

    def configured_limit(self, source: str) -> int:
        canonical = canonical_source(source)
        return min(
            self.requests_per_minute,
            int(self.source_limits.get(canonical, self.requests_per_minute)),
        )

    def effective_limit(self, source: str) -> int:
        """Safe per-minute budget after applying the usage headroom."""

        return max(1, int(self.configured_limit(source) * self.usage_ratio))

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def gemini_runtime_enabled(self) -> bool:
        return bool(self.gemini_enabled and self.gemini_api_key)
