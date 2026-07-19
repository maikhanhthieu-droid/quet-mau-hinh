"""Diagnose Falling Wedge tradable blockers under a local branch grid."""

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


PATTERN_ID = "wedges_falling"
OUT_DIR = Path("artifacts/scanner_v2/falling_wedge_tradable_blocker_audit")
AUDIT_ID = "falling_wedge_tradable_blocker_audit_v2_sizing_parity"
NO_OVERLIFT_POLICY_ID = "tradable_no_overlift_guard_v1"


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
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(default if value is None else value)
    except (TypeError, ValueError):
        return int(default)


def _score_between(value: Any, low: float, high: float) -> float:
    numeric = _as_float(value, default=low)
    if high == low:
        return 100.0 if numeric >= high else 0.0
    return max(0.0, min(100.0, (numeric - low) / (high - low) * 100.0))


def _utility(row: Mapping[str, Any], prefix: str = "") -> float:
    key = lambda name: f"{prefix}_{name}" if prefix else name
    return (
        0.30 * _score_between(row.get(key("total_return_pct")), 0.0, 8.0)
        + 0.20 * _score_between(row.get(key("max_drawdown_pct")), -10.0, -2.0)
        + 0.18 * _score_between(row.get(key("win_rate_pct")), 45.0, 68.0)
        + 0.12 * _score_between(row.get(key("trades")), 12.0, 60.0)
        + 0.10 * _score_between(row.get(key("profit_factor")), 1.0, 2.5)
        + 0.10 * _score_between(8.0 - _as_float(row.get("median_adtv_participation_pct"), default=8.0), 0.0, 8.0)
    )


def build_grid() -> list[GenericExecutionConfig]:
    configs: list[GenericExecutionConfig] = []
    sizing_profiles = (
        ("p033", 0.033, 30, 5.0),
        ("p050", 0.050, 20, 5.0),
    )
    for target in (0.50, 0.75, 1.00, 1.25):
        for stop in (7.0, 10.0):
            for hold in (20, 60):
                for delay in (1, 3):
                    for setup in (80.0, 85.0):
                        for confirm in (None, 75.0):
                            for size_label, position_size, max_positions, target_participation in sizing_profiles:
                                configs.append(
                                    GenericExecutionConfig(
                                        strategy_id=(
                                            f"wedges_falling__local_t{str(target).replace('.', '')}"
                                            f"_s{int(stop)}_h{hold}_d{delay}_q{int(setup or 0)}_c{int(confirm or 0)}"
                                            f"_{size_label}"
                                        ),
                                        target_multiple=target,
                                        stop_loss_pct=stop,
                                        max_holding_days=hold,
                                        entry_delay_bars=delay,
                                        min_setup_score=setup,
                                        min_confirmation_score=confirm,
                                        allowed_breakout_directions=("up",),
                                        position_size_pct=position_size,
                                        max_positions=max_positions,
                                        max_adtv_participation_pct=30.0,
                                        target_adtv_participation_pct=target_participation,
                                    ),
                                )
    for target in (0.75, 1.00):
        for stop in (7.0, 10.0):
            for regime in (("bear",), ("unknown",)):
                for liquidity in (("mid", "high"), ("high",), None):
                    for setup in (70.0, 80.0):
                        for confirm in (65.0, 75.0):
                            for size_label, position_size, max_positions, target_participation in sizing_profiles:
                                liq_label = "all" if liquidity is None else "".join(liquidity)
                                configs.append(
                                    GenericExecutionConfig(
                                        strategy_id=(
                                            f"wedges_falling__local_reg{regime[0]}_t{str(target).replace('.', '')}"
                                            f"_s{int(stop)}_q{int(setup)}_c{int(confirm)}_liq{liq_label}_{size_label}"
                                        ),
                                        target_multiple=target,
                                        stop_loss_pct=stop,
                                        max_holding_days=60,
                                        entry_delay_bars=3,
                                        min_setup_score=setup,
                                        min_confirmation_score=confirm,
                                        allowed_breakout_directions=("up",),
                                        allowed_liquidity_buckets=liquidity,
                                        allowed_market_regimes=regime,
                                        position_size_pct=position_size,
                                        max_positions=max_positions,
                                        max_adtv_participation_pct=30.0,
                                        target_adtv_participation_pct=target_participation,
                                    ),
                                )
    return configs


def select_shortlist(rows: Sequence[Mapping[str, Any]], *, top_n: int) -> list[str]:
    candidates = [dict(row) for row in rows]
    passing = [
        row
        for row in candidates
        if _as_int(row.get("validation_trades")) >= 12
        and _as_float(row.get("validation_total_return_pct"), default=-999.0) > 0.0
        and _as_float(row.get("validation_max_drawdown_pct"), default=-999.0) >= -15.0
        and _as_float(row.get("median_adtv_participation_pct"), default=999.0) <= 8.0
    ]
    pool = passing if passing else candidates
    ranked = sorted(pool, key=lambda row: 0.62 * _utility(row, "validation") + 0.38 * _utility(row, "train"), reverse=True)
    return [str(row.get("strategy_id")) for row in ranked[:top_n] if row.get("strategy_id")]


