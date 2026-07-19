from __future__ import annotations

import pandas as pd

from scanner.v2.bear_flags_monograph import _assign_bear_branch, _assign_bear_branches


def test_bear_branch_scanner_promotes_high_liquidity_no_gap_core_without_path_quality() -> None:
    branch_id, lane, reason, headline = _assign_bear_branch(
        {
            "liquidity_bucket": "high",
            "market_group": "Outside VN100",
            "market_regime": "bull",
            "breakout_gap_pct": 0.2,
            "yearly_range_position_pct": 45.0,
            "breakout_body_to_range": 0.25,
            "breakout_close_location": 0.4,
            "volume_confirmed": False,
            # This must not affect branch assignment because it is post-breakout QA.
            "path_quality_bucket": "short_path",
        }
    )

    assert branch_id == "defensive_core_high_liquidity_no_gap"
    assert lane == "defensive-core"
    assert "path" not in reason.lower()
    assert headline is True


def test_bear_branch_scanner_keeps_broad_low_liquidity_events_informational() -> None:
    branch_id, lane, _, headline = _assign_bear_branch(
        {
            "liquidity_bucket": "low",
            "market_group": "Outside VN100",
            "market_regime": "bull",
            "breakout_gap_pct": 2.0,
            "yearly_range_position_pct": 20.0,
            "breakout_body_to_range": 0.1,
            "breakout_close_location": 0.2,
            "volume_confirmed": False,
        }
    )

    assert branch_id == "informational_broad"
    assert lane == "informational"
    assert headline is False


def test_assign_bear_branches_adds_contract_fields_to_scan() -> None:
    scan = {
        "detections": [
            {
                "liquidity_bucket": "high",
                "market_group": "VN30",
                "market_regime": "bull",
                "breakout_gap_pct": 0.0,
                "yearly_range_position_pct": 55.0,
                "breakout_body_to_range": 0.5,
            }
        ]
    }

    _assign_bear_branches(scan)
    frame = pd.DataFrame(scan["detections"])

    assert frame.loc[0, "bear_branch_id"] == "defensive_core_high_liquidity_no_gap"
    assert frame.loc[0, "bear_branch_lane"] == "defensive-core"
    assert bool(frame.loc[0, "bear_branch_is_headline_candidate"]) is True
