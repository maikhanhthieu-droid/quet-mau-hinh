from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from scanner.v2 import ScannerV2Engine, enrich_payload_with_p1_p5_status, evaluate_release_gate, load_core_registry


def _base_payload() -> dict:
    registry = load_core_registry()
    rules = registry["patterns"]["bear_flags"]["rules"]
    scanner_contract = ScannerV2Engine(registry=registry).compile_pattern("bear_flags", require_official=True).result_metadata()
    return {
        "generated_at": "2026-05-16T00:00:00+00:00",
        "pattern_key": "bear_flags",
        "display_name": "Bear Flags",
        "source_alignment": {"aligned": True, "errors": []},
        "scanner_contract": scanner_contract,
        "rules": rules,
        "market_data": {
            "source": "Market Stats V1 stock_series JSON",
            "symbols_scanned": 812,
            "regime": {"enabled": True, "method": "VNINDEX fixed rule"},
        },
        "statistics": {
            "detection_count": 1146,
            "evaluated_count": 1145,
            "breakout_groups": {"all": {}, "up": {}, "down": {}},
            "regime_groups": {"bull": {}, "bear": {}, "unknown": {}},
        },
        "example_scope": {"universe": "VN100"},
        "example_detections": [{"symbol": "PLX"}],
        "investment_reference_status": {"tradable_setup": False},
    }


def test_release_gate_holds_current_draft_without_p1_p5_data_integrity() -> None:
    report = evaluate_release_gate(_base_payload())

    assert report["publish_status"] == "Hold"
    assert report["classification"] == "research-only"
    assert "point_in_time_universe" in report["high_severity_failures"]
    assert "corporate_actions" in report["high_severity_failures"]
    assert "event_path" in report["high_severity_failures"]
    assert "event_level_ohlcv_path" in report["p0_missing"]


def test_release_gate_rejects_missing_rule_provenance_as_not_usable() -> None:
    payload = _base_payload()
    mutated = copy.deepcopy(payload)
    del mutated["rules"][0]["source_page"]

    report = evaluate_release_gate(mutated)

    assert report["publish_status"] == "Hold"
    assert report["classification"] == "not-usable"
    assert "rule_provenance" in report["high_severity_failures"]


def test_release_gate_recognizes_event_artifacts_and_sample_policy() -> None:
    payload = _base_payload()
    payload["event_artifacts"] = {
        "event_json": "artifacts/events.json",
        "event_csv": "artifacts/events.csv",
        "post_breakout_path": "artifacts/post_breakout_path.json",
    }
    payload["sample_policy"] = {
        "overlap_policy": "one primary event per symbol cluster",
        "censoring_policy": "right-censor at available future path",
    }
    payload["statistics"].update(
        {
            "anchor_mode": "B_ref_and_B_exec",
            "market_group_table": {"VN30": {}, "VN100 ex VN30": {}, "Outside VN100": {}},
            "failure_ladder": {"fail_5pct_rate": 1.0},
            "target_first_before_adverse_5pct": 1.0,
            "tbpb_30_rate": 1.0,
            "time_to_target": {"median_days_to_target": 10},
            "quantile_metrics": {"fav_exc_pct": {"P50": 5.0}},
            "symbol_concentration": {"top10_symbol_share": 10.0},
            "post_breakout_table": {"lookahead_bars": 60},
        }
    )

    report = evaluate_release_gate(payload)

    assert "event_path" not in report["high_severity_failures"]
    assert "overlap_censoring" not in report["high_severity_failures"]
    assert "event_level_ohlcv_path" not in report["p0_missing"]
    assert "event_level_json_csv" not in report["p0_missing"]


def test_enriched_payload_validates_against_monograph_schema() -> None:
    enriched = enrich_payload_with_p1_p5_status(_base_payload())
    schema = json.loads(Path("schemas/scanner_v2/monograph_payload.schema.json").read_text(encoding="utf-8"))

    errors = sorted(Draft202012Validator(schema).iter_errors(enriched), key=lambda err: list(err.path))

    assert errors == []
    assert enriched["release_gate_status"]["publish_status"] == "Hold"
    assert enriched["methodology_status"]["standard_version"] == "bulkowski_vietnam_p1_p5_v1"
