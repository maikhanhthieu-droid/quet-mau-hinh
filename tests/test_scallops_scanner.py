from __future__ import annotations

import pandas as pd

from scanner.pivot_detector import Pivot, PivotType
from scanner.run_chapter_tradable_layer import CHAPTER_SPECS, _filter_pattern_tradable_scope, build_strategy_grid
from scanner.v2.scallops import (
    SCALLOPS_ASCENDING,
    SCALLOPS_ASCENDING_INVERTED,
    SCALLOPS_DESCENDING,
    SCALLOPS_DESCENDING_INVERTED,
    ScallopDetector,
)


def _frame(values: list[float], symbol: str = "AAA") -> pd.DataFrame:
    rows = []
    for i, close in enumerate(values):
        rows.append(
            {
                "symbol": symbol,
                "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=i),
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": 100_000 + i,
            }
        )
    return pd.DataFrame(rows)


def _pivot(idx: int, price: float, pivot_type: PivotType) -> Pivot:
    return Pivot(idx=idx, date=pd.Timestamp("2024-01-01") + pd.Timedelta(days=idx), price=price, type=pivot_type, strength=5, classification="intermediate")


def _series(points: list[tuple[int, float]], length: int = 140) -> list[float]:
    out = [points[0][1]] * length
    for (i0, p0), (i1, p1) in zip(points, points[1:]):
        span = max(i1 - i0, 1)
        for idx in range(i0, min(i1 + 1, length)):
            out[idx] = p0 + (p1 - p0) * ((idx - i0) / span)
    if points[-1][0] < length:
        for idx in range(points[-1][0], length):
            out[idx] = points[-1][1]
    return out


def test_ascending_scallop_uses_hlh_with_higher_right_lip() -> None:
    values = _series([(0, 14), (20, 15), (36, 11), (55, 19.3), (58, 21.5)])
    row = ScallopDetector(SCALLOPS_ASCENDING).scan_window(
        _frame(values),
        [_pivot(20, 15.0, PivotType.HIGH), _pivot(36, 11.0, PivotType.LOW), _pivot(55, 19.3, PivotType.HIGH)],
    )
    assert row is not None
    assert row["sequence_tag"] == "HLH"
    assert row["lip_shift_pct"] > 0
    assert row["breakout_direction"] == "up"


def test_descending_scallop_uses_hlh_with_lower_right_lip() -> None:
    values = _series([(0, 31), (20, 30), (36, 22), (55, 25), (58, 21)])
    row = ScallopDetector(SCALLOPS_DESCENDING).scan_window(
        _frame(values),
        [_pivot(20, 30.0, PivotType.HIGH), _pivot(36, 22.0, PivotType.LOW), _pivot(55, 25.0, PivotType.HIGH)],
    )
    assert row is not None
    assert row["sequence_tag"] == "HLH"
    assert row["lip_shift_pct"] < 0
    assert row["breakout_direction"] == "down"


def test_ascending_inverted_scallop_uses_lhl_and_up_confirmation() -> None:
    values = _series([(0, 9), (20, 10), (36, 14), (55, 12), (58, 15)])
    row = ScallopDetector(SCALLOPS_ASCENDING_INVERTED).scan_window(
        _frame(values),
        [_pivot(20, 10.0, PivotType.LOW), _pivot(36, 14.0, PivotType.HIGH), _pivot(55, 12.0, PivotType.LOW)],
    )
    assert row is not None
    assert row["sequence_tag"] == "LHL"
    assert row["lip_shift_pct"] > 0
    assert row["breakout_direction"] == "up"


def test_descending_inverted_scallop_uses_lhl_and_down_confirmation() -> None:
    values = _series([(0, 28), (20, 30), (36, 32), (55, 20), (58, 14.5)])
    row = ScallopDetector(SCALLOPS_DESCENDING_INVERTED).scan_window(
        _frame(values),
        [_pivot(20, 30.0, PivotType.LOW), _pivot(36, 32.0, PivotType.HIGH), _pivot(55, 20.0, PivotType.LOW)],
    )
    assert row is not None
    assert row["sequence_tag"] == "LHL"
    assert row["lip_shift_pct"] < 0
    assert row["breakout_direction"] == "down"


def test_ascending_inverted_tradable_scope_is_mid_high_up_quality_branch() -> None:
    events = pd.DataFrame(
        [
            {
                "event_id": "keep_mid",
                "breakout_direction": "up",
                "liquidity_bucket": "mid",
                "publication_quality_tier": "standard",
                "publication_quality_score": 72,
            },
            {
                "event_id": "keep_high",
                "breakout_direction": "up",
                "liquidity_bucket": "high",
                "publication_quality_tier": "premium",
                "publication_quality_score": 80,
            },
            {
                "event_id": "drop_low",
                "breakout_direction": "up",
                "liquidity_bucket": "low",
                "publication_quality_tier": "premium",
                "publication_quality_score": 90,
            },
            {
                "event_id": "drop_down",
                "breakout_direction": "down",
                "liquidity_bucket": "high",
                "publication_quality_tier": "premium",
                "publication_quality_score": 90,
            },
            {
                "event_id": "drop_quality",
                "breakout_direction": "up",
                "liquidity_bucket": "high",
                "publication_quality_tier": "standard",
                "publication_quality_score": 71.9,
            },
        ]
        * 50
    )

    scoped = _filter_pattern_tradable_scope(events, CHAPTER_SPECS["scallops_ascending_inverted"])

    assert set(scoped["event_id"]) == {"keep_mid", "keep_high"}


def test_ascending_inverted_strategy_grid_contains_fold_repair_liquidity_branch() -> None:
    configs = build_strategy_grid("scallops_ascending_inverted")
    repaired = [
        config
        for config in configs
        if config.target_multiple == 0.65
        and config.allowed_liquidity_buckets == ("mid", "high")
        and config.position_size_pct == 0.033
        and config.min_setup_score == 72.0
    ]

    assert repaired
