"""Build the Bull Flag Scanner V2 watchlist monograph."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.v2.bull_flags_monograph import DEFAULT_MARKET_STATS_JSON, DEFAULT_OUT_DIR, DEFAULT_SOURCE_DIR, run_pipeline
from scanner.v2.flags_experiment import DEFAULT_INDEX_DB, DEFAULT_INDEX_SYMBOL


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR), help="Market Stats V1 stock_series directory")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output artifact directory")
    parser.add_argument("--limit-symbols", type=int, default=None, help="Optional symbol limit for smoke runs")
    parser.add_argument("--index-db", default=str(DEFAULT_INDEX_DB), help="Index price DB used for VNINDEX regime split")
    parser.add_argument("--index-symbol", default=DEFAULT_INDEX_SYMBOL, help="Index symbol used for regime split")
    parser.add_argument("--market-stats-json", default=str(DEFAULT_MARKET_STATS_JSON), help="Market Stats V1 metadata used for current active universe filtering")
    parser.add_argument("--detector-config-json", default=None, help="Optional JSON file with FlagDetectorConfig overrides")
    parser.add_argument("--event-filter-config-json", default=None, help="Optional JSON file with localized event-filter profile")
    args = parser.parse_args()
    detector_config = json.loads(Path(args.detector_config_json).read_text(encoding="utf-8")) if args.detector_config_json else None
    event_filter_config = json.loads(Path(args.event_filter_config_json).read_text(encoding="utf-8")) if args.event_filter_config_json else None

    paths = run_pipeline(
        source_dir=Path(args.source_dir),
        out_dir=Path(args.out_dir),
        limit_symbols=args.limit_symbols,
        index_db=Path(args.index_db),
        index_symbol=str(args.index_symbol),
        market_stats_json=Path(args.market_stats_json),
        detector_config=detector_config,
        event_filter_config=event_filter_config,
    )
    print(paths["pdf"])


if __name__ == "__main__":
    main()
