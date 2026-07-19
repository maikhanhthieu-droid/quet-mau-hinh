from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd

from scanner.double_pattern_utils import _classify_extreme_shape
from scanner.digitized_pattern_engine import (
    CupWithHandleScanner,
    DoubleBottomFamilyScanner,
    DoubleTopFamilyScanner,
    GapScanner,
    HeadShouldersBottomFamilyScanner,
    InvertedCupWithHandleScanner,
    IslandScanner,
    MeasuredMoveScanner,
    PivotType,
    RoundingBottomsTopsScanner,
    ScallopFamilyScanner,
    TriangleFamilyScanner,
    _HeadShouldersFamilyScanner,
)


def test_double_gap_midpoint_width_stays_unresolved() -> None:
    result = _classify_extreme_shape(width=5, reaction_pct=10.0, adam_max=3, eve_min=7)
    assert result["label"] is None
    assert "gap_not_resolved" in result["evidence"]


def test_double_gap_midpoint_width_can_resolve_to_eve_when_extra_rounded() -> None:
    result = _classify_extreme_shape(width=5, reaction_pct=2.2, adam_max=3, eve_min=7)
    assert result["label"] == "E"
    assert "mid_gap_resolved_toward_eve_by_extra_roundness" in result["evidence"]


def test_double_near_threshold_widths_still_resolve() -> None:
    near_adam = _classify_extreme_shape(width=4, reaction_pct=4.5, adam_max=3, eve_min=7)
    near_eve = _classify_extreme_shape(width=6, reaction_pct=3.0, adam_max=3, eve_min=7)
    assert near_adam["label"] == "A"
    assert near_eve["label"] == "E"


def test_double_bottom_aa_rejects_flat_illiquid_microstructure() -> None:
    scanner = DoubleBottomFamilyScanner("double_bottoms", {})
    ok = scanner._variant_metrics_ok(
        {
            "same_close_ratio": 0.55,
            "unique_close_ratio": 0.22,
            "zero_range_ratio": 0.68,
        },
        {"variant_code": "AA"},
    )
    assert ok is False


def test_double_bottom_non_aa_bypasses_aa_flat_microstructure_gate() -> None:
    scanner = DoubleBottomFamilyScanner("double_bottoms", {})
    ok = scanner._variant_metrics_ok(
        {
            "same_close_ratio": 0.55,
            "unique_close_ratio": 0.22,
            "zero_range_ratio": 0.68,
        },
        {"variant_code": "AE"},
    )
    assert ok is True


def test_double_top_aa_rejects_shallow_uneven_twin_peaks() -> None:
    scanner = DoubleTopFamilyScanner("double_tops", {})
    ok = scanner._variant_metrics_ok(
        {
            "extreme_price_diff_pct": 0.31,
            "extreme_slope_deg": 0.22,
            "middle_depth_pct": 12.0,
        },
        {"variant_code": "AA"},
    )
    assert ok is False


def test_double_top_aa_keeps_deeper_twin_peaks() -> None:
    scanner = DoubleTopFamilyScanner("double_tops", {})
    ok = scanner._variant_metrics_ok(
        {
            "extreme_price_diff_pct": 0.31,
            "extreme_slope_deg": 0.22,
            "middle_depth_pct": 18.0,
        },
        {"variant_code": "AA"},
    )
    assert ok is True


def test_hs_bottom_single_extra_shoulder_is_demoted_to_standard(monkeypatch) -> None:
    scanner = HeadShouldersBottomFamilyScanner("head_and_shoulders_bottom", {})

    def fake_classify(self, **kwargs):  # type: ignore[no-untyped-def]
        return {
            "variant_code": "complex",
            "variant_confidence": 76,
            "evidence": {
                "extra_shoulders_total": 1,
                "width_exceeds_standard_max": False,
            },
        }

    monkeypatch.setattr(_HeadShouldersFamilyScanner, "_classify_variant", fake_classify)
    result = scanner._classify_variant(row={}, metrics={}, pivots_filtered=[], pivots_raw=[])
    assert result["variant_code"] == "standard"
    assert result["variant_confidence"] == 68
    assert result["evidence"]["single_extra_demoted_to_standard"] is True


