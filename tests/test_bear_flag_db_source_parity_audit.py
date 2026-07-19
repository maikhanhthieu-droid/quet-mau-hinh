from __future__ import annotations

from scanner.run_bear_flag_db_source_parity_audit import _summary_row


def test_db_source_parity_summary_prefers_selected_branch_headline() -> None:
    stats = {
        "detection_count": 137,
        "symbols_scanned": 1088,
        "bear_branch_headline": {
            "aggregate_id": "defensive_expanded",
            "n": 50,
            "n_symbols": 41,
            "base_target_hit_rate": 70.0,
            "base_target_first_before_adverse_5pct_rate": 50.0,
            "failure_5pct_rate": 18.0,
            "mfe_mae_median_ratio": 1.54,
        },
    }

    row = _summary_row("db_active", stats)

    assert row["source_id"] == "db_active"
    assert row["n_all"] == 137
    assert row["headline_scope"] == "defensive_expanded"
    assert row["headline_n"] == 50
    assert row["headline_hit_rate"] == 70.0
