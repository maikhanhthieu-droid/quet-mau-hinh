from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd

from scanner.v2.data_gate_audit import audit_chapter_data_gates, render_data_gate_markdown


def test_data_gate_audit_blocks_when_market_stats_is_snapshot_only(tmp_path: Path) -> None:
    events = pd.DataFrame(
        {
            "detection_id": ["bull_flags:000001"],
            "symbol": ["AAA"],
            "breakout_date": ["2024-01-10"],
            "target_dist_pct": [10.0],
            "mfe_pct": [8.0],
            "mae_pct": [2.0],
        }
    )
    path = pd.DataFrame(
        {
            "event_id": ["bull_flags:000001"] * 60,
            "bar_after_breakout": list(range(1, 61)),
            "signed_high_excursion_pct": [1.0] * 60,
            "signed_low_excursion_pct": [-1.0] * 60,
        }
    )
    stock_dir = tmp_path / "stock_series"
    stock_dir.mkdir()
    (stock_dir / "AAA.json").write_text(
        json.dumps(
            [
                {"date": "2024-01-08", "value": 2_000_000_000},
                {"date": "2024-01-09", "value": 2_000_000_000},
            ]
        ),
        encoding="utf-8",
    )
    events_path = tmp_path / "events.csv"
    path_path = tmp_path / "path.csv"
    meta_path = tmp_path / "market_stats.json"
    db_path = tmp_path / "membership.sqlite"
    events.to_csv(events_path, index=False)
    path.to_csv(path_path, index=False)
    meta_path.write_text(
        json.dumps(
            {
                "stocks": [{"symbol": "AAA", "exchange": "HOSE"}],
                "sources": {"stock_ohlcv": {"symbol_count": 1, "stock_series_count": 1, "excluded_symbol_count": 0}},
                "data_basis": {"price": "provider_adjusted_ohlcv", "adjustment": "provider_adjusted_without_factor_audit"},
                "membership_version": {"mode": "current_snapshot", "point_in_time_ready": False, "history_maturity": "unavailable"},
            }
        ),
        encoding="utf-8",
    )
    con = sqlite3.connect(db_path)
    con.execute(
        "create table index_membership_history(index_code text, ticker text, effective_from text, effective_to text, snapshot_date text, source text, created_at text, closed_at text)"
    )
    con.execute(
        "insert into index_membership_history values('VN30','AAA','2026-01-01',NULL,'2026-01-01','snapshot','2026-01-01',NULL)"
    )
    con.commit()
    con.close()

    report = audit_chapter_data_gates(
        pattern_key="bull_flags",
        events_csv=events_path,
        path_csv=path_path,
        market_stats_json=meta_path,
        membership_db=db_path,
        stock_series_dir=stock_dir,
    )

    assert report["investment_reference_data_gates_pass"] is False
    assert "point_in_time_universe" in report["blocked_by"]
    assert "corporate_action_audit" in report["blocked_by"]
    assert "membership_history_db" in report["blocked_by"]
    assert "delisted_halted_status" in report["blocked_by"]
    assert "| Point-in-time universe" in render_data_gate_markdown(report)


