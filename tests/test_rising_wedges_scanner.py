from __future__ import annotations

import pandas as pd

from scanner.pivot_detector import Pivot, PivotType
from scanner.v2.rising_wedges import RisingWedgeConfig, RisingWedgeDetector, _assign_publication_quality_tiers
from scanner.v2.symmetrical_triangles import _evaluate_detection


def _series() -> pd.DataFrame:
    rows = []
    for idx in range(60):
        close = 100.0
        high = 105.0
        low = 95.0
        if idx == 5:
            high = 100.0
            low = 90.0
            close = 96.0
        elif idx == 12:
            high = 103.0
            low = 90.0
            close = 96.0
        elif idx == 28:
            high = 106.0
            low = 98.0
            close = 103.0
        elif idx == 35:
            high = 105.0
            low = 100.0
            close = 103.0
        elif idx == 37:
            high = 101.0
            low = 94.0
            close = 96.0
        elif idx == 38:
            high = 99.0
            low = 88.0
            close = 90.0
        elif 39 <= idx <= 43:
            high = 88.0
            low = 72.0
            close = 78.0
        rows.append(
            {
                "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=idx),
                "symbol": "RWG",
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": 100000,
                "volume_ratio": 1.4 if idx == 37 else 1.0,
            }
        )
    return pd.DataFrame(rows)


def _pivots(df: pd.DataFrame) -> list[Pivot]:
    return [
        Pivot(idx=5, date=df.loc[5, "date"], price=100.0, type=PivotType.HIGH, strength=3, classification="minor"),
        Pivot(idx=12, date=df.loc[12, "date"], price=90.0, type=PivotType.LOW, strength=3, classification="minor"),
        Pivot(idx=28, date=df.loc[28, "date"], price=106.0, type=PivotType.HIGH, strength=3, classification="minor"),
        Pivot(idx=35, date=df.loc[35, "date"], price=100.0, type=PivotType.LOW, strength=3, classification="minor"),
    ]


def test_rising_wedge_uses_upward_converging_boundaries_and_down_breakout() -> None:
    df = _series()
    detector = RisingWedgeDetector(RisingWedgeConfig(width_min_bars=10, width_max_bars=50, breakout_search_bars=10))

    detection = detector.scan_window(df, _pivots(df))

    assert detection is not None
    assert detection["variant"] == "rising_wedge"
    assert detection["breakout_direction"] == "down"
    assert detection["upper_slope_deg"] > 0
    assert detection["lower_slope_deg"] > 0
    assert detection["lower_slope_deg"] > detection["upper_slope_deg"]
    assert detection["compression_ratio"] < 1
    assert detection["target_price"] < detection["breakout_price"]

    outcomes = _evaluate_detection(df, detection, lookahead=12)
    assert outcomes["target_hit"] is True
    assert outcomes["failure_5pct"] is False


def test_rising_wedge_publication_tier_does_not_use_post_breakout_outcome() -> None:
    rows = [
        {
            "path_quality_bucket": "clean",
            "tradability_quality_bucket": "clean",
            "high_rise_pct": 7.0,
            "low_rise_pct": 12.0,
            "compression_ratio": 0.42,
            "breakout_clearance_pct": 2.5,
            "breakout_volume_ratio": 1.4,
            "pattern_height_pct": 14.0,
            "upper_slope_deg": 7.0,
            "lower_slope_deg": 13.0,
            "mfe_pct": 4.0,
            "mae_pct": 18.0,
            "target_hit": False,
            "failure_5pct": True,
            "target_first_before_adverse_5pct": False,
        }
    ]

    _assign_publication_quality_tiers(rows)

    assert rows[0]["publication_quality_tier"] == "premium"
    assert "failure_5pct" not in rows[0]["publication_quality_reasons"]
    assert rows[0]["post_breakout_quality_label"] == "failed_follow_through"
    assert "failure_5pct" in rows[0]["post_breakout_quality_reasons"]
