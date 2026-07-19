from __future__ import annotations

from pathlib import Path

import pytest

from scanner.after_buy_source_grounding import (
    AFTER_BUY_SOURCE_CHAPTERS,
    DEFAULT_AFTER_BUY_PDF,
    assert_after_buy_buy_rule_allowed,
    build_after_buy_source_map,
)


def test_after_buy_catalog_is_buy_first_not_short_symmetric() -> None:
    assert len(AFTER_BUY_SOURCE_CHAPTERS) == 26
    roles = {chapter.local_role for chapter in AFTER_BUY_SOURCE_CHAPTERS}
    assert {"buy_core", "buy_watchlist", "avoid_exit", "context_module"} <= roles

    buy_allowed = [chapter for chapter in AFTER_BUY_SOURCE_CHAPTERS if chapter.local_role in {"buy_core", "buy_watchlist"}]
    avoid_or_context = [chapter for chapter in AFTER_BUY_SOURCE_CHAPTERS if chapter.local_role not in {"buy_core", "buy_watchlist"}]
    assert len(buy_allowed) < len(AFTER_BUY_SOURCE_CHAPTERS)
    assert len(avoid_or_context) >= 10


def test_after_buy_source_map_reads_pdf_outline_and_gates_buy_rules(tmp_path: Path) -> None:
    if not DEFAULT_AFTER_BUY_PDF.exists():
        pytest.skip("After-the-Buy PDF is a local ignored reference asset.")

    source_map = build_after_buy_source_map(out_dir=tmp_path / "after_buy")

    assert source_map["gate"]["status"] == "PASS"
    assert source_map["source_chapter_count"] == 26
    assert source_map["mapped_chapter_count"] == 26
    assert source_map["buy_core_count"] >= 6
    assert source_map["buy_layer_allowed_count"] >= 10
    assert (tmp_path / "after_buy" / "after_buy_source_map.json").exists()
    assert (tmp_path / "after_buy" / "after_buy_source_map.csv").exists()
    assert (tmp_path / "after_buy" / "after_buy_source_map.md").exists()

    bull = assert_after_buy_buy_rule_allowed("bull_flags", source_map)
    assert bull["source_title"] == "Flags and Pennants"
    assert bull["buy_layer_allowed"] is True
    assert bull["pattern_buy_role"]["buy_scope"] == "full_pattern_or_family_scope"

    with pytest.raises(ValueError, match="do not create a long-cash BUY tradable rule"):
        assert_after_buy_buy_rule_allowed("double_tops_adam_adam", source_map)

    with pytest.raises(ValueError, match="do not create a long-cash BUY tradable rule"):
        assert_after_buy_buy_rule_allowed("bear_flags", source_map)

    descending = assert_after_buy_buy_rule_allowed("triangles_descending", source_map)
    assert descending["pattern_buy_role"]["buy_scope"] == "up_breakout_branch_only"

    with pytest.raises(ValueError, match="no source-grounded"):
        assert_after_buy_buy_rule_allowed("unknown_pattern", source_map)
