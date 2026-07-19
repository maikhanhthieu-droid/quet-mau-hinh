from __future__ import annotations

import json

import pandas as pd

from scanner.v2.bull_flag_localization import (
    BULL_FLAG_V2_BALANCED_PROFILE_ID,
    BULL_FLAG_V2_BREAKOUT_QUALITY_PROFILE_ID,
    BULL_FLAG_V2_FOLLOWTHROUGH_DIAGNOSTIC_PROFILE_ID,
    BULL_FLAG_V2_PROFILE_ID,
    BULL_FLAG_V2_RECALL_PROFILE_ID,
    BULL_FLAG_V2_SETUP_QUALITY_PROFILE_ID,
    BULL_FLAG_V2_SPLIT_STABLE_PROFILE_ID,
    BULL_FLAG_V2_STABILITY_PROFILE_ID,
    BULL_FLAG_V2_STRICT_PROFILE_ID,
    _alternate_split_rows,
    _apply_post_score_filter,
    _apply_three_layer_scores,
    _breakout_timing_rows,
    _bull_flag_v2_release_gate,
    _metric_contract,
    _negative_control_rows,
    _three_layer_comparison_rows,
    adaptive_detector_profiles,
    detector_config_profiles,
    evaluate_profile,
    select_adaptive_detector_profile,
    select_bull_flag_v2_variant,
    select_detector_profile,
    select_profile,
)
from scanner.v2.bull_flags_monograph import _bulkowski_equivalent_metrics_for_event, _event_passes_filter
from scanner.v2.bull_flags_monograph import _corporate_action_metrics_for_event, _tradability_quality_metrics_for_event
from scanner.v2.flags_experiment import FlagDetectorConfig
from scanner.research_support_analysis import PatternArtifacts


def test_flag_detector_config_ignores_unknown_keys() -> None:
    config = FlagDetectorConfig.from_mapping({"pole_min_change_pct": 12.0, "unknown": "ignored"})

    assert config.pole_min_change_pct == 12.0
    assert "unknown" not in config.to_dict()


def test_event_filter_checks_geometry_path_and_liquidity() -> None:
    row = {
        "pole_move_pct": 14.0,
        "flag_to_pole_pct": 33.0,
        "slope_gap_deg": 1.5,
        "pattern_quality_score": 88,
        "path_quality_bucket": "clean",
        "liquidity_bucket": "high",
        "volume_confirmed": True,
        "is_primary_event_60d": True,
        "post_breakout_zero_volume_days_60d": 0,
        "breakout_year": 2024,
        "time_split": "validation_20",
    }

    assert _event_passes_filter(
        row,
        {
            "min_pole_move_pct": 12.0,
            "max_flag_to_pole_pct": 35.0,
            "max_slope_gap_deg": 2.0,
            "min_pattern_quality_score": 85,
            "allowed_path_quality_buckets": ["clean"],
            "allowed_liquidity_buckets": ["high", "mid"],
            "require_volume_confirmed": True,
            "require_primary_event_60d": True,
            "min_breakout_year": 2023,
            "allowed_time_splits": ["validation_20"],
        },
    )
    assert not _event_passes_filter(row, {"max_slope_gap_deg": 1.0})
    assert not _event_passes_filter(row, {"max_breakout_year": 2023})


def test_bulkowski_equivalent_event_metrics_cover_gap_volume_throwback_and_stops() -> None:
    series = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=90, freq="B"),
            "open": [100 + i * 0.2 for i in range(90)],
            "high": [101 + i * 0.2 for i in range(90)],
            "low": [99 + i * 0.2 for i in range(90)],
            "close": [100 + i * 0.2 for i in range(90)],
            "volume": [5000 - i * 70 for i in range(90)],
        }
    )
    breakout_idx = 35
    series.loc[breakout_idx, ["open", "high", "low", "close", "volume"]] = [112.0, 116.0, 111.0, 115.0, 6000]
    series.loc[breakout_idx + 1, ["high", "low", "close"]] = [118.0, 114.0, 117.0]
    series.loc[breakout_idx + 3, ["high", "low", "close"]] = [117.0, 111.0, 112.0]
    series.loc[breakout_idx + 8, ["high", "low", "close"]] = [112.0, 104.0, 105.0]
    row = {
        "formation_start_date": str(series.loc[20, "date"].date()),
        "formation_end_date": str(series.loc[30, "date"].date()),
        "breakout_date": str(series.loc[breakout_idx, "date"].date()),
        "pole_idx": 5,
        "flag_upper_idx0": 20,
        "flag_upper_price0": 110.0,
        "flag_upper_slope_per_bar": 0.15,
        "flag_lower_idx0": 20,
        "flag_lower_price0": 106.0,
        "flag_lower_slope_per_bar": 0.10,
    }

    metrics = _bulkowski_equivalent_metrics_for_event(series, row)

    assert metrics["breakout_gap_pct"] is not None
    assert metrics["breakout_volume_ratio_20"] > 1
    assert metrics["volume_trend_direction"] == "down"
    assert metrics["yearly_range_position_pct"] is not None
    assert metrics["throwback_exact_30d"] is True
    assert metrics["throwback_to_breakout_30d"] is True
    assert metrics["stop_hit_7pct"] is True
    assert metrics["busted_pattern_flag"] is True


