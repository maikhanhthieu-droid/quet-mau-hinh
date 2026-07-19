from __future__ import annotations

from pathlib import Path

import pytest

from scanner.after_buy_source_grounding import DEFAULT_AFTER_BUY_PDF, build_after_buy_source_map
from scanner.build_after_buy_tradable_priority import build_after_buy_tradable_priority


def test_after_buy_priority_queue_excludes_bearish_chapters_from_buy(tmp_path: Path) -> None:
    if not DEFAULT_AFTER_BUY_PDF.exists():
        pytest.skip("After-the-Buy PDF is a local ignored reference asset.")

    after_buy_dir = tmp_path / "after_buy"
    build_after_buy_source_map(out_dir=after_buy_dir)
    priority = build_after_buy_tradable_priority(source_map_path=after_buy_dir / "after_buy_source_map.json", out_dir=after_buy_dir)

    row_pattern_ids = [row["pattern_id"] for row in priority["rows"]]
    pattern_ids = set(row_pattern_ids)
    assert len(row_pattern_ids) == len(pattern_ids)
    assert "bull_flags" in pattern_ids
    assert "bear_flags" not in pattern_ids
    assert "bear_pennants" not in pattern_ids
    assert "rectangle_tops" not in pattern_ids
    assert "triangles_descending" in pattern_ids

    descending = next(row for row in priority["rows"] if row["pattern_id"] == "triangles_descending")
    assert descending["buy_scope"] == "up_breakout_branch_only"
    assert "up-breakout branch" in descending["next_after_buy_action"]

    assert (after_buy_dir / "after_buy_tradable_priority.json").exists()
    assert (after_buy_dir / "after_buy_tradable_priority.csv").exists()
    assert (after_buy_dir / "after_buy_tradable_priority.md").exists()
