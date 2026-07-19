from __future__ import annotations

import pandas as pd

from scanner.pivot_detector import Pivot, PivotType
from scanner.v2.diamonds import DIAMOND_BOTTOMS, DIAMOND_TOPS, DiamondConfig, DiamondDetector


def _frame(closes: list[float], highs: dict[int, float], lows: dict[int, float], symbol: str = "AAA") -> pd.DataFrame:
    rows = []
    for i, close in enumerate(closes):
        rows.append(
            {
                "symbol": symbol,
                "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=i),
                "open": close,
                "high": highs.get(i, close * 1.01),
                "low": lows.get(i, close * 0.99),
                "close": close,
                "volume": 100_000 - i * 500,
            }
        )
    return pd.DataFrame(rows)


def _pivot(idx: int, price: float, pivot_type: PivotType) -> Pivot:
    return Pivot(idx=idx, date=pd.Timestamp("2024-01-01") + pd.Timedelta(days=idx), price=price, type=pivot_type, strength=5, classification="minor")


def _config() -> DiamondConfig:
    return DiamondConfig(
        min_width_bars=12,
        max_width_bars=40,
        min_height_pct=5.0,
        max_height_pct=80.0,
        prior_trend_lookback_bars=8,
        breakout_search_bars=8,
    )


def test_diamond_bottom_requires_downtrend_widening_then_narrowing_and_close_breakout() -> None:
    closes = [20, 19, 18, 17, 16, 15, 14, 13.5, 13.2, 13.0] + [13.5] * 21 + [16.8, 17.2, 17.5]
    highs = {10: 14.0, 18: 18.0, 24: 16.0, 30: 14.5, 31: 16.9}
    lows = {13: 12.0, 21: 9.0, 27: 11.0}
    pivots = [
        _pivot(10, 14.0, PivotType.HIGH),
        _pivot(13, 12.0, PivotType.LOW),
        _pivot(18, 18.0, PivotType.HIGH),
        _pivot(21, 9.0, PivotType.LOW),
        _pivot(24, 16.0, PivotType.HIGH),
        _pivot(27, 11.0, PivotType.LOW),
        _pivot(30, 14.5, PivotType.HIGH),
    ]

    row = DiamondDetector(DIAMOND_BOTTOMS, _config()).scan_window(_frame(closes, highs, lows), pivots)

    assert row is not None
    assert row["diamond_shape"] == "widening_then_narrowing"
    assert row["breakout_direction"] == "up"
    assert row["prior_trend_pct"] < 0
    assert row["expansion_ratio"] > 1.0
    assert row["contraction_ratio"] < 1.0


def test_diamond_top_requires_uptrend_but_still_allows_down_breakout() -> None:
    closes = [10, 10.5, 11, 11.5, 12, 12.5, 13, 13.4, 13.8, 14.0] + [14.2] * 21 + [10.8, 10.2, 10.0]
    highs = {10: 15.0, 18: 18.0, 24: 16.5, 30: 15.0}
    lows = {13: 13.0, 21: 11.0, 27: 13.0, 31: 10.7}
    pivots = [
        _pivot(10, 15.0, PivotType.HIGH),
        _pivot(13, 13.0, PivotType.LOW),
        _pivot(18, 18.0, PivotType.HIGH),
        _pivot(21, 11.0, PivotType.LOW),
        _pivot(24, 16.5, PivotType.HIGH),
        _pivot(27, 13.0, PivotType.LOW),
        _pivot(30, 15.0, PivotType.HIGH),
    ]

    row = DiamondDetector(DIAMOND_TOPS, _config()).scan_window(_frame(closes, highs, lows), pivots)

    assert row is not None
    assert row["diamond_shape"] == "widening_then_narrowing"
    assert row["breakout_direction"] == "down"
    assert row["prior_trend_pct"] > 0
    assert row["target_price"] < row["breakout_price"]