def test_corporate_action_and_tradability_metrics_flag_event_risk() -> None:
    actions = pd.DataFrame(
        {
            "action_date": pd.to_datetime(["2024-01-10", "2024-01-22", "2024-02-20"]),
            "event_list_name": ["Trả cổ tức bằng tiền mặt", "Phát hành thêm", "Chia cổ phiếu"],
            "event_title": ["AAA cổ tức", "AAA quyền mua", "AAA chia cổ phiếu"],
        }
    )
    row = {
        "formation_start_date": "2024-01-08",
        "formation_end_date": "2024-01-15",
        "breakout_date": "2024-01-20",
    }
    corp = _corporate_action_metrics_for_event(actions, row)
    series = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=80, freq="B"),
            "open": [10.0] * 80,
            "high": [10.7] * 80,
            "low": [9.8] * 80,
            "close": [10.0] * 80,
            "volume": [1000] * 80,
        }
    )
    series.loc[20:25, "volume"] = 0

    quality = _tradability_quality_metrics_for_event(series, "2024-01-20", corp)

    assert corp["corp_action_overlap_flag"] is True
    assert corp["corp_action_near_breakout_flag"] is True
    assert corp["corp_action_in_forward_window_flag"] is True
    assert "Trả cổ tức" in corp["corp_action_event_types"]
    assert quality["tradability_quality_score"] < 100
    assert "corp_action_near_breakout" in quality["tradability_risk_reasons"]


def test_localization_selection_prefers_passing_profile() -> None:
    rows = [
        {"profile_id": "a", "gates_pass": False, "localization_score": 90.0, "n": 100},
        {"profile_id": "b", "gates_pass": True, "localization_score": 60.0, "n": 80},
    ]

    selected = select_profile(rows)

    assert selected["selected_profile_id"] == "b"
    assert selected["status"] == "selected_localized_profile"


def test_detector_grid_profiles_include_baseline_and_event_filter() -> None:
    profiles = detector_config_profiles()

    assert profiles[0]["profile_id"] == "detector_baseline"
    assert "detector_config" in profiles[0]
    assert any(profile.get("event_filter_config") for profile in profiles[1:])


def test_adaptive_detector_profiles_have_context_branches() -> None:
    profiles = adaptive_detector_profiles()
    candidate = next(profile for profile in profiles if profile["profile_id"] == "adaptive_liquidity_regime")
    v2 = next(profile for profile in profiles if profile["profile_id"] == BULL_FLAG_V2_PROFILE_ID)
    v2_ids = {profile["profile_id"] for profile in profiles if profile.get("profile_role") == "canonical_bull_flag_v2"}
    branch_filters = [branch["event_filter_config"] for branch in candidate["branches"]]

    assert profiles[0]["profile_id"] == "detector_baseline"
    assert any("allowed_regimes" in config for config in branch_filters)
    assert any("allowed_liquidity_buckets" in config for config in branch_filters)
    assert {
        BULL_FLAG_V2_STRICT_PROFILE_ID,
        BULL_FLAG_V2_BALANCED_PROFILE_ID,
        BULL_FLAG_V2_RECALL_PROFILE_ID,
        BULL_FLAG_V2_STABILITY_PROFILE_ID,
        BULL_FLAG_V2_SPLIT_STABLE_PROFILE_ID,
        BULL_FLAG_V2_SETUP_QUALITY_PROFILE_ID,
        BULL_FLAG_V2_BREAKOUT_QUALITY_PROFILE_ID,
    }.issubset(v2_ids)
    diagnostic = next(profile for profile in profiles if profile["profile_id"] == BULL_FLAG_V2_FOLLOWTHROUGH_DIAGNOSTIC_PROFILE_ID)
    assert v2["post_score_filter_config"]["entry_layer"] == "setup_confirmation"
    assert v2["post_score_filter_config"]["min_setup_score"] == 68.0
    assert v2["post_score_filter_config"]["min_confirmation_score"] == 58.0
    assert v2["post_score_filter_config"]["use_followthrough_for_entry"] is False
    assert diagnostic["post_score_filter_config"]["use_followthrough_for_entry"] is True
    assert diagnostic["profile_role"] == "diagnostic_bull_flag_v2"


