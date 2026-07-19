from __future__ import annotations

import pandas as pd

from scanner.pivot_detector import Pivot, PivotType
from scanner.v2.three_peaks_valleys import (
    THREE_FALLING_PEAKS,
    THREE_RISING_VALLEYS,
    ThreePeaksValleysConfig,
    ThreePeaksValleysDetector,
)
from scanner.run_chapter_tradable_layer import select_strategy_for_pattern


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


def test_three_falling_peaks_requires_lower_successive_peaks() -> None:
    closes = [100 + i * 0.5 for i in range(50)] + [130] * 80
    for idx in range(112, len(closes)):
        closes[idx] = 92
    df = _frame(closes)
    pivots = [
        _pivot(50, 130, PivotType.HIGH),
        _pivot(62, 108, PivotType.LOW),
        _pivot(78, 123, PivotType.HIGH),
        _pivot(94, 106, PivotType.LOW),
        _pivot(110, 116, PivotType.HIGH),
    ]
    result = ThreePeaksValleysDetector(
        THREE_FALLING_PEAKS,
        ThreePeaksValleysConfig(prior_trend_min_pct=5, confirmation_search_bars=10),
    ).scan_window(df, pivots)
    assert result is not None
    assert result["breakout_direction"] == "down"
    assert result["target_price"] < result["breakout_price"]


def test_three_falling_peaks_rejects_higher_third_peak() -> None:
    closes = [100 + i * 0.5 for i in range(50)] + [130] * 80
    df = _frame(closes)
    pivots = [
        _pivot(50, 130, PivotType.HIGH),
        _pivot(62, 108, PivotType.LOW),
        _pivot(78, 123, PivotType.HIGH),
        _pivot(94, 106, PivotType.LOW),
        _pivot(110, 126, PivotType.HIGH),
    ]
    result = ThreePeaksValleysDetector(
        THREE_FALLING_PEAKS,
        ThreePeaksValleysConfig(prior_trend_min_pct=5, confirmation_search_bars=10),
    ).scan_window(df, pivots)
    assert result is None


def test_three_rising_valleys_requires_higher_successive_valleys() -> None:
    closes = [140 - i * 0.5 for i in range(50)] + [110] * 90
    for idx in range(112, len(closes)):
        closes[idx] = 132
    df = _frame(closes)
    pivots = [
        _pivot(50, 100, PivotType.LOW),
        _pivot(62, 122, PivotType.HIGH),
        _pivot(78, 106, PivotType.LOW),
        _pivot(94, 124, PivotType.HIGH),
        _pivot(110, 112, PivotType.LOW),
    ]
    result = ThreePeaksValleysDetector(
        THREE_RISING_VALLEYS,
        ThreePeaksValleysConfig(prior_trend_min_pct=5, confirmation_search_bars=10),
    ).scan_window(df, pivots)
    assert result is not None
    assert result["breakout_direction"] == "up"
    assert result["target_price"] > result["breakout_price"]


def test_three_rising_valleys_rejects_lower_third_valley() -> None:
    closes = [140 - i * 0.5 for i in range(50)] + [110] * 90
    df = _frame(closes)
    pivots = [
        _pivot(50, 100, PivotType.LOW),
        _pivot(62, 122, PivotType.HIGH),
        _pivot(78, 106, PivotType.LOW),
        _pivot(94, 124, PivotType.HIGH),
        _pivot(110, 103, PivotType.LOW),
    ]
    result = ThreePeaksValleysDetector(
        THREE_RISING_VALLEYS,
        ThreePeaksValleysConfig(prior_trend_min_pct=5, confirmation_search_bars=10),
    ).scan_window(df, pivots)
    assert result is None


def test_three_rising_valleys_tradable_selector_prefers_source_aligned_branch() -> None:
    preferred = {
        "strategy_id": "three_rising_valleys__t10_s14_h20_d1_q65_liqmh_threevalleys",
        "validation_trades": 20,
        "holdout_trades": 20,
        "validation_total_return_pct": 5.0,
        "validation_max_drawdown_pct": -3.0,
        "median_adtv_participation_pct": 1.0,
    }
    generic_friendly = {
        "strategy_id": "three_rising_valleys__t05_s14_h60_d1_q72_liqmh_threevalleys",
        "validation_trades": 40,
        "holdout_trades": 40,
        "validation_total_return_pct": 12.0,
        "validation_max_drawdown_pct": -2.0,
        "median_adtv_participation_pct": 1.0,
    }

    selected = select_strategy_for_pattern(THREE_RISING_VALLEYS, [generic_friendly, preferred])

    assert selected["status"] == "selected_tradable_setup"
    assert selected["selected_strategy_id"] == preferred["strategy_id"]
    assert "source_aligned_three_rising_valleys_branch" in selected["selection_basis"]
