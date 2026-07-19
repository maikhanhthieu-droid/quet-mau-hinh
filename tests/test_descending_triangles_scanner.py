from __future__ import annotations

import pandas as pd
import pytest

from scanner.pivot_detector import Pivot, PivotType
from scanner.v2.descending_triangles import (
    DescendingTriangleConfig,
    DescendingTriangleDetector,
    _evaluate_detection,
)


def _series() -> pd.DataFrame:
    rows = []
    for idx in range(45):
        close = 106.0
        high = 108.0
        low = 102.0
        if idx == 5:
            high = 120.0
            close = 116.0
        elif idx == 12:
            low = 100.0
            close = 102.0
        elif idx == 25:
            high = 110.0
            close = 106.0
        elif idx == 28:
            low = 100.4
            close = 101.0
        elif idx == 32:
            high = 99.5
            low = 97.8
            close = 98.5
        elif idx == 35:
            high = 91.0
            low = 78.0
            close = 80.0
        elif 33 <= idx <= 36:
            high = 100.0
            low = 92.0
            close = 94.0
        rows.append(
            {
                "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=idx),
                "symbol": "TST",
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": 100000,
                "volume_ratio": 1.3 if idx == 32 else 1.0,
            }
        )
    return pd.DataFrame(rows)


def test_descending_triangle_geometry_and_downside_outcomes() -> None:
    df = _series()
    pivots = [
        Pivot(idx=5, date=df.loc[5, "date"], price=120.0, type=PivotType.HIGH, strength=3, classification="minor"),
        Pivot(idx=12, date=df.loc[12, "date"], price=100.0, type=PivotType.LOW, strength=3, classification="minor"),
        Pivot(idx=25, date=df.loc[25, "date"], price=110.0, type=PivotType.HIGH, strength=3, classification="minor"),
        Pivot(idx=28, date=df.loc[28, "date"], price=100.4, type=PivotType.LOW, strength=3, classification="minor"),
    ]
    detector = DescendingTriangleDetector(
        DescendingTriangleConfig(width_min_bars=10, width_max_bars=40, breakout_search_bars=10)
    )

    detection = detector.scan_window(df, pivots)

    assert detection is not None
    assert detection["breakout_direction"] == "down"
    assert detection["target_price"] < detection["breakout_price"]
    assert detection["target_price"] == pytest.approx(
        detection["triangle_support"] - detection["triangle_height_abs"],
        abs=1e-3,
    )
    assert detection["low_spread_pct"] <= 1.0
    assert detection["high_fall_pct"] >= 8.0
    assert detection["triangle_support"] > detection["target_price"]
    assert detection["triangle_resistance"] > detection["triangle_support"]
    assert detection["formation_start_idx"] == 5
    assert detection["formation_end_idx"] == 28
    assert detection["breakout_idx"] == 32
    assert "triangle_crossing_count" in detection
    assert "triangle_white_space_score" in detection
    assert "volume_trend_slope_pct_per_bar" in detection
    assert "apex_progress_pct" in detection
    assert "yearly_range_position_pct" in detection

    outcomes = _evaluate_detection(df, detection, lookahead=10)
    assert outcomes["target_hit"] is True
    assert outcomes["failure_5pct"] is False
    assert outcomes["target_first_before_adverse_5pct"] is True
    assert outcomes["mfe_pct"] > outcomes["mae_pct"]
    assert "throwback_pullback_30d" in outcomes
