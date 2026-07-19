from __future__ import annotations

import pandas as pd

from scanner.v2.dead_cat_bounce import DEAD_CAT_BOUNCE, DEAD_CAT_BOUNCE_INVERTED, DeadCatDetector


def _frame(closes: list[float], highs: dict[int, float] | None = None, lows: dict[int, float] | None = None, symbol: str = "AAA") -> pd.DataFrame:
    highs = highs or {}
    lows = lows or {}
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
                "volume": 100_000 + i * 1_000,
            }
        )
    return pd.DataFrame(rows)


def test_dead_cat_bounce_requires_sharp_drop_then_bounded_recovery_bounce() -> None:
    closes = [100.0, 92.0, 72.0, 73.0, 74.0, 75.0, 76.0, 84.0] + [82.0] * 40
    highs = {0: 100.0, 1: 95.0, 2: 74.0, 7: 85.0}
    lows = {1: 88.0, 2: 70.0, 7: 82.0}

    rows = DeadCatDetector(DEAD_CAT_BOUNCE).scan(_frame(closes, highs, lows))

    assert len(rows) == 1
    row = rows[0]
    assert row["breakout_direction"] == "down"
    assert row["event_decline_pct"] >= 15.0
    assert 15.0 <= row["bounce_pct"] <= 35.0
    assert row["target_price"] == row["event_low_price"]
    assert row["dead_cat_phase"] == "decline_bounce_postbounce"


def test_dead_cat_bounce_rejects_too_small_recovery_bounce() -> None:
    closes = [100.0, 92.0, 72.0, 73.0, 74.0, 75.0, 76.0, 78.0] + [78.0] * 40
    highs = {0: 100.0, 1: 95.0, 2: 74.0, 7: 79.0}
    lows = {1: 88.0, 2: 70.0, 7: 76.0}

    rows = DeadCatDetector(DEAD_CAT_BOUNCE).scan(_frame(closes, highs, lows))

    assert rows == []


def test_inverted_dead_cat_bounce_requires_sharp_rise_and_day2_push() -> None:
    closes = [100.0, 110.0, 112.0] + [108.0] * 40
    highs = {0: 101.0, 1: 111.0, 2: 113.0}
    lows = {0: 99.0, 1: 108.0, 2: 109.0}

    rows = DeadCatDetector(DEAD_CAT_BOUNCE_INVERTED).scan(_frame(closes, highs, lows))

    assert len(rows) == 1
    row = rows[0]
    assert row["breakout_direction"] == "down"
    assert 5.0 <= row["event_rise_pct"] <= 20.0
    assert row["day2_push"] is True
    assert row["target_price"] == row["reference_close"]
    assert row["dead_cat_phase"] == "rise_day2_giveback"


def test_inverted_dead_cat_bounce_rejects_missing_day2_push() -> None:
    closes = [100.0, 110.0, 106.0] + [105.0] * 40
    highs = {0: 101.0, 1: 111.0, 2: 110.5}
    lows = {0: 99.0, 1: 108.0, 2: 104.0}

    rows = DeadCatDetector(DEAD_CAT_BOUNCE_INVERTED).scan(_frame(closes, highs, lows))

    assert rows == []