def test_hs_bottom_failures_report_clearance_shortfall() -> None:
    scanner = HeadShouldersBottomFamilyScanner("head_and_shoulders_bottom", {})
    failures = scanner._family_gate_failures(
        {
            "shoulder_diff_pct": 1.0,
            "shoulder_ratio": 1.0,
            "head_prominence_pct": 4.0,
            "shoulder_clearance_pct": 6.5,
            "height_pct": 16.0,
            "neckline_slope_deg": 0.5,
            "side_span_ratio": 1.4,
            "same_close_ratio": 0.2,
            "unique_close_ratio": 0.4,
            "zero_range_ratio": 0.1,
        }
    )
    assert any(f.get("rule") == "bottom_shoulder_clearance_pct" for f in failures)


def test_hs_bottom_allows_mild_neckline_slope_when_other_metrics_are_clean() -> None:
    scanner = HeadShouldersBottomFamilyScanner("head_and_shoulders_bottom", {})
    failures = scanner._family_gate_failures(
        {
            "shoulder_diff_pct": 1.7,
            "shoulder_ratio": 0.9835,
            "head_prominence_pct": 6.0,
            "shoulder_clearance_pct": 8.2,
            "height_pct": 14.8,
            "neckline_slope_deg": 2.77,
            "neckline_diff_pct": 3.56,
            "side_span_ratio": 1.38,
            "same_close_ratio": 0.18,
            "unique_close_ratio": 0.23,
            "zero_range_ratio": 0.01,
        }
    )
    assert not any(f.get("rule") == "neckline_slope_deg" for f in failures)


def test_hs_bottom_relaxed_neckline_does_not_bypass_large_shoulder_mismatch() -> None:
    scanner = HeadShouldersBottomFamilyScanner("head_and_shoulders_bottom", {})
    failures = scanner._family_gate_failures(
        {
            "shoulder_diff_pct": 9.7,
            "shoulder_ratio": 0.9116,
            "head_prominence_pct": 4.7,
            "shoulder_clearance_pct": 9.5,
            "height_pct": 14.8,
            "neckline_slope_deg": 2.57,
            "neckline_diff_pct": 2.34,
            "side_span_ratio": 1.42,
            "same_close_ratio": 0.15,
            "unique_close_ratio": 0.53,
            "zero_range_ratio": 0.01,
        }
    )
    assert any(f.get("rule") == "neckline_slope_deg" for f in failures)
    assert any(f.get("rule") == "shoulder_diff_pct" for f in failures)


def test_scallop_descending_requires_stronger_bearish_shift() -> None:
    scanner = ScallopFamilyScanner("scallops", {})
    weak_metrics = {
        "sequence_tag": "HLH",
        "overall_shift_pct": -2.5,
        "left_share_pct": 60.0,
        "left_leg_deg": -28.0,
        "right_leg_deg": 36.0,
        "arc_excursion_pct": 82.0,
        "left_directional_ratio": 0.52,
        "right_directional_ratio": 0.55,
    }
    strong_metrics = dict(weak_metrics, overall_shift_pct=-6.5)

    assert scanner._resolve_variant(weak_metrics, breakout_direction="down") is None
    resolved = scanner._resolve_variant(strong_metrics, breakout_direction="down")
    assert resolved is not None
    assert resolved["variant_code"] == "scallops_descending"


def test_scallop_descending_requires_deeper_arc_excursion() -> None:
    scanner = ScallopFamilyScanner("scallops", {})
    metrics = {
        "sequence_tag": "HLH",
        "overall_shift_pct": -6.5,
        "left_share_pct": 60.0,
        "left_leg_deg": -28.0,
        "right_leg_deg": 36.0,
        "arc_excursion_pct": 55.0,
        "left_directional_ratio": 0.52,
        "right_directional_ratio": 0.55,
    }
    assert scanner._resolve_variant(metrics, breakout_direction="down") is None

    metrics["arc_excursion_pct"] = 68.0
    resolved = scanner._resolve_variant(metrics, breakout_direction="down")
    assert resolved is not None
    assert resolved["variant_code"] == "scallops_descending"


