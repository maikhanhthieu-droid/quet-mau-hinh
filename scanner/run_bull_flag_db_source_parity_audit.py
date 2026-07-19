"""Bull Flag parity audit for the Market Cache OHLCV SQLite source."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.run_bear_flag_db_source_parity_audit import (  # noqa: E402
    DEFAULT_DB,
    _db_meta,
    _enrich_events_from_series,
    _load_symbol_from_db,
    _path_rows_from_series,
    _symbols_in_db,
)
from scanner.v2.bull_flags_monograph import (  # noqa: E402
    BULL_FLAG_EVENT_FIELDS,
    DEFAULT_MARKET_STATS_JSON,
    PATTERN_KEY,
    _add_sensitivity_tables,
    _add_target_calibration,
    _filter_bull_flags,
    _load_active_symbols,
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

import sqlite3


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bull_flags_db_source_parity")
DEFAULT_STOCK_SERIES_STATS = Path("artifacts/scanner_v2/bull_flags/statistics.json")


def _read_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def scan_bull_flags_db(
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
    scan = _filter_bull_flags(raw_scan)
    _enrich_events_from_series(scan, series_by_symbol, corporate_db=index_db)
    stats = summarize(scan)
    stats["pattern_key"] = PATTERN_KEY
    stats["source"] = raw_scan["source"]
    stats["db_source_meta"] = _db_meta(db_path)
    stats["detector_config"] = config.to_dict()
    stats["target_family"] = {
        "bulkowski_adjusted_base": 0.46,
        "rounded_local_base": 0.5,
        "local_stretch": 0.75,
        "legacy_full_pole": 1.0,
    }
    _add_sensitivity_tables(stats, scan)
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
    _write_csv(paths["events_csv"], scan.get("detections") or [], BULL_FLAG_EVENT_FIELDS)
    _write_csv(
        paths["post_breakout_path_csv"],
        path_rows,
        ["event_id", "symbol", "trade_date", "bar_after_breakout", "open", "high", "low", "close", "volume", "signed_close_return_pct", "signed_high_excursion_pct", "signed_low_excursion_pct"],
    )
    return paths


def _target_row(stats: Mapping[str, Any], multiple: float) -> Mapping[str, Any]:
    for row in stats.get("target_family_sensitivity") or []:
        if row.get("label") == "bull_flags" and float(row.get("target_multiple") or -1) == float(multiple):
            return row
    return {}


def _summary_row(label: str, stats: Mapping[str, Any]) -> dict[str, Any]:
    base = _target_row(stats, 0.46)
    return {
        "source_id": label,
        "n_all": stats.get("detection_count"),
        "symbols_scanned": stats.get("symbols_scanned"),
        "base_target_n": base.get("n"),
        "base_target_hit_rate": base.get("target_hit_rate"),
        "base_target_first_rate": base.get("target_first_before_adverse_5pct_rate"),
        "failure_5pct_rate": base.get("failure_5pct_rate"),
        "mfe_mae_ratio": base.get("mfe_mae_median_ratio"),
        "median_mfe_pct": stats.get("median_mfe_pct"),
        "median_mae_pct": stats.get("median_mae_pct"),
    }


def write_parity_report(*, stock_series_stats: Path, db_active_stats: Path, db_all_stats: Path, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stock = _read_json(stock_series_stats)
    db_active = _read_json(db_active_stats)
    db_all = _read_json(db_all_stats)
    rows = [_summary_row("stock_series_active", stock), _summary_row("db_active", db_active), _summary_row("db_all", db_all)]
    stock_n = int(rows[0].get("base_target_n") or 0)
    active_n = int(rows[1].get("base_target_n") or 0)
    active_hit = float(rows[1].get("base_target_hit_rate") or 0)
    active_fail = float(rows[1].get("failure_5pct_rate") or 100)
    active_ratio = float(rows[1].get("mfe_mae_ratio") or 0)
    promote = active_n > stock_n and active_hit >= 65.0 and active_fail <= 30.0 and active_ratio >= 1.2
    payload = {
        "audit_version": "bull_flag_db_source_parity_v1",
        "rows": rows,
        "decision": "PROMOTE_DB_ACTIVE_CHAPTER_CANDIDATE" if promote else "KEEP_STOCK_SERIES_CHAPTER",
        "decision_note": "Promotion means DB-active should be rendered and reviewed as the preferred Bull Flag source candidate.",
    }
    json_path = out_dir / "bull_flag_db_source_parity_audit.json"
    csv_path = out_dir / "bull_flag_db_source_parity_rows.csv"
    md_path = out_dir / "bull_flag_db_source_parity_audit.md"
    _write_json(json_path, payload)
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    lines = [
        "# Bull Flag DB source parity audit",
        "",
        f"**Decision:** {payload['decision']}",
        "",
        "| Source | All N | Symbols | Base N | Hit | Target-first | Failure | MFE/MAE | Median MFE | Median MAE |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['source_id']} | {row.get('n_all')} | {row.get('symbols_scanned')} | {row.get('base_target_n')} | {row.get('base_target_hit_rate')}% | {row.get('base_target_first_rate')}% | {row.get('failure_5pct_rate')}% | {row.get('mfe_mae_ratio')} | {row.get('median_mfe_pct')}% | {row.get('median_mae_pct')}% |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "csv": csv_path, "md": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Bull Flag parity audit against Market Cache latest.sqlite.")
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
        scan_bull_flags_db(db_path=db_path, out_dir=active_dir, allowed_symbols=active_symbols, limit_symbols=args.limit_symbols)
        scan_bull_flags_db(db_path=db_path, out_dir=all_dir, allowed_symbols=None, limit_symbols=args.limit_symbols)
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
