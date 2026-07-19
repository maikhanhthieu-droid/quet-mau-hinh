from __future__ import annotations

import pandas as pd

from scanner.run_bull_flag_supporting_robustness import (
    _cooldown_events,
    _eligible_pass,
    _price_limit_proxy_event_ids,
    render_supporting_robustness,
)


def test_cooldown_events_keeps_first_symbol_event_inside_window() -> None:
    events = pd.DataFrame(
        {
            "event_id": ["e1", "e2", "e3", "e4"],
            "symbol": ["AAA", "AAA", "AAA", "BBB"],
            "breakout_date": ["2024-01-01", "2024-01-15", "2024-02-15", "2024-01-10"],
        }
    )

    filtered = _cooldown_events(events, 30)

    assert filtered["event_id"].tolist() == ["e1", "e4", "e3"]


def test_price_limit_proxy_detects_wide_ohlcv_bar() -> None:
    path = pd.DataFrame(
        {
            "event_id": ["quiet", "wide", "late"],
            "bar_after_breakout": [1, 2, 80],
            "open": [100.0, 100.0, 100.0],
            "high": [101.0, 108.0, 120.0],
            "low": [99.0, 100.0, 100.0],
            "close": [100.0, 107.0, 119.0],
        }
    )

    flagged = _price_limit_proxy_event_ids(path, threshold_pct=6.5, horizon_days=60)

    assert flagged == {"wide"}


def test_eligible_pass_requires_positive_eligible_rows() -> None:
    result = _eligible_pass(
        [
            {"row_id": "ok", "trades": 10, "total_return_pct": 1.0, "max_drawdown_pct": -1.0},
            {"row_id": "bad", "trades": 10, "total_return_pct": -0.1, "max_drawdown_pct": -1.0},
            {"row_id": "small", "trades": 3, "total_return_pct": -10.0, "max_drawdown_pct": -10.0},
        ]
    )

    assert result["status"] == "FAIL"
    assert result["failed_rows"] == ["bad"]


def test_supporting_robustness_markdown_lists_three_checks() -> None:
    report = render_supporting_robustness(
        {
            "status": "PASS",
            "frozen_strategy_id": "s",
            "failures": [],
            "profiles": [
                {
                    "profile_id": "main",
                    "scoped_events": 10,
                    "checks": {
                        "overlap_sensitivity": "PASS",
                        "liquidity_bucket_robustness": "PASS",
                        "price_limit_proxy_robustness": "PASS",
                    },
                    "overlap_sensitivity": {"status": "PASS", "summary": {}, "rows": []},
                    "liquidity_bucket_robustness": {"status": "PASS", "summary": {}, "rows": []},
                    "price_limit_proxy_robustness": {"status": "PASS", "summary": {}, "rows": []},
                }
            ],
        }
    )

    assert "overlap_sensitivity" in report
    assert "liquidity_bucket_robustness" in report
    assert "price_limit_proxy_robustness" in report