def evaluate_full_candidate(events: pd.DataFrame, path: pd.DataFrame, config: GenericExecutionConfig) -> dict[str, Any]:
    summary, trades, _ = evaluate_strategy(events, path, config)
    _, _, fixed_folds, fixed_summary = run_walk_forward(events, path, [config], config)
    cost_stress, cost_stress_summary = run_cost_stress(events, path, config)
    monte_carlo, monte_carlo_summary = run_monte_carlo(trades, config, iterations=500)
    selection = {
        "status": "selected_tradable_setup",
        "selection_basis": "falling wedge local train+validation shortlist; holdout/walk-forward are promotion evidence",
        "selected_strategy_id": config.strategy_id,
        "selected_metrics": summary,
    }
    scorecard = score_tradable_setup(selection, fixed_summary, cost_stress_summary, monte_carlo_summary)
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
        "max_drawdown_pct": summary.get("max_drawdown_pct"),
        "median_adtv_participation_pct": summary.get("median_adtv_participation_pct"),
        "walk_forward_positive_fold_rate_pct": fixed_summary.get("positive_fold_rate_pct"),
        "walk_forward_negative_folds": negative_folds,
        "walk_forward_sum_return_pct": fixed_summary.get("sum_fold_return_pct"),
        "walk_forward_worst_fold_return_pct": fixed_summary.get("worst_fold_return_pct"),
        "cost_positive_scenario_rate_pct": cost_stress_summary.get("positive_scenario_rate_pct"),
        "cost_worst_scenario_return_pct": cost_stress_summary.get("worst_scenario_return_pct"),
        "monte_carlo_prob_positive_pct": monte_carlo_summary.get("prob_positive_pct"),
        "scorecard_component_scores": scorecard.get("component_scores"),
        "selected_config": asdict(config),
    }


def _guard(best: Mapping[str, Any]) -> dict[str, Any]:
    blockers = {item.strip() for item in str(best.get("promotion_blockers") or "").split(",") if item.strip()}
    checks = [
        {"check": "score_threshold", "status": "fail" if _as_float(best.get("score")) < 95.0 else "pass", "observed": best.get("score"), "rule": "best Falling Wedge branch must score >= 95"},
        {"check": "promotion_blockers", "status": "fail" if blockers else "pass", "observed": ",".join(sorted(blockers)) or "none", "rule": "best Falling Wedge branch must have no blocker"},
        {"check": "walk_forward_positive", "status": "fail" if _as_float(best.get("walk_forward_positive_fold_rate_pct")) < 100.0 else "pass", "observed": best.get("walk_forward_positive_fold_rate_pct"), "rule": "fixed walk-forward must have no negative fold"},
    ]
    failures = [item["check"] for item in checks if item["status"] == "fail"]
    return {
        "policy_id": NO_OVERLIFT_POLICY_ID,
        "promotion_decision": "STOP_NO_PROMOTION_UNDER_NO_OVERLIFT_POLICY" if failures else "ELIGIBLE_FOR_FORMAL_PROMOTION_REVIEW",
        "failures": failures,
        "checks": checks,
    }


def run_audit(*, out_dir: Path = OUT_DIR, shortlist_size: int = 5) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    events, path, source_scope = load_chapter_events_and_path(CHAPTER_SPECS[PATTERN_ID])
    configs = build_grid()
    grid_rows = []
    for config in configs:
        summary, _, _ = evaluate_strategy(events, path, config)
        grid_rows.append(summary)
    shortlist = select_shortlist(grid_rows, top_n=shortlist_size)
    config_by_id = {config.strategy_id: config for config in configs}
    rows = [evaluate_full_candidate(events, path, config_by_id[strategy_id]) for strategy_id in shortlist if strategy_id in config_by_id]
    rows = sorted(rows, key=lambda row: _as_float(row.get("score")), reverse=True)
    best = rows[0] if rows else {}
    payload = {
        "audit_id": AUDIT_ID,
        "pattern_id": PATTERN_ID,
        "scope": "long_cash_candidate",
        "source_scope": source_scope,
        "grid_count": len(configs),
        "shortlist_size": len(shortlist),
        "best_score": best.get("score"),
        "best_strategy_id": best.get("strategy_id"),
        "no_overlift_guard": _guard(best),
        "rows": rows,
    }
    paths = {
        "json": out_dir / "falling_wedge_tradable_blocker_audit.json",
        "grid": out_dir / "falling_wedge_local_strategy_grid.csv",
        "candidates": out_dir / "falling_wedge_full_candidate_scores.csv",
        "md": out_dir / "falling_wedge_tradable_blocker_audit.md",
    }
    _write_json(paths["json"], payload)
    _write_csv(paths["grid"], grid_rows)
    _write_csv(paths["candidates"], rows)
    paths["md"].write_text(render_markdown(payload), encoding="utf-8")
    return paths


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Falling Wedge Tradable Blocker Audit",
        "",
        f"Audit: `{AUDIT_ID}`",
        "",
        f"- Best score: `{payload.get('best_score')}`",
        f"- Best strategy: `{payload.get('best_strategy_id')}`",
        f"- No-overlift decision: `{(payload.get('no_overlift_guard') or {}).get('promotion_decision')}`",
        "",
        "| Strategy | Score | Blockers | Trades | Validation | Holdout | WF positive | WF sum | WF worst |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload.get("rows") or []:
        lines.append(
            "| {strategy} | {score:.2f} | {blockers} | {trades} | {validation} | {holdout} | {wf_pos} | {wf_sum} | {wf_worst} |".format(
                strategy=row.get("strategy_id"),
                score=_as_float(row.get("score")),
                blockers=row.get("promotion_blockers") or "",
                trades=row.get("trades") or "",
                validation=row.get("validation_total_return_pct") or "",
                holdout=row.get("holdout_total_return_pct") or "",
                wf_pos=row.get("walk_forward_positive_fold_rate_pct") or "",
                wf_sum=row.get("walk_forward_sum_return_pct") or "",
                wf_worst=row.get("walk_forward_worst_fold_return_pct") or "",
            )
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Falling Wedge blocker audit.")
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--shortlist-size", type=int, default=5)
    args = parser.parse_args()
    paths = run_audit(out_dir=Path(args.out_dir), shortlist_size=int(args.shortlist_size))
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
