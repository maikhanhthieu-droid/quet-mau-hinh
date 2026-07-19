from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scanner.run_bull_flag_fresh_discovery import export_sqlite_to_stock_series, sqlite_ohlcv_manifest


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            """
            CREATE TABLE stocks (ticker TEXT PRIMARY KEY, status TEXT);
            CREATE TABLE stock_exchange (ticker TEXT, exchange TEXT);
            CREATE TABLE stock_price_history (
                symbol TEXT,
                time TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume INTEGER
            );
            INSERT INTO stocks VALUES ('AAA', 'listed'), ('BBB', 'delisted');
            INSERT INTO stock_exchange VALUES ('AAA', 'HSX'), ('BBB', 'DELISTED');
            """
        )
        for day in range(1, 6):
            conn.execute(
                "INSERT INTO stock_price_history VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("AAA", f"2026-01-0{day}", 10 + day, 11 + day, 9 + day, 10.5 + day, 1000 * day),
            )
            conn.execute(
                "INSERT INTO stock_price_history VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("BBB", f"2026-01-0{day}", 20 + day, 21 + day, 19 + day, 20.5 + day, 1000 * day),
            )
        conn.commit()
    finally:
        conn.close()


def test_sqlite_manifest_detects_ohlcv_candidate(tmp_path: Path) -> None:
    db_path = tmp_path / "stocks.db"
    _make_db(db_path)

    manifest = sqlite_ohlcv_manifest(db_path)

    assert manifest["status"] == "ohlcv_candidate"
    assert manifest["total_rows"] == 10
    assert manifest["symbol_count"] == 2
    assert manifest["active_symbol_count"] == 1
    assert manifest["max_date"] == "2026-01-05"


def test_export_sqlite_to_stock_series_uses_active_symbols(tmp_path: Path) -> None:
    db_path = tmp_path / "stocks.db"
    out_root = tmp_path / "export"
    _make_db(db_path)

    report = export_sqlite_to_stock_series(db_path, out_root, min_history_rows=3)

    assert report["status"] == "exported"
    assert report["exported_symbols"] == 1
    assert (out_root / "stock_series" / "AAA.json").exists()
    assert not (out_root / "stock_series" / "BBB.json").exists()
    rows = json.loads((out_root / "stock_series" / "AAA.json").read_text(encoding="utf-8"))
    assert {"date", "open", "high", "low", "close", "volume", "value", "ret_1d", "range_pct"}.issubset(rows[0])
    metadata = json.loads((out_root / "market_stats_data.json").read_text(encoding="utf-8"))
    assert metadata["membership_version"]["snapshot_date"] == "2026-01-05"
    assert metadata["stocks"][0]["symbol"] == "AAA"
