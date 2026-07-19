"""Targeted tradable-ceiling push for selected blocked chapters.

The goal is to push the remaining researchable patterns as far as the current
available series allows without weakening the Bull Flag-style release contract.

Selection rule:
- scan a bounded, deterministic branch grid;
- choose candidates using train + validation only;
- report holdout, fixed walk-forward, cost stress, and Monte Carlo as evidence;
- never promote to tradable-final unless score >= 95, scope is direct
  long-cash/explicit long-up, and all scorecard blockers clear.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

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


PUSH_ID = "targeted_pattern_ceiling_push_v1"
NO_OVERLIFT_POLICY_ID = "targeted_ceiling_no_overlift_guard_v1"
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/targeted_pattern_ceiling_push")
DEFAULT_PATTERNS = (
    "triangles_symmetrical",
    "triangles_descending",
    "bear_flags",
    "triangles_ascending",
    "wedges_falling",
    "wedges_rising",
)


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
    if "flag" in pattern_id:
        return (0.35, 0.46, 0.50, 0.75, 1.00)
    if "wedge" in pattern_id:
        return (0.35, 0.50, 0.65, 0.75, 1.00)
    return (0.35, 0.50, 0.65, 0.75, 1.00)


def build_grid(pattern_id: str, *, max_configs: int) -> list[GenericExecutionConfig]:
    direction = _direction_for(pattern_id)
    configs: list[GenericExecutionConfig] = []

    for target in _target_family(pattern_id):
        for stop in (5.0, 7.0, 10.0, 12.0):
            for hold in (20, 40, 60):
                for delay in (1, 3):
                    configs.append(
                        GenericExecutionConfig(
                            strategy_id=(
                                f"{pattern_id}__push_base_t{str(target).replace('.', '')}"
                                f"_s{int(stop)}_h{hold}_d{delay}_q0_c0_liqall_p005"
                            ),
                            target_multiple=target,
                            stop_loss_pct=stop,
                            max_holding_days=hold,
                            entry_delay_bars=delay,
                            allowed_breakout_directions=direction,
                            position_size_pct=0.05,
                            max_positions=20,
                        )
                    )

    for target in _target_family(pattern_id):
        for stop in (7.0, 10.0):
            for hold in (40, 60):
                for setup in (60.0, 70.0, 80.0):
                    for confirm in (None, 65.0, 75.0):
                        for liquidity in (("mid", "high"), ("high",)):
                            liquidity_label = "mh" if liquidity == ("mid", "high") else "high"
                            configs.append(
                                GenericExecutionConfig(
                                    strategy_id=(
                                        f"{pattern_id}__push_quality_t{str(target).replace('.', '')}"
                                        f"_s{int(stop)}_h{hold}_d1_q{int(setup)}_c{int(confirm or 0)}"
                                        f"_liq{liquidity_label}_p0033"
                                    ),
                                    target_multiple=target,
                                    stop_loss_pct=stop,
                                    max_holding_days=hold,
                                    entry_delay_bars=1,
                                    min_setup_score=setup,
                                    min_confirmation_score=confirm,
                                    allowed_breakout_directions=direction,
                                    allowed_liquidity_buckets=liquidity,
                                    position_size_pct=0.033,
                                    max_positions=30,
                                    target_adtv_participation_pct=5.0,
                                )
                            )

    for target in _target_family(pattern_id):
        for regime in (("bull",), ("bear",), ("unknown",)):
            for hold in (20, 60):
                for position_size in (0.033, 0.05):
                    configs.append(
                        GenericExecutionConfig(
                            strategy_id=(
                                f"{pattern_id}__push_reg{regime[0]}_t{str(target).replace('.', '')}"
                                f"_s7_h{hold}_d3_q60_c0_liqmh_p{str(position_size).replace('.', '')}"
                            ),
                            target_multiple=target,
                            stop_loss_pct=7.0,
                            max_holding_days=hold,
                            entry_delay_bars=3,
                            min_setup_score=60.0,
                            allowed_breakout_directions=direction,
                            allowed_liquidity_buckets=("mid", "high"),
                            allowed_market_regimes=regime,
                            position_size_pct=position_size,
                            max_positions=30,
                            target_adtv_participation_pct=5.0,
                        )
                    )

    # Deterministic cap: preserve base coverage and keep contextual branches.
    if len(configs) <= max_configs:
        return configs
    head = configs[: max_configs // 2]
    tail = configs[-(max_configs - len(head)) :]
    return head + tail


def _utility(row: Mapping[str, Any], prefix: str) -> float:
    key = lambda name: f"{prefix}_{name}"
    return (
        0.28 * _score_between(row.get(key("total_return_pct")), 0.0, 8.0)
        + 0.18 * _score_between(row.get(key("max_drawdown_pct")), -10.0, -2.0)
        + 0.18 * _score_between(row.get(key("win_rate_pct")), 45.0, 68.0)
        + 0.14 * _score_between(row.get(key("trades")), 10.0, 50.0)
        + 0.12 * _score_between(row.get(key("profit_factor")), 1.0, 2.5)
        + 0.10 * _score_between(8.0 - _as_float(row.get("median_adtv_participation_pct"), default=8.0), 0.0, 8.0)
    )


def _all_utility(row: Mapping[str, Any]) -> float:
    return (
        0.25 * _score_between(row.get("total_return_pct"), 0.0, 15.0)
        + 0.20 * _score_between(row.get("max_drawdown_pct"), -12.0, -2.0)
        + 0.20 * _score_between(row.get("win_rate_pct"), 45.0, 68.0)
        + 0.15 * _score_between(row.get("profit_factor"), 1.0, 2.5)
        + 0.10 * _score_between(row.get("trades"), 20.0, 120.0)
        + 0.10 * _score_between(8.0 - _as_float(row.get("median_adtv_participation_pct"), default=8.0), 0.0, 8.0)
    )


def select_shortlist(rows: Sequence[Mapping[str, Any]], configs: Sequence[GenericExecutionConfig], *, top_n: int) -> tuple[list[GenericExecutionConfig], int]:
    config_by_id = {config.strategy_id: config for config in configs}
    candidates = [dict(row) for row in rows]
    passing = [
        row
        for row in candidates
        if _as_int(row.get("validation_trades")) >= 10
        and _as_float(row.get("validation_total_return_pct"), default=-999.0) > 0.0
        and _as_float(row.get("validation_max_drawdown_pct"), default=-999.0) >= -18.0
        and _as_float(row.get("median_adtv_participation_pct"), default=999.0) <= 8.0
    ]
    pool = passing if passing else candidates
    ranked = sorted(
        pool,
        key=lambda row: (
            0.58 * _utility(row, "validation")
            + 0.27 * _utility(row, "train")
            + 0.15 * _all_utility(row)
        ),
        reverse=True,
    )
    chosen: list[GenericExecutionConfig] = []
    seen: set[str] = set()
    for row in ranked:
        strategy_id = str(row.get("strategy_id") or "")
        config = config_by_id.get(strategy_id)
        if config is None or strategy_id in seen:
            continue
        chosen.append(config)
        seen.add(strategy_id)
        if len(chosen) >= top_n:
            break
    return chosen, len(passing)


def evaluate_full_candidate(events: pd.DataFrame, path: pd.DataFrame, config: GenericExecutionConfig, *, selection_status: str) -> dict[str, Any]:
    summary, trades, _ = evaluate_strategy(events, path, config)
    _, _, fixed_folds, fixed_summary = run_walk_forward(events, path, [config], config)
    _, cost_stress_summary = run_cost_stress(events, path, config)
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
        "walk_forward_worst_fold_drawdown_pct": fixed_summary.get("worst_fold_drawdown_pct"),
        "cost_worst_scenario_return_pct": cost_stress_summary.get("worst_scenario_return_pct"),
        "monte_carlo_prob_positive_pct": monte_carlo_summary.get("prob_positive_pct"),
        "scorecard_component_scores": scorecard.get("component_scores"),
        "selected_config": asdict(config),
    }


def _guard(pattern_id: str, best: Mapping[str, Any]) -> dict[str, Any]:
    scope = _scope_for(pattern_id)
    score = _as_float(best.get("score"))
    blockers = {item.strip() for item in str(best.get("promotion_blockers") or "").split(",") if item.strip()}
    remaining = set(blockers)
    if scope == "defensive_informational":
        remaining.add("scope_not_direct_long_cash_equity")
    if scope not in {"long_cash_candidate", "long_up_breakout_branch"}:
        direct_scope = False
    else:
        direct_scope = True
    if score < 95.0:
        remaining.add("score_below_95")
    checks = [
        {
            "check": "score_threshold_95",
            "status": "fail" if score < 95.0 else "pass",
            "observed": best.get("score"),
            "rule": "tradable-final review requires score >= 95",
        },
        {
            "check": "direct_long_cash_scope",
            "status": "fail" if not direct_scope else "pass",
            "observed": scope,
            "rule": "tradable-final is allowed only for direct long-cash or explicit long-up branch scope",
        },
        {
            "check": "promotion_blockers_clear",
            "status": "fail" if blockers else "pass",
            "observed": ",".join(sorted(blockers)) or "none",
            "rule": "scorecard blockers must be empty",
        },
        {
            "check": "fixed_walk_forward_positive",
            "status": "fail" if _as_float(best.get("walk_forward_positive_fold_rate_pct")) < 100.0 else "pass",
            "observed": best.get("walk_forward_positive_fold_rate_pct"),
            "rule": "fixed walk-forward must have no negative fold",
        },
    ]
    failures = [item["check"] for item in checks if item["status"] == "fail"]
    return {
        "policy_id": NO_OVERLIFT_POLICY_ID,
        "promotion_decision": "ELIGIBLE_FOR_FORMAL_PROMOTION_REVIEW" if not failures else "STOP_NO_PROMOTION_UNDER_NO_OVERLIFT_POLICY",
        "failures": failures,
        "remaining_tradable_blockers": sorted(item for item in remaining if item),
        "checks": checks,
    }


def run_one(pattern_id: str, out_dir: Path, *, max_configs: int, shortlist_size: int) -> dict[str, Any]:
    chapter_dir = out_dir / pattern_id
    chapter_dir.mkdir(parents=True, exist_ok=True)
    spec = CHAPTER_SPECS[pattern_id]
    events, path, source_scope = load_chapter_events_and_path(spec)
    configs = build_grid(pattern_id, max_configs=max_configs)
    first_pass_rows = [evaluate_strategy(events, path, config)[0] for config in configs]
    shortlist, passing_count = select_shortlist(first_pass_rows, configs, top_n=shortlist_size)
    selection_status = "selected_tradable_setup" if passing_count > 0 else "no_strategy_passed_validation_gate"
    full_rows = [
        evaluate_full_candidate(events, path, config, selection_status=selection_status)
        for config in shortlist
    ]
    full_rows = sorted(full_rows, key=lambda row: _as_float(row.get("score")), reverse=True)
    best = full_rows[0] if full_rows else {}
    payload = {
        "push_id": PUSH_ID,
        "pattern_id": pattern_id,
        "scope": _scope_for(pattern_id),
        "source_scope": source_scope,
        "grid_count": len(configs),
        "validation_passing_count": passing_count,
        "shortlist_size": len(shortlist),
        "selection_policy": "train+validation only; holdout, fixed walk-forward, cost stress, and Monte Carlo are evidence, not selection inputs",
        "best_score": best.get("score"),
        "best_strategy_id": best.get("strategy_id"),
        "no_overlift_guard": _guard(pattern_id, best),
        "rows": full_rows,
        "first_pass_top_rows": sorted(
            first_pass_rows,
            key=lambda row: 0.58 * _utility(row, "validation") + 0.27 * _utility(row, "train") + 0.15 * _all_utility(row),
            reverse=True,
        )[:25],
    }
    paths = {
        "json": chapter_dir / f"{pattern_id}_targeted_ceiling_push.json",
        "csv": chapter_dir / f"{pattern_id}_targeted_ceiling_push.csv",
        "md": chapter_dir / f"{pattern_id}_targeted_ceiling_push.md",
        "grid": chapter_dir / f"{pattern_id}_targeted_ceiling_grid.csv",
    }
    _write_json(paths["json"], payload)
    _write_csv(paths["csv"], full_rows)
    _write_csv(paths["grid"], first_pass_rows)
    paths["md"].write_text(render_pattern_markdown(payload), encoding="utf-8")
    return payload | {"artifact_paths": {key: str(value) for key, value in paths.items()}}


def run_all(
    *,
    out_dir: Path = DEFAULT_OUT_DIR,
    patterns: Sequence[str] = DEFAULT_PATTERNS,
    max_configs: int = 220,
    shortlist_size: int = 8,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        run_one(pattern_id, out_dir, max_configs=max_configs, shortlist_size=shortlist_size)
        for pattern_id in patterns
    ]
    payload = {
        "push_id": PUSH_ID,
        "pattern_count": len(rows),
        "patterns": list(patterns),
        "max_configs": max_configs,
        "shortlist_size": shortlist_size,
        "rows": rows,
    }
    paths = {
        "json": out_dir / "targeted_pattern_ceiling_push.json",
        "csv": out_dir / "targeted_pattern_ceiling_push.csv",
        "md": out_dir / "targeted_pattern_ceiling_push.md",
    }
    _write_json(paths["json"], payload)
    summary_rows = [
        {
            "pattern_id": row.get("pattern_id"),
            "scope": row.get("scope"),
            "best_score": row.get("best_score"),
            "best_strategy_id": row.get("best_strategy_id"),
            "decision": (row.get("no_overlift_guard") or {}).get("promotion_decision"),
            "remaining_tradable_blockers": ",".join((row.get("no_overlift_guard") or {}).get("remaining_tradable_blockers") or []),
        }
        for row in rows
    ]
    _write_csv(paths["csv"], summary_rows)
    paths["md"].write_text(render_aggregate_markdown(payload), encoding="utf-8")
    return paths


def aggregate_existing(
    *,
    out_dir: Path = DEFAULT_OUT_DIR,
    patterns: Sequence[str] = DEFAULT_PATTERNS,
    max_configs: int = 220,
    shortlist_size: int = 8,
) -> dict[str, Path]:
    rows: list[dict[str, Any]] = []
    for pattern_id in patterns:
        path = out_dir / pattern_id / f"{pattern_id}_targeted_ceiling_push.json"
        if path.exists():
            rows.append(json.loads(path.read_text(encoding="utf-8")))
    payload = {
        "push_id": PUSH_ID,
        "pattern_count": len(rows),
        "patterns": [str(row.get("pattern_id")) for row in rows],
        "max_configs": max_configs,
        "shortlist_size": shortlist_size,
        "rows": rows,
    }
    paths = {
        "json": out_dir / "targeted_pattern_ceiling_push.json",
        "csv": out_dir / "targeted_pattern_ceiling_push.csv",
        "md": out_dir / "targeted_pattern_ceiling_push.md",
    }
    _write_json(paths["json"], payload)
    summary_rows = [
        {
            "pattern_id": row.get("pattern_id"),
            "scope": row.get("scope"),
            "best_score": row.get("best_score"),
            "best_strategy_id": row.get("best_strategy_id"),
            "decision": (row.get("no_overlift_guard") or {}).get("promotion_decision"),
            "remaining_tradable_blockers": ",".join((row.get("no_overlift_guard") or {}).get("remaining_tradable_blockers") or []),
        }
        for row in rows
    ]
    _write_csv(paths["csv"], summary_rows)
    paths["md"].write_text(render_aggregate_markdown(payload), encoding="utf-8")
    return paths


def render_pattern_markdown(payload: Mapping[str, Any]) -> str:
    guard = payload.get("no_overlift_guard") if isinstance(payload.get("no_overlift_guard"), Mapping) else {}
    lines = [
        f"# {payload.get('pattern_id')} Targeted Ceiling Push",
        "",
        f"Push: `{PUSH_ID}`",
        "",
        f"- Best score: `{payload.get('best_score')}`",
        f"- Best strategy: `{payload.get('best_strategy_id')}`",
        f"- Decision: `{guard.get('promotion_decision')}`",
        f"- Remaining blockers: `{', '.join(guard.get('remaining_tradable_blockers') or [])}`",
        "",
        "| Strategy | Score | Blockers | Trades | Validation | Holdout | WF positive | WF sum | WF worst | ADTV |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload.get("rows") or []:
        lines.append(
            "| {strategy} | {score:.2f} | {blockers} | {trades} | {validation} | {holdout} | {wf_pos} | {wf_sum} | {wf_worst} | {adtv} |".format(
                strategy=row.get("strategy_id"),
                score=_as_float(row.get("score")),
                blockers=row.get("promotion_blockers") or "",
                trades=row.get("trades") or "",
                validation=row.get("validation_total_return_pct") or "",
                holdout=row.get("holdout_total_return_pct") or "",
                wf_pos=row.get("walk_forward_positive_fold_rate_pct") or "",
                wf_sum=row.get("walk_forward_sum_return_pct") or "",
                wf_worst=row.get("walk_forward_worst_fold_return_pct") or "",
                adtv=row.get("median_adtv_participation_pct") or "",
            )
        )
    return "\n".join(lines) + "\n"


def render_aggregate_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Targeted Pattern Ceiling Push",
        "",
        f"Push: `{PUSH_ID}`",
        "",
        "This artifact pushes blocked patterns toward the tradable gate without weakening release rules.",
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
    parser = argparse.ArgumentParser(description="Run targeted ceiling push for blocked pattern chapters.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--patterns", default=",".join(DEFAULT_PATTERNS))
    parser.add_argument("--max-configs", type=int, default=220)
    parser.add_argument("--shortlist-size", type=int, default=8)
    parser.add_argument("--aggregate-existing", action="store_true")
    args = parser.parse_args()
    patterns = [item.strip() for item in str(args.patterns).split(",") if item.strip()]
    if args.aggregate_existing:
        paths = aggregate_existing(
            out_dir=Path(args.out_dir),
            patterns=patterns,
            max_configs=int(args.max_configs),
            shortlist_size=int(args.shortlist_size),
        )
    else:
        paths = run_all(
            out_dir=Path(args.out_dir),
            patterns=patterns,
            max_configs=int(args.max_configs),
            shortlist_size=int(args.shortlist_size),
        )
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
