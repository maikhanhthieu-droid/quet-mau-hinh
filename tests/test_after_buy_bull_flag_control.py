from pathlib import Path

import pytest

from scanner.after_buy_source_grounding import DEFAULT_AFTER_BUY_PDF
from scanner.build_after_buy_bull_flag_control import (
    REQUIRED_SOURCE_SECTIONS,
    build_after_buy_bull_flag_control,
)


REQUIRED_BULL_FLAG_ARTIFACTS = (
    Path("artifacts/scanner_v2/bull_flags_tradable_setup/bull_flag_tradable_scorecard.json"),
    Path("artifacts/scanner_v2/bull_flags_tradable_setup/bull_flag_tradable_selected_strategy.json"),
    Path("artifacts/scanner_v2/bull_flags_release_candidate/bull_flag_release_candidate.json"),
)


def _skip_if_inputs_missing() -> None:
    missing = [path for path in (DEFAULT_AFTER_BUY_PDF, *REQUIRED_BULL_FLAG_ARTIFACTS) if not path.exists()]
    if missing:
        pytest.skip(f"Missing After-the-Buy or Bull Flag benchmark artifacts: {missing}")


def test_bull_flag_after_buy_control_preserves_benchmark(tmp_path: Path) -> None:
    _skip_if_inputs_missing()
    source_map_path = tmp_path / "source" / "after_buy_source_map.json"
    out_dir = tmp_path / "bull_flags_control"

    result = build_after_buy_bull_flag_control(
        source_map_path=source_map_path,
        out_dir=out_dir,
    )

    assert result["status"] == "PASS"
    assert result["pattern_id"] == "bull_flags"
    assert result["source_chapter"]["source_title"] == "Flags and Pennants"

    section_titles = {section["title"] for section in result["source_chapter"]["sections"]}
    assert set(REQUIRED_SOURCE_SECTIONS).issubset(section_titles)

    rule_ids = {rule["rule_id"] for rule in result["source_rules"]}
    assert len(rule_ids) >= 10
    assert "atb.flags.avoid_bottom_of_flag_naive_stop" in rule_ids
    assert "atb.flags.measure_rule_is_guideline" in rule_ids
    assert "atb.flags.primary_uptrend_preferred" in rule_ids

    benchmark = result["benchmark_control"]
    assert benchmark["benchmark_preserved"] is True
    assert benchmark["benchmark_score"] >= 95.0
    assert benchmark["release_status"] == "PASS"
    assert benchmark["entry_rule"]
    assert benchmark["target_rule"] == "0.46x local Bull Flag pole target"
    assert benchmark["stop_rule"] == "first target, stop, or max holding day; same-bar target/stop uses stop-first"

    policy = result["local_buy_adaptation"]["policy"]
    assert "Vietnam long-cash BUY control" in policy
    assert "no short-selling assumption" in policy

    assert result["source_allowed_mapping"]["pattern_buy_role"]["buy_layer_allowed"] is True
    assert (out_dir / "bull_flag_after_buy_control.json").exists()
    assert (out_dir / "bull_flag_after_buy_control.md").exists()
