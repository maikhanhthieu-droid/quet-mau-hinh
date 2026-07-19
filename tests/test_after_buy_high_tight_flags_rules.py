from pathlib import Path

import pytest

from scanner.after_buy_source_grounding import DEFAULT_AFTER_BUY_PDF
from scanner.build_after_buy_high_tight_flags_rules import (
    REQUIRED_SOURCE_SECTIONS,
    build_after_buy_high_tight_flags_rules,
)


def test_high_tight_flags_after_buy_rules_are_indirect_and_source_grounded(tmp_path: Path) -> None:
    if not DEFAULT_AFTER_BUY_PDF.exists():
        pytest.skip("Missing After-the-Buy PDF")

    source_map_path = tmp_path / "source" / "after_buy_source_map.json"
    out_dir = tmp_path / "high_tight_flags"
    result = build_after_buy_high_tight_flags_rules(
        source_map_path=source_map_path,
        out_dir=out_dir,
    )

    assert result["status"] == "PASS"
    assert result["pattern_id"] == "high_tight_flags"
    assert result["source_chapter"]["source_title"] == "Flags and Pennants"
    assert result["source_relationship"]["direct_after_buy_chapter_available"] is False
    assert result["direct_after_buy_reference_audit"]["match_count"] == 0
    assert "High-and-Tight morphology" in result["source_relationship"]["interpretation"]

    section_titles = {section["title"] for section in result["source_chapter"]["sections"]}
    assert set(REQUIRED_SOURCE_SECTIONS).issubset(section_titles)

    assert result["pattern_buy_role"]["buy_layer_allowed"] is True
    assert result["source_notes"]["available"] is True
    assert result["source_notes"]["source_review_status"] == "PASS"
    assert result["source_notes"]["rule_count"] >= 6

    rule_ids = {rule["rule_id"] for rule in result["source_rules"]}
    assert "atb.htf.indirect_after_buy_source" in rule_ids
    assert "atb.htf.flagpole_vigor" in rule_ids
    assert "atb.htf.confirmed_up_breakout_close" in rule_ids
    assert "htf.prior_trend.near_double" in rule_ids
    assert "htf.target.half_prior_move" in rule_ids

    contract = result["local_buy_contract"]
    assert "0.5x prior advance" in contract["target_family"][0]
    assert "walk-forward fold returns" in contract["must_keep_metrics"]
    assert "Do not claim a direct After-the-Buy High-and-Tight chapter." in contract["do_not_do"]

    branch = result["current_evidence"]["branch_optimization_layer"]
    if branch["score"] is not None:
        assert branch["score"] < 95.0
        assert "walk_forward_has_negative_fold" in branch["promotion_blockers"]
        assert "negative walk-forward folds" in result["phase_b_action"]

    assert (out_dir / "high_tight_flags_after_buy_rules.json").exists()
    assert (out_dir / "high_tight_flags_after_buy_rules.md").exists()
