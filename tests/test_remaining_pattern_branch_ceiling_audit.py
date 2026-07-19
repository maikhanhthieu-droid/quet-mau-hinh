from __future__ import annotations

import json
from pathlib import Path


def test_remaining_pattern_branch_ceiling_audit_is_diagnostic_only() -> None:
    payload = json.loads(
        Path("artifacts/scanner_v2/remaining_pattern_branch_ceiling_audit/remaining_pattern_branch_ceiling_audit.json").read_text(
            encoding="utf-8"
        )
    )

    rows = {row["pattern_id"]: row for row in payload["rows"]}
    assert {
        "bear_flags",
        "triangles_descending",
        "double_tops_adam_eve",
        "double_tops_eve_adam",
        "double_tops_eve_eve",
        "wedges_rising",
    }.issubset(rows)

    assert rows["bear_flags"]["best_score"] >= 80
    assert rows["triangles_descending"]["best_score"] >= 80

    for row in rows.values():
        guard = row["no_overlift_guard"]
        assert guard["policy_id"] == "diagnostic_branch_ceiling_no_overlift_v1"
        assert guard["promotion_decision"] == "KEEP_CURRENT_BLOCKED_STATUS"
        assert "score_below_95" in guard["remaining_tradable_blockers"]


def test_governance_uses_improved_diagnostic_audits_without_promotion() -> None:
    governance = json.loads(Path("artifacts/final_chapters/governance/chapter_governance_matrix.json").read_text(encoding="utf-8"))
    by_pattern = {row["pattern_id"]: row for row in governance["chapters"]}

    assert by_pattern["bear_flags"]["tradable_score"] == 84.49
    assert by_pattern["bear_flags"]["tradable_status"] == "tradable_tested_blocked"
    assert by_pattern["bear_flags"]["tradable_evidence_id"] == "local_blocker_audit"

    assert by_pattern["triangles_descending"]["tradable_score"] == 89.13
    assert by_pattern["triangles_descending"]["tradable_status"] == "tradable_tested_blocked"
    assert by_pattern["triangles_descending"]["tradable_evidence_id"] == "local_blocker_audit"

    assert by_pattern["double_tops_adam_eve"]["tradable_evidence_id"] == "local_blocker_audit"
    assert by_pattern["double_tops_eve_adam"]["tradable_evidence_id"] == "local_blocker_audit"
    assert by_pattern["double_tops_eve_eve"]["tradable_evidence_id"] == "local_blocker_audit"


def test_targeted_pattern_ceiling_push_improves_wedges_without_promotion() -> None:
    payload = json.loads(
        Path("artifacts/scanner_v2/targeted_pattern_ceiling_push/targeted_pattern_ceiling_push.json").read_text(
            encoding="utf-8"
        )
    )
    rows = {row["pattern_id"]: row for row in payload["rows"]}

    assert rows["wedges_falling"]["best_score"] == 82.75
    assert rows["wedges_falling"]["no_overlift_guard"]["promotion_decision"] == "STOP_NO_PROMOTION_UNDER_NO_OVERLIFT_POLICY"
    assert "walk_forward_has_negative_fold" in rows["wedges_falling"]["no_overlift_guard"]["remaining_tradable_blockers"]

    assert rows["wedges_rising"]["best_score"] == 79.31
    assert rows["wedges_rising"]["no_overlift_guard"]["promotion_decision"] == "STOP_NO_PROMOTION_UNDER_NO_OVERLIFT_POLICY"
    assert "scope_not_direct_long_cash_equity" in rows["wedges_rising"]["no_overlift_guard"]["remaining_tradable_blockers"]

    governance = json.loads(Path("artifacts/final_chapters/governance/chapter_governance_matrix.json").read_text(encoding="utf-8"))
    by_pattern = {row["pattern_id"]: row for row in governance["chapters"]}
    assert by_pattern["wedges_falling"]["tradable_score"] == 87.41
    assert by_pattern["wedges_falling"]["tradable_status"] == "tradable_tested_blocked"
    assert by_pattern["wedges_rising"]["tradable_score"] == 90.95
    assert by_pattern["wedges_rising"]["tradable_status"] == "tradable_research_candidate_blocked"


def test_feature_filter_push_is_negative_ceiling_evidence_not_best_evidence() -> None:
    payload = json.loads(
        Path("artifacts/scanner_v2/feature_filter_ceiling_push/feature_filter_ceiling_push.json").read_text(
            encoding="utf-8"
        )
    )
    rows = {row["pattern_id"]: row for row in payload["rows"]}
    current_best = {
        "triangles_symmetrical": 84.03,
        "triangles_descending": 89.13,
        "bear_flags": 84.49,
        "triangles_ascending": 85.84,
        "wedges_falling": 87.41,
        "wedges_rising": 90.95,
    }
    assert set(current_best).issubset(rows)
    for pattern_id, score in current_best.items():
        row = rows[pattern_id]
        assert row["best_score"] < score
        assert row["no_overlift_guard"]["promotion_decision"] == "STOP_NO_PROMOTION_UNDER_NO_OVERLIFT_POLICY"

    governance = json.loads(Path("artifacts/final_chapters/governance/chapter_governance_matrix.json").read_text(encoding="utf-8"))
    by_pattern = {row["pattern_id"]: row for row in governance["chapters"]}
    for pattern_id, score in current_best.items():
        assert by_pattern[pattern_id]["tradable_score"] == score