def test_scallop_ascending_inverted_requires_stronger_positive_shift() -> None:
    scanner = ScallopFamilyScanner("scallops", {})
    metrics = {
        "sequence_tag": "HLH",
        "overall_shift_pct": 4.6,
        "left_share_pct": 60.0,
        "left_leg_deg": -30.0,
        "right_leg_deg": 38.0,
        "arc_excursion_pct": 82.0,
        "left_directional_ratio": 0.55,
        "right_directional_ratio": 0.58,
    }
    assert scanner._resolve_variant(metrics, breakout_direction="down") is None

    metrics["overall_shift_pct"] = 5.4
    resolved = scanner._resolve_variant(metrics, breakout_direction="down")
    assert resolved is not None
    assert resolved["variant_code"] == "scallops_ascending_inverted"


def test_scallop_ascending_inverted_review_gate_rejects_weak_left_leg() -> None:
    scanner = ScallopFamilyScanner("scallops", {})
    ok = scanner._variant_metrics_ok(
        {
            "left_share_pct": 64.0,
            "overall_shift_pct": 7.0,
            "left_leg_deg": -18.8,
            "right_directional_ratio": 0.55,
        },
        {"variant_code": "scallops_ascending_inverted"},
    )
    assert ok is False


def test_scallop_ascending_inverted_review_gate_keeps_cleaner_case() -> None:
    scanner = ScallopFamilyScanner("scallops", {})
    ok = scanner._variant_metrics_ok(
        {
            "left_share_pct": 60.0,
            "overall_shift_pct": 7.0,
            "left_leg_deg": -24.0,
            "right_directional_ratio": 0.58,
        },
        {"variant_code": "scallops_ascending_inverted"},
    )
    assert ok is True


def test_gap_classifier_marks_breakaway_from_consolidation() -> None:
    scanner = GapScanner("gaps", {})
    result = scanner._classify_gap_variant(
        {
            "direction": "up",
            "gap_pct": 0.85,
            "volume_ratio": 1.6,
            "prior_change_10_pct": 2.1,
            "prior_change_20_pct": 2.4,
            "recent_range_10_pct": 3.8,
            "directional_ratio_10": 0.56,
        }
    )
    assert result["variant_code"] == "breakaway_gap_up"


def test_gap_classifier_marks_exhaustion_after_extended_trend() -> None:
    scanner = GapScanner("gaps", {})
    result = scanner._classify_gap_variant(
        {
            "direction": "up",
            "gap_pct": 1.15,
            "volume_ratio": 1.9,
            "prior_change_10_pct": 9.8,
            "prior_change_20_pct": 14.2,
            "recent_range_10_pct": 9.0,
            "directional_ratio_10": 0.81,
        }
    )
    assert result["variant_code"] == "exhaustion_gap_up"


def test_gap_classifier_keeps_small_flat_gap_as_common() -> None:
    scanner = GapScanner("gaps", {})
    result = scanner._classify_gap_variant(
        {
            "direction": "down",
            "gap_pct": 0.22,
            "volume_ratio": 0.9,
            "prior_change_10_pct": -1.0,
            "prior_change_20_pct": -1.8,
            "recent_range_10_pct": 5.1,
            "directional_ratio_10": 0.51,
        }
    )
    assert result["variant_code"] == "common_gap_down"


def _island_test_spec() -> dict:
    return {
        "geometry_constraints": {
            "height_ratio_min": 1.0,
            "height_ratio_max": 20.0,
            "width_min_bars": 3,
            "width_max_bars": 10,
            "gap_constraints": {
                "min_gap_size_pct": 0.5,
                "max_gap_size_pct": 10.0,
                "gap_similarity_pct": 50.0,
            },
            "island_duration": {"min_bars": 1, "max_bars": 10},
            "price_separation": {"min_separation_pct": 0.5},
        },
        "duration_constraints": {"min_bars": 3, "max_bars": 12},
        "prior_trend_requirements": {"min_period_bars": 3, "min_change_pct": 3.0},
        "breakout_confirmation": {"volume_multiplier_min": 1.1},
    }


