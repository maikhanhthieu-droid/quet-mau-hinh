from pathlib import Path

import pytest

from scanner.after_buy_source_grounding import DEFAULT_AFTER_BUY_PDF
from scanner.build_after_buy_rectangles_rules import (
    REQUIRED_SOURCE_SECTIONS,
    build_after_buy_rectangles_rules,
)
from scanner.run_chapter_tradable_layer import CHAPTER_SPECS, load_chapter_events_and_path


def test_rectangles_after_buy_rules_keep_bottoms_watchlist_and_tops_blocked(tmp_path: Path) -> None:
    if not DEFAULT_AFTER_BUY_PDF.exists():
        pytest.skip("Missing After-the-Buy PDF")

    source_map_path = tmp_path / "source" / "after_buy_source_map.json"
    out_dir = tmp_path / "rectangles"
    result = build_after_buy_rectangles_rules(source_map_path=source_map_path, out_dir=out_dir)

    assert result["status"] == "PASS"
    assert result["source_chapter"]["source_title"] == "Rectangles"

    section_titles = {section["title"] for section in result["source_chapter"]["sections"]}
    assert set(REQUIRED_SOURCE_SECTIONS).issubset(section_titles)

    rows = {row["pattern_id"]: row for row in result["patterns"]}
    assert set(rows) == {"rectangle_bottoms", "rectangle_tops"}
    assert rows["rectangle_bottoms"]["buy_role"]["buy_layer_allowed"] is True
    assert rows["rectangle_bottoms"]["buy_role"]["buy_scope"] == "full_pattern_or_family_scope"
    assert rows["rectangle_tops"]["buy_role"]["buy_layer_allowed"] is False
    assert "do not promote" in rows["rectangle_tops"]["phase_b_action"]

    rule_ids = {rule["rule_id"] for rule in result["source_rules"]}
    assert len(rule_ids) >= 11
    assert "atb.rect.direction_specific_breakout" in rule_ids
    assert "atb.rect.throwback_common" in rule_ids
    assert "atb.rect.stop_below_rectangle" in rule_ids
    assert "atb.rect_rectangle_top_not_buy" in rule_ids
    assert "atb.rect.watchlist_not_direct_signal" in rule_ids

    contract = result["local_buy_contract"]
    assert "BUY-watchlist" in contract["scope"]
    assert "Rectangle Tops are avoid/exit" in contract["scope"]
    assert "up-breakout branch only" in contract["must_keep_metrics"]
    assert "busted breakout rate" in contract["must_keep_metrics"]

    assert (out_dir / "rectangles_after_buy_rules.json").exists()
    assert (out_dir / "rectangles_after_buy_rules.md").exists()


def test_rectangle_bottoms_tradable_scope_is_up_breakout_branch_only() -> None:
    spec = CHAPTER_SPECS["rectangle_bottoms"]
    if not spec.events_path.exists() or not spec.path_path.exists():
        pytest.skip("Missing Rectangle Bottoms events/path artifacts")

    events, path, source_scope = load_chapter_events_and_path(spec)

    assert source_scope["status"] == "loaded"
    assert len(events) >= 80
    assert set(events["breakout_direction"].astype(str)) == {"up"}
    assert set(path["event_id"].astype(str)).issubset(set(events["event_id"].astype(str)))
