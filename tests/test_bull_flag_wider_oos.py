from __future__ import annotations

import json
from pathlib import Path

from scanner.run_bull_flag_wider_oos import (
    build_source_manifest,
    classify_snapshot_scope,
    context_robustness_summary,
    execution_stress_summary,
    provenance_audit,
    render_report,
    temporal_power_summary,
)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_source_manifest_counts_rows_dates_and_metadata(tmp_path: Path) -> None:
    source_dir = tmp_path / "stock_series"
    source_dir.mkdir()
    _write_json(
        source_dir / "AAA.json",
        [
            {"date": "2025-01-02", "close": 10.0},
            {"date": "2025-01-03", "close": 10.2},
        ],
    )
    _write_json(source_dir / "BBB.json", [{"date": "2024-12-31", "close": 8.0}])
    metadata_path = tmp_path / "market_stats_data.json"
    _write_json(
        metadata_path,
        {
            "schema_version": "market-stats-v1.1",
            "generated_at": "2026-05-15T08:51:42+00:00",
            "membership_version": {"mode": "current_snapshot", "point_in_time_ready": False},
            "classification_version": {"point_in_time_ready": False},
            "data_basis": {"adjustment_label": "provider_adjusted_ohlcv"},
            "stocks": [{"symbol": "AAA"}],
            "indices": [{"symbol": "VNINDEX"}],
        },
    )

    manifest = build_source_manifest(source_dir, metadata_path)

    assert manifest["symbol_files"] == 2
    assert manifest["total_rows"] == 3
    assert manifest["min_date"] == "2024-12-31"
    assert manifest["max_date"] == "2025-01-03"
    assert manifest["bad_file_count"] == 0
    assert manifest["metadata"]["membership_point_in_time_ready"] is False
    assert manifest["snapshot_fingerprint"]


def test_scope_without_snapshot_id_is_temporal_not_fresh() -> None:
    manifest = {"bad_file_count": 0, "metadata": {"membership_point_in_time_ready": False}}

    scope = classify_snapshot_scope(manifest)

    assert scope["scope_status"] == "same_snapshot_temporal_check"
    assert scope["is_fresh_oos"] is False
    assert "source_snapshot_id_not_provided" in scope["warnings"]
    assert "membership_not_point_in_time" in scope["warnings"]


def test_scope_with_distinct_snapshot_id_is_fresh_candidate() -> None:
    manifest = {"bad_file_count": 0, "metadata": {"membership_point_in_time_ready": True}}

    scope = classify_snapshot_scope(manifest, source_snapshot_id="market_stats_2026-06-01")

    assert scope["scope_status"] == "fresh_snapshot_candidate"
    assert scope["is_fresh_oos"] is True
    assert scope["warnings"] == []


def test_provenance_audit_caps_same_snapshot_claims() -> None:
    manifest = {
        "bad_file_count": 0,
        "total_rows": 100,
        "min_date": "2020-01-01",
        "max_date": "2026-01-01",
        "metadata": {
            "membership_point_in_time_ready": False,
            "classification_point_in_time_ready": False,
            "adjustment_label": "provider_adjusted_ohlcv",
        },
    }
    scope = classify_snapshot_scope(manifest)

    audit = provenance_audit(manifest, scope)

    assert audit["classification_ceiling"] == "same-snapshot-diagnostic"
    assert "same_snapshot_only_not_independent_fresh_oos" in audit["limitations"]
    assert "historical VN30/VN100 point-in-time membership conclusion" in audit["forbidden_claims"]


def test_temporal_context_and_execution_summaries_count_statuses() -> None:
    temporal = temporal_power_summary(
        [
            {"power_status": "pass", "events": 40, "trades": 30},
            {"power_status": "underpowered", "events": 8, "trades": 7},
        ]
    )
    context = context_robustness_summary(
        [
            {"diagnostic_status": "pass", "trades": 10},
            {"diagnostic_status": "negative_return", "trades": 9},
            {"diagnostic_status": "underpowered", "trades": 3},
        ]
    )
    execution = execution_stress_summary(
        [
            {"total_return_pct": 1.5, "max_drawdown_pct": -1.0},
            {"total_return_pct": -0.5, "max_drawdown_pct": -2.0},
        ]
    )

    assert temporal["pass_count"] == 1
    assert temporal["underpowered_count"] == 1
    assert context["eligible_context_rows"] == 2
    assert context["failed_eligible_context_rows"] == 1
    assert execution["positive_scenario_rate_pct"] == 50.0
    assert execution["worst_scenario_return_pct"] == -0.5


def test_report_states_same_snapshot_scope() -> None:
    payload = {
        "scope": {"scope_status": "same_snapshot_temporal_check", "is_fresh_oos": False, "scope_note": "Diagnostic only."},
        "source_manifest": {"total_rows": 10, "symbol_files": 2, "min_date": "2025-01-01", "max_date": "2025-01-05"},
        "data_provenance_audit": {"classification_ceiling": "same-snapshot-diagnostic"},
        "full_profile_evaluation": {
            "events_n": 3,
            "summary": {"trades": 2, "validation_total_return_pct": 1.0, "holdout_total_return_pct": 2.0},
            "scorecard": {"score": 91.0, "classification": "candidate"},
        },
        "execution_stress_summary": {"scenario_count": 2, "positive_scenario_rate_pct": 100.0, "worst_scenario_return_pct": 1.0, "worst_scenario_drawdown_pct": -1.0},
        "temporal_power_summary": {"slice_count": 2, "pass_count": 1, "underpowered_count": 1, "min_trades": 7},
        "context_robustness_summary": {"eligible_context_rows": 2, "failed_eligible_context_rows": 1, "pass_rate_eligible_pct": 50.0},
        "temporal_evaluation": {
            "start_date": "2025-01-01",
            "end_date": None,
            "events_n": 1,
            "summary": {"trades": 1},
            "scorecard": {"score": 80.0, "classification": "diagnostic"},
            "scope_note": "Same fixed scanner/rule.",
        },
    }

    report = render_report(payload)

    assert "same_snapshot_temporal_check" in report
    assert "Fresh OOS: `False`" in report
    assert "Temporal Slice" in report