def test_detector_profile_selection_prefers_passing_profile() -> None:
    rows = [
        {"profile_id": "detector_baseline", "gates_pass": False, "localization_score": 70.0, "n": 100},
        {"profile_id": "detector_a", "gates_pass": False, "localization_score": 80.0, "n": 90},
        {"profile_id": "detector_b", "gates_pass": True, "localization_score": 60.0, "n": 70},
    ]

    selected = select_detector_profile(rows)

    assert selected["selected_profile_id"] == "detector_b"
    assert selected["status"] == "selected_detector_profile"


def test_adaptive_profile_selection_prefers_passing_profile() -> None:
    rows = [
        {"profile_id": "detector_baseline", "gates_pass": False, "localization_score": 70.0, "n": 100},
        {"profile_id": "adaptive_a", "gates_pass": False, "localization_score": 85.0, "n": 95},
        {"profile_id": "adaptive_b", "gates_pass": True, "localization_score": 60.0, "n": 70},
    ]

    selected = select_adaptive_detector_profile(rows)

    assert selected["selected_profile_id"] == "adaptive_b"
    assert selected["status"] == "selected_adaptive_detector_profile"


def test_evaluate_profile_emits_overfit_flags_for_small_sample() -> None:
    events = pd.DataFrame(
        {
            "event_id": ["e1", "e2"],
            "symbol": ["AAA", "BBB"],
            "target_dist_pct": [10.0, 10.0],
            "mfe_pct": [12.0, 2.0],
            "mae_pct": [3.0, 8.0],
            "time_split": ["train_60", "holdout_20"],
            "market_regime": ["bull", "bear"],
            "path_quality_bucket": ["clean", "clean"],
        }
    )
    path = pd.DataFrame(
        {
            "event_id": ["e1", "e2"],
            "bar_after_breakout": [1, 1],
            "signed_high_excursion_pct": [12.0, 2.0],
            "signed_low_excursion_pct": [-1.0, -8.0],
        }
    )

    row = evaluate_profile({"profile_id": "baseline_all"}, PatternArtifacts("bull_flags", events, path), baseline_n=2)

    assert row["n"] == 2
    assert "validation_too_small" in row["overfit_flags"]


def test_metric_contract_exposes_base_and_legacy_targets() -> None:
    events = pd.DataFrame(
        {
            "event_id": ["e1", "e2"],
            "symbol": ["AAA", "BBB"],
            "target_dist_pct": [10.0, 10.0],
            "mfe_pct": [5.0, 12.0],
            "mae_pct": [2.0, 4.0],
            "failure_5pct": [False, False],
        }
    )
    path = pd.DataFrame(
        {
            "event_id": ["e1", "e2"],
            "bar_after_breakout": [1, 1],
            "signed_high_excursion_pct": [5.0, 12.0],
            "signed_low_excursion_pct": [-1.0, -1.0],
        }
    )

    contract = _metric_contract(events, path)

    assert contract["target_hit_base_046x_rate"] == 100.0
    assert contract["target_hit_legacy_1x_rate"] == 50.0
    assert contract["target_family_monotonic"] is True


