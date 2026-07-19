from __future__ import annotations

import json
from pathlib import Path


def test_tradable_candidate_ceiling_audit_stops_all_current_candidates() -> None:
    payload = json.loads(Path("artifacts/final_chapters/governance/tradable_candidate_ceiling_audit.json").read_text(encoding="utf-8"))

    assert payload["audit_id"] == "tradable_candidate_ceiling_audit_v1"
    assert payload["counts"] == {
        "patterns": 8,
        "ceiling_reached": 8,
        "additional_tradable_lift_available": 0,
        "promotion_review_available": 0,
        "score_90_plus": 3,
        "score_95_plus": 0,
    }

    rows = {row["pattern_id"]: row for row in payload["rows"]}
    assert set(rows) == {
        "bull_pennants",
        "wedges_rising",
        "double_tops_adam_adam",
        "triangles_descending",
        "wedges_falling",
        "triangles_ascending",
        "triangles_symmetrical",
        "bear_flags",
    }
    for row in rows.values():
        assert row["technical_ceiling_decision"] == "STOP_TRADABLE_CEILING_REACHED"
        assert row["score_lift_vs_current_pp"] == 0.0
        assert row["best_known_score"] < payload["promotion_threshold"]


def test_tradable_candidate_ceiling_identifies_the_three_near_90_plus_cases() -> None:
    payload = json.loads(Path("artifacts/final_chapters/governance/tradable_candidate_ceiling_audit.json").read_text(encoding="utf-8"))
    rows = {row["pattern_id"]: row for row in payload["rows"]}

    assert rows["bull_pennants"]["best_known_score"] == 93.8
    assert rows["bull_pennants"]["remaining_ceiling_reason"] == "fixed_walk_forward_instability_caps_promotion"

    assert rows["wedges_rising"]["best_known_score"] == 90.95
    assert rows["wedges_rising"]["remaining_ceiling_reason"] == "defensive_or_downside_scope_caps_direct_tradable_promotion"

    assert rows["double_tops_adam_adam"]["best_known_score"] == 90.76
    assert rows["double_tops_adam_adam"]["remaining_ceiling_reason"] == "defensive_or_downside_scope_caps_direct_tradable_promotion"


def test_tradable_candidate_ceiling_keeps_walk_forward_blockers_explicit() -> None:
    payload = json.loads(Path("artifacts/final_chapters/governance/tradable_candidate_ceiling_audit.json").read_text(encoding="utf-8"))
    rows = {row["pattern_id"]: row for row in payload["rows"]}

    for pattern_id in ["bull_pennants", "wedges_falling", "triangles_ascending"]:
        assert "walk_forward_has_negative_fold" in rows[pattern_id]["remaining_blockers"] or "walk_forward_negative_folds" in rows[pattern_id]["remaining_blockers"]

    assert "scope_not_direct_long_cash_equity" in rows["wedges_rising"]["remaining_blockers"]
    assert "scope_not_direct_long_cash_equity" in rows["double_tops_adam_adam"]["remaining_blockers"]
