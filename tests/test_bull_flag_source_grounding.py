from __future__ import annotations

from pathlib import Path

from scanner.build_bull_flag_source_grounding import build_source_notes, write_source_notes


def test_bull_flag_source_notes_capture_original_anchors(tmp_path: Path) -> None:
    notes = build_source_notes()

    assert notes["status"] == "PASS"
    assert notes["local_source"]["pattern_key"] == "bull_flags"
    assert notes["thepatternsite_measure_rule"]["flags_up_breakout_rule"].endswith("* 46%)")
    assert any(rule["rule_id"] == "bf.breakout.close_above_trendline" for rule in notes["source_rules"])
    assert notes["alignment_constraints"]["base_target_multiple"] == 0.46

    paths = write_source_notes(notes, tmp_path)

    assert paths["json"].exists()
    assert paths["markdown"].exists()
    assert "thepatternsite.com/flags.html" in paths["markdown"].read_text(encoding="utf-8")
