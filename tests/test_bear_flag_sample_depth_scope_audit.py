from __future__ import annotations

from scanner.run_bear_flag_sample_depth_scope_audit import select_recommendation


def test_sample_depth_recommendation_keeps_current_when_uplift_is_not_material() -> None:
    rows = [
        {
            "scope_id": "active_current",
            "config_id": "default",
            "headline_n": 26,
            "headline_hit_rate": 69.23,
            "headline_failure_5pct_rate": 15.38,
            "headline_mfe_mae_ratio": 1.59,
            "quality_gate_pass": True,
        },
        {
            "scope_id": "active_current",
            "config_id": "height_wider",
            "headline_n": 27,
            "headline_hit_rate": 66.67,
            "headline_failure_5pct_rate": 18.52,
            "headline_mfe_mae_ratio": 1.46,
            "quality_gate_pass": True,
        },
        {
            "scope_id": "active_current",
            "config_id": "combo_wide",
            "headline_n": 86,
            "headline_hit_rate": 58.14,
            "headline_failure_5pct_rate": 25.58,
            "headline_mfe_mae_ratio": 1.32,
            "quality_gate_pass": False,
        },
    ]

    rec = select_recommendation(rows)

    assert rec["decision"] == "KEEP_CURRENT_HEADLINE_CONFIG"
    assert rec["best_quality_preserving"]["config_id"] == "height_wider"
    assert rec["best_depth_even_if_quality_fails"]["config_id"] == "combo_wide"


def test_sample_depth_recommendation_promotes_when_quality_and_n_materially_improve() -> None:
    rows = [
        {
            "scope_id": "active_current",
            "config_id": "default",
            "headline_n": 26,
            "headline_hit_rate": 69.23,
            "headline_failure_5pct_rate": 15.38,
            "headline_mfe_mae_ratio": 1.59,
            "quality_gate_pass": True,
        },
        {
            "scope_id": "active_current",
            "config_id": "better_depth",
            "headline_n": 34,
            "headline_hit_rate": 68.0,
            "headline_failure_5pct_rate": 16.0,
            "headline_mfe_mae_ratio": 1.4,
            "quality_gate_pass": True,
        },
    ]

    rec = select_recommendation(rows)

    assert rec["decision"] == "PROMOTE_SAMPLE_DEPTH_CONFIG"
    assert rec["best_quality_preserving"]["config_id"] == "better_depth"
