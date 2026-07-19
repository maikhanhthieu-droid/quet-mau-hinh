from pathlib import Path

import pytest

from scanner.after_buy_source_grounding import DEFAULT_AFTER_BUY_PDF
from scanner.build_after_buy_head_shoulders_bottoms_rules import (
    REQUIRED_SOURCE_SECTIONS,
    build_after_buy_head_shoulders_bottoms_rules,
)


def test_head_shoulders_bottoms_after_buy_rules_are_source_grounded(tmp_path: Path) -> None:
    if not DEFAULT_AFTER_BUY_PDF.exists():
        pytest.skip("Missing After-the-Buy PDF")

    source_map_path = tmp_path / "source" / "after_buy_source_map.json"
    out_dir = tmp_path / "head_shoulders_bottoms"
    result = build_after_buy_head_shoulders_bottoms_rules(
        source_map_path=source_map_path,
        out_dir=out_dir,
    )

    assert result["status"] == "PASS"
    assert result["source_chapter"]["source_title"] == "Head-and-Shoulders Bottoms"

    section_titles = {section["title"] for section in result["source_chapter"]["sections"]}
    assert set(REQUIRED_SOURCE_SECTIONS).issubset(section_titles)

    pattern_rows = {row["pattern_id"]: row for row in result["patterns"]}
    assert set(pattern_rows) == {"head_and_shoulders_bottoms", "head_and_shoulders_bottoms_complex"}
    assert pattern_rows["head_and_shoulders_bottoms"]["buy_role"]["buy_layer_allowed"] is True
    assert pattern_rows["head_and_shoulders_bottoms_complex"]["buy_role"]["buy_layer_allowed"] is True

    rule_ids = {rule["rule_id"] for rule in result["source_rules"]}
    assert len(rule_ids) >= 12
    assert "atb.hsb.confirmed_neckline_breakout" in rule_ids
    assert "atb.hsb.short_inbound_trend_preferred" in rule_ids
    assert "atb.hsb.overhead_resistance_filter" in rule_ids
    assert "atb.hsb.stop_below_head_reference" in rule_ids
    assert "atb.hsb.measure_rule_half_height_diagnostic" in rule_ids

    contract = result["local_buy_contract"]
    assert contract["scope"] == "Vietnam long-cash BUY only."
    assert "target-first-before-adverse" in contract["must_keep_metrics"]
    assert "ABC correction risk" in contract["avoid_configurations"]

    complex_tradable = pattern_rows["head_and_shoulders_bottoms_complex"]["current_tradable"]
    if complex_tradable["score"] is not None:
        assert complex_tradable["score"] < 95.0
        assert pattern_rows["head_and_shoulders_bottoms_complex"]["phase_b_action"].startswith("Rerun with source-grounded")

    normal_governance = pattern_rows["head_and_shoulders_bottoms"]["governance_tradable"]
    if normal_governance["tradable_score"] is not None:
        assert normal_governance["tradable_score"] < 95.0
        assert normal_governance["tradable_status"] == "tradable_tested_blocked"

    assert (out_dir / "head_shoulders_bottoms_after_buy_rules.json").exists()
    assert (out_dir / "head_shoulders_bottoms_after_buy_rules.md").exists()
