from pathlib import Path

import pytest

from scanner.after_buy_source_grounding import DEFAULT_AFTER_BUY_PDF
from scanner.build_after_buy_broadening_bottoms_rules import (
    REQUIRED_SOURCE_SECTIONS,
    build_after_buy_broadening_bottoms_rules,
)


def test_broadening_bottoms_after_buy_rules_lock_watchlist_not_promotion(tmp_path: Path) -> None:
    if not DEFAULT_AFTER_BUY_PDF.exists():
        pytest.skip("Missing After-the-Buy PDF")

    source_map_path = tmp_path / "source" / "after_buy_source_map.json"
    out_dir = tmp_path / "broadening_bottoms"
    result = build_after_buy_broadening_bottoms_rules(
        source_map_path=source_map_path,
        out_dir=out_dir,
    )

    assert result["status"] == "PASS"
    assert result["pattern_id"] == "broadening_bottoms"
    assert result["source_chapter"]["source_title"] == "Broadening Bottoms"
    assert result["pattern_buy_role"]["buy_layer_allowed"] is True

    section_titles = {section["title"] for section in result["source_chapter"]["sections"]}
    assert set(REQUIRED_SOURCE_SECTIONS).issubset(section_titles)

    assert result["source_notes"]["available"] is True
    assert result["source_notes"]["source_review_status"] == "PASS"

    rule_ids = {rule["rule_id"] for rule in result["source_rules"]}
    assert "atb.bb.two_sided_behavior" in rule_ids
    assert "atb.bb.buy_setup_not_aggregate" in rule_ids
    assert "atb.bb.sell_setup_caveat" in rule_ids
    assert "bb.shape.megaphone" in rule_ids
    assert "bb.role.reference_not_trade_promise" in rule_ids

    branch = result["current_evidence"]["branch_optimization_layer"]
    assert branch["score"] is not None
    assert branch["score"] < 95.0
    assert "walk_forward_has_negative_fold" in branch["promotion_blockers"]

    contract = result["local_buy_contract"]
    assert "BUY-watchlist/reference" in contract["scope"]
    assert "walk-forward fold returns" in contract["must_keep_metrics"]
    assert "Do not promote" in contract["no_overlift_decision"]
    assert "blocked by scope and negative walk-forward folds" in result["phase_c_action"]

    assert (out_dir / "broadening_bottoms_after_buy_rules.json").exists()
    assert (out_dir / "broadening_bottoms_after_buy_rules.md").exists()
