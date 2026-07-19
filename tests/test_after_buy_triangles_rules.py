from pathlib import Path

import pytest

from scanner.after_buy_source_grounding import DEFAULT_AFTER_BUY_PDF
from scanner.build_after_buy_triangles_rules import (
    REQUIRED_SOURCE_SECTIONS,
    build_after_buy_triangles_rules,
)


def test_triangles_after_buy_rules_are_branch_aware(tmp_path: Path) -> None:
    if not DEFAULT_AFTER_BUY_PDF.exists():
        pytest.skip("Missing After-the-Buy PDF")

    source_map_path = tmp_path / "source" / "after_buy_source_map.json"
    out_dir = tmp_path / "triangles"
    result = build_after_buy_triangles_rules(source_map_path=source_map_path, out_dir=out_dir)

    assert result["status"] == "PASS"
    assert set(result["source_chapters"]) == {21, 22, 23, 24}
    for chapter_no, required in REQUIRED_SOURCE_SECTIONS.items():
        section_titles = {section["title"] for section in result["source_chapters"][chapter_no]["sections"]}
        assert set(required).issubset(section_titles)

    rows = {row["pattern_id"]: row for row in result["patterns"]}
    assert set(rows) == {"triangles_ascending", "triangles_descending", "triangles_symmetrical"}
    assert rows["triangles_ascending"]["buy_role"]["buy_scope"] == "full_pattern_or_family_scope"
    assert rows["triangles_descending"]["buy_role"]["buy_scope"] == "up_breakout_branch_only"
    assert rows["triangles_symmetrical"]["buy_role"]["buy_scope"] == "up_breakout_branch_only"

    for row in rows.values():
        assert row["source_notes"]["available"] is True
        assert row["source_notes"]["source_review_status"] == "PASS"
        assert row["governance_tradable"]["tradable_score"] < 95.0
        assert "walk-forward" in row["phase_c_action"]

    rule_ids = {rule["rule_id"] for rule in result["source_rules"]}
    assert "atb.tri.apex_timing_context" in rule_ids
    assert "atb.tri.ascending_buy_core" in rule_ids
    assert "atb.tri.descending_up_branch_only" in rule_ids
    assert "atb.tri.symmetrical_direction_split" in rule_ids

    contract = result["local_buy_contract"]
    assert "Descending/Symmetrical upward branch only" in contract["scope"]
    assert "apex progress" in contract["must_keep_metrics"]
    assert "Do not use descending breakdowns as Vietnam BUY setups." in contract["forbidden_promotions"]

    assert (out_dir / "triangles_after_buy_rules.json").exists()
    assert (out_dir / "triangles_after_buy_rules.md").exists()
