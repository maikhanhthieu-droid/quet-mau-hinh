from __future__ import annotations

import pandas as pd
import pytest

from scanner.pivot_detector import Pivot, PivotType
from scanner.v2.pennants import PennantDetector, PennantDetectorConfig


def _base_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for idx in range(50):
        close = 110.0
        rows.append(
            {
                "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=idx),
                "symbol": "TST",
                "open": close,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 100000 - idx * 200,
                "volume_ratio": 1.0,
            }
        )
    return rows


def _pivot(df: pd.DataFrame, idx: int, price: float, kind: PivotType) -> Pivot:
    return Pivot(idx=idx, date=df.loc[idx, "date"], price=price, type=kind, strength=3, classification="minor")


def _bull_df() -> pd.DataFrame:
    rows = _base_rows()
    rows[2].update({"low": 90.0, "close": 92.0, "high": 94.0})
    rows[10].update({"high": 120.0, "low": 115.0, "close": 118.0})
    rows[13].update({"high": 117.0, "low": 112.0, "close": 113.0})
    rows[17].update({"high": 118.0, "low": 114.0, "close": 117.0})
    rows[20].update({"high": 116.5, "low": 114.0, "close": 115.0})
    rows[22].update({"high": 121.0, "low": 117.5, "close": 119.0, "volume_ratio": 1.4})
    return pd.DataFrame(rows)


def _bear_df() -> pd.DataFrame:
    rows = _base_rows()
    rows[2].update({"high": 110.0, "low": 106.0, "close": 108.0})
    rows[10].update({"high": 84.0, "low": 80.0, "close": 82.0})
    rows[13].update({"high": 88.0, "low": 83.0, "close": 87.0})
    rows[17].update({"high": 85.0, "low": 82.0, "close": 83.0})
    rows[20].update({"high": 86.0, "low": 83.5, "close": 85.0})
    rows[22].update({"high": 83.0, "low": 79.0, "close": 81.0, "volume_ratio": 1.4})
    return pd.DataFrame(rows)


def test_bull_pennant_requires_converging_body_prior_pole_and_up_breakout() -> None:
    df = _bull_df()
    pivots = [
        _pivot(df, 10, 120.0, PivotType.HIGH),
        _pivot(df, 13, 112.0, PivotType.LOW),
        _pivot(df, 17, 118.0, PivotType.HIGH),
        _pivot(df, 20, 114.0, PivotType.LOW),
    ]
    detector = PennantDetector(PennantDetectorConfig(breakout_search_bars=5))

    detection = detector.scan_window(df, pivots)

    assert detection is not None
    assert detection["variant"] == "bull_pennant"
    assert detection["breakout_direction"] == "up"
    assert detection["compression_ratio"] < 1.0
    assert detection["pennant_to_pole_pct"] < 65.0
    assert detection["target_price"] > detection["breakout_price"]
    assert detection["volume_confirmed"] is True


def test_bear_pennant_requires_converging_body_prior_pole_and_down_breakout() -> None:
    df = _bear_df()
    pivots = [
        _pivot(df, 10, 80.0, PivotType.LOW),
        _pivot(df, 13, 88.0, PivotType.HIGH),
        _pivot(df, 17, 82.0, PivotType.LOW),
        _pivot(df, 20, 86.0, PivotType.HIGH),
    ]
    detector = PennantDetector(PennantDetectorConfig(breakout_search_bars=5))

    detection = detector.scan_window(df, pivots)

    assert detection is not None
    assert detection["variant"] == "bear_pennant"
    assert detection["breakout_direction"] == "down"
    assert detection["compression_ratio"] < 1.0
    assert detection["pennant_to_pole_pct"] < 65.0
    assert detection["target_price"] < detection["breakout_price"]
    assert detection["volume_confirmed"] is True


def test_pennant_rejects_too_long_triangle_like_body() -> None:
    df = _bull_df()
    pivots = [
        _pivot(df, 5, 120.0, PivotType.HIGH),
        _pivot(df, 15, 112.0, PivotType.LOW),
        _pivot(df, 25, 118.0, PivotType.HIGH),
        _pivot(df, 35, 114.0, PivotType.LOW),
    ]
    detector = PennantDetector(PennantDetectorConfig(width_max_bars=15))

    assert detector.scan_window(df, pivots) is None


def test_pennant_rejects_parallel_flag_like_body() -> None:
    df = _bull_df()
    df.loc[20, "low"] = 110.0
    pivots = [
        _pivot(df, 10, 120.0, PivotType.HIGH),
        _pivot(df, 13, 112.0, PivotType.LOW),
        _pivot(df, 17, 118.0, PivotType.HIGH),
        _pivot(df, 20, 110.0, PivotType.LOW),
    ]
    detector = PennantDetector(PennantDetectorConfig(breakout_search_bars=5))

    assert detector.scan_window(df, pivots) is None