def test_alternate_splits_and_negative_controls_are_reported() -> None:
    events = pd.DataFrame(
        {
            "event_id": [f"e{i}" for i in range(12)],
            "detection_id": [f"e{i}" for i in range(12)],
            "symbol": ["AAA"] * 12,
            "breakout_date": pd.date_range("2024-01-01", periods=12, freq="D").astype(str),
            "target_dist_pct": [10.0] * 12,
            "mfe_pct": [8.0] * 12,
            "mae_pct": [3.0] * 12,
            "failure_5pct": [False] * 12,
        }
    )
    path = pd.DataFrame(
        {
            "event_id": [f"e{i}" for i in range(12)],
            "bar_after_breakout": [1] * 12,
            "signed_high_excursion_pct": [8.0] * 12,
            "signed_low_excursion_pct": [-1.0] * 12,
        }
    )

    split_rows = _alternate_split_rows(events, path, profile_id="p")
    control_rows = _negative_control_rows(events, path, profile_id="p")

    assert {row["scheme_id"] for row in split_rows} == {
        "chronological_50_25_25",
        "chronological_60_20_20",
        "chronological_70_15_15",
    }
    assert any(row["control_id"] == "opposite_direction_base_046x" for row in control_rows)


def test_breakout_timing_rows_compare_delayed_and_prebreakout_controls(tmp_path) -> None:
    rows = []
    for idx in range(30):
        close = 90.0 + idx
        rows.append(
            {
                "date": f"2024-01-{idx + 1:02d}",
                "open": close,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1000,
            }
        )
    (tmp_path / "AAA.json").write_text(json.dumps(rows), encoding="utf-8")
    events = pd.DataFrame(
        {
            "event_id": ["e1"],
            "detection_id": ["e1"],
            "symbol": ["AAA"],
            "breakout_direction": ["up"],
            "breakout_price": [100.0],
            "target_dist_pct": [10.0],
            "breakout_idx": [10],
            "formation_start_idx": [5],
            "formation_end_idx": [8],
        }
    )
    path_rows = []
    for bar in range(1, 26):
        close = 100.0 + bar
        path_rows.append(
            {
                "event_id": "e1",
                "symbol": "AAA",
                "bar_after_breakout": bar,
                "open": close,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
            }
        )
    path = pd.DataFrame(path_rows)

    timing_rows = _breakout_timing_rows(events, path, profile_id="p", source_dir=tmp_path)
    timing_ids = {row["timing_id"] for row in timing_rows}

    assert "actual_breakout_base_046x" in timing_ids
    assert "delayed_10_close_reanchored_base_046x" in timing_ids
    assert "pre_breakout_minus_3_close_same_abs_base_046x" in timing_ids
    actual = next(row for row in timing_rows if row["timing_id"] == "actual_breakout_base_046x")
    delayed = next(row for row in timing_rows if row["timing_id"] == "delayed_10_close_reanchored_base_046x")
    pre = next(row for row in timing_rows if row["timing_id"] == "pre_breakout_minus_3_close_same_abs_base_046x")

    assert actual["target_first_rate"] == 100.0
    assert delayed["n"] == 1
    assert delayed["median_entry_offset_bars"] == 10.0
    assert pre["median_entry_offset_bars"] == -3.0


def test_three_layer_scores_and_comparison_rows_are_emitted() -> None:
    events = pd.DataFrame(
        {
            "event_id": ["e1", "e2"],
            "detection_id": ["e1", "e2"],
            "symbol": ["AAA", "BBB"],
            "breakout_direction": ["up", "up"],
            "breakout_price": [100.0, 100.0],
            "target_dist_pct": [10.0, 10.0],
            "pole_move_pct": [18.0, 9.0],
            "pole_slope_deg": [14.0, 5.0],
            "flag_to_pole_pct": [30.0, 70.0],
            "slope_gap_deg": [1.0, 6.0],
            "pattern_height_pct": [6.0, 14.0],
            "volume_confirmed": [True, False],
        }
    )
    path = pd.DataFrame(
        {
            "event_id": ["e1", "e1", "e2", "e2"],
            "bar_after_breakout": [1, 10, 1, 10],
            "signed_high_excursion_pct": [3.0, 9.0, 1.0, 3.0],
            "signed_low_excursion_pct": [-1.0, -2.0, -3.5, -6.0],
            "signed_close_return_pct": [2.0, 7.0, -1.0, -4.0],
        }
    )

    scored = _apply_three_layer_scores(events, path)
    rows = _three_layer_comparison_rows(scored, path, profile_id="p")

    assert {"setup_score", "confirmation_score", "followthrough_score", "bull_flag_score_total"}.issubset(scored.columns)
    assert scored.loc[0, "setup_score"] > scored.loc[1, "setup_score"]
    assert scored.loc[0, "bull_flag_scanner_branch"] in {"confirmed_breakout", "post_breakout_continuation", "early_setup_watch"}
    assert {row["layer_filter_id"] for row in rows} >= {
        "current_adaptive",
        "setup_only_70",
        "confirmation_only_65",
        "setup_confirmation_followthrough",
    }


