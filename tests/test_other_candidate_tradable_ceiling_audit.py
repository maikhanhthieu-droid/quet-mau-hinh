from scanner.run_other_candidate_tradable_ceiling_audit import _build_no_overlift_guard


def test_other_candidate_guard_stops_when_score_and_walk_forward_fail() -> None:
    guard = _build_no_overlift_guard(
        {
            "score": 84.03,
            "scope": "mixed_direction_reference",
            "promotion_blockers": "walk_forward_has_negative_fold",
            "walk_forward_positive_fold_rate_pct": 78.57,
        }
    )

    assert guard["promotion_decision"] == "STOP_NO_PROMOTION_UNDER_NO_OVERLIFT_POLICY"
    assert guard["failures"] == [
        "score_threshold",
        "scope_direct_long_cash",
        "promotion_blockers",
        "walk_forward_positive",
    ]


def test_other_candidate_guard_allows_review_only_when_all_hard_checks_pass() -> None:
    guard = _build_no_overlift_guard(
        {
            "score": 95.2,
            "scope": "long_cash_candidate",
            "promotion_blockers": "",
            "walk_forward_positive_fold_rate_pct": 100.0,
        }
    )

    assert guard["promotion_decision"] == "ELIGIBLE_FOR_FORMAL_PROMOTION_REVIEW"
    assert guard["failures"] == []
