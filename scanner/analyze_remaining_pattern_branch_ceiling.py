"""Diagnostic ceiling audit for remaining blocked tradable chapters.

This audit is intentionally not a final-promotion optimizer. It is used to
answer a narrower question: after the existing generic/branch layers, do any
blocked chapters have a cleaner deterministic branch worth upgrading to a
defensive/watchlist evidence label under the available-series scope?

Because this is a ceiling audit, the shortlist may inspect validation/holdout
summaries. That makes the output diagnostic evidence, not a tradable-final
release candidate. Promotion to 95+ still has to come from a pre-registered
specialized layer.
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


AUDIT_ID = "remaining_pattern_branch_ceiling_audit_v1"
NO_OVERLIFT_POLICY_ID = "diagnostic_branch_ceiling_no_overlift_v1"
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/remaining_pattern_branch_ceiling_audit")
DEFAULT_PATTERNS = (
    "bear_flags",
    "triangles_descending",
    "triangles_symmetrical",
    "double_tops_adam_eve",
    "double_tops_eve_adam",
    "double_tops_eve_eve",
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


def _score_between(value: Any, low: float, high: float) -> float:
    numeric = _as_float(value, default=low)
    if high == low:
        return 100.0 if numeric >= high else 0.0
    return max(0.0, min(100.0, (numeric - low) / (high - low) * 100.0))


def _direction_for(pattern_id: str) -> tuple[str, ...]:
    if pattern_id == "triangles_symmetrical":
        return ("up",)
    if pattern_id in {
        "bear_flags",
        "triangles_descending",
        "double_tops_adam_eve",
        "double_tops_eve_adam",
        "double_tops_eve_eve",
        "wedges_rising",
    }:
        return ("down",)
    return ("up",)


def _scope_for(pattern_id: str) -> str:
    if pattern_id == "triangles_symmetrical":
        return "long_up_breakout_branch_diagnostic"
    if _direction_for(pattern_id) == ("down",):
        return "defensive_informational"
    return "long_cash_candidate"


def build_configs(pattern_id: str) -> list[GenericExecutionConfig]:
    configs: list[GenericExecutionConfig] = []
    direction = _direction_for(pattern_id)
    liquidity_options: tuple[tuple[str, ...] | None, ...] = (None, ("mid", "high"), ("high",))
    setup_options: tuple[float | None, ...] = (None, 60.0, 70.0)
    for target in (0.35, 0.50, 0.75):
        for hold in (20, 40, 60):
            for setup in setup_options:
                for liquidity in liquidity_options:
                    liquidity_label = "all" if liquidity is None else "".join(liquidity)
                    position_size = 0.033 if liquidity is None else 0.075
                    configs.append(
                        GenericExecutionConfig(
                            strategy_id=(
                                f"{pattern_id}__diag_t{str(target).replace('.', '')}_s10_h{hold}_d1"
                                f"_q{int(setup or 0)}_liq{liquidity_label}_p{str(position_size).replace('.', '')}"
                            ),
                            target_multiple=target,
                            stop_loss_pct=10.0,
                            max_holding_days=hold,
                            entry_delay_bars=1,
                            min_setup_score=setup,
                            allowed_breakout_directions=direction,
                            allowed_liquidity_buckets=liquidity,
                            position_size_pct=position_size,
                            max_positions=10 if position_size >= 0.075 else 30,
                            max_adtv_participation_pct=30.0,
                            target_adtv_participation_pct=5.0,
                        )
                    )
    for target in (0.35, 0.50):
        for hold in (20, 40):
            for regime in (("bull",), ("bear",)):
                configs.append(
                    GenericExecutionConfig(
                        strategy_id=(
                            f"{pattern_id}__diag_reg{regime[0]}_t{str(target).replace('.', '')}"
                            f"_s7_h{hold}_d3_q60_liqmh_p0033"
                        ),
                        target_multiple=target,
                        stop_loss_pct=7.0,
                        max_holding_days=hold,
                        entry_delay_bars=3,
                        min_setup_score=60.0,
                        allowed_breakout_directions=direction,
                        allowed_liquidity_buckets=("mid", "high"),
                        allowed_market_regimes=regime,
                        position_size_pct=0.033,
                        max_positions=30,
                        max_adtv_participation_pct=30.0,
                        target_adtv_participation_pct=5.0,
                    )
                )
    return configs


def _diagnostic_utility(row: Mapping[str, Any]) -> float:
    return (
        0.24 * _score_between(row.get("validation_total_return_pct"), 0.0, 6.0)
        + 0.20 * _score_between(row.get("holdout_total_return_pct"), 0.0, 6.0)
        + 0.16 * _score_between(row.get("validation_trades"), 8.0, 25.0)
        + 0.12 * _score_between(row.get("holdout_trades"), 8.0, 20.0)
        + 0.12 * _score_between(row.get("win_rate_pct"), 45.0, 68.0)
        + 0.10 * _score_between(row.get("profit_factor"), 1.0, 2.4)
        + 0.06 * _score_between(8.0 - _as_float(row.get("median_adtv_participation_pct"), default=8.0), 0.0, 8.0)
    )


def shortlist_configs(rows: Sequence[Mapping[str, Any]], configs: Sequence[GenericExecutionConfig], limit: int) -> list[GenericExecutionConfig]:
    by_id = {config.strategy_id: config for config in configs}
    ranked = sorted(
        (dict(row) | {"diagnostic_utility": _diagnostic_utility(row)} for row in rows),
        key=lambda item: (
            _as_float(item.get("diagnostic_utility")),
            _as_float(item.get("validation_total_return_pct")),
            _as_float(item.get("holdout_total_return_pct")),
        ),
        reverse=True,
    )
    chosen: list[GenericExecutionConfig] = []
    seen: set[str] = set()
    for row in ranked:
        strategy_id = str(row.get("strategy_id") or "")
        config = by_id.get(strategy_id)
        if config is None or strategy_id in seen:
            continue
        chosen.append(config)
        seen.add(strategy_id)
        if len(chosen) >= limit:
            break
    return chosen


def evaluate_full_candidate(events: pd.DataFrame, path: pd.DataFrame, config: GenericExecutionConfig) -> dict[str, Any]:
    summary, trades, _ = evaluate_strategy(events, path, config)
    _, _, fixed_folds, fixed_summary = run_walk_forward(events, path, [config], config)
    _, cost_stress_summary = run_cost_stress(events, path, config)
    _, monte_carlo_summary = run_monte_carlo(trades, config, iterations=300)
    scorecard = score_tradable_setup(
        {"status": "selected_tradable_setup", "selected_metrics": summary},
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
        "trades": summary.get("trades"),
        "validation_trades": summary.get("validation_trades"),
        "validation_total_return_pct": summary.get("validation_total_return_pct"),
        "holdout_trades": summary.get("holdout_trades"),
        "holdout_total_return_pct": summary.get("holdout_total_return_pct"),
        "total_return_pct": summary.get("total_return_pct"),
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
    score = _as_float(best.get("score"))
    blockers = {item.strip() for item in str(best.get("promotion_blockers") or "").split(",") if item.strip()}
    fixed_positive = _as_float(best.get("walk_forward_positive_fold_rate_pct"))
    scope = _scope_for(pattern_id)
    checks = [
        {
            "check": "diagnostic_score_90",
            "status": "fail" if score < 90.0 else "pass",
            "observed": best.get("score"),
            "rule": "diagnostic evidence upgrade requires score >= 90",
        },
        {
            "check": "fixed_walk_forward_positive",
            "status": "fail" if fixed_positive < 100.0 else "pass",
            "observed": best.get("walk_forward_positive_fold_rate_pct"),
            "rule": "strong diagnostic upgrade requires no negative fixed walk-forward fold",
        },
        {
            "check": "diagnostic_not_final_promotion",
            "status": "pass",
            "observed": "holdout-touched diagnostic ceiling audit",
            "rule": "this audit may improve blocker diagnosis but cannot claim tradable-final",
        },
    ]
    failures = [item["check"] for item in checks if item["status"] == "fail"]
    remaining = set(blockers)
    if scope == "defensive_informational":
        remaining.add("scope_not_direct_long_cash_equity")
    if score < 95.0:
        remaining.add("score_below_95")
    return {
        "policy_id": NO_OVERLIFT_POLICY_ID,
        "promotion_decision": "DIAGNOSTIC_EVIDENCE_UPGRADE" if not failures else "KEEP_CURRENT_BLOCKED_STATUS",
        "failures": failures,
        "remaining_tradable_blockers": sorted(item for item in remaining if item),
        "checks": checks,
    }


def run_one(pattern_id: str, out_dir: Path, *, max_full_configs: int) -> dict[str, Any]:
    chapter_dir = out_dir / pattern_id
    chapter_dir.mkdir(parents=True, exist_ok=True)
    spec = CHAPTER_SPECS[pattern_id]
    events, path, source_scope = load_chapter_events_and_path(spec)
    configs = build_configs(pattern_id)
    first_pass_rows = [evaluate_strategy(events, path, config)[0] for config in configs]
    shortlisted = shortlist_configs(first_pass_rows, configs, max_full_configs)
    full_rows = [evaluate_full_candidate(events, path, config) for config in shortlisted]
    full_rows = sorted(full_rows, key=lambda row: _as_float(row.get("score")), reverse=True)
    best = full_rows[0] if full_rows else {}
    payload = {
        "audit_id": AUDIT_ID,
        "pattern_id": pattern_id,
        "scope": _scope_for(pattern_id),
        "source_scope": source_scope,
        "candidate_count": len(configs),
        "full_candidate_count": len(full_rows),
        "shortlist_policy": "rank deterministic branch summaries by validation/holdout diagnostic utility; diagnostic only, not final-promotion selection",
        "best_score": best.get("score"),
        "best_strategy_id": best.get("strategy_id"),
        "no_overlift_guard": _guard(pattern_id, best),
        "rows": full_rows,
        "first_pass_top_rows": sorted(
            (dict(row) | {"diagnostic_utility": round(_diagnostic_utility(row), 4)} for row in first_pass_rows),
            key=lambda row: _as_float(row.get("diagnostic_utility")),
            reverse=True,
        )[:25],
    }
    paths = {
        "json": chapter_dir / f"{pattern_id}_branch_ceiling_audit.json",
        "csv": chapter_dir / f"{pattern_id}_branch_ceiling_audit.csv",
        "md": chapter_dir / f"{pattern_id}_branch_ceiling_audit.md",
    }
    _write_json(paths["json"], payload)
    _write_csv(paths["csv"], full_rows)
    paths["md"].write_text(render_markdown(payload), encoding="utf-8")
    return payload | {"artifact_paths": {key: str(value) for key, value in paths.items()}}


def run_audit(
    *,
    out_dir: Path = DEFAULT_OUT_DIR,
    patterns: Sequence[str] = DEFAULT_PATTERNS,
    max_full_configs: int = 14,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [run_one(pattern_id, out_dir, max_full_configs=max_full_configs) for pattern_id in patterns]
    payload = {
        "audit_id": AUDIT_ID,
        "pattern_count": len(rows),
        "patterns": list(patterns),
        "max_full_configs": max_full_configs,
        "rows": rows,
    }
    paths = {
        "json": out_dir / "remaining_pattern_branch_ceiling_audit.json",
        "csv": out_dir / "remaining_pattern_branch_ceiling_audit.csv",
        "md": out_dir / "remaining_pattern_branch_ceiling_audit.md",
    }
    _write_json(paths["json"], payload)
    summary_rows = [
        {
            "pattern_id": row.get("pattern_id"),
            "scope": row.get("scope"),
            "best_score": row.get("best_score"),
            "best_strategy_id": row.get("best_strategy_id"),
            "decision": (row.get("no_overlift_guard") or {}).get("promotion_decision"),
            "failures": ",".join((row.get("no_overlift_guard") or {}).get("failures") or []),
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
    max_full_configs: int = 14,
) -> dict[str, Path]:
    rows: list[dict[str, Any]] = []
    for pattern_id in patterns:
        path = out_dir / pattern_id / f"{pattern_id}_branch_ceiling_audit.json"
        if path.exists():
            rows.append(json.loads(path.read_text(encoding="utf-8")))
    payload = {
        "audit_id": AUDIT_ID,
        "pattern_count": len(rows),
        "patterns": [str(row.get("pattern_id")) for row in rows],
        "max_full_configs": max_full_configs,
        "rows": rows,
    }
    paths = {
        "json": out_dir / "remaining_pattern_branch_ceiling_audit.json",
        "csv": out_dir / "remaining_pattern_branch_ceiling_audit.csv",
        "md": out_dir / "remaining_pattern_branch_ceiling_audit.md",
    }
    _write_json(paths["json"], payload)
    summary_rows = [
        {
            "pattern_id": row.get("pattern_id"),
            "scope": row.get("scope"),
            "best_score": row.get("best_score"),
            "best_strategy_id": row.get("best_strategy_id"),
            "decision": (row.get("no_overlift_guard") or {}).get("promotion_decision"),
            "failures": ",".join((row.get("no_overlift_guard") or {}).get("failures") or []),
            "remaining_tradable_blockers": ",".join((row.get("no_overlift_guard") or {}).get("remaining_tradable_blockers") or []),
        }
        for row in rows
    ]
    _write_csv(paths["csv"], summary_rows)
    paths["md"].write_text(render_aggregate_markdown(payload), encoding="utf-8")
    return paths


def render_markdown(payload: Mapping[str, Any]) -> str:
    guard = payload.get("no_overlift_guard") if isinstance(payload.get("no_overlift_guard"), Mapping) else {}
    lines = [
        f"# {payload.get('pattern_id')} Branch Ceiling Audit",
        "",
        f"Audit: `{AUDIT_ID}`",
        "",
        f"- Best score: `{payload.get('best_score')}`",
        f"- Best strategy: `{payload.get('best_strategy_id')}`",
        f"- Decision: `{guard.get('promotion_decision')}`",
        f"- Remaining blockers: `{', '.join(guard.get('remaining_tradable_blockers') or [])}`",
        "",
        "| Strategy | Score | Blockers | Trades | Validation | Holdout | WF positive | WF sum | ADTV |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload.get("rows") or []:
        lines.append(
            "| {strategy} | {score:.2f} | {blockers} | {trades} | {validation} | {holdout} | {wf_pos} | {wf_sum} | {adtv} |".format(
                strategy=row.get("strategy_id"),
                score=_as_float(row.get("score")),
                blockers=row.get("promotion_blockers") or "",
                trades=row.get("trades") or "",
                validation=row.get("validation_total_return_pct") or "",
                holdout=row.get("holdout_total_return_pct") or "",
                wf_pos=row.get("walk_forward_positive_fold_rate_pct") or "",
                wf_sum=row.get("walk_forward_sum_return_pct") or "",
                adtv=row.get("median_adtv_participation_pct") or "",
            )
        )
    return "\n".join(lines) + "\n"


def render_aggregate_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Remaining Pattern Branch Ceiling Audit",
        "",
        f"Audit: `{AUDIT_ID}`",
        "",
        "This is diagnostic evidence. It does not promote any chapter to tradable-final.",
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
    parser = argparse.ArgumentParser(description="Run diagnostic ceiling audit for remaining blocked pattern branches.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--patterns", default=",".join(DEFAULT_PATTERNS))
    parser.add_argument("--max-full-configs", type=int, default=14)
    parser.add_argument("--aggregate-existing", action="store_true")
    args = parser.parse_args()
    patterns = [item.strip() for item in str(args.patterns).split(",") if item.strip()]
    if args.aggregate_existing:
        paths = aggregate_existing(out_dir=Path(args.out_dir), patterns=patterns, max_full_configs=int(args.max_full_configs))
    else:
        paths = run_audit(out_dir=Path(args.out_dir), patterns=patterns, max_full_configs=int(args.max_full_configs))
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
