from __future__ import annotations

import pandas as pd

from scanner.research_support_analysis import (
    PatternArtifacts,
    build_comparison,
    build_bull_flag_robustness_checks,
    build_target_calibration_decisions,
    summarize_events,
    target_family_for_label,
    target_sensitivity,
    wilson_ci,
)


def test_wilson_ci_returns_percent_bounds() -> None:
    ci = wilson_ci(40, 100)

    assert ci["rate"] == 40.0
    assert ci["low"] < ci["rate"] < ci["high"]
    assert ci["n"] == 100


def test_summarize_events_reports_core_rates() -> None:
    events = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA", "BBB"],
            "mfe_pct": [10.0, 2.0, 8.0],
            "mae_pct": [3.0, 6.0, 4.0],
            "target_hit": [True, False, True],
            "failure_5pct": [False, True, False],
            "target_first_before_adverse_5pct": [True, False, True],
        }
    )

    summary = summarize_events("x", events)

    assert summary["n"] == 3
    assert summary["n_symbols"] == 2
    assert summary["median_mfe_pct"] == 8.0
    assert summary["target_hit_ci"]["rate"] == 66.67


def test_target_sensitivity_uses_path_order_for_target_first() -> None:
    events = pd.DataFrame(
        {
            "event_id": ["e1", "e2"],
            "symbol": ["AAA", "BBB"],
            "mfe_pct": [12.0, 12.0],
            "target_dist_pct": [10.0, 10.0],
        }
    )
    path = pd.DataFrame(
        {
            "event_id": ["e1", "e1", "e2", "e2"],
            "bar_after_breakout": [1, 2, 1, 2],
            "signed_high_excursion_pct": [11.0, 12.0, 2.0, 11.0],
            "signed_low_excursion_pct": [-1.0, -6.0, -6.0, -6.0],
        }
    )

    rows = target_sensitivity(PatternArtifacts("x", events, path), "x")
    one_x = [row for row in rows if row["target_multiple"] == 1.0][0]

    assert one_x["target_hit_rate"] == 100.0
    assert one_x["target_first_before_adverse_5pct_rate"] == 50.0


def test_target_sensitivity_respects_horizon_days() -> None:
    events = pd.DataFrame(
        {
            "event_id": ["e1"],
            "symbol": ["AAA"],
            "mfe_pct": [12.0],
            "target_dist_pct": [10.0],
        }
    )
    path = pd.DataFrame(
        {
            "event_id": ["e1", "e1"],
            "bar_after_breakout": [61, 62],
            "signed_high_excursion_pct": [11.0, 12.0],
            "signed_low_excursion_pct": [-1.0, -1.0],
        }
    )

    rows = target_sensitivity(PatternArtifacts("x", events, path), "x", horizon_days=60)
    one_x = [row for row in rows if row["target_multiple"] == 1.0][0]

    assert one_x["target_hit_rate"] == 100.0
    assert one_x["target_first_before_adverse_5pct_rate"] == 0.0
    assert one_x["horizon_days"] == 60


def test_target_family_uses_pattern_specific_bulkowski_adjusted_bands() -> None:
    official_bull_flag = target_family_for_label("bull_flags")
    bull_flag = target_family_for_label("flags_experiment:bull_flag")
    fallback = target_family_for_label("unknown_pattern")

    assert [row["multiple"] for row in official_bull_flag] == [0.46, 0.5, 0.75, 1.0]
    assert [row["multiple"] for row in bull_flag] == [0.46, 0.5, 0.75, 1.0]
    assert bull_flag[-1]["role"] == "legacy_full_pole"
    assert [row["multiple"] for row in fallback] == [0.5, 0.75, 1.0, 1.25]


