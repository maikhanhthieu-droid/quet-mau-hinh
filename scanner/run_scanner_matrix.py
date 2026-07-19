"""Build scanner matrix artifacts from active V2 scanners."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.v2.matrix import build_flag_family_matrix_artifacts


DEFAULT_BULL_FLAG_EVENTS = Path("artifacts/scanner_v2/bull_flags/events.csv")
DEFAULT_BEAR_FLAG_EVENTS = Path("artifacts/scanner_v2/bear_flags/events.csv")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/scanner_matrix")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the scanner matrix unified event table.")
    parser.add_argument("--bull-flag-events", default=str(DEFAULT_BULL_FLAG_EVENTS))
    parser.add_argument("--bear-flag-events", default=str(DEFAULT_BEAR_FLAG_EVENTS))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()

    paths = build_flag_family_matrix_artifacts(
        {
            "bull_flags": Path(args.bull_flag_events),
            "bear_flags": Path(args.bear_flag_events),
        },
        Path(args.out_dir),
    )
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
