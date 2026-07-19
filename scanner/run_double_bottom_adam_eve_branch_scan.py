"""Run the source-grounded Adam & Eve Double Bottom branch scan."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.run_bear_flag_db_source_parity_audit import DEFAULT_DB  # noqa: E402
from scanner.v2.bull_flags_monograph import DEFAULT_MARKET_STATS_JSON, _load_active_symbols  # noqa: E402
from scanner.v2.double_patterns import scan_double_patterns_db  # noqa: E402
from scanner.v2.flags_experiment import DEFAULT_INDEX_DB  # noqa: E402


DEFAULT_OUT_ROOT = Path("artifacts/scanner_v2/double_pattern_family_adam_eve_branch")
ADAM_EVE_BRANCH_CONFIG = {
    "width_min_bars": 12,
    "width_max_bars": 150,
    "extreme_similarity_tol_pct": 5.5,
    "min_neckline_height_pct": 3.5,
    "min_prior_trend_pct": 3.0,
    "breakout_search_bars": 50,
    "breakout_cooldown_bars": 25,
    "max_events_per_symbol": 20,
}


def run_branch_scan(
    *,
    out_root: Path = DEFAULT_OUT_ROOT,
    db_path: Path = DEFAULT_DB,
    market_stats_json: Path = DEFAULT_MARKET_STATS_JSON,
    limit_symbols: int | None = None,
) -> dict[str, Path]:
    active_meta = _load_active_symbols(market_stats_json if market_stats_json else None)
    active_symbols = active_meta.get("active_symbols") if active_meta.get("enabled") else None
    return scan_double_patterns_db(
        family="double_bottoms",
        db_path=db_path,
        out_dir=out_root / "double_bottoms" / "db_active",
        allowed_symbols=active_symbols,
        detector_config=ADAM_EVE_BRANCH_CONFIG,
        limit_symbols=limit_symbols,
        index_db=DEFAULT_INDEX_DB,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run source-grounded Adam & Eve Double Bottom branch scan.")
    parser.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT))
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--market-stats-json", default=str(DEFAULT_MARKET_STATS_JSON))
    parser.add_argument("--limit-symbols", type=int, default=None)
    args = parser.parse_args()
    paths = run_branch_scan(
        out_root=Path(args.out_root),
        db_path=Path(args.db),
        market_stats_json=Path(args.market_stats_json),
        limit_symbols=args.limit_symbols,
    )
    print(json.dumps({key: str(value) for key, value in paths.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
