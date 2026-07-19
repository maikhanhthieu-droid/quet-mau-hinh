from pathlib import Path

import pytest

from scanner.after_buy_source_grounding import DEFAULT_AFTER_BUY_PDF
from scanner.build_after_buy_bull_pennants_rules import (
    REQUIRED_SOURCE_SECTIONS,
    build_after_buy_bull_pennants_rules,
)


def test_bull_pennants_after_buy_rules_lock_near_threshold_no_overlift(tmp_path: Path) -> None:
    if not DEFAULT_AFTER_BUY_PDF.exists():
        pytest.skip("Missing After-the-Buy PDF")

    source_map_path = tmp_path / "source" / "after_buy_source_map.json"
    out_dir = tmp_path / "bull_pennants"
    result = build_after_buy_bull_pennants_rules(
        source_map_path=source_map_path,
        out_dir=out_dir,
    )

    assert result["status"] == "PASS"
    assert result["pattern_id"] == "bull_pennants"
    assert result["source_chapter"]["source_title"] == "Flags and Pennants"
    assert result["pattern_buy_role"]["buy_layer_allowed"] is True

    section_titles = {section["title"] for section in result["source_chapter"]["sections"]}
    assert set(REQUIRED_SOURCE_SECTIONS).issubset(section_titles)

    assert result["source_notes"]["available"] is True
    assert result["source_notes"]["source_review_status"] == "PASS"
    assert "bp.shape.converging_lines" in result["source_notes"]["rule_ids"]

    rule_ids = {rule["rule_id"] for rule in result["source_rules"]}
    assert "atb.bp.flagpole_vigor" in rule_ids
    assert "atb.bp.confirmed_close_breakout" in rule_ids
    assert "bp.shape.converging_lines" in rule_ids
    assert "bp.target.pole_projection_conservative" in rule_ids

    scorecard = result["current_evidence"]["scorecard"]
    ceiling = result["current_evidence"]["ceiling_audit"]
    assert scorecard["score"] is not None
    assert ceiling["best_score"] is not None
    assert scorecard["score"] < 95.0
    assert ceiling["best_score"] < 95.0
    assert ceiling["main_blocker"] == "walk_forward_has_negative_fold"
    assert "Stop optimization under no-overlift guard" in result["phase_b_action"]

    contract = result["local_buy_contract"]
    assert "0.75x selected local stretch target" in contract["target_family"]
    assert "walk-forward fold returns" in contract["must_keep_metrics"]
    assert "Do not promote" in contract["no_overlift_decision"]

    assert (out_dir / "bull_pennants_after_buy_rules.json").exists()
    assert (out_dir / "bull_pennants_after_buy_rules.md").exists()
