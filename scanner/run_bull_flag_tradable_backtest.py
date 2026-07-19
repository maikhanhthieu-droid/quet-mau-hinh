"""Run Bull Flag V2 executable setup backtest."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.v2.bull_flag_tradable_setup import DEFAULT_OUT_DIR, DEFAULT_PROFILE_DIR, run_bull_flag_tradable_backtest


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Bull Flag V2 tradable setup backtest.")
    parser.add_argument("--profile-dir", default=str(DEFAULT_PROFILE_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    paths = run_bull_flag_tradable_backtest(profile_dir=Path(args.profile_dir), out_dir=Path(args.out_dir))
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
