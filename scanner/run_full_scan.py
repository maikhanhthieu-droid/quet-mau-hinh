"""
Run a full (or partial) scan over the source OHLCV SQLite DB and persist results
to a separate results DB with run_id tracking.

Usage examples:
  python3 scanner/run_full_scan.py --limit 50
  python3 scanner/run_full_scan.py --patterns double_tops,head_and_shoulders_top
  python3 scanner/run_full_scan.py --results-db scan_results/databases/final/pattern_scans.sqlite
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sqlite3
import traceback
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

# Allow running as a script (imports are local-module style in this folder)
import sys

SCANNER_DIR = os.path.dirname(__file__)
sys.path.insert(0, SCANNER_DIR)

from legacy_guard import require_legacy_enabled  # noqa: E402
from pattern_scanner import PatternScanner, ScannerConfig  # noqa: E402
from post_breakout_analyzer import (  # noqa: E402
    PostBreakoutEvaluator,
    EvaluationConfig,
)
from results_db import (  # noqa: E402
    connect_results_db,
    ensure_schema,
    generate_run_id,
    insert_detections,
    insert_post_breakout_results,
    record_error,
    upsert_run,
    upsert_run_statistics,
)
from pattern_set_metadata import build_pattern_metadata  # noqa: E402


SOURCE_TABLE = "stock_price_history"


def _md5_json(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
    return hashlib.md5(payload).hexdigest()


def _parse_patterns(s: Optional[str], available: Sequence[str]) -> List[str]:
    if not s:
        return list(available)
    parts = [p.strip() for p in s.split(",") if p.strip()]
    unknown = [p for p in parts if p not in available]
    if unknown:
        raise SystemExit(f"Unknown patterns: {unknown}. Available: {sorted(available)}")
    return parts


def _parse_csv_set(s: Optional[str]) -> set[str]:
    if not s:
        return set()
    return {p.strip() for p in s.split(",") if p.strip()}


def _interval_for_detection(d: Any) -> Optional[Tuple[int, int]]:
    piv = getattr(d, "pivot_indices", None)
    if isinstance(piv, str):
        try:
            piv = json.loads(piv)
        except Exception:
            piv = None
    if isinstance(piv, (list, tuple)) and piv:
        try:
            xs = [int(x) for x in piv]
        except Exception:
            xs = []
        if xs:
            return (min(xs), max(xs))
    return None


def _overlaps(a: Tuple[int, int], b: Tuple[int, int]) -> bool:
    return not (a[1] < b[0] or b[1] < a[0])


def _apply_overlap_policy(detections: List[Any], policy: str) -> List[Any]:
    if policy == "none":
        return list(detections)

    scored: List[Tuple[Tuple[int, int], int, int, int, str, str, Any]] = []
    for d in detections:
        iv = _interval_for_detection(d)
        if iv is None:
            # Can't reason about overlap: keep it.
            iv = (10**12, 10**12)
        length = int(iv[1] - iv[0] + 1) if iv[0] < 10**11 else 0
        confirmed = 1 if (getattr(d, "breakout_date", None) is not None and getattr(d, "breakout_price", None) is not None) else 0
        conf = int(getattr(d, "confidence_score", 0) or 0)
        scored.append(
            (
                iv,
                length,
                confirmed,
                conf,
                str(getattr(d, "pattern_name", "") or ""),
                str(getattr(d, "pattern_id", "") or ""),
                d,
            )
        )

    # Bulkowski-style: larger timeframe first; then confirmed; then higher confidence.
    scored.sort(key=lambda x: (-x[1], -x[2], -x[3], x[4], x[5]))

    kept: List[Any] = []
    kept_intervals: List[Tuple[int, int]] = []
    for iv, _, _, _, _, _, d in scored:
        if iv[0] >= 10**11:
            kept.append(d)
            continue
        if any(_overlaps(iv, k) for k in kept_intervals):
            continue
        kept.append(d)
        kept_intervals.append(iv)
    return kept


def _load_symbols(
    conn: sqlite3.Connection,
    *,
    min_rows: int,
    limit: Optional[int],
    universe_index: Optional[str] = None,
) -> List[str]:
    df = pd.read_sql_query(
        """
        SELECT symbol, COUNT(*) AS cnt
        FROM stock_price_history
        GROUP BY symbol
        HAVING cnt >= ?
        ORDER BY symbol
        """,
        conn,
        params=[min_rows],
    )
    symbols = df["symbol"].tolist()

    # Data filtering (Bulkowski-style): exclude index series from the stock sample.
    # Vietnam DB stores indices (e.g., VN30/VN100) in the same price table.
    try:
        idx_df = pd.read_sql_query("SELECT index_code FROM indices", conn)
        index_symbols = set(str(x) for x in idx_df["index_code"].dropna().tolist())
    except Exception:
        index_symbols = set()
    if index_symbols:
        symbols = [s for s in symbols if str(s) not in index_symbols]

    if universe_index:
        idx_codes = {x.strip() for x in str(universe_index).split(",") if x.strip()}
        if idx_codes:
            rows = conn.execute(
                f"SELECT DISTINCT ticker FROM stock_index WHERE index_code IN ({','.join(['?']*len(idx_codes))})",
                tuple(sorted(idx_codes)),
            ).fetchall()
            universe = {str(r[0]) for r in rows if r and r[0] is not None}
            symbols = [s for s in symbols if str(s) in universe]

    if limit is not None:
        symbols = symbols[: int(limit)]
    return symbols


def _load_symbol_df(conn: sqlite3.Connection, symbol: str) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT symbol, time as date, open, high, low, close, volume "
        "FROM stock_price_history WHERE symbol = ? ORDER BY time",
        conn,
        params=[symbol],
    )
    df["date"] = pd.to_datetime(df["date"])
    return df


def _filter_df_by_date_window(
    df: pd.DataFrame,
    *,
    date_from: Optional[str],
    date_to: Optional[str],
    warmup_bars: int,
) -> pd.DataFrame:
    """
    Optionally restrict the scan window by date.

    Implementation notes:
      - If `date_to` is provided, rows after it are dropped (inclusive end).
      - If `date_from` is provided, the scan keeps up to `warmup_bars` rows *before*
        the first row >= date_from (for indicators/pivots), and everything after.
    """
    if df.empty:
        return df

    g = df.copy()
    g = g.sort_values("date").reset_index(drop=True)

    if date_to:
        dt_to = pd.to_datetime(date_to, errors="coerce")
        if pd.notna(dt_to):
            g = g[g["date"] <= dt_to].copy()

    if date_from and not g.empty:
        dt_from = pd.to_datetime(date_from, errors="coerce")
        if pd.notna(dt_from):
            # First position whose date >= dt_from
            start_pos = int(g["date"].searchsorted(dt_from, side="left"))
            warmup_start = max(0, start_pos - int(max(0, warmup_bars)))
            g = g.iloc[warmup_start:].copy().reset_index(drop=True)

    return g


def _detection_anchor_date(d: Any, *, anchor: str) -> Optional[pd.Timestamp]:
    def _to_ts(x: Any) -> Optional[pd.Timestamp]:
        if x is None:
            return None
        try:
            ts = pd.to_datetime(x, errors="coerce")
        except Exception:
            return None
        return ts if pd.notna(ts) else None

    a = str(anchor or "breakout_or_end").strip()
    if a == "formation_start":
        return _to_ts(getattr(d, "formation_start", None))
    if a == "formation_end":
        return _to_ts(getattr(d, "formation_end", None))
    if a == "breakout_date":
        return _to_ts(getattr(d, "breakout_date", None))
    # default: breakout_or_end
    return _to_ts(getattr(d, "breakout_date", None) or getattr(d, "formation_end", None))


def _filter_detections_by_date_window(
    detections: Sequence[Any],
    *,
    date_from: Optional[str],
    date_to: Optional[str],
    anchor: str,
) -> List[Any]:
    if (not date_from) and (not date_to):
        return list(detections)

    dt_from = pd.to_datetime(date_from, errors="coerce") if date_from else None
    if dt_from is not None and pd.isna(dt_from):
        dt_from = None
    dt_to = pd.to_datetime(date_to, errors="coerce") if date_to else None
    if dt_to is not None and pd.isna(dt_to):
        dt_to = None

    out: List[Any] = []
    for d in detections:
        ts = _detection_anchor_date(d, anchor=str(anchor))
        if ts is None:
            continue
        if dt_from is not None and ts < dt_from:
            continue
        if dt_to is not None and ts > dt_to:
            continue
        out.append(d)
    return out


def _stable_detection_key(d: Any) -> Tuple[Any, ...]:
    # Used to make sampling deterministic/reproducible across runs when desired.
    return (
        str(getattr(d, "breakout_date", "") or ""),
        -int(getattr(d, "confidence_score", 0) or 0),
        str(getattr(d, "pattern_name", "") or ""),
        str(getattr(d, "pattern_id", "") or ""),
    )


def _select_for_eval(
    detections: Sequence[Any],
    *,
    max_n: Optional[int],
    mode: str,
    rng: random.Random,
) -> List[Any]:
    if max_n is None:
        return list(detections)
    max_n = int(max_n)
    if max_n <= 0:
        return []
    if len(detections) <= max_n:
        return list(detections)

    dets = list(detections)
    if mode == "first":
        return sorted(dets, key=_stable_detection_key)[:max_n]
    if mode == "top_confidence":
        return sorted(
            dets,
            key=lambda d: (
                -int(getattr(d, "confidence_score", 0) or 0),
                str(getattr(d, "breakout_date", "") or ""),
                str(getattr(d, "pattern_id", "") or ""),
            ),
        )[:max_n]
    if mode == "random":
        dets = sorted(dets, key=_stable_detection_key)
        return rng.sample(dets, k=max_n)
    raise ValueError(f"Unknown eval selection mode: {mode}")


PIVOT_MIN_SPACING_OVERRIDES: Dict[str, int] = {
    # Shorter-duration pivot patterns need a tighter pivot spacing than the global default
    # (otherwise width_max_bars becomes impossible with min_spacing=10).
    "flags": 2,
    "flags_high_tight": 2,
    "pennants": 2,
    "horn_bottoms_tops": 2,
    "horn_bottoms": 2,
    "horn_tops": 2,
    "diamond_top": 3,
    "diamond_bottom": 3,
    "diamond_tops": 3,
    "diamond_bottoms": 3,
    "rounding_bottoms_tops": 4,
    "rounding_bottoms": 4,
    "rounding_tops": 4,
}


def _compute_run_statistics(conn: sqlite3.Connection, run_id: str) -> Dict[str, Any]:
    stats: Dict[str, Any] = {"run_id": run_id}

    def _scalar(q: str, params: Tuple[Any, ...] = ()) -> Any:
        cur = conn.execute(q, params)
        row = cur.fetchone()
        return row[0] if row else None

    stats["detections_total"] = _scalar(
        "SELECT COUNT(*) FROM pattern_detections WHERE run_id = ?",
        (run_id,),
    )
    stats["detections_with_breakout"] = _scalar(
        "SELECT COUNT(*) FROM pattern_detections WHERE run_id = ? AND breakout_date IS NOT NULL",
        (run_id,),
    )
    stats["evaluations_total"] = _scalar(
        "SELECT COUNT(*) FROM post_breakout_results WHERE run_id = ?",
        (run_id,),
    )

    # Overall rates (only rows with non-null metric participate)
    def _rate(col: str) -> Optional[float]:
        v = _scalar(
            f"SELECT AVG({col}) FROM post_breakout_results WHERE run_id = ? AND {col} IS NOT NULL",
            (run_id,),
        )
        return None if v is None else float(v) * 100.0

    stats["bust_failure_rate_5pct"] = _rate("bust_failure_5pct")
    stats["bust_failure_rate_10pct"] = _rate("bust_failure_10pct")
    stats["boundary_invalidation_rate_pct"] = _rate("boundary_invalidated")
    stats["throwback_pullback_rate_pct"] = _rate("throwback_pullback_occurred")
    stats["target_achievement_rate_intraday_pct"] = _rate("target_achieved_intraday")
    stats["target_achievement_rate_close_pct"] = _rate("target_achieved_close")

    stats["avg_days_to_ultimate"] = _scalar(
        "SELECT AVG(days_to_ultimate) FROM post_breakout_results WHERE run_id = ? AND days_to_ultimate IS NOT NULL",
        (run_id,),
    )
    stats["avg_mfe_pct"] = _scalar(
        "SELECT AVG(max_favorable_excursion_pct) FROM post_breakout_results "
        "WHERE run_id = ? AND max_favorable_excursion_pct IS NOT NULL AND ABS(max_favorable_excursion_pct) < 1e308",
        (run_id,),
    )
    stats["avg_mae_pct"] = _scalar(
        "SELECT AVG(max_adverse_excursion_pct) FROM post_breakout_results "
        "WHERE run_id = ? AND max_adverse_excursion_pct IS NOT NULL AND ABS(max_adverse_excursion_pct) < 1e308",
        (run_id,),
    )

    # By pattern
    by_pattern: Dict[str, Any] = {}
    for (pattern_name,) in conn.execute(
        "SELECT DISTINCT pattern_name FROM post_breakout_results WHERE run_id = ? ORDER BY pattern_name",
        (run_id,),
    ).fetchall():
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS n,
                AVG(throwback_pullback_occurred) * 100.0,
                AVG(target_achieved_intraday) * 100.0,
                AVG(bust_failure_5pct) * 100.0,
                AVG(boundary_invalidated) * 100.0,
                AVG(CASE WHEN max_favorable_excursion_pct IS NOT NULL AND ABS(max_favorable_excursion_pct) < 1e308 THEN max_favorable_excursion_pct END),
                AVG(CASE WHEN max_adverse_excursion_pct IS NOT NULL AND ABS(max_adverse_excursion_pct) < 1e308 THEN max_adverse_excursion_pct END),
                AVG(days_to_ultimate)
            FROM post_breakout_results
            WHERE run_id = ? AND pattern_name = ?
            """,
            (run_id, pattern_name),
        ).fetchone()
        if not row:
            continue
        by_pattern[pattern_name] = {
            "count": int(row[0]),
            "throwback_pullback_rate_pct": float(row[1]) if row[1] is not None else None,
            "target_achievement_rate_intraday_pct": float(row[2]) if row[2] is not None else None,
            "bust_failure_rate_5pct": float(row[3]) if row[3] is not None else None,
            "boundary_invalidation_rate_pct": float(row[4]) if row[4] is not None else None,
            "avg_mfe_pct": float(row[5]) if row[5] is not None else None,
            "avg_mae_pct": float(row[6]) if row[6] is not None else None,
            "avg_days_to_ultimate": float(row[7]) if row[7] is not None else None,
        }

    stats["by_pattern"] = by_pattern

    # By variant (double pattern families + chapter variants)
    for family in ("double_bottoms", "double_tops"):
        by_variant: Dict[str, Any] = {}
        for (variant,) in conn.execute(
            """
            SELECT DISTINCT variant
            FROM post_breakout_results
            WHERE run_id = ?
              AND pattern_name LIKE ?
              AND variant IS NOT NULL
            ORDER BY variant
            """,
            (run_id, f"{family}%"),
        ).fetchall():
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS n,
                    AVG(CASE WHEN max_favorable_excursion_pct IS NOT NULL AND ABS(max_favorable_excursion_pct) < 1e308 THEN max_favorable_excursion_pct END),
                    AVG(CASE WHEN max_adverse_excursion_pct IS NOT NULL AND ABS(max_adverse_excursion_pct) < 1e308 THEN max_adverse_excursion_pct END),
                    AVG(bust_failure_5pct) * 100.0,
                    AVG(target_achieved_intraday) * 100.0
                FROM post_breakout_results
                WHERE run_id = ?
                  AND pattern_name LIKE ?
                  AND variant = ?
                """,
                (run_id, f"{family}%", variant),
            ).fetchone()
            if not row:
                continue
            by_variant[variant] = {
                "count": int(row[0]),
                "avg_mfe_pct": float(row[1]) if row[1] is not None else None,
                "avg_mae_pct": float(row[2]) if row[2] is not None else None,
                "bust_failure_rate_5pct": float(row[3]) if row[3] is not None else None,
                "target_achievement_rate_intraday_pct": float(row[4]) if row[4] is not None else None,
            }

        if by_variant:
            stats[f"{family}_by_variant"] = by_variant

    return stats


def main() -> None:
    require_legacy_enabled("scanner/run_full_scan.py")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        default=os.path.join(os.path.abspath(os.path.join(SCANNER_DIR, "..")), "vietnam_stocks.db"),
        help="Path to source price DB (SQLite).",
    )
    parser.add_argument(
        "--results-db",
        default=os.path.join(os.path.abspath(os.path.join(SCANNER_DIR, "..")), "scan_results", "pattern_scans.sqlite"),
        help="Path to results DB (SQLite). Will be created if missing.",
    )
    parser.add_argument("--run-id", default=None, help="Optional run_id. If omitted, one is generated.")
    parser.add_argument("--min-rows", type=int, default=500, help="Minimum bars per symbol to scan.")
    parser.add_argument(
        "--patterns",
        default=None,
        help="Comma-separated list of patterns to scan (default: all available in scanner).",
    )
    parser.add_argument(
        "--pattern-set",
        choices=[
            "digitized",
            "bulkowski_53",
            "bulkowski_53_strict",
            "bulkowski_strict_ohlcv",
            "bulkowski_49_strict_ohlcv",
            "event_ohlcv",
            "bulkowski_55_ohlcv",
        ],
        default="digitized",
        help="Which pattern set to load (default: digitized).",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit symbols (for testing).")
    parser.add_argument(
        "--universe-index",
        default=None,
        help="Restrict symbols to those in stock_index for these index_code(s) (comma-separated), e.g. VN30,VN100.",
    )
    parser.add_argument(
        "--date-from",
        default=None,
        help="Restrict detections to those with an anchor date >= this (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--date-to",
        default=None,
        help="Restrict detections to those with an anchor date <= this (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--date-anchor",
        choices=["formation_start", "formation_end", "breakout_date", "breakout_or_end"],
        default="breakout_or_end",
        help="Which detection date to use for --date-from/--date-to filtering (default: breakout_or_end).",
    )
    parser.add_argument(
        "--warmup-bars",
        type=int,
        default=300,
        help="Extra bars to include before --date-from to stabilize indicators/pivots (default: 300).",
    )
    parser.add_argument("--commit-every", type=int, default=25, help="Commit every N symbols.")
    parser.add_argument("--notes", default=None, help="Optional notes saved with the run.")
    parser.add_argument(
        "--skip-eval",
        action="store_true",
        help="Skip post-breakout evaluation (persist detections only). Useful for high-frequency patterns.",
    )
    parser.add_argument(
        "--skip-eval-patterns",
        default=None,
        help="Comma-separated list of patterns to skip post-breakout evaluation for (still detects/persists).",
    )
    parser.add_argument(
        "--eval-lookahead",
        type=int,
        default=252,
        help="Look-ahead bars for post-breakout evaluation metrics (default: 252).",
    )
    parser.add_argument(
        "--eval-max-per-symbol",
        type=int,
        default=None,
        help="Max number of confirmed breakouts to evaluate per symbol (after skip pattern filter).",
    )
    parser.add_argument(
        "--eval-max-per-symbol-per-pattern",
        type=int,
        default=None,
        help="Max number of confirmed breakouts to evaluate per symbol per pattern (useful for high-frequency patterns).",
    )
    parser.add_argument(
        "--eval-selection",
        choices=["random", "first", "top_confidence"],
        default="random",
        help="How to select detections when caps are applied (default: random).",
    )
    parser.add_argument(
        "--eval-sample-seed",
        type=int,
        default=0,
        help="Random seed for deterministic sampling when eval caps are applied (default: 0).",
    )
    parser.add_argument(
        "--overlap-policy",
        choices=["none", "bulkowski"],
        default="bulkowski",
        help="How to handle overlapping patterns in evaluation selection (default: bulkowski).",
    )
    parser.add_argument(
        "--min-breakout-price",
        type=float,
        default=None,
        help="Exclude evaluated patterns whose breakout_price is below this threshold (default: None).",
    )
    parser.add_argument(
        "--detect-max-per-symbol",
        type=int,
        default=None,
        help="Max number of detections to persist per symbol (all patterns). Useful for high-frequency runs.",
    )
    parser.add_argument(
        "--detect-max-per-symbol-per-pattern",
        type=int,
        default=None,
        help="Max number of detections to persist per symbol per pattern.",
    )
    parser.add_argument(
        "--detect-selection",
        choices=["random", "first", "top_confidence"],
        default="random",
        help="How to select detections when detection caps are applied (default: random).",
    )
    parser.add_argument(
        "--detect-sample-seed",
        type=int,
        default=0,
        help="Random seed for deterministic detection sampling when caps are applied (default: 0).",
    )
    args = parser.parse_args()

    source_db_path = os.path.abspath(args.db)
    results_db_path = os.path.abspath(args.results_db)
    run_id = args.run_id or generate_run_id(prefix="scan")

    scanner = PatternScanner(ScannerConfig(), pattern_set=str(args.pattern_set))
    available_patterns = list(scanner.scanners.keys())
    patterns = _parse_patterns(args.patterns, available_patterns)

    skip_eval_patterns = _parse_csv_set(args.skip_eval_patterns)
    unknown_skip = sorted([p for p in skip_eval_patterns if p not in available_patterns])
    if unknown_skip:
        raise SystemExit(f"Unknown --skip-eval-patterns: {unknown_skip}. Available: {sorted(available_patterns)}")

    eval_config = EvaluationConfig(
        lookahead_bars=int(args.eval_lookahead),
        reversal_threshold_pct=20.0,
        throwback_tolerance_pct=1.0,
        # Bulkowski-style invalidation: close back across boundary (no extra threshold).
        invalidation_return_threshold_pct=0.0,
        invalidation_within_bars=0,
        variant_peak_width_tolerance_pct=2.0,
        variant_peak_width_window_bars=15,
        variant_adam_max_peak_width_bars=3,
        variant_eve_min_peak_width_bars=7,
    )
    evaluator = PostBreakoutEvaluator(eval_config)
    rng = random.Random(int(args.eval_sample_seed))
    detect_rng = random.Random(int(args.detect_sample_seed))

    pattern_metadata = build_pattern_metadata(
        pattern_set=str(args.pattern_set),
        scanners=scanner.scanners,
        patterns=list(patterns),
    )

    run_config: Dict[str, Any] = {
        "pattern_set": str(args.pattern_set),
        "pattern_metadata": pattern_metadata,
        "scanner_config": scanner.config.__dict__,
        "evaluation_config": eval_config.__dict__,
        "evaluation_enabled": (not bool(args.skip_eval)),
        "skip_eval_patterns": sorted(skip_eval_patterns),
        "eval_max_per_symbol": args.eval_max_per_symbol,
        "eval_max_per_symbol_per_pattern": args.eval_max_per_symbol_per_pattern,
        "eval_selection": args.eval_selection,
        "eval_sample_seed": int(args.eval_sample_seed),
        "overlap_policy": str(args.overlap_policy),
        "min_breakout_price": float(args.min_breakout_price) if args.min_breakout_price is not None else None,
        "detect_max_per_symbol": args.detect_max_per_symbol,
        "detect_max_per_symbol_per_pattern": args.detect_max_per_symbol_per_pattern,
        "detect_selection": args.detect_selection,
        "detect_sample_seed": int(args.detect_sample_seed),
        "min_rows": int(args.min_rows),
        "universe_index": args.universe_index,
        "limit_symbols": args.limit,
        "date_from": args.date_from,
        "date_to": args.date_to,
        "date_anchor": str(args.date_anchor),
        "warmup_bars": int(args.warmup_bars),
        "patterns": patterns,
        "pivot_min_spacing_default_bars": 10,
        "pivot_min_spacing_overrides": dict(PIVOT_MIN_SPACING_OVERRIDES),
    }
    run_config_hash = _md5_json(run_config)

    # Connections
    src_conn = sqlite3.connect(source_db_path)
    src_conn.execute("PRAGMA query_only=ON;")
    res_conn = connect_results_db(results_db_path)
    ensure_schema(res_conn)

    symbols = _load_symbols(
        src_conn,
        min_rows=int(args.min_rows),
        limit=args.limit,
        universe_index=args.universe_index,
    )

    upsert_run(
        res_conn,
        run_id=run_id,
        source_db_path=source_db_path,
        source_table=SOURCE_TABLE,
        patterns=patterns,
        run_config=run_config,
        run_config_hash=run_config_hash,
        symbols_planned=len(symbols),
        symbols_scanned=0,
        symbols_failed=0,
        notes=args.notes,
    )
    res_conn.commit()

    detections_total = 0
    eval_total = 0
    scanned = 0
    failed = 0

    try:
        for i, symbol in enumerate(symbols, start=1):
            if i == 1 or (i % 50 == 0):
                print(f"[{run_id}] Scanning {i}/{len(symbols)}: {symbol}")

            try:
                df = _load_symbol_df(src_conn, symbol)
                df = _filter_df_by_date_window(
                    df,
                    date_from=args.date_from,
                    date_to=args.date_to,
                    warmup_bars=int(args.warmup_bars),
                )
                if len(df) < int(args.min_rows):
                    continue

                # Normalize once here so detection + evaluation see the same bars.
                df_norm, _ = scanner.normalizer.normalize(df)
                if len(df_norm) < int(args.min_rows):
                    scanned += 1
                    continue

                raw_pivots = scanner.pivot_detector.detect_pivots(df_norm, scanner.config.pivot_type)
                pivots_by_spacing: Dict[int, List[Any]] = {}
                pivots_by_spacing[10] = scanner.pivot_detector.get_filtered_pivots(raw_pivots, min_spacing=10)

                detections = []
                for p in patterns:
                    s = scanner.scanners[p]
                    spacing = int(PIVOT_MIN_SPACING_OVERRIDES.get(p, 10))
                    if spacing not in pivots_by_spacing:
                        pivots_by_spacing[spacing] = scanner.pivot_detector.get_filtered_pivots(raw_pivots, min_spacing=spacing)
                    pivots = pivots_by_spacing[spacing]
                    try:
                        detections.extend(
                            s.scan(
                                symbol=symbol,
                                df=df_norm,
                                pivots_filtered=pivots,
                                pivots_raw=raw_pivots,
                            )
                        )
                    except TypeError:
                        # Legacy signature
                        detections.extend(s.scan(symbol, df_norm, pivots, raw_pivots))

                detections_pd_all = [scanner._to_detection(d) for d in detections]
                detections_pd_all = _filter_detections_by_date_window(
                    detections_pd_all,
                    date_from=args.date_from,
                    date_to=args.date_to,
                    anchor=str(args.date_anchor),
                )
                detections_pd = detections_pd_all

                # Optional detection caps/sampling (persist layer + eval depend on these IDs).
                if args.detect_max_per_symbol_per_pattern is not None:
                    by_pat: Dict[str, List[Any]] = {}
                    for d in detections_pd:
                        by_pat.setdefault(d.pattern_name, []).append(d)
                    limited: List[Any] = []
                    for pat in sorted(by_pat.keys()):
                        limited.extend(
                            _select_for_eval(
                                by_pat[pat],
                                max_n=args.detect_max_per_symbol_per_pattern,
                                mode=args.detect_selection,
                                rng=detect_rng,
                            )
                        )
                    detections_pd = limited

                detections_pd = _select_for_eval(
                    detections_pd,
                    max_n=args.detect_max_per_symbol,
                    mode=args.detect_selection,
                    rng=detect_rng,
                )

                if detections_pd:
                    # Ensure PatternDetection objects for persistence layer.
                    detections_total += insert_detections(res_conn, run_id=run_id, detections=detections_pd)

                # Evaluate confirmed breakouts only (look-ahead metrics)
                if not bool(args.skip_eval):
                    confirmed = [
                        d
                        for d in detections_pd
                        if d.breakout_date is not None
                        and d.breakout_price is not None
                        and d.pattern_name not in skip_eval_patterns
                    ]
                    if args.min_breakout_price is not None:
                        confirmed = [d for d in confirmed if float(d.breakout_price) >= float(args.min_breakout_price)]

                    if args.overlap_policy != "none":
                        confirmed = _apply_overlap_policy(confirmed, str(args.overlap_policy))

                    # Optional caps/sampling (to keep high-frequency runs manageable).
                    if args.eval_max_per_symbol_per_pattern is not None:
                        by_pat: Dict[str, List[Any]] = {}
                        for d in confirmed:
                            by_pat.setdefault(d.pattern_name, []).append(d)
                        limited: List[Any] = []
                        for pat in sorted(by_pat.keys()):
                            limited.extend(
                                _select_for_eval(
                                    by_pat[pat],
                                    max_n=args.eval_max_per_symbol_per_pattern,
                                    mode=args.eval_selection,
                                    rng=rng,
                                )
                            )
                        confirmed = limited

                    confirmed = _select_for_eval(
                        confirmed,
                        max_n=args.eval_max_per_symbol,
                        mode=args.eval_selection,
                        rng=rng,
                    )

                    if confirmed:
                        results = [evaluator.evaluate(d, df_norm) for d in confirmed]
                        eval_total += insert_post_breakout_results(res_conn, run_id=run_id, results=results)

                scanned += 1

            except Exception as e:
                failed += 1
                record_error(
                    res_conn,
                    run_id=run_id,
                    symbol=symbol,
                    error=str(e),
                    traceback_text=traceback.format_exc(),
                )

            if (i % int(args.commit_every)) == 0:
                upsert_run(
                    res_conn,
                    run_id=run_id,
                    source_db_path=source_db_path,
                    source_table=SOURCE_TABLE,
                    patterns=patterns,
                    run_config=run_config,
                    run_config_hash=run_config_hash,
                    symbols_planned=len(symbols),
                    symbols_scanned=scanned,
                    symbols_failed=failed,
                    notes=args.notes,
                )
                res_conn.commit()

    finally:
        # Finalize run record + stats
        upsert_run(
            res_conn,
            run_id=run_id,
            source_db_path=source_db_path,
            source_table=SOURCE_TABLE,
            patterns=patterns,
            run_config=run_config,
            run_config_hash=run_config_hash,
            symbols_planned=len(symbols),
            symbols_scanned=scanned,
            symbols_failed=failed,
            notes=args.notes,
        )
        res_conn.commit()

        stats = _compute_run_statistics(res_conn, run_id)
        upsert_run_statistics(res_conn, run_id=run_id, stats=stats)
        res_conn.commit()

        src_conn.close()
        res_conn.close()

    print("\n=== Completed ===")
    print(f"run_id: {run_id}")
    print(f"results_db: {results_db_path}")
    print(f"symbols planned: {len(symbols)} scanned: {scanned} failed: {failed}")
    print(f"detections inserted: {detections_total}")
    print(f"evaluations inserted: {eval_total}")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
