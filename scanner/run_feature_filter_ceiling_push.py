"""Feature-filter ceiling push for blocked pattern chapters.

This pass tests whether pre-breakout setup and breakout-confirmation filters
can improve the remaining blocked chapters.  It deliberately avoids outcome
labels such as target hit, MFE/MAE, post-breakout path quality, or forward
price-limit proxies as selectors.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.run_chapter_tradable_layer import (  # noqa: E402
    CHAPTER_SPECS,
    GenericExecutionConfig,
    evaluate_strategy,
    load_chapter_events_and_path,
    run_cost_stress,
    run_monte_carlo,
    run_walk_forward,
    score_tradable_setup,
)


PUSH_ID = "feature_filter_ceiling_push_v1"
NO_OVERLIFT_POLICY_ID = "feature_filter_no_overlift_guard_v1"
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/feature_filter_ceiling_push")
DEFAULT_PATTERNS = (
    "triangles_symmetrical",
    "triangles_descending",
    "bear_flags",
    "triangles_ascending",
    "wedges_falling",
    "wedges_rising",
)


@dataclass(frozen=True)
class EventFilter:
    filter_id: str
    description: str
    predicate: Callable[[pd.DataFrame], pd.Series]


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _score_between(value: Any, low: float, high: float) -> float:
    numeric = _as_float(value, default=low)
    if high == low:
        return 100.0 if numeric >= high else 0.0
    return max(0.0, min(100.0, (numeric - low) / (high - low) * 100.0))


def _num(frame: pd.DataFrame, column: str, default: float = np.nan) -> pd.Series:
    if column not in frame:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _bool(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(False, index=frame.index, dtype="bool")
    series = frame[column]
    if series.dtype == bool:
        return series.fillna(False)
    return series.astype(str).str.lower().isin({"true", "1", "yes", "y"})


def _cat(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series("", index=frame.index, dtype="object")
    return frame[column].astype(str)


def _direction_for(pattern_id: str) -> tuple[str, ...]:
    if pattern_id in {"triangles_descending", "bear_flags", "wedges_rising"}:
        return ("down",)
    return ("up",)


def _scope_for(pattern_id: str) -> str:
    if pattern_id == "triangles_symmetrical":
        return "long_up_breakout_branch"
    if _direction_for(pattern_id) == ("down",):
        return "defensive_informational"
    return "long_cash_candidate"


def _target_family(pattern_id: str) -> tuple[float, ...]:
    if pattern_id == "bear_flags":
        return (0.35, 0.46, 0.50, 0.75, 1.00)
    return (0.35, 0.50, 0.65, 0.75, 1.00)


def build_event_filters(pattern_id: str) -> list[EventFilter]:
    filters: list[EventFilter] = [
        EventFilter("all", "No additional feature filter.", lambda f: pd.Series(True, index=f.index)),
        EventFilter("vol_confirmed", "Breakout volume confirmed.", lambda f: _bool(f, "volume_confirmed")),
        EventFilter("vol_ratio_ge_120", "Breakout volume ratio >= 1.20.", lambda f: _num(f, "breakout_volume_ratio") >= 1.20),
        EventFilter("vol_ratio_ge_150", "Breakout volume ratio >= 1.50.", lambda f: _num(f, "breakout_volume_ratio") >= 1.50),
        EventFilter("clearance_ge_200", "Breakout clearance >= 2%.", lambda f: _num(f, "breakout_clearance_pct") >= 2.00),
        EventFilter("quality_ge_80", "Pattern/publication quality >= 80.", lambda f: _num(f, "publication_quality_score", np.nan).fillna(_num(f, "pattern_quality_score")) >= 80.0),
        EventFilter("tradability_ge_75", "Tradability quality score >= 75.", lambda f: _num(f, "tradability_quality_score") >= 75.0),
        EventFilter("yearly_pos_mid_high", "Yearly range position in middle/high band.", lambda f: _num(f, "yearly_range_position_pct").between(35.0, 85.0)),
    ]

    if pattern_id == "bear_flags":
        filters.extend(
            [
                EventFilter("bear_headline", "Scanner Bear Flag headline candidate.", lambda f: _bool(f, "bear_branch_is_headline_candidate")),
                EventFilter("bear_defensive_core", "Scanner defensive-core Bear Flag branch.", lambda f: _cat(f, "bear_branch_lane").eq("defensive-core")),
                EventFilter("bear_liquid_clean_breakout", "Usable Bear Flag branch with confirmed volume.", lambda f: _bool(f, "bear_branch_is_headline_candidate") & _bool(f, "volume_confirmed")),
            ]
        )
        return filters

    if "triangle" in pattern_id:
        filters.extend(
            [
                EventFilter("white_space_ge_85", "Triangle white-space score >= 85.", lambda f: _num(f, "triangle_white_space_score") >= 85.0),
                EventFilter("crossings_le_4", "Triangle crossing count <= 4.", lambda f: _num(f, "triangle_crossing_count") <= 4.0),
                EventFilter("apex_live_window", "Breakout occurs near but not too far past apex.", lambda f: _num(f, "apex_progress_pct").between(60.0, 115.0)),
                EventFilter("bars_to_apex_positive", "Breakout before/near apex, bars_to_apex >= 0.", lambda f: _num(f, "bars_to_apex") >= 0.0),
                EventFilter("clean_apex_cross", "Clean triangle: white-space high, crossings low, near apex.", lambda f: (_num(f, "triangle_white_space_score") >= 85.0) & (_num(f, "triangle_crossing_count") <= 4.0) & _num(f, "apex_progress_pct").between(60.0, 115.0)),
                EventFilter("tight_compression", "Tighter compression ratio <= 0.40.", lambda f: _num(f, "compression_ratio") <= 0.40),
            ]
        )
        return filters

    if "wedge" in pattern_id:
        filters.extend(
            [
                EventFilter("wedge_tight_compression", "Wedge compression ratio <= 0.45.", lambda f: _num(f, "compression_ratio") <= 0.45),
                EventFilter("wedge_moderate_height", "Wedge height between 10% and 25%.", lambda f: _num(f, "pattern_height_pct").between(10.0, 25.0)),
                EventFilter("wedge_width_25_55", "Wedge width between 25 and 55 bars.", lambda f: _num(f, "pattern_width_bars").between(25.0, 55.0)),
                EventFilter("wedge_clean_breakout", "Tight wedge with >=2% breakout clearance.", lambda f: (_num(f, "compression_ratio") <= 0.45) & (_num(f, "breakout_clearance_pct") >= 2.0)),
            ]
        )
        return filters

    return filters


def build_configs(pattern_id: str) -> list[GenericExecutionConfig]:
    """Build a focused execution grid for feature-filter attribution.

    The broad target/stop search lives in ``run_targeted_pattern_ceiling_push``.
    This pass answers a narrower question: do source-aligned setup and breakout
    filters improve a representative execution profile?  Keeping the grid small
    prevents high-depth patterns such as Ascending Triangles from spending the
    whole run re-testing generic target/stop combinations.
    """
    direction = _direction_for(pattern_id)
    configs: list[GenericExecutionConfig] = []
    representative_targets = (0.35, 0.50, 0.75) if _direction_for(pattern_id) == ("down",) else (0.50, 0.65, 0.75)
    if pattern_id == "bear_flags":
        representative_targets = (0.35, 0.46, 0.50)
    for target in representative_targets:
        for hold in (40, 60):
            configs.append(
                GenericExecutionConfig(
                    strategy_id=f"base_t{str(target).replace('.', '')}_s7_h{hold}_d1_liqall_p005",
                    target_multiple=target,
                    stop_loss_pct=7.0,
                    max_holding_days=hold,
                    entry_delay_bars=1,
                    allowed_breakout_directions=direction,
                    position_size_pct=0.05,
                )
            )
    for target in representative_targets[:2]:
        configs.append(
            GenericExecutionConfig(
                strategy_id=f"context_liqmh_t{str(target).replace('.', '')}_s7_h60_d3_p0033",
                target_multiple=target,
                stop_loss_pct=7.0,
                max_holding_days=60,
                entry_delay_bars=3,
                allowed_breakout_directions=direction,
                allowed_liquidity_buckets=("mid", "high"),
                position_size_pct=0.033,
                max_positions=30,
                target_adtv_participation_pct=5.0,
            )
        )
    return configs


def _filtered_events(events: pd.DataFrame, event_filter: EventFilter) -> pd.DataFrame:
    mask = event_filter.predicate(events)
    mask = mask.reindex(events.index).fillna(False).astype(bool)
    return events[mask].copy()


def _utility(row: Mapping[str, Any], prefix: str) -> float:
    key = lambda name: f"{prefix}_{name}"
    return (
        0.30 * _score_between(row.get(key("total_return_pct")), 0.0, 8.0)
        + 0.18 * _score_between(row.get(key("max_drawdown_pct")), -10.0, -2.0)
        + 0.18 * _score_between(row.get(key("win_rate_pct")), 45.0, 68.0)
        + 0.14 * _score_between(row.get(key("trades")), 10.0, 50.0)
        + 0.10 * _score_between(row.get(key("profit_factor")), 1.0, 2.5)
        + 0.10 * _score_between(8.0 - _as_float(row.get("median_adtv_participation_pct"), default=8.0), 0.0, 8.0)
    )


def _candidate_score(row: Mapping[str, Any]) -> float:
    return 0.62 * _utility(row, "validation") + 0.25 * _utility(row, "train") + 0.13 * _score_between(row.get("trades"), 20.0, 160.0)


def first_pass(events: pd.DataFrame, path: pd.DataFrame, filters: Sequence[EventFilter], configs: Sequence[GenericExecutionConfig]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event_filter in filters:
        scoped = _filtered_events(events, event_filter)
        if len(scoped) < 24:
            continue
        split_counts = scoped.get("time_split", pd.Series("", index=scoped.index)).value_counts().to_dict()
        if min(int(split_counts.get(split, 0)) for split in ("train_60", "validation_20", "holdout_20")) < 5:
            continue
        for config in configs:
            summary, _, _ = evaluate_strategy(scoped, path, config)
            rows.append(
                summary
                | {
                    "filter_id": event_filter.filter_id,
                    "filter_description": event_filter.description,
                    "filter_event_count": int(len(scoped)),
                    "strategy_id": f"{event_filter.filter_id}__{config.strategy_id}",
                    "base_strategy_id": config.strategy_id,
                }
            )
    return rows


def select_shortlist(rows: Sequence[Mapping[str, Any]], filters: Sequence[EventFilter], configs: Sequence[GenericExecutionConfig], *, top_n: int) -> tuple[list[tuple[EventFilter, GenericExecutionConfig]], int]:
    filter_by_id = {event_filter.filter_id: event_filter for event_filter in filters}
    config_by_id = {config.strategy_id: config for config in configs}
    candidates = [dict(row) for row in rows]
    passing = [
        row
        for row in candidates
        if _as_int(row.get("validation_trades")) >= 8
        and _as_float(row.get("validation_total_return_pct"), default=-999.0) > 0.0
        and _as_float(row.get("validation_max_drawdown_pct"), default=-999.0) >= -18.0
        and _as_float(row.get("median_adtv_participation_pct"), default=999.0) <= 8.0
    ]
    pool = passing if passing else candidates
    ranked = sorted(pool, key=_candidate_score, reverse=True)
    chosen: list[tuple[EventFilter, GenericExecutionConfig]] = []
    seen: set[tuple[str, str]] = set()
    for row in ranked:
        pair = (str(row.get("filter_id")), str(row.get("base_strategy_id")))
        if pair in seen or pair[0] not in filter_by_id or pair[1] not in config_by_id:
            continue
        chosen.append((filter_by_id[pair[0]], config_by_id[pair[1]]))
        seen.add(pair)
        if len(chosen) >= top_n:
            break
    return chosen, len(passing)


def evaluate_full_candidate(events: pd.DataFrame, path: pd.DataFrame, event_filter: EventFilter, config: GenericExecutionConfig, *, selection_status: str) -> dict[str, Any]:
    scoped = _filtered_events(events, event_filter)
    config = GenericExecutionConfig(**(asdict(config) | {"strategy_id": f"{event_filter.filter_id}__{config.strategy_id}"}))
    summary, trades, _ = evaluate_strategy(scoped, path, config)
    _, _, fixed_folds, fixed_summary = run_walk_forward(scoped, path, [config], config)
    _, cost_stress_summary = run_cost_stress(scoped, path, config)
    _, monte_carlo_summary = run_monte_carlo(trades, config, iterations=300)
    scorecard = score_tradable_setup(
        {"status": selection_status, "selected_metrics": summary},
        fixed_summary,
        cost_stress_summary,
        monte_carlo_summary,
    )
    negative_folds = int((pd.to_numeric(fixed_folds.get("test_total_return_pct"), errors="coerce") < 0).sum()) if not fixed_folds.empty else None
    return {
        "strategy_id": config.strategy_id,
        "filter_id": event_filter.filter_id,
        "filter_description": event_filter.description,
        "filter_event_count": int(len(scoped)),
        "score": scorecard.get("score"),
        "classification": scorecard.get("classification"),
        "promotion_blockers": ",".join(scorecard.get("promotion_blockers") or []),
        "selection_status": selection_status,
        "trades": summary.get("trades"),
        "validation_trades": summary.get("validation_trades"),
        "validation_total_return_pct": summary.get("validation_total_return_pct"),
        "validation_max_drawdown_pct": summary.get("validation_max_drawdown_pct"),
        "holdout_trades": summary.get("holdout_trades"),
        "holdout_total_return_pct": summary.get("holdout_total_return_pct"),
        "holdout_max_drawdown_pct": summary.get("holdout_max_drawdown_pct"),
        "total_return_pct": summary.get("total_return_pct"),
        "max_drawdown_pct": summary.get("max_drawdown_pct"),
        "win_rate_pct": summary.get("win_rate_pct"),
        "profit_factor": summary.get("profit_factor"),
        "median_adtv_participation_pct": summary.get("median_adtv_participation_pct"),
        "walk_forward_positive_fold_rate_pct": fixed_summary.get("positive_fold_rate_pct"),
        "walk_forward_negative_folds": negative_folds,
        "walk_forward_sum_return_pct": fixed_summary.get("sum_fold_return_pct"),
        "walk_forward_worst_fold_return_pct": fixed_summary.get("worst_fold_return_pct"),
        "cost_worst_scenario_return_pct": cost_stress_summary.get("worst_scenario_return_pct"),
        "monte_carlo_prob_positive_pct": monte_carlo_summary.get("prob_positive_pct"),
        "scorecard_component_scores": scorecard.get("component_scores"),
        "selected_config": asdict(config),
    }


def _guard(pattern_id: str, best: Mapping[str, Any]) -> dict[str, Any]:
    scope = _scope_for(pattern_id)
    score = _as_float(best.get("score"))
    blockers = {item.strip() for item in str(best.get("promotion_blockers") or "").split(",") if item.strip()}
    direct_scope = scope in {"long_cash_candidate", "long_up_breakout_branch"}
    remaining = set(blockers)
    if not direct_scope:
        remaining.add("scope_not_direct_long_cash_equity")
    if score < 95.0:
        remaining.add("score_below_95")
    checks = [
        {"check": "score_threshold_95", "status": "fail" if score < 95.0 else "pass", "observed": best.get("score"), "rule": "score must be >= 95"},
        {"check": "direct_long_cash_scope", "status": "fail" if not direct_scope else "pass", "observed": scope, "rule": "must be direct long-cash or explicit long-up branch"},
        {"check": "promotion_blockers_clear", "status": "fail" if blockers else "pass", "observed": ",".join(sorted(blockers)) or "none", "rule": "scorecard blockers must clear"},
        {"check": "fixed_walk_forward_positive", "status": "fail" if _as_float(best.get("walk_forward_positive_fold_rate_pct")) < 100.0 else "pass", "observed": best.get("walk_forward_positive_fold_rate_pct"), "rule": "fixed walk-forward must have no negative fold"},
    ]
    failures = [check["check"] for check in checks if check["status"] == "fail"]
    return {
        "policy_id": NO_OVERLIFT_POLICY_ID,
        "promotion_decision": "ELIGIBLE_FOR_FORMAL_PROMOTION_REVIEW" if not failures else "STOP_NO_PROMOTION_UNDER_NO_OVERLIFT_POLICY",
        "failures": failures,
        "remaining_tradable_blockers": sorted(item for item in remaining if item),
        "checks": checks,
    }


def run_one(pattern_id: str, out_dir: Path, *, shortlist_size: int) -> dict[str, Any]:
    chapter_dir = out_dir / pattern_id
    chapter_dir.mkdir(parents=True, exist_ok=True)
    spec = CHAPTER_SPECS[pattern_id]
    events, path, source_scope = load_chapter_events_and_path(spec)
    filters = build_event_filters(pattern_id)
    configs = build_configs(pattern_id)
    print(
        f"[feature-filter] {pattern_id}: {len(filters)} filters x {len(configs)} representative configs",
        flush=True,
    )
    first_rows = first_pass(events, path, filters, configs)
    print(f"[feature-filter] {pattern_id}: first pass rows={len(first_rows)}", flush=True)
    shortlist, passing_count = select_shortlist(first_rows, filters, configs, top_n=shortlist_size)
    selection_status = "selected_tradable_setup" if passing_count > 0 else "no_strategy_passed_validation_gate"
    full_rows = [
        evaluate_full_candidate(events, path, event_filter, config, selection_status=selection_status)
        for event_filter, config in shortlist
    ]
    print(f"[feature-filter] {pattern_id}: full rows={len(full_rows)}", flush=True)
    full_rows = sorted(full_rows, key=lambda row: _as_float(row.get("score")), reverse=True)
    best = full_rows[0] if full_rows else {}
    payload = {
        "push_id": PUSH_ID,
        "pattern_id": pattern_id,
        "scope": _scope_for(pattern_id),
        "source_scope": source_scope,
        "filter_count": len(filters),
        "config_count": len(configs),
        "first_pass_count": len(first_rows),
        "validation_passing_count": passing_count,
        "shortlist_size": len(shortlist),
        "selection_policy": "feature filters use setup/breakout fields only; train+validation selection, holdout/walk-forward as evidence",
        "best_score": best.get("score"),
        "best_strategy_id": best.get("strategy_id"),
        "no_overlift_guard": _guard(pattern_id, best),
        "rows": full_rows,
        "first_pass_top_rows": sorted(first_rows, key=_candidate_score, reverse=True)[:30],
    }
    paths = {
        "json": chapter_dir / f"{pattern_id}_feature_filter_push.json",
        "csv": chapter_dir / f"{pattern_id}_feature_filter_push.csv",
        "grid": chapter_dir / f"{pattern_id}_feature_filter_grid.csv",
        "md": chapter_dir / f"{pattern_id}_feature_filter_push.md",
    }
    _write_json(paths["json"], payload)
    _write_csv(paths["csv"], full_rows)
    _write_csv(paths["grid"], first_rows)
    paths["md"].write_text(render_pattern_markdown(payload), encoding="utf-8")
    return payload | {"artifact_paths": {key: str(value) for key, value in paths.items()}}


def run_all(*, out_dir: Path = DEFAULT_OUT_DIR, patterns: Sequence[str] = DEFAULT_PATTERNS, shortlist_size: int = 8) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [run_one(pattern_id, out_dir, shortlist_size=shortlist_size) for pattern_id in patterns]
    return write_aggregate(out_dir, rows, shortlist_size=shortlist_size)


def aggregate_existing(*, out_dir: Path = DEFAULT_OUT_DIR, patterns: Sequence[str] = DEFAULT_PATTERNS, shortlist_size: int = 8) -> dict[str, Path]:
    rows: list[dict[str, Any]] = []
    for pattern_id in patterns:
        path = out_dir / pattern_id / f"{pattern_id}_feature_filter_push.json"
        if path.exists():
            rows.append(json.loads(path.read_text(encoding="utf-8")))
    return write_aggregate(out_dir, rows, shortlist_size=shortlist_size)


def write_aggregate(out_dir: Path, rows: Sequence[Mapping[str, Any]], *, shortlist_size: int) -> dict[str, Path]:
    payload = {
        "push_id": PUSH_ID,
        "pattern_count": len(rows),
        "patterns": [str(row.get("pattern_id")) for row in rows],
        "shortlist_size": shortlist_size,
        "rows": list(rows),
    }
    paths = {
        "json": out_dir / "feature_filter_ceiling_push.json",
        "csv": out_dir / "feature_filter_ceiling_push.csv",
        "md": out_dir / "feature_filter_ceiling_push.md",
    }
    _write_json(paths["json"], payload)
    _write_csv(
        paths["csv"],
        [
            {
                "pattern_id": row.get("pattern_id"),
                "scope": row.get("scope"),
                "best_score": row.get("best_score"),
                "best_strategy_id": row.get("best_strategy_id"),
                "decision": (row.get("no_overlift_guard") or {}).get("promotion_decision"),
                "remaining_tradable_blockers": ",".join((row.get("no_overlift_guard") or {}).get("remaining_tradable_blockers") or []),
            }
            for row in rows
        ],
    )
    paths["md"].write_text(render_aggregate_markdown(payload), encoding="utf-8")
    return paths


def render_pattern_markdown(payload: Mapping[str, Any]) -> str:
    guard = payload.get("no_overlift_guard") if isinstance(payload.get("no_overlift_guard"), Mapping) else {}
    lines = [
        f"# {payload.get('pattern_id')} Feature Filter Push",
        "",
        f"Push: `{PUSH_ID}`",
        "",
        f"- Best score: `{payload.get('best_score')}`",
        f"- Best strategy: `{payload.get('best_strategy_id')}`",
        f"- Decision: `{guard.get('promotion_decision')}`",
        f"- Remaining blockers: `{', '.join(guard.get('remaining_tradable_blockers') or [])}`",
        "",
        "| Strategy | Filter | Score | Blockers | Events | Trades | Validation | Holdout | WF positive | WF sum |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload.get("rows") or []:
        lines.append(
            "| {strategy} | {filter_id} | {score:.2f} | {blockers} | {events} | {trades} | {validation} | {holdout} | {wf_pos} | {wf_sum} |".format(
                strategy=row.get("strategy_id"),
                filter_id=row.get("filter_id"),
                score=_as_float(row.get("score")),
                blockers=row.get("promotion_blockers") or "",
                events=row.get("filter_event_count") or "",
                trades=row.get("trades") or "",
                validation=row.get("validation_total_return_pct") or "",
                holdout=row.get("holdout_total_return_pct") or "",
                wf_pos=row.get("walk_forward_positive_fold_rate_pct") or "",
                wf_sum=row.get("walk_forward_sum_return_pct") or "",
            )
        )
    return "\n".join(lines) + "\n"


def render_aggregate_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Feature Filter Ceiling Push",
        "",
        f"Push: `{PUSH_ID}`",
        "",
        "Feature filters are limited to setup and breakout-confirmation fields.",
        "",
        "| Pattern | Scope | Best score | Decision | Remaining blockers |",
        "|---|---|---:|---|---|",
    ]
    for row in payload.get("rows") or []:
        guard = row.get("no_overlift_guard") if isinstance(row.get("no_overlift_guard"), Mapping) else {}
        score = "" if row.get("best_score") is None else f"{_as_float(row.get('best_score')):.2f}"
        lines.append(
            f"| {row.get('pattern_id')} | {row.get('scope')} | {score} | {guard.get('promotion_decision')} | {', '.join(guard.get('remaining_tradable_blockers') or [])} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run feature-filter ceiling push for blocked pattern chapters.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--patterns", default=",".join(DEFAULT_PATTERNS))
    parser.add_argument("--shortlist-size", type=int, default=8)
    parser.add_argument("--aggregate-existing", action="store_true")
    args = parser.parse_args()
    patterns = [item.strip() for item in str(args.patterns).split(",") if item.strip()]
    if args.aggregate_existing:
        paths = aggregate_existing(out_dir=Path(args.out_dir), patterns=patterns, shortlist_size=int(args.shortlist_size))
    else:
        paths = run_all(out_dir=Path(args.out_dir), patterns=patterns, shortlist_size=int(args.shortlist_size))
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
