"""Run Bull Flag adaptive detector-branch grid."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.v2.bull_flag_localization import DEFAULT_ADAPTIVE_GRID_OUT_DIR, run_adaptive_detector_grid
from scanner.v2.bull_flags_monograph import DEFAULT_MARKET_STATS_JSON
from scanner.v2.flags_experiment import DEFAULT_INDEX_DB, DEFAULT_INDEX_SYMBOL
from scanner.v2.source_data import DEFAULT_SOURCE_DIR


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Bull Flag adaptive detector branch grid.")
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_ADAPTIVE_GRID_OUT_DIR))
    parser.add_argument("--market-stats-json", default=str(DEFAULT_MARKET_STATS_JSON))
    parser.add_argument("--index-db", default=str(DEFAULT_INDEX_DB))
    parser.add_argument("--index-symbol", default=DEFAULT_INDEX_SYMBOL)
    parser.add_argument("--limit-symbols", type=int, default=None)
    parser.add_argument("--limit-profiles", type=int, default=None)
    args = parser.parse_args()
    paths = run_adaptive_detector_grid(
        source_dir=Path(args.source_dir),
        out_dir=Path(args.out_dir),
        market_stats_json=Path(args.market_stats_json) if args.market_stats_json else None,
        index_db=Path(args.index_db),
        index_symbol=args.index_symbol,
        limit_symbols=args.limit_symbols,
        limit_profiles=args.limit_profiles,
    )
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
