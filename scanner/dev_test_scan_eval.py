"""
Developer smoke-test: scan a small symbol set and run post-breakout evaluation.

Run:
  python3 scanner/dev_test_scan_eval.py
"""

from __future__ import annotations

import os
import sys
import sqlite3
from typing import List

import pandas as pd

# Allow running as a script (imports are local-module style in this folder)
SCANNER_DIR = os.path.dirname(__file__)
sys.path.insert(0, SCANNER_DIR)

from pattern_scanner import PatternScanner  # noqa: E402
from post_breakout_analyzer import PostBreakoutEvaluator, EvaluationConfig, StatisticsAggregator  # noqa: E402


def _load_symbol_df(conn: sqlite3.Connection, symbol: str) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT symbol, time as date, open, high, low, close, volume "
        "FROM stock_price_history WHERE symbol = ? ORDER BY time",
        conn,
        params=[symbol],
    )
    df["date"] = pd.to_datetime(df["date"])
    return df


def main() -> None:
    root = os.path.abspath(os.path.join(SCANNER_DIR, ".."))
    db_path = os.path.join(root, "vietnam_stocks.db")

    test_symbols: List[str] = [
        "VCB",
        "FPT",
        "HCM",
        "MWG",
        "VNM",
        "HPG",
        "SSI",
        "VIC",
        "VHM",
        "CTG",
        "TCB",
        "BID",
    ]

    scanner = PatternScanner()
    detections = scanner.scan_database(db_path, symbols=test_symbols)
    confirmed = [d for d in detections if d.breakout_date is not None and d.breakout_price is not None]

    print("\n=== Scan Summary ===")
    print(f"Symbols: {len(test_symbols)}")
    print(f"Detections: {len(detections)}")
    print(f"Confirmed breakouts: {len(confirmed)}")

    if not confirmed:
        return

    conn = sqlite3.connect(db_path)
    try:
        df_dict = {s: _load_symbol_df(conn, s) for s in sorted(set(d.symbol for d in confirmed))}
    finally:
        conn.close()

    evaluator = PostBreakoutEvaluator(
        EvaluationConfig(
            lookahead_bars=252,
            throwback_tolerance_pct=1.0,
            variant_peak_width_tolerance_pct=2.0,
            variant_peak_width_window_bars=15,
            variant_adam_max_peak_width_bars=3,
            variant_eve_min_peak_width_bars=7,
        )
    )

    results = [evaluator.evaluate(d, df_dict[d.symbol]) for d in confirmed]
    stats = StatisticsAggregator().aggregate(results)

    print("\n=== Key Stats (Confirmed Breakouts) ===")
    print(f"Throwback/Pullback rate: {stats.get('throwback_pullback_rate_pct'):.1f}%")
    print(f"Breakout retest rate:    {stats.get('breakout_retest_rate_pct'):.1f}%")
    print(f"Boundary retest rate:    {stats.get('boundary_retest_rate_pct'):.1f}%")
    print(f"Bust failure 5% rate:    {stats.get('bust_failure_rate_5pct'):.1f}%")
    print(f"Boundary invalidation:   {stats.get('boundary_invalidation_rate_pct'):.1f}%")
    print(f"Target achieved (intra): {stats.get('target_achievement_rate_intraday_pct'):.1f}%")
    print(f"Avg days to ultimate:    {stats.get('avg_days_to_ultimate', float('nan')):.1f}")
    print(f"Avg MFE:                 {stats.get('avg_max_favorable_excursion_pct', float('nan')):.2f}%")
    print(f"Avg MAE:                 {stats.get('avg_max_adverse_excursion_pct', float('nan')):.2f}%")

    if "double_tops_by_variant" in stats:
        print("\n=== Double Tops By Variant ===")
        unknown = stats.get("double_tops_variant_unknown_count", 0)
        print(f"Unknown variant: {unknown}")
        for v, vstats in stats["double_tops_by_variant"].items():
            count = vstats.get("count", 0)
            avg_mfe = vstats.get("avg_mfe_pct")
            avg_mae = vstats.get("avg_mae_pct")
            print(
                f"{v}: n={count}"
                + (f", avg_MFE={avg_mfe:.2f}%" if avg_mfe is not None else "")
                + (f", avg_MAE={avg_mae:.2f}%" if avg_mae is not None else "")
            )


if __name__ == "__main__":
    main()

