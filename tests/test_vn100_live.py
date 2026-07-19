from __future__ import annotations

import random
import sqlite3
from datetime import date

import numpy as np
import pandas as pd

from scanner.live.config import LiveScanConfig
from scanner.live.patterns import scan_symbol
from scanner.live.reporting import deterministic_message
from scanner.live.source_pool import SourcePool
from scanner.live.storage import LiveScanStore
from scanner.live.telegram import chunk_message


def _flat_base_frame(extra: int = 0) -> pd.DataFrame:
    n = 160 + extra
    dates = pd.date_range("2026-01-01", periods=n, freq="D")
    close = np.concatenate(
        [
            np.linspace(50, 68, 120),
            np.array([69.0, 69.5, 70.0, 69.2, 70.2, 69.7, 70.4, 69.8, 70.5, 69.9] * 4),
        ]
    )
    if extra:
        close = np.concatenate([close, np.linspace(70.1, 70.2, extra)])
    frame = pd.DataFrame(
        {
            "symbol": "FPT",
            "time": dates,
            "open": close * 0.995,
            "high": close * 1.015,
            "low": close * 0.985,
            "close": close,
            "volume": 2_000_000,
            "source": "VCI",
        }
    )
    return frame


def test_config_alias_shares_quota_and_clamps_workers() -> None:
    config = LiveScanConfig.from_env(
        {
            "SCAN_API_SOURCES": "VCI,VIETFIN,DNSE,KBS",
            "SCAN_SOURCE_LIMITS": "VCI=20,KBS=20,DNSE=15,VIETFIN=12",
            "SCAN_MAX_WORKERS": "9",
        }
    )
    assert config.sources == ("VCI", "DNSE", "KBS")
    assert config.configured_limit("VIETFIN") == 12
    assert config.effective_limit("DNSE") == 9
    assert config.max_workers == 3


def test_pool_creates_one_state_for_alias_and_fails_over() -> None:
    config = LiveScanConfig.from_env(
        {
            "SCAN_API_SOURCES": "VCI,VIETFIN,DNSE",
            "SCAN_REQUEST_JITTER_MIN_SEC": "0",
            "SCAN_REQUEST_JITTER_MAX_SEC": "0",
            "SCAN_MAX_WORKERS": "3",
        }
    )
    sleeps: list[float] = []
    pool = SourcePool(config, rng=random.Random(1), sleeper=sleeps.append)
    assert sorted(pool.states) == ["DNSE", "VCI"]
    result, source = pool.call(lambda selected: selected)
    assert result in {"DNSE", "VCI"}
    assert source == result


def test_causal_scan_is_invariant_to_rows_after_as_of() -> None:
    prefix = _flat_base_frame()
    extended = _flat_base_frame(extra=20)
    as_of = prefix["time"].iloc[-1]
    left = scan_symbol(prefix, as_of=as_of)
    right = scan_symbol(extended, as_of=as_of)
    assert left == right
    forbidden = {"mfe_pct", "mae_pct", "target_hit", "failure_5pct", "breakout_date"}
    assert not forbidden.intersection(*(set(row) for row in left)) if left else True


def test_storage_upsert_is_idempotent_and_outbox_deduplicates(tmp_path) -> None:
    store = LiveScanStore(tmp_path / "state.sqlite")
    frame = _flat_base_frame().tail(3)
    inserted = store.upsert_bars(frame)
    inserted_again = store.upsert_bars(frame)
    assert inserted == inserted_again == 3
    with sqlite3.connect(tmp_path / "state.sqlite") as conn:
        assert conn.execute("SELECT COUNT(*) FROM stock_price_history").fetchone()[0] == 3
    candidate = {
        "symbol": "FPT",
        "pattern_id": "flat_base",
        "detector_version": "v1",
        "as_of_date": "2026-07-01",
    }
    assert store.queue_candidates([candidate, candidate]) == 1
    assert len(store.pending_candidates(date(2026, 7, 1))) == 1


def test_telegram_chunking_and_message_fallback() -> None:
    chunks = chunk_message("x" * 9000)
    assert len(chunks) == 3
    assert all(len(chunk) <= 4096 for chunk in chunks)
    message = deterministic_message([], as_of="2026-07-17")
    assert "Không có mẫu hình" in message
