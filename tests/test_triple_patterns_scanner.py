from __future__ import annotations

import pandas as pd

from scanner.pivot_detector import Pivot, PivotType
from scanner.run_chapter_tradable_layer import build_strategy_grid
from scanner.v2.triple_patterns import TRIPLE_BOTTOMS, TRIPLE_TOPS, TriplePatternsConfig, TriplePatternsDetector


def _frame(closes: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=len(closes), freq="B")
    return pd.DataFrame(
        {
            "symbol": "TEST",
            "date": dates,
            "open": closes,
            "high": [x * 1.01 for x in closes],
            "low": [x * 0.99 for x in closes],
            "close": closes,
            "volume": [100_000] * len(closes),
        }
    )


def _pivot(idx: int, price: float, typ: PivotType) -> Pivot:
    return Pivot(idx=idx, date=pd.Timestamp("2024-01-01") + pd.Timedelta(days=idx), price=price, type=typ, strength=5, classification="intermediate")


def _config() -> TriplePatternsConfig:
    return TriplePatternsConfig(
        width_min_bars=10,
        width_max_bars=80,
        height_min_pct=4.0,
        height_max_pct=80.0,
        prior_trend_min_pct=5.0,
        prior_trend_lookback_bars=20,
        confirmation_search_bars=8,
        extreme_similarity_tol_pct=4.0,
        min_inner_swing_pct=4.0,
    )


def test_triple_tops_accepts_near_level_tops_and_down_breakout() -> None:
    closes = [90 + i * 1.0 for i in range(30)] + [120] * 60
    for idx in range(67, len(closes)):
        closes[idx] = 108
    df = _frame(closes)
    pivots = [
        _pivot(30, 122, PivotType.HIGH),
        _pivot(38, 112, PivotType.LOW),
        _pivot(46, 120, PivotType.HIGH),
        _pivot(54, 111, PivotType.LOW),
        _pivot(62, 121, PivotType.HIGH),
    ]

    result = TriplePatternsDetector(TRIPLE_TOPS, _config()).scan_window(df, pivots)

    assert result is not None
    assert result["breakout_direction"] == "down"
    assert result["target_price"] < result["breakout_price"]
    assert result["extreme_spread_pct"] <= 4.0


def test_triple_tops_rejects_tops_that_drift_too_far() -> None:
    closes = [90 + i * 1.0 for i in range(30)] + [120] * 60
    df = _frame(closes)
    pivots = [
        _pivot(30, 122, PivotType.HIGH),
        _pivot(38, 112, PivotType.LOW),
        _pivot(46, 120, PivotType.HIGH),
        _pivot(54, 111, PivotType.LOW),
        _pivot(62, 112, PivotType.HIGH),
    ]

    result = TriplePatternsDetector(TRIPLE_TOPS, _config()).scan_window(df, pivots)

    assert result is None


def test_triple_bottoms_accepts_near_level_bottoms_and_up_breakout() -> None:
    closes = [140 - i * 1.0 for i in range(30)] + [110] * 60
    for idx in range(67, len(closes)):
        closes[idx] = 125
    df = _frame(closes)
    pivots = [
        _pivot(30, 100, PivotType.LOW),
        _pivot(38, 118, PivotType.HIGH),
        _pivot(46, 102, PivotType.LOW),
        _pivot(54, 119, PivotType.HIGH),
        _pivot(62, 101, PivotType.LOW),
    ]

    result = TriplePatternsDetector(TRIPLE_BOTTOMS, _config()).scan_window(df, pivots)

    assert result is not None
    assert result["breakout_direction"] == "up"
    assert result["target_price"] > result["breakout_price"]
    assert result["extreme_spread_pct"] <= 4.0


def test_triple_bottoms_rejects_bottoms_that_drift_too_far() -> None:
    closes = [140 - i * 1.0 for i in range(30)] + [110] * 60
    df = _frame(closes)
    pivots = [
        _pivot(30, 100, PivotType.LOW),
        _pivot(38, 118, PivotType.HIGH),
        _pivot(46, 102, PivotType.LOW),
        _pivot(54, 119, PivotType.HIGH),
        _pivot(62, 109, PivotType.LOW),
    ]

    result = TriplePatternsDetector(TRIPLE_BOTTOMS, _config()).scan_window(df, pivots)

    assert result is None


def test_triple_bottoms_tradable_grid_includes_micro_target_ceiling_branch() -> None:
    configs = build_strategy_grid("triple_bottoms")

    assert any(
        config.target_multiple == 0.25
        and config.stop_loss_pct == 28.0
        and config.max_holding_days in {90, 120}
        and config.entry_delay_bars == 2
        and config.allowed_liquidity_buckets == ("mid", "high")
        for config in configs
    )
