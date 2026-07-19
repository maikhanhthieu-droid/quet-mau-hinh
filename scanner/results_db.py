"""
Persistence layer for pattern scan results.

Goal: write detections to a separate SQLite DB (not the source price DB),
track runs with run_id, and provide indexes for analysis queries.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import traceback as _traceback
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple
from uuid import uuid4


def generate_run_id(prefix: str = "scan") -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}_{ts}_{uuid4().hex[:8]}"


def connect_results_db(results_db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(results_db_path)), exist_ok=True)
    conn = sqlite3.connect(results_db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS scanner_runs (
            run_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            source_db_path TEXT NOT NULL,
            source_table TEXT NOT NULL,
            symbols_planned INTEGER,
            symbols_scanned INTEGER,
            symbols_failed INTEGER,
            patterns_json TEXT NOT NULL,
            run_config_json TEXT NOT NULL,
            run_config_hash TEXT NOT NULL,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS pattern_detections (
            run_id TEXT NOT NULL,
            pattern_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            pattern_name TEXT NOT NULL,
            pattern_type TEXT,
            formation_start TEXT,
            formation_end TEXT,
            breakout_date TEXT,
            breakout_direction TEXT,
            breakout_price REAL,
            target_price REAL,
            stop_loss_price REAL,
            confidence_score INTEGER,
            volume_confirmed INTEGER,
            pattern_height_pct REAL,
            pattern_width_bars INTEGER,
            touch_count INTEGER,
            pivot_indices_json TEXT,
            config_hash TEXT,
            base_pattern_name TEXT,
            variant_code TEXT,
            variant_confidence INTEGER,
            variant_evidence_json TEXT,
            first_extreme_width_bars INTEGER,
            second_extreme_width_bars INTEGER,
            family_metrics_json TEXT,
            created_at TEXT,
            PRIMARY KEY (run_id, pattern_id),
            FOREIGN KEY (run_id) REFERENCES scanner_runs(run_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS post_breakout_results (
            run_id TEXT NOT NULL,
            pattern_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            pattern_name TEXT NOT NULL,
            breakout_date TEXT,
            breakout_price REAL,
            breakout_direction TEXT,
            target_price REAL,
            stop_loss_price REAL,
            bust_failure_5pct INTEGER,
            bust_failure_10pct INTEGER,
            bust_failure_date TEXT,
            bust_failure_pct REAL,
            boundary_invalidated INTEGER,
            boundary_invalidation_date TEXT,
            ultimate_price REAL,
            ultimate_date TEXT,
            days_to_ultimate INTEGER,
            ultimate_stop_reason TEXT,
            throwback_pullback_occurred INTEGER,
            throwback_pullback_date TEXT,
            days_to_throwback_pullback INTEGER,
            retested_breakout_level INTEGER,
            retested_boundary_level INTEGER,
            target_achieved_intraday INTEGER,
            target_achieved_close INTEGER,
            target_achievement_date TEXT,
            days_to_target INTEGER,
            max_favorable_excursion_pct REAL,
            max_adverse_excursion_pct REAL,
            variant TEXT,
            peak1_width_bars INTEGER,
            peak2_width_bars INTEGER,
            evaluation_window_bars INTEGER,
            evaluation_date TEXT,
            PRIMARY KEY (run_id, pattern_id),
            FOREIGN KEY (run_id, pattern_id) REFERENCES pattern_detections(run_id, pattern_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS run_statistics (
            run_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            stats_json TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES scanner_runs(run_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS scan_errors (
            run_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            created_at TEXT NOT NULL,
            error TEXT NOT NULL,
            traceback TEXT NOT NULL,
            PRIMARY KEY (run_id, symbol, created_at),
            FOREIGN KEY (run_id) REFERENCES scanner_runs(run_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_detections_run_symbol
            ON pattern_detections(run_id, symbol);
        CREATE INDEX IF NOT EXISTS idx_detections_run_pattern
            ON pattern_detections(run_id, pattern_name);
        CREATE INDEX IF NOT EXISTS idx_detections_run_symbol_pattern
            ON pattern_detections(run_id, symbol, pattern_name);
        CREATE INDEX IF NOT EXISTS idx_detections_run_breakout_date
            ON pattern_detections(run_id, breakout_date);
        CREATE INDEX IF NOT EXISTS idx_detections_run_confidence
            ON pattern_detections(run_id, confidence_score);
        CREATE INDEX IF NOT EXISTS idx_detections_run_variant
            ON pattern_detections(run_id, variant_code);

        CREATE INDEX IF NOT EXISTS idx_eval_run_symbol
            ON post_breakout_results(run_id, symbol);
        CREATE INDEX IF NOT EXISTS idx_eval_run_pattern
            ON post_breakout_results(run_id, pattern_name);
        CREATE INDEX IF NOT EXISTS idx_eval_run_variant
            ON post_breakout_results(run_id, variant);
        CREATE INDEX IF NOT EXISTS idx_eval_run_breakout_date
            ON post_breakout_results(run_id, breakout_date);

        CREATE INDEX IF NOT EXISTS idx_errors_run_symbol
            ON scan_errors(run_id, symbol);
        """
    )

    # Older result DBs were created before family/variant metadata existed.
    # Keep migrations inline so reruns persist the richer detector evidence.
    def _ensure_column(table: str, column: str, ddl: str) -> None:
        existing = {
            str(row[1])
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

    _ensure_column("pattern_detections", "base_pattern_name", "base_pattern_name TEXT")
    _ensure_column("pattern_detections", "variant_code", "variant_code TEXT")
    _ensure_column("pattern_detections", "variant_confidence", "variant_confidence INTEGER")
    _ensure_column("pattern_detections", "variant_evidence_json", "variant_evidence_json TEXT")
    _ensure_column("pattern_detections", "first_extreme_width_bars", "first_extreme_width_bars INTEGER")
    _ensure_column("pattern_detections", "second_extreme_width_bars", "second_extreme_width_bars INTEGER")
    _ensure_column("pattern_detections", "family_metrics_json", "family_metrics_json TEXT")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_detections_run_variant
            ON pattern_detections(run_id, variant_code)
        """
    )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    source_db_path: str,
    source_table: str,
    patterns: Sequence[str],
    run_config: Dict[str, Any],
    run_config_hash: str,
    symbols_planned: Optional[int] = None,
    symbols_scanned: Optional[int] = None,
    symbols_failed: Optional[int] = None,
    notes: Optional[str] = None,
    created_at: Optional[str] = None,
) -> None:
    created_at = created_at or _utc_now_iso()

    conn.execute(
        """
        INSERT INTO scanner_runs (
            run_id, created_at, source_db_path, source_table,
            symbols_planned, symbols_scanned, symbols_failed,
            patterns_json, run_config_json, run_config_hash, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET
            source_db_path=excluded.source_db_path,
            source_table=excluded.source_table,
            symbols_planned=excluded.symbols_planned,
            symbols_scanned=excluded.symbols_scanned,
            symbols_failed=excluded.symbols_failed,
            patterns_json=excluded.patterns_json,
            run_config_json=excluded.run_config_json,
            run_config_hash=excluded.run_config_hash,
            notes=excluded.notes
        """,
        (
            run_id,
            created_at,
            source_db_path,
            source_table,
            symbols_planned,
            symbols_scanned,
            symbols_failed,
            json.dumps(list(patterns)),
            json.dumps(run_config, sort_keys=True, default=str),
            run_config_hash,
            notes,
        ),
    )


def insert_detections(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    detections: Iterable[Any],
) -> int:
    rows: list[Tuple[Any, ...]] = []
    for d in detections:
        pivot_indices = getattr(d, "pivot_indices", None)
        if pivot_indices is None and is_dataclass(d):
            pivot_indices = asdict(d).get("pivot_indices")

        rows.append(
            (
                run_id,
                getattr(d, "pattern_id"),
                getattr(d, "symbol"),
                getattr(d, "pattern_name"),
                getattr(d, "pattern_type", None),
                getattr(d, "formation_start", None),
                getattr(d, "formation_end", None),
                getattr(d, "breakout_date", None),
                getattr(d, "breakout_direction", None),
                getattr(d, "breakout_price", None),
                getattr(d, "target_price", None),
                getattr(d, "stop_loss_price", None),
                getattr(d, "confidence_score", None),
                1 if getattr(d, "volume_confirmed", False) else 0,
                getattr(d, "pattern_height_pct", None),
                getattr(d, "pattern_width_bars", None),
                getattr(d, "touch_count", None),
                json.dumps(pivot_indices) if pivot_indices is not None else None,
                getattr(d, "config_hash", None),
                getattr(d, "base_pattern_name", None),
                getattr(d, "variant_code", None),
                getattr(d, "variant_confidence", None),
                getattr(d, "variant_evidence_json", None),
                getattr(d, "first_extreme_width_bars", None),
                getattr(d, "second_extreme_width_bars", None),
                getattr(d, "family_metrics_json", None),
                getattr(d, "created_at", None),
            )
        )

    if not rows:
        return 0

    conn.executemany(
        """
        INSERT OR REPLACE INTO pattern_detections (
            run_id, pattern_id, symbol, pattern_name, pattern_type,
            formation_start, formation_end, breakout_date,
            breakout_direction, breakout_price, target_price, stop_loss_price,
            confidence_score, volume_confirmed,
            pattern_height_pct, pattern_width_bars, touch_count,
            pivot_indices_json, config_hash,
            base_pattern_name, variant_code, variant_confidence,
            variant_evidence_json, first_extreme_width_bars, second_extreme_width_bars,
            family_metrics_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def insert_post_breakout_results(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    results: Iterable[Any],
) -> int:
    def _finite_or_none(v: Any) -> Optional[float]:
        if v is None:
            return None
        try:
            f = float(v)
        except Exception:
            return None
        return f if math.isfinite(f) else None

    rows: list[Tuple[Any, ...]] = []
    for r in results:
        rows.append(
            (
                run_id,
                getattr(r, "pattern_id"),
                getattr(r, "symbol"),
                getattr(r, "pattern_name"),
                getattr(r, "breakout_date", None),
                getattr(r, "breakout_price", None),
                getattr(r, "breakout_direction", None),
                getattr(r, "target_price", None),
                getattr(r, "stop_loss_price", None),
                1 if getattr(r, "bust_failure_5pct", None) is True else (0 if getattr(r, "bust_failure_5pct", None) is False else None),
                1 if getattr(r, "bust_failure_10pct", None) is True else (0 if getattr(r, "bust_failure_10pct", None) is False else None),
                getattr(r, "bust_failure_date", None),
                _finite_or_none(getattr(r, "bust_failure_pct", None)),
                1 if getattr(r, "boundary_invalidated", None) is True else (0 if getattr(r, "boundary_invalidated", None) is False else None),
                getattr(r, "boundary_invalidation_date", None),
                _finite_or_none(getattr(r, "ultimate_price", None)),
                getattr(r, "ultimate_date", None),
                getattr(r, "days_to_ultimate", None),
                getattr(r, "ultimate_stop_reason", None),
                1 if getattr(r, "throwback_pullback_occurred", None) is True else (0 if getattr(r, "throwback_pullback_occurred", None) is False else None),
                getattr(r, "throwback_pullback_date", None),
                getattr(r, "days_to_throwback_pullback", None),
                1 if getattr(r, "retested_breakout_level", None) is True else (0 if getattr(r, "retested_breakout_level", None) is False else None),
                1 if getattr(r, "retested_boundary_level", None) is True else (0 if getattr(r, "retested_boundary_level", None) is False else None),
                1 if getattr(r, "target_achieved_intraday", None) is True else (0 if getattr(r, "target_achieved_intraday", None) is False else None),
                1 if getattr(r, "target_achieved_close", None) is True else (0 if getattr(r, "target_achieved_close", None) is False else None),
                getattr(r, "target_achievement_date", None),
                getattr(r, "days_to_target", None),
                _finite_or_none(getattr(r, "max_favorable_excursion_pct", None)),
                _finite_or_none(getattr(r, "max_adverse_excursion_pct", None)),
                getattr(r, "variant", None),
                getattr(r, "peak1_width_bars", None),
                getattr(r, "peak2_width_bars", None),
                getattr(r, "evaluation_window_bars", None),
                getattr(r, "evaluation_date", None),
            )
        )

    if not rows:
        return 0

    conn.executemany(
        """
        INSERT OR REPLACE INTO post_breakout_results (
            run_id, pattern_id, symbol, pattern_name,
            breakout_date, breakout_price, breakout_direction,
            target_price, stop_loss_price,
            bust_failure_5pct, bust_failure_10pct, bust_failure_date, bust_failure_pct,
            boundary_invalidated, boundary_invalidation_date,
            ultimate_price, ultimate_date, days_to_ultimate, ultimate_stop_reason,
            throwback_pullback_occurred, throwback_pullback_date, days_to_throwback_pullback,
            retested_breakout_level, retested_boundary_level,
            target_achieved_intraday, target_achieved_close, target_achievement_date, days_to_target,
            max_favorable_excursion_pct, max_adverse_excursion_pct,
            variant, peak1_width_bars, peak2_width_bars,
            evaluation_window_bars, evaluation_date
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def upsert_run_statistics(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    stats: Dict[str, Any],
    created_at: Optional[str] = None,
) -> None:
    created_at = created_at or _utc_now_iso()
    conn.execute(
        """
        INSERT INTO run_statistics (run_id, created_at, stats_json)
        VALUES (?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET
            created_at=excluded.created_at,
            stats_json=excluded.stats_json
        """,
        (run_id, created_at, json.dumps(stats, sort_keys=True, default=str)),
    )


def record_error(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    symbol: str,
    error: str,
    traceback_text: Optional[str] = None,
    created_at: Optional[str] = None,
) -> None:
    created_at = created_at or _utc_now_iso()
    traceback_text = traceback_text or _traceback.format_exc()
    conn.execute(
        """
        INSERT INTO scan_errors (run_id, symbol, created_at, error, traceback)
        VALUES (?, ?, ?, ?, ?)
        """,
        (run_id, symbol, created_at, error, traceback_text),
    )
