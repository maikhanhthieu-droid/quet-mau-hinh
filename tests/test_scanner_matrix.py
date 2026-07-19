from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scanner.v2 import ScannerV2Engine
from scanner.v2.matrix import (
    MATRIX_EVENT_COLUMNS,
    ContractError,
    build_bull_flag_matrix_artifacts,
    build_flag_family_matrix_artifacts,
    default_scanner_matrix,
    normalize_bull_flag_events,
    validate_matrix_events,
)


def _bull_flag_fixture() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "detection_id": "bf_AAA_2024-01-10",
                "symbol": "AAA",
                "market_group": "VN100 ex VN30",
                "market_regime": "bull",
                "formation_start_date": "2023-12-20",
                "formation_end_date": "2024-01-09",
                "breakout_date": "2024-01-10",
                "breakout_direction": "up",
                "breakout_price": 20.0,
                "b_exec_price": 20.2,
                "target_price": 23.5,
                "mfe_pct": 18.0,
                "mae_pct": 4.0,
                "target_hit": True,
                "failure_5pct": False,
                "target_first_before_adverse_5pct": True,
                "pattern_quality_score": 82.0,
                "pattern_quality_tier": "premium",
                "breakout_close_location": 0.85,
                "breakout_body_to_range": 0.60,
                "breakout_volume_ratio_20": 1.4,
                "breakout_gap_pct": 0.4,
                "tradability_quality_score": 94.0,
                "tradability_quality_bucket": "clean",
                "liquidity_bucket": "high",
                "path_quality_bucket": "clean",
                "corp_action_near_breakout_flag": False,
            },
            {
                "detection_id": "bf_BBB_2024-02-12",
                "symbol": "BBB",
                "market_group": "Outside VN100",
                "market_regime": "bear",
                "formation_start_date": "2024-01-22",
                "formation_end_date": "2024-02-09",
                "breakout_date": "2024-02-12",
                "breakout_direction": "up",
                "breakout_price": 10.0,
                "b_exec_price": 10.1,
                "target_price": 11.2,
                "mfe_pct": 2.0,
                "mae_pct": 9.0,
                "target_hit": False,
                "failure_5pct": True,
                "target_first_before_adverse_5pct": False,
                "pattern_quality_score": 55.0,
                "breakout_close_location": 0.45,
                "breakout_body_to_range": 0.2,
                "breakout_volume_ratio_20": 0.8,
                "breakout_gap_pct": 4.0,
                "tradability_quality_score": 65.0,
                "tradability_quality_bucket": "usable",
                "liquidity_bucket": "mid",
                "path_quality_bucket": "stale_close",
                "corp_action_near_breakout_flag": True,
            },
        ]
    )


def test_default_scanner_matrix_registers_bull_flag_as_reference_scanner() -> None:
    registry = default_scanner_matrix()
    manifest = registry.manifest()

    assert manifest["event_contract_version"] == "scanner_matrix_event_v1"
    assert [scanner["pattern_id"] for scanner in manifest["scanners"]] == [
        "bull_flags",
        "bear_flags",
        "triangles_ascending",
        "triangles_descending",
        "triangles_symmetrical",
        "wedges_falling",
        "wedges_rising",
    ]
    roles = {scanner["pattern_id"]: scanner["role"] for scanner in manifest["scanners"]}
    assert roles["bull_flags"] == "reference_scanner"
    assert roles["bear_flags"] == "reference_scanner"
    assert roles["triangles_ascending"] == "chapter_scanner"
    assert roles["triangles_descending"] == "chapter_scanner"
    assert roles["triangles_symmetrical"] == "chapter_scanner"
    assert roles["wedges_falling"] == "chapter_scanner"
    assert roles["wedges_rising"] == "chapter_scanner"
    assert manifest["columns"] == list(MATRIX_EVENT_COLUMNS)


def test_bull_flag_events_normalize_to_matrix_contract() -> None:
    registry = default_scanner_matrix()
    normalized = normalize_bull_flag_events(_bull_flag_fixture())

    assert list(normalized.columns) == list(MATRIX_EVENT_COLUMNS)
    assert validate_matrix_events(normalized, registry) == []
    assert set(normalized["pattern_id"]) == {"bull_flags"}
    assert set(normalized["status"]) == {"confirmed"}
    assert normalized.loc[0, "quality_tier"] in {"premium", "standard"}
    assert normalized.loc[1, "invalidation_reasons"]
    assert "failure_5pct" in json.loads(normalized.loc[1, "invalidation_reasons"])
    target_family = json.loads(normalized.loc[0, "target_family"])
    assert target_family["base"] == 0.46
    assert target_family["legacy_full"] == 1.0


def test_matrix_validation_fails_closed_for_unknown_pattern() -> None:
    registry = default_scanner_matrix()
    normalized = normalize_bull_flag_events(_bull_flag_fixture())
    normalized.loc[0, "pattern_id"] = "unknown_pattern"

    errors = validate_matrix_events(normalized, registry)

    assert any("unregistered active pattern ids" in error for error in errors)


def test_matrix_artifact_writer_emits_manifest_and_events(tmp_path: Path) -> None:
    events_path = tmp_path / "events.csv"
    _bull_flag_fixture().to_csv(events_path, index=False)

    paths = build_bull_flag_matrix_artifacts(events_path, tmp_path / "matrix", engine=ScannerV2Engine())

    assert paths["events"].exists()
    assert paths["manifest"].exists()
    events = pd.read_csv(paths["events"])
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    assert len(events) == 2
    assert manifest["scanners"][0]["pattern_id"] == "bull_flags"


def test_matrix_artifact_writer_blocks_invalid_contract(tmp_path: Path) -> None:
    events_path = tmp_path / "events.csv"
    bad = _bull_flag_fixture()
    bad.loc[0, "breakout_price"] = None
    bad.to_csv(events_path, index=False)

    with pytest.raises(ContractError, match="confirmation_price"):
        build_bull_flag_matrix_artifacts(events_path, tmp_path / "matrix")


def test_flag_family_matrix_artifact_writer_accepts_bull_and_bear_flags(tmp_path: Path) -> None:
    bull_path = tmp_path / "bull_events.csv"
    bear_path = tmp_path / "bear_events.csv"
    bull = _bull_flag_fixture()
    bear = _bull_flag_fixture()
    bear["detection_id"] = bear["detection_id"].str.replace("bf_", "brf_", regex=False)
    bear["breakout_direction"] = "down"
    bull.to_csv(bull_path, index=False)
    bear.to_csv(bear_path, index=False)

    paths = build_flag_family_matrix_artifacts(
        {"bull_flags": bull_path, "bear_flags": bear_path},
        tmp_path / "family_matrix",
    )

    events = pd.read_csv(paths["events"])
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    assert set(events["pattern_id"]) == {"bull_flags", "bear_flags"}
    assert set(events["direction"]) == {"up", "down"}
    assert [scanner["pattern_id"] for scanner in manifest["scanners"]] == [
        "bull_flags",
        "bear_flags",
        "triangles_ascending",
        "triangles_descending",
        "triangles_symmetrical",
        "wedges_falling",
        "wedges_rising",
    ]