def test_pattern_specific_branch_redesign_updates_best_evidence_without_promotion() -> None:
    payload = json.loads(
        Path("artifacts/scanner_v2/pattern_specific_branch_redesign/pattern_specific_branch_redesign.json").read_text(
            encoding="utf-8"
        )
    )
    rows = {row["pattern_id"]: row for row in payload["rows"]}
    expected_scores = {
        "triangles_descending": 89.13,
        "triangles_ascending": 85.26,
        "wedges_falling": 82.83,
        "wedges_rising": 84.03,
    }
    for pattern_id, score in expected_scores.items():
        assert rows[pattern_id]["best_score"] == score
        assert rows[pattern_id]["no_overlift_guard"]["promotion_decision"] == "STOP_NO_PROMOTION_UNDER_NO_OVERLIFT_POLICY"
        assert "score_below_95" in rows[pattern_id]["no_overlift_guard"]["remaining_tradable_blockers"]

    assert rows["triangles_symmetrical"]["best_score"] < 84.03
    assert rows["bear_flags"]["best_score"] < 80.86

    governance = json.loads(Path("artifacts/final_chapters/governance/chapter_governance_matrix.json").read_text(encoding="utf-8"))
    by_pattern = {row["pattern_id"]: row for row in governance["chapters"]}
    assert by_pattern["triangles_descending"]["tradable_score"] == 89.13
    assert by_pattern["triangles_descending"]["tradable_evidence_id"] == "local_blocker_audit"


def test_pattern_specific_fold_repair_updates_only_true_improvements() -> None:
    payload = json.loads(
        Path("artifacts/scanner_v2/pattern_specific_fold_repair/pattern_specific_fold_repair.json").read_text(
            encoding="utf-8"
        )
    )
    rows = {row["pattern_id"]: row for row in payload["rows"]}
    expected_scores = {
        "triangles_symmetrical": 78.49,
        "triangles_descending": 86.98,
        "bear_flags": 76.03,
        "triangles_ascending": 85.84,
        "wedges_falling": 87.05,
        "wedges_rising": 90.95,
    }
    for pattern_id, score in expected_scores.items():
        assert rows[pattern_id]["best_score"] == score
        assert rows[pattern_id]["no_overlift_guard"]["promotion_decision"] == "STOP_NO_PROMOTION_UNDER_NO_OVERLIFT_POLICY"

    governance = json.loads(Path("artifacts/final_chapters/governance/chapter_governance_matrix.json").read_text(encoding="utf-8"))
    by_pattern = {row["pattern_id"]: row for row in governance["chapters"]}
    assert by_pattern["triangles_symmetrical"]["tradable_score"] == 84.03
    assert by_pattern["triangles_descending"]["tradable_score"] == 89.13
    assert by_pattern["bear_flags"]["tradable_score"] == 84.49
    assert by_pattern["triangles_ascending"]["tradable_score"] == 85.84
    assert by_pattern["wedges_falling"]["tradable_score"] == 87.41
    assert by_pattern["wedges_rising"]["tradable_score"] == 90.95
    assert by_pattern["wedges_rising"]["tradable_status"] == "tradable_research_candidate_blocked"


def test_pattern_specific_final_push_is_last_bounded_pass() -> None:
    payload = json.loads(
        Path("artifacts/scanner_v2/pattern_specific_final_push/pattern_specific_final_push.json").read_text(
            encoding="utf-8"
        )
    )
    rows = {row["pattern_id"]: row for row in payload["rows"]}
    expected_scores = {
        "triangles_symmetrical": 80.75,
        "triangles_descending": 86.98,
        "bear_flags": 84.49,
        "triangles_ascending": 85.84,
        "wedges_falling": 87.41,
        "wedges_rising": 90.95,
    }
    for pattern_id, score in expected_scores.items():
        assert rows[pattern_id]["best_score"] == score
        assert rows[pattern_id]["no_overlift_guard"]["promotion_decision"] == "STOP_NO_PROMOTION_UNDER_NO_OVERLIFT_POLICY"

    governance = json.loads(Path("artifacts/final_chapters/governance/chapter_governance_matrix.json").read_text(encoding="utf-8"))
    by_pattern = {row["pattern_id"]: row for row in governance["chapters"]}
    assert by_pattern["triangles_symmetrical"]["tradable_score"] == 84.03
    assert by_pattern["triangles_descending"]["tradable_score"] == 89.13
    assert by_pattern["bear_flags"]["tradable_score"] == 84.49
    assert by_pattern["triangles_ascending"]["tradable_score"] == 85.84
    assert by_pattern["wedges_falling"]["tradable_score"] == 87.41
    assert by_pattern["wedges_rising"]["tradable_score"] == 90.95
