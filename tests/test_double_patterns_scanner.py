from __future__ import annotations

import pandas as pd

from scanner.v2.double_patterns import DoublePatternConfig, scan_symbol


def _frame(symbol: str, closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": symbol,
            "date": pd.date_range("2024-01-01", periods=len(closes), freq="B"),
            "open": closes,
            "high": [x * 1.01 for x in closes],
            "low": [x * 0.99 for x in closes],
            "close": closes,
            "volume": [1000000] * len(closes),
        }
    )


def test_double_bottom_scanner_detects_neckline_breakout() -> None:
    closes = [120 - i * 0.4 for i in range(45)]
    closes += [100, 102, 104, 108, 114, 122, 116, 111, 106, 101, 103, 106, 111, 119, 126, 130]
    closes += [132 + i * 0.3 for i in range(130)]
    rows, stats = scan_symbol(
        _frame("AAA", closes),
        family="double_bottoms",
        detector_config=DoublePatternConfig(width_min_bars=8, min_neckline_height_pct=4, min_prior_trend_pct=1).to_dict(),
    )
    assert stats["pivots"] > 0
    assert rows
    row = rows[0]
    assert row["breakout_direction"] == "up"
    assert row["target_price"] > row["breakout_price"]
    assert row["variant"] in {"AA", "AE", "EA", "EE", "unclassified"}


def test_double_top_scanner_detects_neckline_breakdown() -> None:
    closes = [80 + i * 0.4 for i in range(45)]
    closes += [102, 106, 111, 119, 126, 121, 113, 105, 99, 104, 112, 121, 125, 118, 108, 96]
    closes += [94 - i * 0.2 for i in range(130)]
    rows, _ = scan_symbol(
        _frame("BBB", closes),
        family="double_tops",
        detector_config=DoublePatternConfig(width_min_bars=8, min_neckline_height_pct=4, min_prior_trend_pct=1).to_dict(),
    )
    assert rows
    row = rows[0]
    assert row["breakout_direction"] == "down"
    assert row["target_price"] < row["breakout_price"]