def test_calibration_decision_selects_first_passing_target_band() -> None:
    rows = [
        {
            "label": "bull_flags",
            "target_multiple": 0.46,
            "target_role": "bulkowski_adjusted_base",
            "target_hit_ci_low": 56.0,
            "target_first_before_adverse_5pct_rate": 36.0,
            "failure_5pct_rate": 25.0,
            "mfe_mae_median_ratio": 1.4,
            "n": 120,
        },
        {
            "label": "bull_flags",
            "target_multiple": 0.5,
            "target_role": "rounded_local_base",
            "target_hit_ci_low": 58.0,
            "target_first_before_adverse_5pct_rate": 37.0,
            "failure_5pct_rate": 25.0,
            "mfe_mae_median_ratio": 1.4,
            "n": 120,
        },
    ]

    decisions = build_target_calibration_decisions(rows)

    assert decisions[0]["status"] == "selected_base_target"
    assert decisions[0]["selected_target_multiple"] == 0.46


def test_build_comparison_adds_bull_flag_deep_split_sensitivity() -> None:
    events = pd.DataFrame(
        {
            "event_id": ["e1", "e2", "e3"],
            "symbol": ["AAA", "BBB", "CCC"],
            "mfe_pct": [12.0, 8.0, 2.0],
            "mae_pct": [3.0, 4.0, 7.0],
            "target_dist_pct": [10.0, 10.0, 10.0],
            "target_hit": [True, False, False],
            "failure_5pct": [False, False, True],
            "target_first_before_adverse_5pct": [True, False, False],
            "liquidity_bucket": ["high", "mid", "low"],
            "is_primary_event_60d": [True, True, False],
            "halted_delisted_proxy_flag": [False, True, False],
            "corp_action_proxy_flag": [False, False, False],
        }
    )
    path = pd.DataFrame(
        {
            "event_id": ["e1", "e2", "e3"],
            "bar_after_breakout": [1, 1, 1],
            "signed_high_excursion_pct": [12.0, 8.0, 2.0],
            "signed_low_excursion_pct": [-1.0, -1.0, -7.0],
        }
    )

    report = build_comparison([PatternArtifacts("bull_flags", events, path)])
    labels = {row["label"] for row in report["target_sensitivity"]}

    assert "bull_flags:liquidity=high" in labels
    assert "bull_flags:path_proxy_clean" in labels
    assert report["target_calibration_decisions"][0]["label"] == "bull_flags"


def test_bull_flag_robustness_classifies_partial_when_path_flagged_is_weak() -> None:
    rows = [
        {
            "label": "bull_flags",
            "target_multiple": 0.46,
            "target_role": "bulkowski_adjusted_base",
            "target_hit_rate": 70.0,
            "target_hit_ci_low": 60.0,
            "target_first_before_adverse_5pct_rate": 42.0,
            "failure_5pct_rate": 24.0,
            "mfe_mae_median_ratio": 1.5,
            "n": 110,
        },
        {
            "label": "bull_flags",
            "target_multiple": 1.0,
            "target_role": "legacy_full_pole",
            "target_hit_rate": 39.0,
            "target_hit_ci_low": 30.0,
            "target_first_before_adverse_5pct_rate": 23.0,
            "failure_5pct_rate": 24.0,
            "mfe_mae_median_ratio": 1.5,
            "n": 110,
        },
    ]
    for bucket in ("high", "mid", "low"):
        rows.append(
            {
                "label": f"bull_flags:liquidity={bucket}",
                "target_multiple": 0.46,
                "target_hit_rate": 70.0,
                "target_hit_ci_low": 54.0,
                "target_first_before_adverse_5pct_rate": 40.0,
                "failure_5pct_rate": 25.0,
                "n": 36,
            }
        )
    rows.extend(
        [
            {
                "label": "bull_flags:primary_60d=true",
                "target_multiple": 0.46,
                "target_hit_rate": 70.0,
                "target_hit_ci_low": 60.0,
                "target_first_before_adverse_5pct_rate": 42.0,
                "failure_5pct_rate": 24.0,
                "n": 109,
            },
            {
                "label": "bull_flags:path_proxy_clean",
                "target_multiple": 0.46,
                "target_hit_rate": 78.0,
                "target_hit_ci_low": 67.0,
                "target_first_before_adverse_5pct_rate": 47.0,
                "failure_5pct_rate": 19.0,
                "mfe_mae_median_ratio": 2.2,
                "n": 72,
            },
            {
                "label": "bull_flags:path_proxy_flagged",
                "target_multiple": 0.46,
                "target_hit_rate": 55.0,
                "target_hit_ci_low": 40.0,
                "target_first_before_adverse_5pct_rate": 34.0,
                "failure_5pct_rate": 34.0,
                "mfe_mae_median_ratio": 0.96,
                "n": 38,
            },
        ]
    )
    report = {
        "target_sensitivity": rows,
        "target_calibration_decisions": build_target_calibration_decisions(rows),
        "data_gate_audits": {"bull_flags": {"blocked_by": [], "investment_reference_data_gates_pass": True}},
    }

    checks = build_bull_flag_robustness_checks(report)
    by_id = {row["check_id"]: row for row in checks}

    assert by_id["base_target_selection"]["status"] == "pass"
    assert by_id["liquidity_bucket_consistency"]["status"] == "partial"
    assert by_id["path_proxy_quality_sensitivity"]["status"] == "partial"
    assert by_id["classification_after_robustness"]["evidence"]["classification"] == "watchlist-reference"


