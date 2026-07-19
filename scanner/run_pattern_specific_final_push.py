"""Final bounded push for the six remaining tradable-blocked chapters.

This is intentionally a small last pass.  It reuses the source-safe branch
rules from the fold-repair pass, adds a few setup/confirmation thresholds, and
evaluates a broader multi-objective shortlist.  It is diagnostic unless it
beats the current best evidence in the governance matrix.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.run_chapter_tradable_layer import CHAPTER_SPECS, GenericExecutionConfig, evaluate_strategy, load_chapter_events_and_path  # noqa: E402
from scanner.run_pattern_specific_fold_repair import (  # noqa: E402
    BranchRule,
    _as_float,
    _branch_events,
    _candidate_score,
    _guard,
    _scope,
    _write_csv,
    _write_json,
    build_branch_rules,
    build_configs,
    evaluate_full_candidate,
)


FINAL_PUSH_ID = "pattern_specific_final_push_v1"
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/pattern_specific_final_push")
DEFAULT_PATTERNS = (
    "triangles_symmetrical",
    "triangles_descending",
    "bear_flags",
    "triangles_ascending",
    "wedges_falling",
    "wedges_rising",
)


def _strategy_key(config: GenericExecutionConfig) -> str:
    return json.dumps(asdict(config), sort_keys=True, default=str)


def _add_config(configs: list[GenericExecutionConfig], seen: set[str], config: GenericExecutionConfig) -> None:
    key = _strategy_key(config)
    if key not in seen:
        seen.add(key)
        configs.append(config)


def build_final_configs(pattern_id: str) -> list[GenericExecutionConfig]:
    configs: list[GenericExecutionConfig] = []
    seen: set[str] = set()
    if pattern_id.startswith("broadening_"):
        direction = ("down",) if pattern_id in {
            "broadening_formations_right_angled_ascending",
            "broadening_tops",
            "broadening_wedges_ascending",
        } else ("up",)
        preferred_regime = ("bull",) if direction == ("down",) else ("bear",)
        for target in (0.50, 0.65):
            for stop in (10.0, 12.0):
                _add_config(
                    configs,
                    seen,
                    GenericExecutionConfig(
                        strategy_id=(
                            f"{pattern_id}__final_{direction[0]}_t{str(target).replace('.', '')}"
                            f"_s{int(stop)}_h40_d1_q0_liqall_regall_p005"
                        ),
                        target_multiple=target,
                        stop_loss_pct=stop,
                        max_holding_days=40,
                        entry_delay_bars=1,
                        allowed_breakout_directions=direction,
                        position_size_pct=0.05,
                        max_positions=15,
                        target_adtv_participation_pct=5.0,
                    ),
                )
            for hold in (40, 60):
                for setup, delay, liquidity, regime, position_size, max_positions, participation in (
                    (None, 1, ("high",), None, 0.05, 15, 5.0),
                    (65.0, 3, ("mid", "high"), preferred_regime, 0.033, 30, 8.0),
                ):
                    suffix = "q0" if setup is None else f"q{int(setup)}"
                    _add_config(
                        configs,
                        seen,
                        GenericExecutionConfig(
                            strategy_id=(
                                f"{pattern_id}__final_{direction[0]}_t{str(target).replace('.', '')}"
                                f"_s10_h{hold}_d{delay}_{suffix}_liq{''.join(liquidity)}"
                                f"_reg{''.join(regime) if regime else 'all'}"
                            ),
                            target_multiple=target,
                            stop_loss_pct=10.0,
                            max_holding_days=hold,
                            entry_delay_bars=delay,
                            min_setup_score=setup,
                            allowed_breakout_directions=direction,
                            allowed_market_regimes=regime,
                            allowed_liquidity_buckets=liquidity,
                            position_size_pct=position_size,
                            max_positions=max_positions,
                            target_adtv_participation_pct=participation,
                        ),
                    )
        return configs
    base_configs = build_configs(pattern_id)
    for config in base_configs:
        _add_config(configs, seen, config)
        if len(configs) <= 24:
            _add_config(configs, seen, replace(config, strategy_id=f"{config.strategy_id}_q60", min_setup_score=60.0))
            _add_config(configs, seen, replace(config, strategy_id=f"{config.strategy_id}_q70", min_setup_score=70.0))
        if pattern_id in {"triangles_ascending", "triangles_symmetrical", "wedges_falling", "wedges_rising"} and len(configs) <= 40:
            _add_config(configs, seen, replace(config, strategy_id=f"{config.strategy_id}_c60", min_confirmation_score=60.0))

    def add(strategy_id: str, **kwargs: Any) -> None:
        _add_config(configs, seen, GenericExecutionConfig(strategy_id=strategy_id, **kwargs))

    if pattern_id == "triangles_symmetrical":
        for setup in (60.0, 70.0):
            add(
                f"{pattern_id}__final_regbull_t10_s7_h60_d3_q{int(setup)}_liqmh_p0033",
                target_multiple=1.00,
                stop_loss_pct=7.0,
                max_holding_days=60,
                entry_delay_bars=3,
                min_setup_score=setup,
                allowed_breakout_directions=("up",),
                allowed_market_regimes=("bull",),
                allowed_liquidity_buckets=("mid", "high"),
                position_size_pct=0.033,
                max_positions=30,
                target_adtv_participation_pct=5.0,
            )
    elif pattern_id == "triangles_descending":
        for stop in (10.0, 12.0):
            add(
                f"{pattern_id}__final_highliq_t075_s{int(stop)}_h20_d1_p0075",
                target_multiple=0.75,
                stop_loss_pct=stop,
                max_holding_days=20,
                entry_delay_bars=1,
                allowed_breakout_directions=("down",),
                allowed_liquidity_buckets=("high",),
                position_size_pct=0.075,
                max_positions=10,
                target_adtv_participation_pct=5.0,
            )
    elif pattern_id == "bear_flags":
        for stop in (10.0, 12.0):
            add(
                f"{pattern_id}__final_highliq_t075_s{int(stop)}_h40_d1_p0075",
                target_multiple=0.75,
                stop_loss_pct=stop,
                max_holding_days=40,
                entry_delay_bars=1,
                allowed_breakout_directions=("down",),
                allowed_liquidity_buckets=("high",),
                position_size_pct=0.075,
                max_positions=10,
                target_adtv_participation_pct=5.0,
            )
    elif pattern_id == "triangles_ascending":
        for target in (0.65, 0.75, 1.00):
            for setup in (None, 60.0, 70.0):
                suffix = "q0" if setup is None else f"q{int(setup)}"
                add(
                    f"{pattern_id}__final_regbear_t{str(target).replace('.', '')}_s7_h60_d3_{suffix}_liqhigh_p010",
                    target_multiple=target,
                    stop_loss_pct=7.0,
                    max_holding_days=60,
                    entry_delay_bars=3,
                    min_setup_score=setup,
                    allowed_breakout_directions=("up",),
                    allowed_market_regimes=("bear",),
                    allowed_liquidity_buckets=("high",),
                    position_size_pct=0.10,
                    max_positions=10,
                    target_adtv_participation_pct=4.0,
                )
    elif pattern_id == "wedges_falling":
        for target in (1.00, 1.25):
            for hold in (60, 80):
                add(
                    f"{pattern_id}__final_regbear_t{str(target).replace('.', '')}_s7_h{hold}_d3_q0_liqmh_p0033",
                    target_multiple=target,
                    stop_loss_pct=7.0,
                    max_holding_days=hold,
                    entry_delay_bars=3,
                    allowed_breakout_directions=("up",),
                    allowed_market_regimes=("bear",),
                    allowed_liquidity_buckets=("mid", "high"),
                    position_size_pct=0.033,
                    max_positions=30,
                    target_adtv_participation_pct=8.0,
                )
    elif pattern_id == "wedges_rising":
        for target in (1.00, 1.25):
            for setup in (None, 60.0):
                suffix = "q0" if setup is None else f"q{int(setup)}"
                add(
                    f"{pattern_id}__final_regbull_t{str(target).replace('.', '')}_s7_h60_d3_{suffix}_liqhigh_p010",
                    target_multiple=target,
                    stop_loss_pct=7.0,
                    max_holding_days=60,
                    entry_delay_bars=3,
                    min_setup_score=setup,
                    allowed_breakout_directions=("down",),
                    allowed_market_regimes=("bull",),
                    allowed_liquidity_buckets=("high",),
                    position_size_pct=0.10,
                    max_positions=10,
                    target_adtv_participation_pct=4.0,
                )
    elif pattern_id == "head_and_shoulders_bottoms_complex":
        for target in (0.50, 0.65, 0.75):
            for setup in (None, 65.0, 75.0):
                suffix = "q0" if setup is None else f"q{int(setup)}"
                add(
                    f"{pattern_id}__final_long_t{str(target).replace('.', '')}_s7_h60_d3_{suffix}_liqmh_p0033",
                    target_multiple=target,
                    stop_loss_pct=7.0,
                    max_holding_days=60,
                    entry_delay_bars=3,
                    min_setup_score=setup,
                    allowed_breakout_directions=("up",),
                    allowed_liquidity_buckets=("mid", "high"),
                    position_size_pct=0.033,
                    max_positions=20,
                    target_adtv_participation_pct=7.5,
                )
                add(
                    f"{pattern_id}__final_long_t{str(target).replace('.', '')}_s10_h80_d3_{suffix}_liqmh_p0033",
                    target_multiple=target,
                    stop_loss_pct=10.0,
                    max_holding_days=80,
                    entry_delay_bars=3,
                    min_setup_score=setup,
                    allowed_breakout_directions=("up",),
                    allowed_liquidity_buckets=("mid", "high"),
                    position_size_pct=0.033,
                    max_positions=20,
                    target_adtv_participation_pct=7.5,
                )
    elif pattern_id == "head_and_shoulders_tops_complex":
        for target in (0.50, 0.65, 0.75):
            for setup in (None, 65.0, 75.0):
                suffix = "q0" if setup is None else f"q{int(setup)}"
                add(
                    f"{pattern_id}__final_exit_t{str(target).replace('.', '')}_s10_h40_d1_{suffix}_liqhigh_p005",
                    target_multiple=target,
                    stop_loss_pct=10.0,
                    max_holding_days=40,
                    entry_delay_bars=1,
                    min_setup_score=setup,
                    allowed_breakout_directions=("down",),
                    allowed_liquidity_buckets=("high",),
                    position_size_pct=0.05,
                    max_positions=12,
                    target_adtv_participation_pct=5.0,
                )
                add(
                    f"{pattern_id}__final_exit_t{str(target).replace('.', '')}_s12_h60_d3_{suffix}_liqmh_p0033",
                    target_multiple=target,
                    stop_loss_pct=12.0,
                    max_holding_days=60,
                    entry_delay_bars=3,
                    min_setup_score=setup,
                    allowed_breakout_directions=("down",),
                    allowed_liquidity_buckets=("mid", "high"),
                    position_size_pct=0.033,
                    max_positions=20,
                    target_adtv_participation_pct=7.5,
                )
    return configs


def first_pass(events: pd.DataFrame, path: pd.DataFrame, branches: Sequence[BranchRule], configs: Sequence[GenericExecutionConfig]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for branch in branches:
        scoped = _branch_events(events, branch)
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
                    "branch_id": branch.branch_id,
                    "branch_description": branch.description,
                    "branch_event_count": int(len(scoped)),
                    "strategy_id": f"{branch.branch_id}__{config.strategy_id}",
                    "base_strategy_id": config.strategy_id,
                }
            )
    return rows


def _rank_value(row: Mapping[str, Any], name: str) -> float:
    return _as_float(row.get(name), default=-999.0)


def _select_ranked(rows: Sequence[Mapping[str, Any]], key: Callable[[Mapping[str, Any]], float], limit: int) -> list[dict[str, Any]]:
    return [dict(row) for row in sorted(rows, key=key, reverse=True)[:limit]]


def select_shortlist(
    rows: Sequence[Mapping[str, Any]],
    branches: Sequence[BranchRule],
    configs: Sequence[GenericExecutionConfig],
    *,
    top_n: int,
) -> tuple[list[tuple[BranchRule, GenericExecutionConfig]], int]:
    branch_by_id = {branch.branch_id: branch for branch in branches}
    config_by_id = {config.strategy_id: config for config in configs}
    candidates = [dict(row) for row in rows]
    passing = [
        row
        for row in candidates
        if int(row.get("validation_trades") or 0) >= 8
        and int(row.get("holdout_trades") or 0) >= 5
        and _rank_value(row, "validation_total_return_pct") > 0.0
        and _rank_value(row, "holdout_total_return_pct") > -1.0
        and _rank_value(row, "median_adtv_participation_pct") <= 8.0
    ]
    pool = passing if passing else candidates
    ranked: list[dict[str, Any]] = []
    ranked.extend(_select_ranked(pool, _candidate_score, 10))
    ranked.extend(_select_ranked(pool, lambda row: _rank_value(row, "validation_total_return_pct") + _rank_value(row, "holdout_total_return_pct"), 10))
    ranked.extend(_select_ranked(pool, lambda row: _rank_value(row, "holdout_total_return_pct"), 8))
    ranked.extend(_select_ranked(pool, lambda row: _rank_value(row, "validation_profit_factor") + _rank_value(row, "holdout_profit_factor"), 8))
    ranked.extend(_select_ranked(pool, lambda row: _rank_value(row, "branch_event_count") - 3.0 * _rank_value(row, "median_adtv_participation_pct"), 8))

    chosen: list[tuple[BranchRule, GenericExecutionConfig]] = []
    seen: set[tuple[str, str]] = set()
    for row in ranked:
        pair = (str(row.get("branch_id")), str(row.get("base_strategy_id")))
        if pair in seen or pair[0] not in branch_by_id or pair[1] not in config_by_id:
            continue
        chosen.append((branch_by_id[pair[0]], config_by_id[pair[1]]))
        seen.add(pair)
        if len(chosen) >= top_n:
            break
    return chosen, len(passing)


def run_one(pattern_id: str, out_dir: Path, *, shortlist_size: int) -> dict[str, Any]:
    chapter_dir = out_dir / pattern_id
    chapter_dir.mkdir(parents=True, exist_ok=True)
    spec = CHAPTER_SPECS[pattern_id]
    events, path, source_scope = load_chapter_events_and_path(spec)
    branches = build_branch_rules(pattern_id)
    configs = build_final_configs(pattern_id)
    print(f"[final-push] {pattern_id}: {len(branches)} branches x {len(configs)} configs", flush=True)
    first_rows = first_pass(events, path, branches, configs)
    print(f"[final-push] {pattern_id}: first pass rows={len(first_rows)}", flush=True)
    shortlist, passing_count = select_shortlist(first_rows, branches, configs, top_n=shortlist_size)
    selection_status = "selected_tradable_setup" if passing_count > 0 else "no_strategy_passed_validation_gate"
    rows = [
        evaluate_full_candidate(events, path, branch, config, selection_status=selection_status)
        for branch, config in shortlist
    ]
    rows = sorted(rows, key=lambda row: _as_float(row.get("score")), reverse=True)
    print(f"[final-push] {pattern_id}: full rows={len(rows)}", flush=True)
    best = rows[0] if rows else {}
    payload = {
        "final_push_id": FINAL_PUSH_ID,
        "pattern_id": pattern_id,
        "scope": _scope(pattern_id),
        "source_scope": source_scope,
        "source_safe_selector_note": "final-push branches use morphology, setup/confirmation, liquidity, regime, and breakout-confirmation fields only; no outcome labels are branch selectors",
        "branch_count": len(branches),
        "config_count": len(configs),
        "first_pass_count": len(first_rows),
        "validation_passing_count": passing_count,
        "shortlist_size": len(shortlist),
        "best_score": best.get("score"),
        "best_strategy_id": best.get("strategy_id"),
        "no_overlift_guard": _guard(pattern_id, best),
        "rows": rows,
        "first_pass_top_rows": sorted(first_rows, key=_candidate_score, reverse=True)[:30],
    }
    paths = {
        "json": chapter_dir / f"{pattern_id}_final_push.json",
        "csv": chapter_dir / f"{pattern_id}_final_push.csv",
        "grid": chapter_dir / f"{pattern_id}_final_push_grid.csv",
        "md": chapter_dir / f"{pattern_id}_final_push.md",
    }
    _write_json(paths["json"], payload)
    _write_csv(paths["csv"], rows)
    _write_csv(paths["grid"], first_rows)
    paths["md"].write_text(render_pattern_markdown(payload), encoding="utf-8")
    return payload | {"artifact_paths": {key: str(value) for key, value in paths.items()}}


def render_pattern_markdown(payload: Mapping[str, Any]) -> str:
    guard = payload.get("no_overlift_guard") if isinstance(payload.get("no_overlift_guard"), Mapping) else {}
    lines = [
        f"# {payload.get('pattern_id')} Pattern-Specific Final Push",
        "",
        f"Final push: `{FINAL_PUSH_ID}`",
        "",
        f"- Best score: `{payload.get('best_score')}`",
        f"- Best strategy: `{payload.get('best_strategy_id')}`",
        f"- Decision: `{guard.get('promotion_decision')}`",
        f"- Remaining blockers: `{', '.join(guard.get('remaining_tradable_blockers') or [])}`",
        "",
        "| Strategy | Branch | Score | Blockers | Events | Trades | Validation | Holdout | WF positive | WF sum |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload.get("rows") or []:
        lines.append(
            "| {strategy} | {branch} | {score:.2f} | {blockers} | {events} | {trades} | {validation} | {holdout} | {wf_pos} | {wf_sum} |".format(
                strategy=row.get("strategy_id"),
                branch=row.get("branch_id"),
                score=_as_float(row.get("score")),
                blockers=row.get("promotion_blockers") or "",
                events=row.get("branch_event_count") or "",
                trades=row.get("trades") or "",
                validation=row.get("validation_total_return_pct") or "",
                holdout=row.get("holdout_total_return_pct") or "",
                wf_pos=row.get("walk_forward_positive_fold_rate_pct") or "",
                wf_sum=row.get("walk_forward_sum_return_pct") or "",
            )
        )
    return "\n".join(lines) + "\n"


def write_aggregate(out_dir: Path, rows: Sequence[Mapping[str, Any]], *, shortlist_size: int) -> dict[str, Path]:
    payload = {
        "final_push_id": FINAL_PUSH_ID,
        "pattern_count": len(rows),
        "patterns": [str(row.get("pattern_id")) for row in rows],
        "shortlist_size": shortlist_size,
        "rows": list(rows),
    }
    paths = {
        "json": out_dir / "pattern_specific_final_push.json",
        "csv": out_dir / "pattern_specific_final_push.csv",
        "md": out_dir / "pattern_specific_final_push.md",
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
    lines = [
        "# Pattern-Specific Final Push",
        "",
        f"Final push: `{FINAL_PUSH_ID}`",
        "",
        "| Pattern | Scope | Best score | Decision | Remaining blockers |",
        "|---|---|---:|---|---|",
    ]
    for row in rows:
        guard = row.get("no_overlift_guard") if isinstance(row.get("no_overlift_guard"), Mapping) else {}
        score = "" if row.get("best_score") is None else f"{_as_float(row.get('best_score')):.2f}"
        lines.append(
            f"| {row.get('pattern_id')} | {row.get('scope')} | {score} | {guard.get('promotion_decision')} | {', '.join(guard.get('remaining_tradable_blockers') or [])} |"
        )
    paths["md"].write_text("\n".join(lines) + "\n", encoding="utf-8")
    return paths


def run_all(*, out_dir: Path, patterns: Sequence[str], shortlist_size: int) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [run_one(pattern_id, out_dir, shortlist_size=shortlist_size) for pattern_id in patterns]
    return write_aggregate(out_dir, rows, shortlist_size=shortlist_size)


def aggregate_existing(*, out_dir: Path, patterns: Sequence[str], shortlist_size: int) -> dict[str, Path]:
    rows: list[dict[str, Any]] = []
    for pattern_id in patterns:
        path = out_dir / pattern_id / f"{pattern_id}_final_push.json"
        if path.exists():
            rows.append(json.loads(path.read_text(encoding="utf-8")))
    return write_aggregate(out_dir, rows, shortlist_size=shortlist_size)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the final bounded pattern-specific push.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--patterns", default=",".join(DEFAULT_PATTERNS))
    parser.add_argument("--shortlist-size", type=int, default=14)
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
