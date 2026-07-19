from __future__ import annotations

import pandas as pd

from scanner.pivot_detector import Pivot, PivotType
from scanner.v2.falling_wedges import FallingWedgeConfig, FallingWedgeDetector, _assign_publication_quality_tiers
from scanner.v2.symmetrical_triangles import _evaluate_detection


def _series() -> pd.DataFrame:
    rows = []
    for idx in range(60):
        close = 86.0
        high = 88.0
        low = 82.0
        if idx == 5:
            high = 120.0
            low = 106.0
            close = 114.0
        elif idx == 12:
            high = 106.0
            low = 90.0
            close = 96.0
        elif idx == 28:
            high = 102.0
            low = 88.0
            close = 96.0
        elif idx == 35:
            high = 91.0
            low = 82.0
            close = 86.0
        elif idx == 39:
            high = 104.0
            low = 96.0
            close = 103.0
        elif 40 <= idx <= 42:
            high = 112.0
            low = 101.0
            close = 109.0
        elif idx == 43:
            high = 136.0
            low = 110.0
            close = 128.0
        rows.append(
            {
                "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=idx),
                "symbol": "FWG",
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": 100000,
                "volume_ratio": 1.4 if idx == 39 else 1.0,
            }
        )
    return pd.DataFrame(rows)


def _pivots(df: pd.DataFrame) -> list[Pivot]:
    return [
        Pivot(idx=5, date=df.loc[5, "date"], price=120.0, type=PivotType.HIGH, strength=3, classification="minor"),
        Pivot(idx=12, date=df.loc[12, "date"], price=90.0, type=PivotType.LOW, strength=3, classification="minor"),
        Pivot(idx=28, date=df.loc[28, "date"], price=102.0, type=PivotType.HIGH, strength=3, classification="minor"),
        Pivot(idx=35, date=df.loc[35, "date"], price=82.0, type=PivotType.LOW, strength=3, classification="minor"),
    ]


def test_falling_wedge_uses_downward_converging_boundaries_and_up_breakout() -> None:
    df = _series()
    detector = FallingWedgeDetector(
        FallingWedgeConfig(width_min_bars=10, width_max_bars=50, breakout_search_bars=10, lower_slope_min_neg_deg=-25.0)
    )

    detection = detector.scan_window(df, _pivots(df))

    assert detection is not None
    assert detection["variant"] == "falling_wedge"
    assert detection["breakout_direction"] == "up"
    assert detection["upper_slope_deg"] < 0
    assert detection["lower_slope_deg"] < 0
    assert abs(detection["upper_slope_deg"]) > abs(detection["lower_slope_deg"])
    assert detection["compression_ratio"] < 1
    assert detection["target_price"] > detection["breakout_price"]

    outcomes = _evaluate_detection(df, detection, lookahead=12)
    assert outcomes["target_hit"] is True
    assert outcomes["failure_5pct"] is False
    assert outcomes["target_first_before_adverse_5pct"] is True


def test_falling_wedge_publication_tier_does_not_use_post_breakout_outcome() -> None:
    rows = [
        {
            "path_quality_bucket": "clean",
            "tradability_quality_bucket": "clean",
            "high_fall_pct": 13.0,
            "low_rise_pct": 8.0,
            "compression_ratio": 0.42,
            "breakout_clearance_pct": 2.5,
            "breakout_volume_ratio": 1.4,
            "pattern_height_pct": 14.0,
            "upper_slope_deg": -11.0,
            "lower_slope_deg": -4.0,
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
