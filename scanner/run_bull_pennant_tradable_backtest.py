"""Run Bull Pennant executable setup backtest."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.v2.bull_pennant_tradable_setup import (  # noqa: E402
    DEFAULT_EVENTS,
    DEFAULT_OUT_DIR,
    DEFAULT_PATH,
    DEFAULT_SOURCE_DIR,
    run_bull_pennant_tradable_backtest,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Bull Pennant tradable setup KPI backtest.")
    parser.add_argument("--events-csv", default=str(DEFAULT_EVENTS))
    parser.add_argument("--path-csv", default=str(DEFAULT_PATH))
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    paths = run_bull_pennant_tradable_backtest(
        events_csv=Path(args.events_csv),
        path_csv=Path(args.path_csv),
        source_dir=Path(args.source_dir),
        out_dir=Path(args.out_dir),
    )
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
