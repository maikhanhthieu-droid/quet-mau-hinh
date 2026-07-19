from __future__ import annotations

import json
from pathlib import Path

from scanner.analyze_bear_flag_statistical_drop import build_audit, write_report


def test_bear_flag_statistical_drop_audit_identifies_data_mix_not_global_code_bug(tmp_path: Path) -> None:
    audit = build_audit()

    assert audit["diagnosis"]["primary_cause"].startswith("data/path-quality/liquidity mix")
    assert audit["code_vs_data_evidence"]["same_pipeline_used_for_bull_and_bear"] is True
    assert audit["code_vs_data_evidence"]["bear_high_liquidity_slice_matches_bull_base_hit"] is True
    assert audit["headline_deltas_bear_minus_bull"]["base_target_hit_rate_pp"] < 0
    assert audit["headline_deltas_bear_minus_bull"]["median_mae_pct"] > 0
    assert audit["branch_repair_summary"]["headline_scope"] == "defensive_expanded"
    assert audit["branch_repair_summary"]["hit_gap_closed_pct"] > 95
    assert audit["branch_headline_deltas_bear_minus_bull"]["base_target_hit_rate_pp"] > -1

    top_filters = audit["ex_ante_filter_probe_top"]
    assert top_filters
    assert top_filters[0]["base_target_hit_rate"] > audit["bear_overall"]["base_target_hit_rate"]
    assert "liquidity_high" in top_filters[0]["filter_id"]

    paths = write_report(audit, tmp_path / "drop_audit")
    assert paths["json"].exists()
    assert paths["csv"].exists()
    assert paths["md"].exists()
    reloaded = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert reloaded["audit_version"] == "bear_flag_statistical_drop_v1"
