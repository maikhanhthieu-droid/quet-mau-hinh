"""Run Bull Flag Scanner V2 localization sweep."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.v2.bull_flag_localization import DEFAULT_BULL_FLAGS_DIR, DEFAULT_OUT_DIR, run_localization


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", default=str(DEFAULT_BULL_FLAGS_DIR), help="Baseline Bull Flag artifact directory")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory for localization artifacts")
    args = parser.parse_args()

    paths = run_localization(artifact_dir=Path(args.artifact_dir), out_dir=Path(args.out_dir))
    print(paths["markdown"])


if __name__ == "__main__":
    main()