def _clean_island_df(overlap: bool) -> pd.DataFrame:
    lows = [97.0, 98.0, 100.0, 103.0, 108.0, 108.6, 105.6]
    if overlap:
        lows[5] = 107.4
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=7, freq="D"),
            "open": [98.0, 99.0, 101.0, 104.0, 108.5, 109.5, 106.5],
            "high": [99.0, 101.0, 104.0, 107.0, 110.0, 111.0, 107.4],
            "low": lows,
            "close": [98.0, 100.0, 103.0, 106.0, 109.0, 110.0, 106.0],
            "volume_ratio": [1.0, 1.0, 1.0, 1.0, 1.3, 1.0, 1.4],
        }
    )


def test_island_scanner_accepts_clean_island_top_candidate() -> None:
    scanner = IslandScanner("islands", _island_test_spec())
    row = scanner._build_candidate(symbol="AAA", df=_clean_island_df(overlap=False), entry_idx=4, exit_idx=6, direction="down")
    assert row is not None
    assert row["variant_code"] == "island_top"
    assert row["breakout_direction"] == "down"


def test_island_scanner_rejects_overlap_back_into_mainland() -> None:
    scanner = IslandScanner("islands", _island_test_spec())
    row = scanner._build_candidate(symbol="AAA", df=_clean_island_df(overlap=True), entry_idx=4, exit_idx=6, direction="down")
    assert row is None


def test_triangle_ascending_rejects_loose_upper_boundary() -> None:
    scanner = TriangleFamilyScanner("triangles", {})
    metrics = {
        "upper_slope_deg": 1.8,
        "lower_slope_deg": 9.0,
        "apex_progress_pct": 62.0,
        "compression_ratio": 0.36,
        "boundary_fit_error_pct": 12.0,
        "sequence_tag": "HLHLH",
    }
    assert scanner._resolve_variant(metrics) is None


def test_triangle_ascending_keeps_tighter_flat_top_case() -> None:
    scanner = TriangleFamilyScanner("triangles", {})
    metrics = {
        "upper_slope_deg": 0.8,
        "lower_slope_deg": 9.0,
        "apex_progress_pct": 62.0,
        "compression_ratio": 0.36,
        "boundary_fit_error_pct": 12.0,
        "sequence_tag": "HLHLH",
    }
    resolved = scanner._resolve_variant(metrics)
    assert resolved is not None
    assert resolved["variant_code"] == "ascending"


def test_measured_move_up_accepts_balanced_three_phase_candidate() -> None:
    scanner = MeasuredMoveScanner("measured_move_down_up", {})
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=45, freq="D"),
            "open": [100.0] * 45,
            "high": [101.0] * 45,
            "low": [99.0] * 45,
            "close": [100.0] * 45,
            "volume_ratio": [1.0] * 45,
        }
    )
    df.loc[0, "low"] = 100.0
    df.loc[20, "high"] = 120.0
    df.loc[35, "low"] = 110.0
    df.loc[38, "close"] = 122.0
    df.loc[39, "close"] = 123.0
    df.loc[38, "volume_ratio"] = 1.4

    pivots = [
        SimpleNamespace(idx=0, type=PivotType.LOW),
        SimpleNamespace(idx=20, type=PivotType.HIGH),
        SimpleNamespace(idx=35, type=PivotType.LOW),
    ]
    candidate = scanner._candidate(df, pivots)
    assert candidate is not None
    assert candidate["variant_code"] == "measured_move_up"
    assert candidate["breakout_direction"] == "up"


def test_measured_move_rejects_shallow_retracement() -> None:
    scanner = MeasuredMoveScanner("measured_move_down_up", {})
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=45, freq="D"),
            "open": [100.0] * 45,
            "high": [101.0] * 45,
            "low": [99.0] * 45,
            "close": [100.0] * 45,
            "volume_ratio": [1.0] * 45,
        }
    )
    df.loc[0, "low"] = 100.0
    df.loc[20, "high"] = 120.0
    df.loc[35, "low"] = 116.0
    df.loc[38, "close"] = 122.0
    df.loc[39, "close"] = 123.0

    pivots = [
        SimpleNamespace(idx=0, type=PivotType.LOW),
        SimpleNamespace(idx=20, type=PivotType.HIGH),
        SimpleNamespace(idx=35, type=PivotType.LOW),
    ]
    assert scanner._candidate(df, pivots) is None