def test_bull_flag_v2_post_score_filter_and_release_gate() -> None:
    events = pd.DataFrame(
        {
            "event_id": ["e1", "e2", "e3"],
            "setup_score": [72.0, 80.0, 60.0],
            "confirmation_score": [61.0, 55.0, 90.0],
            "followthrough_score": [20.0, 100.0, 100.0],
        }
    )
    filtered, report = _apply_post_score_filter(
        events,
        {
            "post_score_filter_config": {
                "profile_id": BULL_FLAG_V2_PROFILE_ID,
                "min_setup_score": 70.0,
                "min_confirmation_score": 60.0,
                "use_followthrough_for_entry": False,
            }
        },
    )
    gate = _bull_flag_v2_release_gate(
        {
            "profile_id": BULL_FLAG_V2_PROFILE_ID,
            "n": 52,
            "validation_n": 12,
            "holdout_n": 14,
            "sample_retention_pct": 50.0,
            "target_first_base_046x_rate": 54.0,
            "failure_5pct_rate": 7.0,
            "mfe_mae_median_ratio": 3.2,
            "post_score_min_setup_score": 70.0,
            "post_score_min_confirmation_score": 60.0,
            "alternate_split_fail_count": 1,
            "timing_breakout_specificity": "trend_continuation_component_material",
        },
        {
            "profile_id": "adaptive_2024_guard",
            "n": 81,
            "target_first_base_046x_rate": 50.0,
            "failure_5pct_rate": 17.0,
        },
    )

    assert filtered["event_id"].tolist() == ["e1"]
    assert report["removed_count"] == 2
    assert gate["bull_flag_v2_release_gate_pass"] is True
    assert gate["classification"] == "Bull Flag V2 investment-reference candidate"
    assert gate["scanner_entry_rule"] == "setup_score >= 70 and confirmation_score >= 60"


def test_bull_flag_v2_contextual_recovery_post_score_filter() -> None:
    events = pd.DataFrame(
        {
            "event_id": ["base", "post_recovered", "setup_recovered", "confirm_recovered", "weak"],
            "setup_score": [66.0, 82.0, 85.0, 62.0, 76.0],
            "confirmation_score": [61.0, 25.0, 25.0, 75.0, 25.0],
            "adaptive_branch_id": [
                "pre_2024_balanced",
                "post_2024_balanced",
                "pre_2024_balanced",
                "pre_2024_balanced",
                "post_2024_balanced",
            ],
            "breakout_year": [2023, 2025, 2022, 2023, 2025],
            "slope_gap_deg": [3.0, 1.0, 2.0, 2.0, 2.5],
            "flag_to_pole_pct": [50.0, 30.0, 30.0, 35.0, 30.0],
            "volume_confirmed": [False, False, False, True, False],
        }
    )
    filtered, report = _apply_post_score_filter(
        events,
        {
            "post_score_filter_config": {
                "profile_id": BULL_FLAG_V2_SPLIT_STABLE_PROFILE_ID,
                "min_setup_score": 65.0,
                "min_confirmation_score": 60.0,
                "use_followthrough_for_entry": False,
                "contextual_rules": [
                    {
                        "allowed_adaptive_branch_ids": ["post_2024_balanced"],
                        "min_breakout_year": 2025,
                        "min_setup_score": 78.0,
                        "min_confirmation_score": 20.0,
                        "max_slope_gap_deg": 1.75,
                        "max_flag_to_pole_pct": 42.0,
                    },
                    {
                        "min_setup_score": 80.0,
                        "min_confirmation_score": 20.0,
                        "max_slope_gap_deg": 3.0,
                        "max_flag_to_pole_pct": 35.0,
                    },
                    {
                        "min_setup_score": 60.0,
                        "min_confirmation_score": 70.0,
                        "require_volume_confirmed": True,
                        "max_slope_gap_deg": 2.5,
                        "max_flag_to_pole_pct": 40.0,
                    },
                ],
            }
        },
    )

    assert filtered["event_id"].tolist() == ["base", "post_recovered", "setup_recovered", "confirm_recovered"]
    assert report["contextual_rule_count"] == 3


