from pathlib import Path

import pytest

from scanner.after_buy_source_grounding import DEFAULT_AFTER_BUY_PDF
from scanner.build_after_buy_measured_move_up_rules import (
    REQUIRED_SOURCE_SECTIONS,
    build_after_buy_measured_move_up_rules,
)


def test_measured_move_up_after_buy_rules_preserve_tradable_final_contract(tmp_path: Path) -> None:
    if not DEFAULT_AFTER_BUY_PDF.exists():
        pytest.skip("Missing After-the-Buy PDF")

    source_map_path = tmp_path / "source" / "after_buy_source_map.json"
    out_dir = tmp_path / "measured_move_up"
    result = build_after_buy_measured_move_up_rules(
        source_map_path=source_map_path,
        out_dir=out_dir,
    )

    assert result["status"] == "PASS"
    assert result["pattern_id"] == "measured_move_up"
    assert result["source_chapter"]["source_title"] == "Measured Move Up"
    assert result["pattern_buy_role"]["buy_layer_allowed"] is True

    section_titles = {section["title"] for section in result["source_chapter"]["sections"]}
    assert set(REQUIRED_SOURCE_SECTIONS).issubset(section_titles)

    assert result["source_notes"]["available"] is True
    assert result["source_notes"]["source_review_status"] == "PASS"
    assert "mmu.corrective.retrace" in result["source_notes"]["rule_ids"]

    rule_ids = {rule["rule_id"] for rule in result["source_rules"]}
    assert "atb.mmu.three_part_behavior" in rule_ids
    assert "atb.mmu.after_pattern_second_leg" in rule_ids
    assert "atb.mmu.measure_rule_practical_target" in rule_ids
    assert "mmu.first_leg.straight" in rule_ids
    assert "mmu.avoid.sawtooth" in rule_ids

    evidence = result["current_evidence"]
    assert evidence["scorecard"]["score"] >= 95.0
    assert evidence["scorecard"]["promotion_blockers"] == []
    assert evidence["release_candidate"]["release_status"] == "PASS"
    assert evidence["selected_strategy"]["target_multiple"] == 0.5
    assert evidence["selected_strategy"]["allowed_source_retrace_bands"] == ["ideal_38_62"]
    assert evidence["selected_strategy"]["min_first_leg_linearity_r2"] == 0.8

    contract = result["local_buy_contract"]
    assert contract["tradable_final_95_supported"] is True
    assert "0.5x first-leg executable base" in contract["target_family"]
    assert "fixed walk-forward positive folds" in contract["must_keep_metrics"]

    assert (out_dir / "measured_move_up_after_buy_rules.json").exists()
    assert (out_dir / "measured_move_up_after_buy_rules.md").exists()
