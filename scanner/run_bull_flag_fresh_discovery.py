"""Discover and materialize fresh Bull Flag OOS source candidates.

The scanner consumes Market Stats-style ``stock_series/*.json`` directories.
This helper audits nearby OHLCV sources, exports compatible snapshots from
SQLite databases when possible, and then runs the frozen Bull Flag wider/OOS
gate without reselection.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.run_bull_flag_wider_oos import (  # noqa: E402
    DEFAULT_PROFILE_ID,
    TUNED_SNAPSHOT_LABEL,
    build_source_manifest,
    run_wider_oos,
)
from scanner.v2.flags_experiment import DEFAULT_INDEX_DB, DEFAULT_INDEX_SYMBOL  # noqa: E402


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bull_flags_fresh_discovery")
DEFAULT_SQLITE_CANDIDATES = (
    Path("../Báo cáo tài chính/vietnam_stocks.db"),
    Path("../market_cache/stock_ohlcv/latest.sqlite"),
    Path("vietnam_stocks.db"),
    Path("../Báo cáo tài chính/vietnam_stocks_liquidity_fixed_2026-02-18.db"),
)


def _sqlite_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {str(row[0]) for row in rows}


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _scalar(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> Any:
    row = conn.execute(sql, tuple(params)).fetchone()
    return row[0] if row else None


def _active_symbols(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    tables = _sqlite_tables(conn)
    if not {"stocks", "stock_exchange"}.issubset(tables):
        rows = conn.execute("SELECT DISTINCT symbol FROM stock_price_history ORDER BY symbol").fetchall()
        return [{"symbol": str(row[0]).upper(), "exchange": None, "status": None} for row in rows]
    rows = conn.execute(
        """
        SELECT DISTINCT s.ticker, se.exchange, s.status
        FROM stocks s
        LEFT JOIN stock_exchange se ON se.ticker = s.ticker
        WHERE UPPER(COALESCE(s.status, 'listed')) = 'LISTED'
          AND UPPER(COALESCE(se.exchange, '')) IN ('HSX', 'HOSE', 'HNX', 'UPCOM')
        ORDER BY s.ticker
        """
    ).fetchall()
    if not rows:
        rows = conn.execute(
            """
            SELECT DISTINCT s.ticker, NULL AS exchange, s.status
            FROM stocks s
            WHERE UPPER(COALESCE(s.status, 'listed')) = 'LISTED'
            ORDER BY s.ticker
            """
        ).fetchall()
    return [{"symbol": str(symbol).upper(), "exchange": exchange, "status": status} for symbol, exchange, status in rows]


def sqlite_ohlcv_manifest(db_path: Path) -> Dict[str, Any]:
    if not db_path.exists():
        return {"source_type": "sqlite", "path": str(db_path), "available": False, "status": "missing"}
    try:
        conn = sqlite3.connect(str(db_path))
    except sqlite3.Error as exc:
        return {"source_type": "sqlite", "path": str(db_path), "available": False, "status": "open_error", "error": str(exc)}
    try:
        tables = _sqlite_tables(conn)
        if "stock_price_history" not in tables:
            return {"source_type": "sqlite", "path": str(db_path), "available": True, "status": "missing_stock_price_history"}
        cols = _table_columns(conn, "stock_price_history")
        required = {"symbol", "time", "open", "high", "low", "close", "volume"}
        missing = sorted(required - cols)
        if missing:
            return {"source_type": "sqlite", "path": str(db_path), "available": True, "status": "missing_columns", "missing_columns": missing}
        total_rows = int(_scalar(conn, "SELECT COUNT(*) FROM stock_price_history") or 0)
        symbol_count = int(_scalar(conn, "SELECT COUNT(DISTINCT symbol) FROM stock_price_history") or 0)
        min_date = _scalar(conn, "SELECT MIN(time) FROM stock_price_history")
        max_date = _scalar(conn, "SELECT MAX(time) FROM stock_price_history")
        active = _active_symbols(conn)
        return {
            "source_type": "sqlite",
            "path": str(db_path),
            "available": True,
            "status": "ohlcv_candidate",
            "total_rows": total_rows,
            "symbol_count": symbol_count,
            "min_date": min_date,
            "max_date": max_date,
            "active_symbol_count": len({row["symbol"] for row in active}),
            "snapshot_id": f"sqlite:{db_path.name}:{max_date}",
        }
    finally:
        conn.close()


def discover_sqlite_candidates(paths: Iterable[Path] = DEFAULT_SQLITE_CANDIDATES) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    rows: List[Dict[str, Any]] = []
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        rows.append(sqlite_ohlcv_manifest(path))
    return rows


def _prepare_export_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    for col in ("open", "high", "low", "close", "volume"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["date", "open", "high", "low", "close"])
    out = out[(out["open"] > 0) & (out["high"] > 0) & (out["low"] > 0) & (out["close"] > 0)].copy()
    out = out.sort_values("date")
    out["volume"] = out["volume"].fillna(0).clip(lower=0)
    out["value"] = (out["close"] * out["volume"]).round(0)
    out["ret_1d"] = (out["close"].pct_change() * 100.0).round(4)
    out["range_pct"] = ((out["high"] - out["low"]) / out["close"].replace(0, pd.NA) * 100.0).round(4)
    out["ma20"] = out["close"].rolling(20, min_periods=1).mean().round(4)
    out["ma50"] = out["close"].rolling(50, min_periods=1).mean().round(4)
    out["ma200"] = out["close"].rolling(200, min_periods=1).mean().round(4)
    volume_base = out["volume"].rolling(20, min_periods=5).median().astype(float).replace(0.0, float("nan"))
    out["volume_spike_20d"] = (out["volume"] / volume_base).round(4)
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    cols = ["date", "open", "high", "low", "close", "volume", "value", "ma20", "ma50", "ma200", "ret_1d", "range_pct", "volume_spike_20d"]
    return out[cols].replace({pd.NA: None})


def export_sqlite_to_stock_series(db_path: Path, out_root: Path, *, min_history_rows: int = 260) -> Dict[str, Any]:
    out_series = out_root / "stock_series"
    out_series.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    exported = 0
    skipped = 0
    rows_written = 0
    max_export_date: Optional[str] = None
    try:
        active = _active_symbols(conn)
        active_symbols = sorted({row["symbol"] for row in active})
        active_meta = {row["symbol"]: row for row in active}
        for symbol in active_symbols:
            df = pd.read_sql_query(
                """
                SELECT time AS date, open, high, low, close, volume
                FROM stock_price_history
                WHERE symbol = ?
                ORDER BY time
                """,
                conn,
                params=[symbol],
            )
            clean = _prepare_export_frame(df)
            if len(clean) < int(min_history_rows):
                skipped += 1
                continue
            (out_series / f"{symbol}.json").write_text(clean.to_json(orient="records", force_ascii=False), encoding="utf-8")
            exported += 1
            rows_written += int(len(clean))
            last_date = str(clean.iloc[-1]["date"]) if not clean.empty else None
            if last_date and (max_export_date is None or last_date > max_export_date):
                max_export_date = last_date
        stocks = [
            {
                "symbol": symbol,
                "exchange": active_meta.get(symbol, {}).get("exchange"),
                "status": active_meta.get(symbol, {}).get("status"),
            }
            for symbol in active_symbols
            if (out_series / f"{symbol}.json").exists()
        ]
        metadata = {
            "schema_version": "market-stats-compatible-sqlite-export-v1",
            "generated_at": pd.Timestamp.now("UTC").replace(microsecond=0).isoformat(),
            "source_db": str(db_path),
            "data_basis": {
                "price": "sqlite_stock_price_history",
                "adjustment_label": "source_db_adjusted_state_unknown",
                "adjustment_guardrail": "No official corporate-action factor log in this export.",
                "membership": "current listed symbols from source DB",
            },
            "membership_version": {
                "mode": "current_snapshot_from_sqlite",
                "point_in_time_ready": False,
                "has_history": False,
                "snapshot_date": max_export_date,
            },
            "classification_version": {"point_in_time_ready": False},
            "sources": {"stock_ohlcv": {"source": str(db_path), "symbol_count": exported, "excluded_symbol_count": skipped}},
            "stocks": stocks,
            "indices": [],
        }
        metadata_path = out_root / "market_stats_data.json"
        metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        return {
            "status": "exported",
            "db_path": str(db_path),
            "stock_series_dir": str(out_series),
            "market_stats_json": str(metadata_path),
            "exported_symbols": exported,
            "skipped_symbols": skipped,
            "rows_written": rows_written,
        }
    finally:
        conn.close()


def _best_candidate(rows: Iterable[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    candidates = [dict(row) for row in rows if row.get("status") == "ohlcv_candidate" and int(row.get("active_symbol_count") or 0) > 0]
    if not candidates:
        return None
    return max(candidates, key=lambda row: (str(row.get("max_date") or ""), int(row.get("active_symbol_count") or 0), int(row.get("total_rows") or 0)))


def run_discovery(
    *,
    out_dir: Path,
    sqlite_candidates: Iterable[Path],
    export_best: bool,
    run_gate: bool,
    min_history_rows: int,
    profile_id: str,
    monte_carlo_iterations: int,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = discover_sqlite_candidates(sqlite_candidates)
    best = _best_candidate(rows)
    export_report: Dict[str, Any] = {"status": "not_requested"}
    gate_paths: Dict[str, str] = {}
    if export_best and best:
        export_root = out_dir / "exported_snapshot"
        export_report = export_sqlite_to_stock_series(Path(str(best["path"])), export_root, min_history_rows=min_history_rows)
        if run_gate and export_report.get("status") == "exported":
            gate_out = out_dir / "gate"
            source_snapshot_id = f"{best.get('snapshot_id')}:active_export:min_rows_{min_history_rows}"
            paths = run_wider_oos(
                out_dir=gate_out,
                source_dir=Path(str(export_report["stock_series_dir"])),
                market_stats_json=Path(str(export_report["market_stats_json"])),
                profile_id=profile_id,
                source_snapshot_id=source_snapshot_id,
                start_date="2025-01-01",
                end_date=None,
                index_db=DEFAULT_INDEX_DB,
                index_symbol=DEFAULT_INDEX_SYMBOL,
                limit_symbols=None,
                monte_carlo_iterations=monte_carlo_iterations,
            )
            gate_paths = {key: str(value) for key, value in paths.items()}
    payload = {
        "discovery_id": "bull_flag_fresh_source_discovery_v1",
        "tuned_snapshot_id": TUNED_SNAPSHOT_LABEL,
        "candidates": rows,
        "best_candidate": best,
        "export_report": export_report,
        "gate_paths": gate_paths,
    }
    paths_out = {
        "json": out_dir / "bull_flag_fresh_discovery.json",
        "csv": out_dir / "bull_flag_fresh_discovery_sources.csv",
    }
    paths_out["json"].write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    pd.DataFrame(rows).to_csv(paths_out["csv"], index=False)
    if gate_paths:
        paths_out["gate_json"] = Path(gate_paths["json"])
        paths_out["gate_report"] = Path(gate_paths["report"])
    return paths_out


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover/export fresh Bull Flag source candidates and optionally run the frozen gate.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--sqlite-candidate", action="append", default=None)
    parser.add_argument("--export-best", action="store_true")
    parser.add_argument("--run-gate", action="store_true")
    parser.add_argument("--min-history-rows", type=int, default=260)
    parser.add_argument("--profile-id", default=DEFAULT_PROFILE_ID)
    parser.add_argument("--monte-carlo-iterations", type=int, default=500)
    args = parser.parse_args()
    candidates = [Path(value) for value in args.sqlite_candidate] if args.sqlite_candidate else list(DEFAULT_SQLITE_CANDIDATES)
    paths = run_discovery(
        out_dir=Path(args.out_dir),
        sqlite_candidates=candidates,
        export_best=args.export_best,
        run_gate=args.run_gate,
        min_history_rows=args.min_history_rows,
        profile_id=args.profile_id,
        monte_carlo_iterations=args.monte_carlo_iterations,
    )
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