def test_breakout_quality_post_score_filter_uses_breakout_bar_fields() -> None:
    events = pd.DataFrame(
        {
            "event_id": ["strong", "weak_close", "wide_flag"],
            "setup_score": [62.0, 72.0, 72.0],
            "confirmation_score": [64.0, 75.0, 75.0],
            "breakout_close_location": [0.82, 0.60, 0.90],
            "breakout_body_to_range": [0.60, 0.80, 0.90],
            "flag_range_to_pole_ratio": [0.90, 0.90, 1.40],
        }
    )

    filtered, _ = _apply_post_score_filter(
        events,
        {
            "post_score_filter_config": {
                "profile_id": BULL_FLAG_V2_BREAKOUT_QUALITY_PROFILE_ID,
                "min_setup_score": 60.0,
                "min_confirmation_score": 60.0,
                "min_breakout_close_location": 0.75,
                "min_breakout_body_to_range": 0.50,
                "max_flag_range_to_pole_ratio": 1.15,
            }
        },
    )

    assert filtered["event_id"].tolist() == ["strong"]


def test_setup_quality_post_score_filter_uses_pre_breakout_contraction_fields() -> None:
    events = pd.DataFrame(
        {
            "event_id": ["clean_setup", "heavy_volume", "wide_range"],
            "setup_score": [72.0, 72.0, 72.0],
            "confirmation_score": [50.0, 50.0, 50.0],
            "flag_to_pole_pct": [40.0, 40.0, 40.0],
            "flag_range_to_pole_ratio": [1.00, 1.00, 1.30],
            "flag_volume_to_pole_ratio": [0.80, 1.30, 0.80],
        }
    )

    filtered, _ = _apply_post_score_filter(
        events,
        {
            "post_score_filter_config": {
                "profile_id": BULL_FLAG_V2_SETUP_QUALITY_PROFILE_ID,
                "min_setup_score": 70.0,
                "min_confirmation_score": 45.0,
                "max_flag_to_pole_pct": 45.0,
                "max_flag_range_to_pole_ratio": 1.15,
                "max_flag_volume_to_pole_ratio": 1.00,
            }
        },
    )

    assert filtered["event_id"].tolist() == ["clean_setup"]


def test_bull_flag_v2_selection_prefers_gate_then_path_quality() -> None:
    rows = [
        {
            "profile_id": BULL_FLAG_V2_STRICT_PROFILE_ID,
            "bull_flag_v2_release_gate_pass": False,
            "target_first_base_046x_rate": 60.0,
            "failure_5pct_rate": 5.0,
            "mfe_mae_median_ratio": 4.0,
            "n": 42,
        },
        {
            "profile_id": BULL_FLAG_V2_RECALL_PROFILE_ID,
            "bull_flag_v2_release_gate_pass": True,
            "target_first_base_046x_rate": 55.0,
            "failure_5pct_rate": 8.0,
            "mfe_mae_median_ratio": 3.2,
            "n": 60,
        },
        {
            "profile_id": BULL_FLAG_V2_BALANCED_PROFILE_ID,
            "bull_flag_v2_release_gate_pass": True,
            "target_first_base_046x_rate": 53.0,
            "failure_5pct_rate": 7.0,
            "mfe_mae_median_ratio": 3.4,
            "n": 55,
        },
    ]

    selected = select_bull_flag_v2_variant(rows)

    assert selected["selected_v2_profile_id"] == BULL_FLAG_V2_RECALL_PROFILE_ID
    assert selected["passing_variant_count"] == 2


def test_bull_flag_v2_selection_prefers_warning_free_gate() -> None:
    rows = [
        {
            "profile_id": BULL_FLAG_V2_STABILITY_PROFILE_ID,
            "bull_flag_v2_release_gate_pass": True,
            "bull_flag_v2_release_gate_warnings": "alternate_split_underpowered_cells",
            "target_first_base_046x_rate": 58.0,
            "failure_5pct_rate": 8.0,
            "mfe_mae_median_ratio": 3.4,
            "n": 57,
        },
        {
            "profile_id": BULL_FLAG_V2_SPLIT_STABLE_PROFILE_ID,
            "bull_flag_v2_release_gate_pass": True,
            "bull_flag_v2_release_gate_warnings": "",
            "target_first_base_046x_rate": 57.0,
            "failure_5pct_rate": 10.0,
            "mfe_mae_median_ratio": 3.3,
            "n": 65,
        },
    ]

    selected = select_bull_flag_v2_variant(rows)

    assert selected["selected_v2_profile_id"] == BULL_FLAG_V2_SPLIT_STABLE_PROFILE_ID
