from __future__ import annotations

import pandas as pd

from scanner.run_triangle_publication_quality_audit import (
    _assign_threshold_variant,
    _cluster_bootstrap_ratio_ci,
    _cooldown_events,
    _metrics,
    _regime_liquidity_interaction,
    _temporal_split_rows,
)


def test_threshold_variant_preserves_premium_hard_gates() -> None:
    events = pd.DataFrame(
        [
            {
                "event_id": "a",
                "publication_quality_tier": "premium",
                "publication_quality_score": 90,
                "path_quality_bucket": "clean",
                "tradability_quality_bucket": "clean",
                "high_spread_pct": 0.5,
                "low_rise_pct": 8,
                "compression_ratio": 0.4,
                "breakout_clearance_pct": 1.5,
                "pattern_height_pct": 12,
                "breakout_volume_ratio": 1.1,
                "mfe_pct": 18,
                "mae_pct": 6,
                "target_hit": True,
                "failure_5pct": False,
                "target_first_before_adverse_5pct": True,
            },
            {
                "event_id": "b",
                "publication_quality_tier": "standard",
                "publication_quality_score": 90,
                "path_quality_bucket": "clean",
                "tradability_quality_bucket": "clean",
                "high_spread_pct": 1.4,
                "low_rise_pct": 8,
                "compression_ratio": 0.4,
                "breakout_clearance_pct": 1.5,
                "pattern_height_pct": 12,
                "breakout_volume_ratio": 1.1,
                "mfe_pct": 18,
                "mae_pct": 6,
                "target_hit": True,
                "failure_5pct": False,
                "target_first_before_adverse_5pct": True,
            },
            {
                "event_id": "c",
                "publication_quality_tier": "data_limited",
                "publication_quality_score": 99,
                "path_quality_bucket": "zero_volume",
                "tradability_quality_bucket": "impaired",
                "high_spread_pct": 0.1,
                "low_rise_pct": 20,
                "compression_ratio": 0.2,
                "breakout_clearance_pct": 1.5,
                "pattern_height_pct": 12,
                "breakout_volume_ratio": 1.1,
                "mfe_pct": 18,
                "mae_pct": 6,
                "target_hit": True,
                "failure_5pct": False,
                "target_first_before_adverse_5pct": True,
            },
        ]
    )

    tier = _assign_threshold_variant(
        events,
        standard_cut=65,
        premium_cut=80,
        high_spread_max=1.0,
        low_rise_min=5.0,
        compression_max=0.6,
    )

    assert tier.tolist() == ["premium", "standard", "data_limited"]


def test_triangle_cooldown_keeps_first_event_per_symbol_window() -> None:
    events = pd.DataFrame(
        {
            "event_id": ["a", "b", "c"],
            "symbol": ["AAA", "AAA", "AAA"],
            "breakout_ts": pd.to_datetime(["2024-01-01", "2024-01-20", "2024-03-15"]),
        }
    )

    filtered = _cooldown_events(events, 40)

    assert filtered["event_id"].tolist() == ["a", "c"]


def test_triangle_metrics_uses_path_order_for_target_first() -> None:
    events = pd.DataFrame(
        {
            "event_id": ["a", "b"],
            "target_dist_pct": [10.0, 10.0],
            "mfe_pct": [12.0, 12.0],
            "mae_pct": [2.0, 7.0],
            "failure_5pct": [False, False],
        }
    )
    path = pd.DataFrame(
        {
            "event_id": ["a", "a", "b", "b"],
            "bar_after_breakout": [1, 2, 1, 2],
            "signed_high_excursion_pct": [6.0, 7.0, 1.0, 6.0],
            "signed_low_excursion_pct": [-1.0, -2.0, -6.0, -6.5],
        }
    )

    row = _metrics(events, path, target_multiple=0.5)

    assert row["target_hit_rate_pct"] == 100.0
    assert row["target_first_before_adverse_5pct_rate_pct"] == 50.0


def test_symbol_cluster_bootstrap_returns_interval() -> None:
    events = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA", "BBB", "BBB", "CCC", "CCC"],
            "mfe_pct": [10, 12, 20, 22, 30, 32],
            "mae_pct": [5, 6, 10, 11, 15, 16],
        }
    )

    ci = _cluster_bootstrap_ratio_ci(events, seed=7, reps=100)

    assert ci["low"] is not None
    assert ci["high"] is not None
    assert ci["low"] <= ci["high"]


def test_temporal_split_and_interaction_rows_are_generated() -> None:
    events = pd.DataFrame(
        {
            "event_id": ["a", "b", "c", "d", "e", "f"],
            "symbol": ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"],
            "breakout_ts": pd.to_datetime(["2012-01-01", "2017-01-01", "2021-01-01", "2024-01-01", "2025-01-01", "2026-01-01"]),
            "publication_quality_tier": ["premium", "standard", "premium", "standard", "premium", "standard"],
            "market_regime": ["bull", "bear", "bull", "bear", "unknown", "bull"],
            "liquidity_bucket": ["high", "high", "mid", "mid", "low", "low"],
            "target_dist_pct": [10, 10, 10, 10, 10, 10],
            "mfe_pct": [8, 9, 10, 11, 12, 13],
            "mae_pct": [2, 2, 3, 3, 4, 4],
            "failure_5pct": [False, False, False, False, False, False],
        }
    )
    path = pd.DataFrame(
        {
            "event_id": ["a", "b", "c", "d", "e", "f"],
            "bar_after_breakout": [1, 1, 1, 1, 1, 1],
            "signed_high_excursion_pct": [6, 6, 6, 6, 6, 6],
            "signed_low_excursion_pct": [0, 0, 0, 0, 0, 0],
        }
    )

    temporal = _temporal_split_rows(events, path)
    interaction = _regime_liquidity_interaction(events, path)

    assert any(row["split_type"] == "sample_thirds" for row in temporal)
    assert any(row["market_regime"] == "bull" and row["liquidity_bucket"] == "high" for row in interaction)