def test_available_series_scope_discloses_membership_without_blocking(tmp_path: Path) -> None:
    events = pd.DataFrame(
        {
            "detection_id": ["bull_flags:000001"],
            "symbol": ["AAA"],
            "breakout_date": ["2024-01-10"],
            "target_dist_pct": [10.0],
            "mfe_pct": [8.0],
            "mae_pct": [2.0],
            "adtv20_value": [2_000_000],
            "liquidity_bucket": ["high"],
            "is_primary_event_60d": [True],
        }
    )
    path = pd.DataFrame(
        {
            "event_id": ["bull_flags:000001"] * 60,
            "bar_after_breakout": list(range(1, 61)),
            "signed_high_excursion_pct": [1.0] * 60,
            "signed_low_excursion_pct": [-1.0] * 60,
        }
    )
    stock_dir = tmp_path / "stock_series"
    stock_dir.mkdir()
    events_path = tmp_path / "events.csv"
    path_path = tmp_path / "path.csv"
    meta_path = tmp_path / "market_stats.json"
    db_path = tmp_path / "membership.sqlite"
    events.to_csv(events_path, index=False)
    path.to_csv(path_path, index=False)
    meta_path.write_text(
        json.dumps(
            {
                "stocks": [{"symbol": "AAA", "exchange": "HOSE"}],
                "sources": {"stock_ohlcv": {"symbol_count": 1, "stock_series_count": 1, "excluded_symbol_count": 0}},
                "data_basis": {"price": "provider_adjusted_ohlcv", "adjustment": "provider_adjusted_without_factor_audit"},
                "membership_version": {"mode": "current_snapshot", "point_in_time_ready": False, "history_maturity": "unavailable"},
            }
        ),
        encoding="utf-8",
    )
    sqlite3.connect(db_path).close()

    report = audit_chapter_data_gates(
        pattern_key="bull_flags",
        events_csv=events_path,
        path_csv=path_path,
        market_stats_json=meta_path,
        membership_db=db_path,
        stock_series_dir=stock_dir,
        universe_scope="available_series_descriptive",
        use_historical_membership=False,
    )

    assert report["universe_scope"] == "available_series_descriptive"
    assert "point_in_time_universe" not in report["blocked_by"]
    assert "active_universe_coverage" not in report["blocked_by"]
    assert "membership_history_db" not in report["blocked_by"]
    assert "corporate_action_audit" in report["blocked_by"]


def test_available_series_scope_blocks_symbols_missing_from_active_universe(tmp_path: Path) -> None:
    events = pd.DataFrame(
        {
            "detection_id": ["bull_flags:000001"],
            "symbol": ["AAA"],
            "breakout_date": ["2024-01-10"],
            "target_dist_pct": [10.0],
            "mfe_pct": [8.0],
            "mae_pct": [2.0],
            "adtv20_value": [2_000_000],
            "liquidity_bucket": ["high"],
            "is_primary_event_60d": [True],
            "corp_action_proxy_flag": [False],
            "halted_delisted_proxy_flag": [False],
        }
    )
    path = pd.DataFrame(
        {
            "event_id": ["bull_flags:000001"] * 60,
            "bar_after_breakout": list(range(1, 61)),
            "signed_high_excursion_pct": [1.0] * 60,
            "signed_low_excursion_pct": [-1.0] * 60,
        }
    )
    stock_dir = tmp_path / "stock_series"
    stock_dir.mkdir()
    events_path = tmp_path / "events.csv"
    path_path = tmp_path / "path.csv"
    meta_path = tmp_path / "market_stats.json"
    db_path = tmp_path / "membership.sqlite"
    events.to_csv(events_path, index=False)
    path.to_csv(path_path, index=False)
    meta_path.write_text(
        json.dumps(
            {
                "stocks": [{"symbol": "FPT", "exchange": "HOSE"}],
                "sources": {"stock_ohlcv": {"symbol_count": 1, "stock_series_count": 1, "excluded_symbol_count": 10}},
                "data_basis": {"price": "provider_adjusted_ohlcv", "adjustment": "provider_adjusted_without_factor_audit"},
                "membership_version": {"mode": "current_snapshot", "point_in_time_ready": False, "history_maturity": "unavailable"},
            }
        ),
        encoding="utf-8",
    )
    sqlite3.connect(db_path).close()

    report = audit_chapter_data_gates(
        pattern_key="bull_flags",
        events_csv=events_path,
        path_csv=path_path,
        market_stats_json=meta_path,
        membership_db=db_path,
        stock_series_dir=stock_dir,
        universe_scope="available_series_descriptive",
        use_historical_membership=False,
    )

    assert "active_universe_coverage" in report["blocked_by"]
    active_gate = next(gate for gate in report["gates"] if gate["gate_id"] == "active_universe_coverage")
    assert active_gate["evidence"]["missing_event_symbols"] == ["AAA"]
