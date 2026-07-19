from __future__ import annotations

import pandas as pd

from scanner.pivot_detector import Pivot, PivotType
from scanner.v2.symmetrical_triangles import (
    SymmetricalTriangleConfig,
    SymmetricalTriangleDetector,
    _evaluate_detection,
)


def _series(*, direction: str = "up") -> pd.DataFrame:
    rows = []
    for idx in range(55):
        close = 104.0
        high = 106.0
        low = 98.0
        if idx == 5:
            high = 120.0
            low = 108.0
            close = 116.0
        elif idx == 12:
            high = 103.0
            low = 96.0
            close = 99.0
        elif idx == 28:
            high = 110.0
            low = 103.0
            close = 107.0
        elif idx == 34:
            high = 106.0
            low = 101.5
            close = 103.0
        elif idx == 38:
            if direction == "up":
                high = 116.0
                low = 110.0
                close = 114.0
            else:
                high = 99.0
                low = 91.0
                close = 93.0
        elif 39 <= idx <= 41:
            if direction == "up":
                high = 121.0
                low = 111.0
                close = 118.0
            else:
                high = 96.0
                low = 84.0
                close = 88.0
        elif idx == 42:
            if direction == "up":
                high = 142.0
                low = 120.0
                close = 132.0
            else:
                high = 94.0
                low = 65.0
                close = 78.0
        rows.append(
            {
                "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=idx),
                "symbol": "TST",
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": 100000,
                "volume_ratio": 1.3 if idx == 38 else 1.0,
            }
        )
    return pd.DataFrame(rows)


def _pivots(df: pd.DataFrame) -> list[Pivot]:
    return [
        Pivot(idx=5, date=df.loc[5, "date"], price=120.0, type=PivotType.HIGH, strength=3, classification="minor"),
        Pivot(idx=12, date=df.loc[12, "date"], price=96.0, type=PivotType.LOW, strength=3, classification="minor"),
        Pivot(idx=28, date=df.loc[28, "date"], price=110.0, type=PivotType.HIGH, strength=3, classification="minor"),
        Pivot(idx=34, date=df.loc[34, "date"], price=101.5, type=PivotType.LOW, strength=3, classification="minor"),
    ]


def test_symmetrical_triangle_up_breakout_geometry_and_outcomes() -> None:
    df = _series(direction="up")
    detector = SymmetricalTriangleDetector(
        SymmetricalTriangleConfig(width_min_bars=10, width_max_bars=45, breakout_search_bars=10)
    )

    detection = detector.scan_window(df, _pivots(df))

    assert detection is not None
    assert detection["breakout_direction"] == "up"
    assert detection["target_price"] > detection["breakout_price"]
    assert detection["high_fall_pct"] >= 8.0
    assert detection["low_rise_pct"] >= 5.0
    assert detection["triangle_resistance"] > detection["triangle_support"]
    assert "triangle_crossing_count" in detection
    assert "triangle_white_space_score" in detection
    assert "volume_trend_slope_pct_per_bar" in detection
    assert "apex_progress_pct" in detection
    assert "yearly_range_position_pct" in detection

    outcomes = _evaluate_detection(df, detection, lookahead=12)
    assert outcomes["target_hit"] is True
    assert outcomes["failure_5pct"] is False
    assert outcomes["target_first_before_adverse_5pct"] is True
    assert "throwback_pullback_30d" in outcomes


def test_symmetrical_triangle_down_breakout_uses_signed_downside_outcomes() -> None:
    df = _series(direction="down")
    detector = SymmetricalTriangleDetector(
        SymmetricalTriangleConfig(width_min_bars=10, width_max_bars=45, breakout_search_bars=10)
    )

    detection = detector.scan_window(df, _pivots(df))

    assert detection is not None
    assert detection["breakout_direction"] == "down"
    assert detection["target_price"] < detection["breakout_price"]

    outcomes = _evaluate_detection(df, detection, lookahead=12)
    assert outcomes["target_hit"] is True
    assert outcomes["failure_5pct"] is False
    assert outcomes["target_first_before_adverse_5pct"] is True
