from scanner.run_bull_pennant_tradable_ceiling_audit import (
    CURRENT_SELECTED_ID,
    NO_OVERLIFT_POLICY_ID,
    _build_no_overlift_guard,
)


def test_no_overlift_guard_stops_when_best_candidate_is_below_95_and_blocked() -> None:
    rows = [
        {
            "strategy_id": "candidate",
            "score": 93.8,
            "trades": 165,
            "promotion_blockers": "walk_forward_has_negative_fold",
            "walk_forward_negative_folds": 22,
        },
        {
            "strategy_id": CURRENT_SELECTED_ID,
            "score": 92.18,
            "trades": 383,
            "promotion_blockers": "walk_forward_has_negative_fold",
            "walk_forward_negative_folds": 30,
        },
    ]

    guard = _build_no_overlift_guard(rows[0], rows)

    assert guard["policy_id"] == NO_OVERLIFT_POLICY_ID
    assert guard["promotion_decision"] == "STOP_NO_PROMOTION_UNDER_NO_OVERLIFT_POLICY"
    assert guard["failures"] == [
        "score_threshold",
        "promotion_blockers",
        "walk_forward_negative_folds",
    ]
    assert guard["warnings"] == []
    assert guard["best_trade_share_vs_current"] == 0.4308


def test_no_overlift_guard_allows_formal_review_only_after_hard_checks_pass() -> None:
    rows = [
        {
            "strategy_id": "candidate",
            "score": 95.4,
            "trades": 220,
            "promotion_blockers": "",
            "walk_forward_negative_folds": 0,
        },
        {
            "strategy_id": CURRENT_SELECTED_ID,
            "score": 92.18,
            "trades": 383,
            "promotion_blockers": "walk_forward_has_negative_fold",
            "walk_forward_negative_folds": 30,
        },
    ]

    guard = _build_no_overlift_guard(rows[0], rows)

    assert guard["promotion_decision"] == "ELIGIBLE_FOR_FORMAL_PROMOTION_REVIEW"
    assert guard["failures"] == []
    assert guard["warnings"] == []