def test_rounding_top_uses_tighter_second_pass_gate() -> None:
    scanner = RoundingBottomsTopsScanner(
        "rounding_bottoms_tops",
        {"detection_signature": {"pivot_sequence": ["L", "H", "L", "H", "L", "H"]}},
    )
    metrics = {
        "variant_tag": "top",
        "width_bars": 100,
        "center_pos_pct": 50.0,
        "span_balance_ratio": 1.3,
        "center_clearance_pct": 8.0,
        "fit_error_pct": 15.0,
        "monotonic_left_ratio": 0.6,
        "monotonic_right_ratio": 0.6,
        "curvature_coeff": -1.0,
        "expected_curvature_sign": -1.0,
    }
    assert scanner._family_metrics_ok(metrics) is False

    metrics["width_bars"] = 78
    assert scanner._family_metrics_ok(metrics) is True


def test_rounding_top_rejects_excess_trend_progress() -> None:
    scanner = RoundingBottomsTopsScanner(
        "rounding_bottoms_tops",
        {"detection_signature": {"pivot_sequence": ["L", "H", "L", "H", "L", "H"]}},
    )
    metrics = {
        "variant_tag": "top",
        "width_bars": 68,
        "center_pos_pct": 50.0,
        "span_balance_ratio": 1.3,
        "center_clearance_pct": 8.0,
        "fit_error_pct": 15.0,
        "monotonic_left_ratio": 0.6,
        "monotonic_right_ratio": 0.6,
        "curvature_coeff": -1.0,
        "expected_curvature_sign": -1.0,
        "mid_progress_pct": 12.0,
        "trend_progress_pct": 12.5,
    }
    assert scanner._family_metrics_ok(metrics) is False


def test_inverted_cup_rejects_handle_that_rebounds_too_high(monkeypatch) -> None:
    scanner = InvertedCupWithHandleScanner("cup_with_handle_inverted", {})
    df = pd.DataFrame(
        {
            "open": [101.0, 108.0, 118.0, 110.0, 101.0, 106.0, 95.0],
            "high": [103.0, 112.0, 120.0, 115.0, 103.0, 110.0, 96.0],
            "low": [100.0, 102.0, 110.0, 105.0, 100.0, 102.0, 93.0],
            "close": [102.0, 110.0, 118.0, 108.0, 101.0, 104.0, 94.0],
        }
    )

    row = {
        "pivot_indices": [0, 2, 4, 5, 5],
        "breakout_idx": 6,
        "family_metrics_json": json.dumps(
            {"handle_slope_pct": 0.0, "breakout_lag_bars": 1, "rim_diff_pct": 5.0},
            sort_keys=True,
        ),
    }

    monkeypatch.setattr(CupWithHandleScanner, "scan", lambda self, **kwargs: [row])
    result = scanner.scan(symbol="XYZ", df=df, pivots_filtered=[], pivots_raw=[])
    assert result == []


def test_inverted_cup_keeps_original_space_metrics_for_survivor(monkeypatch) -> None:
    scanner = InvertedCupWithHandleScanner("cup_with_handle_inverted", {})
    df = pd.DataFrame(
        {
            "open": [101.0, 108.0, 118.0, 110.0, 101.0, 104.0, 95.0],
            "high": [103.0, 112.0, 120.0, 115.0, 103.0, 106.0, 96.0],
            "low": [100.0, 102.0, 110.0, 105.0, 100.0, 102.0, 93.0],
            "close": [102.0, 110.0, 118.0, 108.0, 101.0, 104.0, 94.0],
        }
    )

    row = {
        "pivot_indices": [0, 2, 4, 5, 5],
        "breakout_idx": 6,
        "family_metrics_json": json.dumps(
            {"handle_slope_pct": 0.0, "breakout_lag_bars": 1, "rim_diff_pct": 5.0},
            sort_keys=True,
        ),
    }

    monkeypatch.setattr(CupWithHandleScanner, "scan", lambda self, **kwargs: [dict(row)])
    result = scanner.scan(symbol="XYZ", df=df, pivots_filtered=[], pivots_raw=[])
    assert len(result) == 1
    family_metrics = json.loads(result[0]["family_metrics_json"])
    assert family_metrics["orig_handle_rebound_pct"] == 6.0
    assert family_metrics["orig_handle_ceiling_pct"] == 30.0
    assert result[0]["breakout_direction"] == "down"
