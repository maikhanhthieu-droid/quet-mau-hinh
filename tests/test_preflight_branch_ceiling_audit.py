from __future__ import annotations

import json
from pathlib import Path


def test_preflight_branch_ceiling_audit_stops_all_priority_patterns() -> None:
    payload = json.loads(Path("artifacts/final_chapters/governance/preflight_branch_ceiling_audit.json").read_text(encoding="utf-8"))

    assert payload["audit_id"] == "preflight_branch_ceiling_audit_v1"
    assert payload["counts"] == {
        "patterns": 4,
        "ceiling_reached": 4,
        "additional_branch_lift_available": 0,
        "preflight_strong": 3,
        "preflight_candidate": 1,
    }

    rows = {row["pattern_id"]: row for row in payload["rows"]}
    assert set(rows) == {"bear_flags", "bull_pennants", "triangles_symmetrical", "wedges_rising"}
    for row in rows.values():
        assert row["technical_ceiling_decision"] == "STOP_PREFLIGHT_CEILING_REACHED"
        assert row["best_unselected_lift_vs_selected_pp"] < payload["material_residual_lift_pp"]


def test_preflight_branch_ceiling_keeps_rising_wedge_as_data_scope_ceiling() -> None:
    payload = json.loads(Path("artifacts/final_chapters/governance/preflight_branch_ceiling_audit.json").read_text(encoding="utf-8"))
    rows = {row["pattern_id"]: row for row in payload["rows"]}

    rising = rows["wedges_rising"]
    assert rising["selected_status"] == "preflight_candidate"
    assert rising["selected_branch_id"] == "bull_high_liq_width_core"
    assert rising["selected_score"] == 80.22
    assert rising["best_unselected_branch_id"] == "bull_high_liq_clear"
    assert rising["best_unselected_score"] == 76.43
    assert rising["remaining_ceiling_reason"] == "best_branch_is_selected_but_thin_sample_and_defensive_scope_cap_the_preflight_layer"


def test_preflight_branch_ceiling_records_material_lifts_already_captured() -> None:
    payload = json.loads(Path("artifacts/final_chapters/governance/preflight_branch_ceiling_audit.json").read_text(encoding="utf-8"))
    rows = {row["pattern_id"]: row for row in payload["rows"]}

    assert rows["bear_flags"]["selected_lift_vs_aggregate_pp"] == 28.47
    assert rows["triangles_symmetrical"]["selected_lift_vs_aggregate_pp"] == 8.57
    assert rows["bull_pennants"]["selected_lift_vs_aggregate_pp"] == 0.0
    assert rows["bull_pennants"]["best_unselected_branch_id"] == "compact_pennant"
    assert rows["bull_pennants"]["best_unselected_lift_vs_selected_pp"] == 0.34
