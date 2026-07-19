"""SQLite persistence, integrity checks, and notification deduplication."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

import pandas as pd


SCHEMA_VERSION = 1


class StorageError(RuntimeError):
    """Raised when scanner state is invalid."""


class LiveScanStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), timeout=30.0)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 30000")
            conn.execute("PRAGMA journal_mode = WAL")
            yield conn
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS stock_price_history (
                    symbol TEXT NOT NULL,
                    time TEXT NOT NULL,
                    open REAL NOT NULL CHECK(open > 0),
                    high REAL NOT NULL CHECK(high > 0),
                    low REAL NOT NULL CHECK(low > 0),
                    close REAL NOT NULL CHECK(close > 0),
                    volume REAL NOT NULL CHECK(volume >= 0),
                    source TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(symbol, time),
                    CHECK(high >= open AND high >= close AND high >= low),
                    CHECK(low <= open AND low <= close AND low <= high)
                );
                CREATE INDEX IF NOT EXISTS idx_stock_price_time
                    ON stock_price_history(time);

                CREATE TABLE IF NOT EXISTS scan_runs (
                    run_id TEXT PRIMARY KEY,
                    scan_date TEXT NOT NULL,
                    latest_market_date TEXT,
                    status TEXT NOT NULL,
                    symbols_requested INTEGER NOT NULL DEFAULT 0,
                    symbols_downloaded INTEGER NOT NULL DEFAULT 0,
                    candidates INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    started_at TEXT NOT NULL,
                    finished_at TEXT
                );

                CREATE TABLE IF NOT EXISTS notification_outbox (
                    event_key TEXT PRIMARY KEY,
                    scan_date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    pattern_id TEXT NOT NULL,
                    detector_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    sent_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_outbox_status
                    ON notification_outbox(status, scan_date);
                """
            )
            conn.execute(
                """
                INSERT INTO schema_meta(key, value) VALUES('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(SCHEMA_VERSION),),
            )
            conn.commit()

    @staticmethod
    def _bar_rows(frame: pd.DataFrame) -> list[tuple[Any, ...]]:
        required = {
            "symbol",
            "time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "source",
        }
        missing = sorted(required - set(frame.columns))
        if missing:
            raise StorageError(f"Thiếu cột OHLCV: {', '.join(missing)}")
        if frame.empty:
            return []

        updated_at = datetime.now(timezone.utc).isoformat()
        return [
            (
                str(row.symbol).upper(),
                pd.Timestamp(row.time).date().isoformat(),
                float(row.open),
                float(row.high),
                float(row.low),
                float(row.close),
                float(row.volume),
                str(row.source).upper(),
                updated_at,
            )
            for row in frame.itertuples(index=False)
        ]

    def upsert_bars(self, frame: pd.DataFrame) -> int:
        rows = self._bar_rows(frame)
        if not rows:
            return 0
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO stock_price_history(
                    symbol, time, open, high, low, close, volume, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, time) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                rows,
            )
            conn.commit()
        return len(rows)

    def replace_symbol_history(self, frame: pd.DataFrame) -> int:
        """Atomically replace one symbol when failover changes data provider."""

        rows = self._bar_rows(frame)
        if not rows:
            return 0
        symbols = {str(row[0]).upper() for row in rows}
        sources = {str(row[7]).upper() for row in rows}
        if len(symbols) != 1 or len(sources) != 1:
            raise StorageError(
                "replace_symbol_history yêu cầu đúng một mã và một nguồn"
            )
        symbol = next(iter(symbols))
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM stock_price_history WHERE symbol = ?",
                (symbol,),
            )
            conn.executemany(
                """
                INSERT INTO stock_price_history(
                    symbol, time, open, high, low, close, volume, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        return len(rows)

    def latest_date(
        self,
        symbol: str | None = None,
        *,
        on_or_before: date | None = None,
    ) -> date | None:
        query = "SELECT MAX(time) FROM stock_price_history"
        clauses: list[str] = []
        params: list[Any] = []
        if symbol:
            clauses.append("symbol = ?")
            params.append(str(symbol).upper())
        if on_or_before:
            clauses.append("time <= ?")
            params.append(on_or_before.isoformat())
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        with self.connect() as conn:
            value = conn.execute(query, params).fetchone()[0]
        return date.fromisoformat(value) if value else None

    def latest_source(
        self,
        symbol: str,
        *,
        on_or_before: date | None = None,
    ) -> str | None:
        cutoff_clause = "AND time <= ?" if on_or_before else ""
        params: tuple[Any, ...] = (
            (str(symbol).upper(), on_or_before.isoformat())
            if on_or_before
            else (str(symbol).upper(),)
        )
        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT source
                FROM stock_price_history
                WHERE symbol = ?
                {cutoff_clause}
                ORDER BY time DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return str(row[0]).upper() if row else None

    def load_symbol(self, symbol: str, *, limit: int | None = None) -> pd.DataFrame:
        query = """
            SELECT symbol, time, open, high, low, close, volume, source
            FROM stock_price_history
            WHERE symbol = ?
            ORDER BY time
        """
        params: list[Any] = [str(symbol).upper()]
        if limit is not None:
            query = """
                SELECT * FROM (
                    SELECT symbol, time, open, high, low, close, volume, source
                    FROM stock_price_history
                    WHERE symbol = ?
                    ORDER BY time DESC
                    LIMIT ?
                ) ORDER BY time
            """
            params.append(int(limit))
        with self.connect() as conn:
            frame = pd.read_sql_query(query, conn, params=params)
        if not frame.empty:
            frame["time"] = pd.to_datetime(frame["time"])
        return frame

    def symbols(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT symbol FROM stock_price_history ORDER BY symbol"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def start_run(self, run_id: str, scan_date: date, symbols_requested: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO scan_runs(
                    run_id, scan_date, status, symbols_requested, started_at
                ) VALUES (?, ?, 'running', ?, ?)
                """,
                (run_id, scan_date.isoformat(), symbols_requested, now),
            )
            conn.commit()

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        latest_market_date: date | None,
        symbols_downloaded: int,
        candidates: int,
        metadata: Mapping[str, Any],
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE scan_runs
                SET status = ?, latest_market_date = ?, symbols_downloaded = ?,
                    candidates = ?, metadata_json = ?, finished_at = ?
                WHERE run_id = ?
                """,
                (
                    status,
                    latest_market_date.isoformat()
                    if latest_market_date
                    else None,
                    int(symbols_downloaded),
                    int(candidates),
                    json.dumps(metadata, ensure_ascii=False, default=str),
                    now,
                    run_id,
                ),
            )
            conn.commit()

    def last_successful_market_date(self) -> date | None:
        with self.connect() as conn:
            value = conn.execute(
                """
                SELECT latest_market_date
                FROM scan_runs
                WHERE status = 'success' AND latest_market_date IS NOT NULL
                ORDER BY finished_at DESC
                LIMIT 1
                """
            ).fetchone()
        return date.fromisoformat(value[0]) if value and value[0] else None

    @staticmethod
    def event_key(candidate: Mapping[str, Any]) -> str:
        stable = "|".join(
            [
                str(candidate.get("as_of_date") or ""),
                str(candidate.get("symbol") or ""),
                str(candidate.get("pattern_id") or ""),
                str(candidate.get("detector_version") or ""),
            ]
        )
        return hashlib.sha256(stable.encode("utf-8")).hexdigest()

    def queue_candidates(self, candidates: Iterable[Mapping[str, Any]]) -> int:
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for candidate in candidates:
            rows.append(
                (
                    self.event_key(candidate),
                    str(candidate.get("as_of_date") or ""),
                    str(candidate.get("symbol") or ""),
                    str(candidate.get("pattern_id") or ""),
                    str(candidate.get("detector_version") or ""),
                    json.dumps(candidate, ensure_ascii=False, default=str),
                    now,
                )
            )
        if not rows:
            return 0
        with self.connect() as conn:
            before = conn.total_changes
            conn.executemany(
                """
                INSERT OR IGNORE INTO notification_outbox(
                    event_key, scan_date, symbol, pattern_id, detector_version,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            inserted = conn.total_changes - before
            conn.commit()
        return int(inserted)

    def pending_candidates(self, scan_date: date) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM notification_outbox
                WHERE status = 'pending' AND scan_date = ?
                ORDER BY symbol, pattern_id
                """,
                (scan_date.isoformat(),),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def mark_sent(self, candidates: Iterable[Mapping[str, Any]]) -> None:
        keys = [(self.event_key(candidate),) for candidate in candidates]
        if not keys:
            return
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.executemany(
                """
                UPDATE notification_outbox
                SET status = 'sent', sent_at = ?
                WHERE event_key = ?
                """,
                [(now, key[0]) for key in keys],
            )
            conn.commit()

    def quick_check(self) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            result = conn.execute("PRAGMA quick_check").fetchone()[0]
        if str(result).lower() != "ok":
            raise StorageError(f"SQLite quick_check thất bại: {result}")