def test_bull_flag_robustness_includes_regime_and_holdout_failures() -> None:
    rows = [
        {
            "label": "bull_flags",
            "target_multiple": 0.46,
            "target_role": "bulkowski_adjusted_base",
            "target_hit_rate": 70.0,
            "target_hit_ci_low": 60.0,
            "target_first_before_adverse_5pct_rate": 42.0,
            "failure_5pct_rate": 24.0,
            "mfe_mae_median_ratio": 1.5,
            "n": 110,
        },
        {
            "label": "bull_flags:regime=bull",
            "target_multiple": 0.46,
            "target_hit_rate": 61.0,
            "target_hit_ci_low": 50.0,
            "target_first_before_adverse_5pct_rate": 41.0,
            "failure_5pct_rate": 29.0,
            "n": 74,
        },
        {
            "label": "bull_flags:regime=bear",
            "target_multiple": 0.46,
            "target_hit_rate": 80.0,
            "target_hit_ci_low": 65.0,
            "target_first_before_adverse_5pct_rate": 42.0,
            "failure_5pct_rate": 14.0,
            "n": 36,
        },
        {
            "label": "bull_flags:time=train_60",
            "target_multiple": 0.46,
            "target_hit_rate": 80.0,
            "target_hit_ci_low": 69.0,
            "target_first_before_adverse_5pct_rate": 51.0,
            "failure_5pct_rate": 14.0,
            "n": 66,
        },
        {
            "label": "bull_flags:time=validation_20",
            "target_multiple": 0.46,
            "target_hit_rate": 50.0,
            "target_hit_ci_low": 31.0,
            "target_first_before_adverse_5pct_rate": 23.0,
            "failure_5pct_rate": 45.0,
            "n": 22,
        },
        {
            "label": "bull_flags:time=holdout_20",
            "target_multiple": 0.46,
            "target_hit_rate": 59.0,
            "target_hit_ci_low": 39.0,
            "target_first_before_adverse_5pct_rate": 36.0,
            "failure_5pct_rate": 36.0,
            "n": 22,
        },
    ]
    report = {
        "target_sensitivity": rows,
        "target_calibration_decisions": build_target_calibration_decisions(rows),
        "data_gate_audits": {"bull_flags": {"blocked_by": [], "investment_reference_data_gates_pass": True}},
    }

    checks = build_bull_flag_robustness_checks(report)
    by_id = {row["check_id"]: row for row in checks}

    assert by_id["regime_split_consistency"]["status"] == "fail"
    assert by_id["time_holdout_consistency"]["status"] == "fail"
    assert "time_holdout_consistency" in by_id["classification_after_robustness"]["evidence"]["noncritical_fail_checks"]
