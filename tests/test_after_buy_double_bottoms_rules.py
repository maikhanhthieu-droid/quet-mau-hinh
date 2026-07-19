from pathlib import Path

import pytest

from scanner.after_buy_source_grounding import DEFAULT_AFTER_BUY_PDF
from scanner.build_after_buy_double_bottoms_rules import (
    DOUBLE_BOTTOM_VARIANTS,
    REQUIRED_SOURCE_SECTIONS,
    build_after_buy_double_bottoms_rules,
)


def test_double_bottoms_after_buy_rules_support_family_evidence(tmp_path: Path) -> None:
    if not DEFAULT_AFTER_BUY_PDF.exists():
        pytest.skip("Missing After-the-Buy PDF")

    source_map_path = tmp_path / "source" / "after_buy_source_map.json"
    out_dir = tmp_path / "double_bottoms"
    result = build_after_buy_double_bottoms_rules(source_map_path=source_map_path, out_dir=out_dir)

    assert result["status"] == "PASS"
    assert result["source_chapter"]["source_title"] == "Double Bottoms"

    section_titles = {section["title"] for section in result["source_chapter"]["sections"]}
    assert set(REQUIRED_SOURCE_SECTIONS).issubset(section_titles)

    pattern_rows = {row["pattern_id"]: row for row in result["patterns"]}
    assert set(pattern_rows) == set(DOUBLE_BOTTOM_VARIANTS)
    for row in pattern_rows.values():
        assert row["buy_role"]["buy_layer_allowed"] is True
        assert row["buy_role"]["buy_scope"] == "full_pattern_or_family_scope"

    rule_ids = {rule["rule_id"] for rule in result["source_rules"]}
    assert len(rule_ids) >= 11
    assert "atb.db.wait_for_confirmation" in rule_ids
    assert "atb.db.stop_below_lower_bottom" in rule_ids
    assert "atb.db.measure_rule_half_height_diagnostic" in rule_ids
    assert "atb.db.variant_as_subgroup_not_overfit_unit" in rule_ids

    rescue = result["family_rescue"]
    assert rescue["best_score"] >= 95.0
    assert rescue["decision"] == "family_tradable_evidence_is_stronger_than_thin_variant_evidence"
    assert rescue["variant_support_decision"] == "FAMILY_PROMOTION_REVIEW_VARIANTS_REMAIN_SUBGROUPS"

    assert pattern_rows["double_bottoms_adam_adam"]["phase_b_action"].startswith("Use as a strong variant")
    assert "family-level tradable evidence" in pattern_rows["double_bottoms_adam_eve"]["phase_b_action"]
    assert "family-level tradable evidence" in pattern_rows["double_bottoms_eve_adam"]["phase_b_action"]
    assert "family-level tradable evidence" in pattern_rows["double_bottoms_eve_eve"]["phase_b_action"]

    contract = result["local_buy_contract"]
    assert "variants are reported subgroups" in contract["scope"]
    assert "confirmation-only entry" in contract["must_keep_metrics"]
    assert "busted-pattern exit/avoid" in contract["must_keep_metrics"]

    assert (out_dir / "double_bottoms_after_buy_rules.json").exists()
    assert (out_dir / "double_bottoms_after_buy_rules.md").exists()
