"""Bear Flag parity audit for the Market Cache OHLCV SQLite source."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.v2.bear_flags_monograph import (  # noqa: E402
    BEAR_FLAG_EVENT_FIELDS,
    PATTERN_KEY,
    _add_target_calibration,
    _assign_bear_branches,
    _filter_bear_flags,
)
from scanner.v2.bull_flags_monograph import (  # noqa: E402
    DEFAULT_MARKET_STATS_JSON,
    _assign_liquidity_buckets,
    _assign_path_quality_buckets,
    _assign_time_splits,
    _bulkowski_equivalent_metrics_for_event,
    _corporate_action_metrics_for_event,
    _liquidity_metrics_for_event,
    _load_active_symbols,
    _load_corporate_actions_by_symbol,
    _mark_primary_events,
    _proxy_risk_flags_for_event,
    _tradability_quality_metrics_for_event,
)
from scanner.v2.flags_experiment import (  # noqa: E402
    DEFAULT_INDEX_DB,
    DEFAULT_INDEX_SYMBOL,
    FlagDetectorConfig,
    _write_csv,
    _write_json,
    scan_symbol,
    summarize,
)
from scanner.v2.source_data import attach_current_market_groups, classify_market_regimes  # noqa: E402


DEFAULT_DB = Path("../market_cache/stock_ohlcv/latest.sqlite")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bear_flags_db_source_parity")
DEFAULT_STOCK_SERIES_STATS = Path("artifacts/scanner_v2/bear_flags/statistics.json")


def _read_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _db_meta(db_path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT COUNT(*) AS n, MIN(time) AS min_date, MAX(time) AS max_date, COUNT(DISTINCT symbol) AS n_symbols FROM stock_price_history").fetchone()
    finally:
        conn.close()
    return {"rows": int(row[0] or 0), "min_date": row[1], "max_date": row[2], "symbols": int(row[3] or 0)}


def _symbols_in_db(db_path: Path, allowed_symbols: Optional[Sequence[str]] = None) -> list[str]:
    allowed = {str(symbol).strip().upper() for symbol in allowed_symbols or [] if str(symbol).strip()}
    conn = sqlite3.connect(str(db_path))
    try:
        if allowed:
            placeholders = ",".join(["?"] * len(allowed))
            rows = conn.execute(f"SELECT DISTINCT symbol FROM stock_price_history WHERE UPPER(symbol) IN ({placeholders}) ORDER BY symbol", sorted(allowed)).fetchall()
        else:
            rows = conn.execute("SELECT DISTINCT symbol FROM stock_price_history ORDER BY symbol").fetchall()
    finally:
        conn.close()
    return [str(row[0]).upper() for row in rows]


def _load_symbol_from_db(conn: sqlite3.Connection, symbol: str) -> pd.DataFrame:
    frame = pd.read_sql_query(
        """
        SELECT
            symbol,
            time AS date,
            open,
            high,
            low,
            close,
            volume
        FROM stock_price_history
        WHERE symbol = ?
        ORDER BY time
        """,
        conn,
        params=[symbol],
    )
    if frame.empty:
        return frame
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["value"] = frame["close"] * frame["volume"]
    return frame.dropna(subset=["date", "open", "high", "low", "close"]).reset_index(drop=True)


def _enrich_events_from_series(scan: Dict[str, Any], series_by_symbol: Mapping[str, pd.DataFrame], *, corporate_db: Path = DEFAULT_INDEX_DB) -> None:
    detections = list(scan.get("detections") or [])
    corp_actions_by_symbol = _load_corporate_actions_by_symbol(corporate_db, [row.get("symbol") for row in detections])
    for row in detections:
        symbol = str(row.get("symbol") or "").upper()
        series = series_by_symbol.get(symbol, pd.DataFrame())
        corp_metrics = _corporate_action_metrics_for_event(corp_actions_by_symbol.get(symbol, pd.DataFrame()), row)
        row.update(_liquidity_metrics_for_event(series, row.get("breakout_date")))
        row.update(_bulkowski_equivalent_metrics_for_event(series, row))
        row.update(corp_metrics)
        row.update(_tradability_quality_metrics_for_event(series, row.get("breakout_date"), corp_metrics))
        row.update(_proxy_risk_flags_for_event(series, row.get("breakout_date")))
    _assign_liquidity_buckets(detections)
    _mark_primary_events(detections)
    _assign_path_quality_buckets(detections)
    _assign_time_splits(detections)
    scan["detections"] = detections


def _path_rows_from_series(scan: Mapping[str, Any], series_by_symbol: Mapping[str, pd.DataFrame], *, horizon_bars: int = 120) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for det in scan.get("detections") or []:
        symbol = str(det.get("symbol") or "").upper()
        df = series_by_symbol.get(symbol, pd.DataFrame()).reset_index(drop=True)
        if df.empty:
            continue
        breakout_idx = int(det["breakout_idx"])
        breakout_price = float(det["breakout_price"])
        direction = 1 if det.get("breakout_direction") == "up" else -1
        for offset, (_, row) in enumerate(df.iloc[breakout_idx + 1 : min(len(df), breakout_idx + 1 + horizon_bars)].iterrows(), start=1):
            close = float(row["close"])
            high = float(row["high"])
            low = float(row["low"])
            if direction == 1:
                signed_close = (close - breakout_price) / breakout_price * 100.0
                signed_high = (high - breakout_price) / breakout_price * 100.0
                signed_low = (low - breakout_price) / breakout_price * 100.0
            else:
                signed_close = (breakout_price - close) / breakout_price * 100.0
                signed_high = (breakout_price - low) / breakout_price * 100.0
                signed_low = (breakout_price - high) / breakout_price * 100.0
            out.append(
                {
                    "event_id": det.get("detection_id"),
                    "symbol": symbol,
                    "trade_date": str(pd.Timestamp(row["date"]).date()),
                    "bar_after_breakout": offset,
                    "open": round(float(row["open"]), 4),
                    "high": round(high, 4),
                    "low": round(low, 4),
                    "close": round(close, 4),
                    "volume": int(row["volume"]) if pd.notna(row["volume"]) else None,
                    "signed_close_return_pct": round(float(signed_close), 4),
                    "signed_high_excursion_pct": round(float(signed_high), 4),
                    "signed_low_excursion_pct": round(float(signed_low), 4),
                }
            )
    return out


def scan_bear_flags_db(
    *,
    db_path: Path,
    out_dir: Path,
    allowed_symbols: Optional[Sequence[str]] = None,
    detector_config: Optional[Mapping[str, Any]] = None,
    limit_symbols: Optional[int] = None,
    index_db: Path = DEFAULT_INDEX_DB,
    index_symbol: str = DEFAULT_INDEX_SYMBOL,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    config = FlagDetectorConfig.from_mapping(detector_config)
    symbols = _symbols_in_db(db_path, allowed_symbols)
    if limit_symbols is not None:
        symbols = symbols[: int(limit_symbols)]
    detections: list[dict[str, Any]] = []
    symbol_stats: list[dict[str, Any]] = []
    series_by_symbol: dict[str, pd.DataFrame] = {}
    conn = sqlite3.connect(str(db_path))
    try:
        for symbol in symbols:
            try:
                frame = _load_symbol_from_db(conn, symbol)
                rows, stats = scan_symbol(frame, detector_config=config)
                if rows:
                    series_by_symbol[symbol] = frame
                detections.extend(rows)
                symbol_stats.append({"symbol": symbol, "detections": len(rows), **stats})
            except Exception as exc:
                symbol_stats.append({"symbol": symbol, "detections": 0, "error": str(exc)})
    finally:
        conn.close()

    for i, row in enumerate(detections):
        row["detection_id"] = f"flags_experiment:{i + 1:06d}"
    detections, regime_meta = classify_market_regimes(detections, index_db=index_db, index_symbol=index_symbol)
    market_group_meta = attach_current_market_groups(detections)
    raw_scan = {
        "generated_at": pd.Timestamp.now(tz="UTC").replace(microsecond=0).isoformat(),
        "source": "Market Cache latest.sqlite stock_price_history",
        "db_path": str(db_path),
        "pattern_key": "flags_experiment",
        "symbols_scanned": len(symbols),
        "detections": detections,
        "symbol_stats": symbol_stats,
        "regime": regime_meta,
        "market_group": market_group_meta,
        "detector_config": config.to_dict(),
    }
    scan = _filter_bear_flags(raw_scan)
    _enrich_events_from_series(scan, series_by_symbol, corporate_db=index_db)
    _assign_bear_branches(scan)
    stats = summarize(scan)
    stats["pattern_key"] = PATTERN_KEY
    stats["source"] = raw_scan["source"]
    stats["db_source_meta"] = _db_meta(db_path)
    stats["detector_config"] = config.to_dict()
    path_rows = _path_rows_from_series(scan, series_by_symbol)
    _add_target_calibration(stats, scan, path_rows)

    paths = {
        "detections": out_dir / "detections.json",
        "statistics": out_dir / "statistics.json",
        "events_csv": out_dir / "events.csv",
        "post_breakout_path_csv": out_dir / "post_breakout_path.csv",
    }
    _write_json(paths["detections"], scan)
    _write_json(paths["statistics"], stats)
    _write_csv(paths["events_csv"], scan.get("detections") or [], BEAR_FLAG_EVENT_FIELDS)
    _write_csv(
        paths["post_breakout_path_csv"],
        path_rows,
        ["event_id", "symbol", "trade_date", "bar_after_breakout", "open", "high", "low", "close", "volume", "signed_close_return_pct", "signed_high_excursion_pct", "signed_low_excursion_pct"],
    )
    return paths


def _headline(stats: Mapping[str, Any]) -> Mapping[str, Any]:
    return stats.get("bear_branch_headline") if isinstance(stats.get("bear_branch_headline"), Mapping) else {}


def _summary_row(label: str, stats: Mapping[str, Any]) -> dict[str, Any]:
    h = _headline(stats)
    return {
        "source_id": label,
        "n_all": stats.get("detection_count"),
        "symbols_scanned": stats.get("symbols_scanned"),
        "headline_scope": h.get("aggregate_id") or h.get("branch_id"),
        "headline_n": h.get("n"),
        "headline_n_symbols": h.get("n_symbols"),
        "headline_hit_rate": h.get("base_target_hit_rate"),
        "headline_target_first_rate": h.get("base_target_first_before_adverse_5pct_rate"),
        "headline_failure_5pct_rate": h.get("failure_5pct_rate"),
        "headline_mfe_mae_ratio": h.get("mfe_mae_median_ratio"),
    }


def write_parity_report(*, stock_series_stats: Path, db_active_stats: Path, db_all_stats: Path, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stock = _read_json(stock_series_stats)
    db_active = _read_json(db_active_stats)
    db_all = _read_json(db_all_stats)
    rows = [_summary_row("stock_series_active", stock), _summary_row("db_active", db_active), _summary_row("db_all", db_all)]
    stock_n = int(rows[0].get("headline_n") or 0)
    db_active_n = int(rows[1].get("headline_n") or 0)
    db_all_n = int(rows[2].get("headline_n") or 0)
    decision = {
        "decision": "PROMOTE_DB_SOURCE_FOR_DEEPER_AUDIT"
        if db_active_n > stock_n or db_all_n > stock_n
        else "DO_NOT_PROMOTE_DB_SOURCE",
        "stock_series_headline_n": stock_n,
        "db_active_headline_n": db_active_n,
        "db_all_headline_n": db_all_n,
        "note": "Promotion here means deeper audit, not replacing publication source automatically.",
    }
    payload = {"audit_version": "bear_flag_db_source_parity_v1", "rows": rows, "decision": decision}
    json_path = out_dir / "bear_flag_db_source_parity_audit.json"
    csv_path = out_dir / "bear_flag_db_source_parity_rows.csv"
    md_path = out_dir / "bear_flag_db_source_parity_audit.md"
    _write_json(json_path, payload)
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    lines = [
        "# Bear Flag DB source parity audit",
        "",
        f"**Decision:** {decision['decision']}",
        "",
        "| Source | All N | Symbols | Headline | Headline N | Hit | Target-first | Failure | MFE/MAE |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['source_id']} | {row.get('n_all')} | {row.get('symbols_scanned')} | {row.get('headline_scope')} | {row.get('headline_n')} | {row.get('headline_hit_rate')}% | {row.get('headline_target_first_rate')}% | {row.get('headline_failure_5pct_rate')}% | {row.get('headline_mfe_mae_ratio')} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "csv": csv_path, "md": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Bear Flag parity audit against Market Cache latest.sqlite.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--stock-series-stats", default=str(DEFAULT_STOCK_SERIES_STATS))
    parser.add_argument("--market-stats-json", default=str(DEFAULT_MARKET_STATS_JSON))
    parser.add_argument("--limit-symbols", type=int, default=None)
    parser.add_argument("--skip-run", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    db_path = Path(args.db)
    active_meta = _load_active_symbols(Path(args.market_stats_json) if args.market_stats_json else None)
    active_symbols = active_meta.get("active_symbols") if active_meta.get("enabled") else None
    active_dir = out_dir / "db_active"
    all_dir = out_dir / "db_all"
    if not args.skip_run:
        scan_bear_flags_db(db_path=db_path, out_dir=active_dir, allowed_symbols=active_symbols, limit_symbols=args.limit_symbols)
        scan_bear_flags_db(db_path=db_path, out_dir=all_dir, allowed_symbols=None, limit_symbols=args.limit_symbols)
    paths = write_parity_report(
        stock_series_stats=Path(args.stock_series_stats),
        db_active_stats=active_dir / "statistics.json",
        db_all_stats=all_dir / "statistics.json",
        out_dir=out_dir,
    )
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
