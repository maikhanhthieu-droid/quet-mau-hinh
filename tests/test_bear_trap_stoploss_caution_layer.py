from pathlib import Path

from scanner.build_bear_trap_stoploss_caution_layer import (
    PATTERN_SPECS,
    _build_one_pattern_cautions,
    build_bear_trap_stoploss_caution_layer,
)


def test_bear_trap_caution_builder_keeps_reclaim_as_risk_observation() -> None:
    events, summary = _build_one_pattern_cautions("bear_flags", reclaim_window_bars=20)

    assert summary["status"] == "complete"
    assert summary["source_events"] > 0
    assert summary["caution_events"] == len(events)
    assert summary["tradable_promotion_allowed"] is False
    assert len(events) > 0

    first = events.iloc[0]
    assert first["source_breakdown_date"] != first["reclaim_date"]
    assert first["reclaim_level_source"] in {"flag_lower_breakout_value", "breakout_price"}
    assert first["stoploss_caution_action"] == "watch_reclaim_before_treating_breakdown_as_clean"
    assert first["allowed_use"] == "risk_management_context_only"
    assert first["forbidden_use"] == "buy_setup_or_tradable_promotion"


def test_bear_trap_caution_layer_writes_no_tradable_artifacts(tmp_path: Path) -> None:
    report = build_bear_trap_stoploss_caution_layer(out_dir=tmp_path, patterns=("bear_flags",), reclaim_window_bars=20)

    assert report["status"] == "PASS"
    assert report["policy"]["replaces"] == "bear_trap_long_branch_v1"
    assert report["policy"]["forbidden_use"] == "BUY setup, long-cash promotion, tradable-final scoring"
    assert report["summary"]["tradable_promotion_allowed"] is False

    pattern_dir = tmp_path / "bear_flags"
    assert (pattern_dir / "stoploss_caution_events.csv").exists()
    assert (pattern_dir / "stoploss_caution_summary.json").exists()
    assert (tmp_path / "bear_trap_stoploss_caution_report.md").exists()
    assert (tmp_path / "bear_trap_stoploss_caution_summary.csv").exists()

    assert not (pattern_dir / "release_candidate.json").exists()
    assert not (pattern_dir / "selected_trades.csv").exists()
    assert not (pattern_dir / "strategy_grid.csv").exists()


def test_bear_trap_caution_default_scope_covers_defensive_patterns(tmp_path: Path) -> None:
    report = build_bear_trap_stoploss_caution_layer(out_dir=tmp_path)

    assert report["summary"]["pattern_count"] == 18
    assert report["summary"]["caution_pattern_count"] == 18
    assert report["summary"]["source_specific_measurable_count"] == 18
    assert report["summary"]["breakout_fallback_only_count"] == 0
    assert report["summary"]["not_measurable_count"] == 0
    assert set(PATTERN_SPECS).issuperset(
        {
            "bear_flags",
            "bear_pennants",
            "triangles_descending",
            "double_tops_adam_adam",
            "double_tops_adam_eve",
            "double_tops_eve_adam",
            "double_tops_eve_eve",
            "head_and_shoulders_tops",
            "head_and_shoulders_tops_complex",
            "measured_move_down",
            "rectangle_tops",
            "broadening_tops",
            "pipe_tops",
            "triple_tops",
            "bump_and_run_reversal_tops",
            "rounding_tops",
            "horn_tops",
            "diamond_tops",
        }
    )
