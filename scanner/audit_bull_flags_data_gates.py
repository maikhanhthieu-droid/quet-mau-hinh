"""Audit Bull Flag data gates before investment-reference promotion."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.v2.bull_flags_monograph import DEFAULT_OUT_DIR
from scanner.v2.data_gate_audit import audit_chapter_data_gates, render_data_gate_markdown


DEFAULT_MARKET_STATS_JSON = Path("../market_stats/web/market_stats_data.json")
DEFAULT_MEMBERSHIP_DB = Path("../market_stats/cache/membership_history.sqlite")
DEFAULT_STOCK_SERIES_DIR = Path("../market_stats/web/stock_series")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--market-stats-json", default=str(DEFAULT_MARKET_STATS_JSON))
    parser.add_argument("--membership-db", default=str(DEFAULT_MEMBERSHIP_DB))
    parser.add_argument("--stock-series-dir", default=str(DEFAULT_STOCK_SERIES_DIR))
    parser.add_argument("--horizon-days", type=int, default=60)
    parser.add_argument("--cooldown-days", type=int, default=15)
    parser.add_argument(
        "--universe-scope",
        default="available_series_descriptive",
        choices=["available_series_descriptive", "full_point_in_time"],
        help="Use available_series_descriptive when the chapter intentionally avoids full PTI universe claims.",
    )
    parser.add_argument(
        "--use-historical-membership",
        action="store_true",
        help="Require historical VN30/VN100 membership coverage for headline claims.",
    )
    args = parser.parse_args()

    artifact_dir = Path(args.artifact_dir)
    report = audit_chapter_data_gates(
        pattern_key="bull_flags",
        events_csv=artifact_dir / "events.csv",
        path_csv=artifact_dir / "post_breakout_path.csv",
        market_stats_json=Path(args.market_stats_json),
        membership_db=Path(args.membership_db),
        stock_series_dir=Path(args.stock_series_dir),
        horizon_days=int(args.horizon_days),
        cooldown_days=int(args.cooldown_days),
        universe_scope=str(args.universe_scope),
        use_historical_membership=bool(args.use_historical_membership),
    )
    json_path = artifact_dir / "data_gate_audit.json"
    md_path = artifact_dir / "data_gate_audit.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_data_gate_markdown(report), encoding="utf-8")
    print(md_path)


if __name__ == "__main__":
    main()
