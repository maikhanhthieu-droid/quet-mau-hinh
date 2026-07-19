from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from scanner.live.config import LiveScanConfig
from scanner.live.contracts import validate_candidates
from scanner.live.patterns import scan_symbol


def _flat_base_frame() -> pd.DataFrame:
    dates = pd.bdate_range("2025-10-01", periods=180)
    trend = np.linspace(40.0, 58.5, 130)
    base = 59.0 + np.sin(np.linspace(0, 7 * np.pi, 50)) * 0.8
    close = np.concatenate([trend, base])
    volume = np.concatenate(
        [
            np.full(150, 1_200_000.0),
            np.full(25, 900_000.0),
            np.full(5, 450_000.0),
        ]
    )
    return pd.DataFrame(
        {
            "symbol": "FPT",
            "time": dates,
            "open": close - 0.15,
            "high": close + 0.9,
            "low": close - 0.9,
            "close": close,
            "volume": volume,
            "source": "KBS",
        }
    )


def test_future_rows_cannot_change_as_of_candidates() -> None:
    frame = _flat_base_frame()
    as_of = frame.iloc[-1]["time"].date()
    config = LiveScanConfig.from_env(
        {
            "SCAN_MIN_AVERAGE_VALUE_VND": "1000000000",
            "SCAN_MAX_DISTANCE_TO_BREAKOUT_PCT": "8",
        }
    )
    original = [
        candidate.to_dict()
        for candidate in scan_symbol(frame, as_of=as_of, config=config)
    ]
    assert original
    assert any(row["pattern_id"] == "flat_base" for row in original)

    future_dates = pd.bdate_range(frame.iloc[-1]["time"] + pd.Timedelta(days=1), periods=20)
    future = pd.DataFrame(
        {
            "symbol": "FPT",
            "time": future_dates,
            "open": np.linspace(60, 30, 20),
            "high": np.linspace(61, 31, 20),
            "low": np.linspace(59, 29, 20),
            "close": np.linspace(60, 30, 20),
            "volume": 10_000_000,
            "source": "VCI",
        }
    )
    with_future = [
        candidate.to_dict()
        for candidate in scan_symbol(
            pd.concat([frame, future], ignore_index=True),
            as_of=as_of,
            config=config,
        )
    ]

    assert with_future == original
    validate_candidates(original)
    forbidden = {
        "mfe_pct",
        "mae_pct",
        "target_hit",
        "failure_5pct",
        "followthrough_score",
        "confirmation_date",
    }
    assert all(not (forbidden & set(row)) for row in original)
    assert all(row["known_data_only"] is True for row in original)
