"""Run the experimental Scanner V2 flags diagnostic."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.v2.flags_experiment import DEFAULT_INDEX_DB, DEFAULT_INDEX_SYMBOL, DEFAULT_OUT_DIR, DEFAULT_SOURCE_DIR, run_experiment


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--limit-symbols", type=int, default=None)
    parser.add_argument("--index-db", default=str(DEFAULT_INDEX_DB))
    parser.add_argument("--index-symbol", default=DEFAULT_INDEX_SYMBOL)
    args = parser.parse_args()

    paths = run_experiment(
        source_dir=Path(args.source_dir),
        out_dir=Path(args.out_dir),
        limit_symbols=args.limit_symbols,
        index_db=Path(args.index_db),
        index_symbol=str(args.index_symbol),
    )
    print(paths["pdf"])


if __name__ == "__main__":
    main()

