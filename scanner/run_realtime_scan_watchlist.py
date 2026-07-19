"""Realtime watchlist orchestration for the current scanner set.

This module deliberately does not invent new pattern logic. It has two jobs:

1. produce a reproducible refresh plan that calls the existing family scanners;
2. normalize the latest event artifacts into a watchlist table for review.

The watchlist is a candidate-discovery layer. Publication scoring, tradable
gates, and chapter claims remain separate.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.rebuild_source_guided_final_chapters import DOUBLE_VARIANTS, EVENT_SOURCES  # noqa: E402
from scanner.run_bear_flag_db_source_parity_audit import DEFAULT_DB  # noqa: E402


WORKFLOW_ID = "realtime_scan_watchlist_v1"
DEFAULT_OUT_DIR = Path("artifacts/realtime_scan/latest")
DEFAULT_AFTER_BUY_CONFIG = Path("artifacts/scanner_v2/after_buy_vietnam_v2/after_buy_scanner_stat_trade_config.json")
STOPLOSS_CAUTION_PATTERNS = {
    "bear_flags",
    "triangles_descending",
    "head_and_shoulders_tops",
    "head_and_shoulders_tops_complex",
}


@dataclass(frozen=True)
class RealtimeScanJob:
    pattern_id: str
    family: str
    refresh_command: list[str]
    event_source: Path
    status: str = "available_artifact"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["event_source"] = str(self.event_source)
        return payload


def _python_module_command(module: str, *args: str) -> list[str]:
    return ["PYTHONPATH=.", "./.venv/bin/python", "-m", module, *args]


def _family_for_pattern(pattern_id: str) -> str:
    if pattern_id in DOUBLE_VARIANTS:
        return "double_pattern_family"
    if pattern_id.startswith("triangles_"):
        return "triangle_family"
    if pattern_id.startswith("wedges_"):
        return "wedge_family"
    if pattern_id.startswith("broadening_"):
        return "broadening_family"
    if pattern_id.startswith("head_and_shoulders_"):
        return "head_shoulders_family"
    if pattern_id.startswith("cup_with_handle"):
        return "cup_handle_family"
    if pattern_id.startswith("rectangle_"):
        return "rectangle_family"
    if pattern_id.endswith("flags") or pattern_id.endswith("pennants") or pattern_id == "high_tight_flags":
        return "flag_family"
    return "uncategorized"


def _refresh_command(pattern_id: str, db_path: Path, out_root: Path) -> list[str]:
    out_dir = out_root / "refresh" / pattern_id
    if pattern_id == "bull_flags":
        return _python_module_command("scanner.run_bull_flag_db_source_parity_audit", "--db", str(db_path), "--out-dir", str(out_dir))
    if pattern_id == "bear_flags":
        return _python_module_command("scanner.run_bear_flag_db_source_parity_audit", "--db", str(db_path), "--out-dir", str(out_dir))
    if pattern_id.startswith("triangles_"):
        module = {
            "triangles_ascending": "scanner.v2.ascending_triangles",
            "triangles_descending": "scanner.v2.descending_triangles",
            "triangles_symmetrical": "scanner.v2.symmetrical_triangles",
        }[pattern_id]
        return _python_module_command(module, "--db", str(db_path), "--out-dir", str(out_dir))
    if pattern_id.startswith("wedges_"):
        module = {"wedges_falling": "scanner.v2.falling_wedges", "wedges_rising": "scanner.v2.rising_wedges"}[pattern_id]
        return _python_module_command(module, "--db", str(db_path), "--out-dir", str(out_dir))
    if pattern_id in {"cup_with_handle", "cup_with_handle_inverted"}:
        variant = "cup_with_handle_inverted" if pattern_id.endswith("inverted") else "cup_with_handle"
        return _python_module_command("scanner.v2.cup_with_handle", "--variant", variant, "--db", str(db_path), "--out-dir", str(out_dir))
    if pattern_id.startswith("rectangle_"):
        variant = pattern_id
        return _python_module_command("scanner.v2.rectangles", "--variant", variant, "--db", str(db_path), "--out-dir", str(out_dir))
    if pattern_id.startswith("head_and_shoulders_"):
        return _python_module_command("scanner.v2.head_shoulders", "--db", str(db_path), "--out-dir", str(out_dir))
    if pattern_id.startswith("broadening_"):
        return _python_module_command("scanner.v2.broadening_patterns", "--variant", pattern_id, "--db", str(db_path), "--out-dir", str(out_dir))
    if pattern_id in DOUBLE_VARIANTS:
        family, variant = DOUBLE_VARIANTS[pattern_id]
        return _python_module_command("scanner.v2.double_patterns", "--family", family, "--variant", variant, "--db", str(db_path), "--out-dir", str(out_dir))
    return ["UNSUPPORTED", pattern_id]


def build_realtime_scan_plan(
    *,
    db_path: Path = DEFAULT_DB,
    out_root: Path = DEFAULT_OUT_DIR,
    patterns: Sequence[str] | None = None,
) -> dict[str, Any]:
    wanted = set(patterns) if patterns else (set(EVENT_SOURCES) | set(DOUBLE_VARIANTS))
    jobs: list[RealtimeScanJob] = []
    for pattern_id, (event_source, filters) in sorted(EVENT_SOURCES.items()):
        if pattern_id not in wanted:
            continue
        if filters:
            # Variant-sliced artifacts are watchlist-readable but scanner refresh
            # may happen at family level. Keep them in the plan with that note.
            status = "variant_artifact_filter"
        else:
            status = "available_artifact"
        jobs.append(
            RealtimeScanJob(
                pattern_id=pattern_id,
                family=_family_for_pattern(pattern_id),
                refresh_command=_refresh_command(pattern_id, db_path, out_root),
                event_source=event_source,
                status=status,
            )
        )
    for pattern_id in sorted(set(DOUBLE_VARIANTS) & wanted):
        event_source = Path("artifacts/scanner_v2/double_pattern_family_adam_eve_branch") / DOUBLE_VARIANTS[pattern_id][0] / "db_active/events.csv"
        jobs.append(
            RealtimeScanJob(
                pattern_id=pattern_id,
                family="double_pattern_family",
                refresh_command=_refresh_command(pattern_id, db_path, out_root),
                event_source=event_source,
                status="variant_artifact_filter",
            )
        )
    return {
        "workflow_id": WORKFLOW_ID,
        "db_path": str(db_path),
        "out_root": str(out_root),
        "jobs": [job.to_dict() for job in jobs],
    }


def _event_date_column(df: pd.DataFrame) -> str | None:
    for column in ("confirmation_date", "breakout_date", "pattern_end", "formation_end"):
        if column in df.columns:
            return column
    return None


def _normalize_watchlist_row(pattern_id: str, family: str, row: Mapping[str, Any]) -> dict[str, Any]:
    date_value = row.get("confirmation_date") or row.get("breakout_date") or row.get("pattern_end") or row.get("formation_end")
    symbol = row.get("symbol") or row.get("ticker")
    direction = row.get("direction") or row.get("breakout_direction") or row.get("variant")
    return {
        "pattern_id": pattern_id,
        "family": family,
        "symbol": symbol,
        "event_date": date_value,
        "direction": direction,
        "quality_tier": row.get("quality_tier") or row.get("publication_quality_tier") or row.get("tradability_quality_bucket"),
        "market_group": row.get("market_group"),
        "market_regime": row.get("market_regime"),
        "liquidity_bucket": row.get("liquidity_bucket"),
        "mfe_pct": row.get("mfe_pct"),
        "mae_pct": row.get("mae_pct"),
        "target_hit": row.get("target_hit"),
        "failure_5pct": row.get("failure_5pct"),
        "target_first_before_adverse_5pct": row.get("target_first_before_adverse_5pct"),
        "source_event_id": row.get("event_id") or row.get("detection_id"),
    }


def _load_after_buy_runtime_config(path: Path = DEFAULT_AFTER_BUY_CONFIG) -> dict[str, Mapping[str, Any]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("patterns") if isinstance(data.get("patterns"), list) else []
    return {str(row.get("pattern_id")): row for row in rows if isinstance(row, Mapping) and row.get("pattern_id")}


def _after_buy_watchlist_fields(pattern_id: str, config: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    row = config.get(pattern_id)
    if not row:
        return {
            "after_buy_role": "unmapped_reference",
            "after_buy_action": "review_with_base_chapter_only",
            "after_buy_trade_mode": "not_after_buy_mapped",
            "after_buy_risk_context": False,
            "after_buy_no_overfit_blocked": False,
        }
    buy_allowed = bool(row.get("buy_layer_allowed"))
    trade_mode = str(row.get("trade_layer_mode") or "")
    no_overfit_gate = row.get("no_overfit_gate") if isinstance(row.get("no_overfit_gate"), Mapping) else {}
    if not buy_allowed:
        action = "avoid_buy_or_exit_warning"
        risk_context = True
    elif trade_mode == "preserve_tradable_final":
        action = "actionable_long_cash_candidate_after_buy_confirmed"
        risk_context = False
    elif no_overfit_gate.get("currently_blocked"):
        action = "watchlist_only_do_not_promote_until_fold_improves"
        risk_context = False
    else:
        action = "source_guided_long_cash_review"
        risk_context = False
    return {
        "after_buy_role": row.get("local_role"),
        "after_buy_action": action,
        "after_buy_trade_mode": trade_mode,
        "after_buy_risk_context": risk_context,
        "after_buy_no_overfit_blocked": bool(no_overfit_gate.get("currently_blocked")),
    }


def _stoploss_caution_watchlist_fields(pattern_id: str) -> dict[str, Any]:
    if pattern_id not in STOPLOSS_CAUTION_PATTERNS:
        return {
            "stoploss_caution_role": "none",
            "stoploss_caution_action": "not_applicable",
            "stoploss_caution_window_bars": None,
            "stoploss_caution_is_buy_signal": False,
        }
    return {
        "stoploss_caution_role": "failed_breakdown_reclaim_watch",
        "stoploss_caution_action": "watch_5_10_20d_reclaim_before_treating_breakdown_as_clean",
        "stoploss_caution_window_bars": 20,
        "stoploss_caution_is_buy_signal": False,
    }


def build_watchlist_from_artifacts(
    plan: Mapping[str, Any],
    *,
    lookback_days: int = 7,
    after_buy_config_path: Path | None = DEFAULT_AFTER_BUY_CONFIG,
) -> pd.DataFrame:
    after_buy_config = _load_after_buy_runtime_config(after_buy_config_path) if after_buy_config_path else {}
    frames: list[pd.DataFrame] = []
    for job in plan.get("jobs", []):
        if not isinstance(job, Mapping):
            continue
        source = Path(str(job.get("event_source") or ""))
        if not source.exists():
            continue
        df = pd.read_csv(source, low_memory=False)
        if df.empty:
            continue
        date_col = _event_date_column(df)
        if not date_col:
            continue
        dates = pd.to_datetime(df[date_col], errors="coerce")
        if dates.notna().any():
            cutoff = dates.max() - pd.Timedelta(days=int(lookback_days))
            df = df.loc[dates >= cutoff].copy()
        pattern_id = str(job["pattern_id"])
        after_buy_fields = _after_buy_watchlist_fields(pattern_id, after_buy_config)
        stoploss_caution_fields = _stoploss_caution_watchlist_fields(pattern_id)
        rows = [
            {**_normalize_watchlist_row(pattern_id, str(job["family"]), row), **after_buy_fields, **stoploss_caution_fields}
            for row in df.to_dict("records")
        ]
        if rows:
            frames.append(pd.DataFrame(rows))
    if not frames:
        return pd.DataFrame(
            columns=[
                "pattern_id",
                "family",
                "symbol",
                "event_date",
                "direction",
                "quality_tier",
                "market_group",
                "market_regime",
                "liquidity_bucket",
                "mfe_pct",
                "mae_pct",
                "target_hit",
                "failure_5pct",
                "target_first_before_adverse_5pct",
                "source_event_id",
                "after_buy_role",
                "after_buy_action",
                "after_buy_trade_mode",
                "after_buy_risk_context",
                "after_buy_no_overfit_blocked",
                "stoploss_caution_role",
                "stoploss_caution_action",
                "stoploss_caution_window_bars",
                "stoploss_caution_is_buy_signal",
            ]
        )
    out = pd.concat(frames, ignore_index=True)
    out["event_date"] = pd.to_datetime(out["event_date"], errors="coerce")
    return out.sort_values(["event_date", "family", "pattern_id", "symbol"], ascending=[False, True, True, True])


def write_realtime_outputs(plan: Mapping[str, Any], watchlist: pd.DataFrame, out_dir: Path = DEFAULT_OUT_DIR) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    plan_path = out_dir / "realtime_scan_plan.json"
    watchlist_csv = out_dir / "realtime_watchlist.csv"
    watchlist_json = out_dir / "realtime_watchlist.json"
    report_md = out_dir / "realtime_watchlist.md"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    watchlist.to_csv(watchlist_csv, index=False)
    watchlist_json.write_text(watchlist.to_json(orient="records", force_ascii=False, date_format="iso", indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Realtime Scan Watchlist",
        "",
        f"Workflow: `{WORKFLOW_ID}`",
        f"Candidate count: `{len(watchlist)}`",
        "",
        "| Date | Pattern | Symbol | Direction | Tier | After-Buy action | Regime |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in watchlist.head(80).to_dict("records"):
        event_date = row.get("event_date")
        if hasattr(event_date, "date"):
            event_date = event_date.date().isoformat()
        lines.append(
            f"| {event_date} | {row.get('pattern_id')} | {row.get('symbol')} | {row.get('direction')} | "
            f"{row.get('quality_tier')} | {row.get('after_buy_action')} | {row.get('market_regime')} |"
        )
    report_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"plan": str(plan_path), "watchlist_csv": str(watchlist_csv), "watchlist_json": str(watchlist_json), "report_md": str(report_md)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build realtime scanner plan and current watchlist from available artifacts.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--pattern", action="append", default=[])
    parser.add_argument("--after-buy-config", default=str(DEFAULT_AFTER_BUY_CONFIG))
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    plan = build_realtime_scan_plan(db_path=Path(args.db), out_root=out_dir, patterns=list(args.pattern) or None)
    watchlist = build_watchlist_from_artifacts(plan, lookback_days=int(args.lookback_days), after_buy_config_path=Path(args.after_buy_config))
    paths = write_realtime_outputs(plan, watchlist, out_dir)
    print(json.dumps({"workflow_id": WORKFLOW_ID, "status": "PASS", "counts": {"jobs": len(plan["jobs"]), "watchlist": len(watchlist)}, "paths": paths}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
