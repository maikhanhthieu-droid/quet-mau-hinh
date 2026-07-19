from __future__ import annotations

from scanner.run_bull_flag_db_source_parity_audit import _summary_row


def test_bull_flag_db_source_parity_summary_uses_base_target_row() -> None:
    stats = {
        "detection_count": 193,
        "symbols_scanned": 1088,
        "median_mfe_pct": 12.07,
        "median_mae_pct": 9.64,
        "target_family_sensitivity": [
            {
                "label": "bull_flags",
                "target_multiple": 0.46,
                "n": 193,
                "target_hit_rate": 68.39,
                "target_first_before_adverse_5pct_rate": 41.45,
                "failure_5pct_rate": 25.39,
                "mfe_mae_median_ratio": 1.25,
            }
        ],
    }

    row = _summary_row("db_active", stats)

    assert row["source_id"] == "db_active"
    assert row["n_all"] == 193
    assert row["base_target_n"] == 193
    assert row["base_target_hit_rate"] == 68.39
    assert row["mfe_mae_ratio"] == 1.25
