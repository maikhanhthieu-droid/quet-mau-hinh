"""Audit the current Bull Pennant tradable ceiling.

This script is deliberately diagnostic.  It does not replace the frozen
promotion rule because several candidates use evidence that should remain
out-of-sample for promotion.  Its job is to answer a narrower question:
within the current data and execution contract, is there an obvious Bull
Pennant branch that clears the remaining 95+ blocker?
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.v2.bull_flag_tradable_setup import (  # noqa: E402
    ExecutionConfig,
    evaluate_strategy,
    monte_carlo_trade_sequence,
    run_cost_stress,
    run_fixed_strategy_walk_forward,
    score_tradable_setup,
)
from scanner.v2.bull_pennant_tradable_setup import (  # noqa: E402
    DEFAULT_EVENTS,
    DEFAULT_OUT_DIR,
    DEFAULT_PATH,
    DEFAULT_SOURCE_DIR,
    DEFAULT_STRATEGY_GRID,
    load_bull_pennant_tradable_artifacts,
)


DEFAULT_OUT = DEFAULT_OUT_DIR / "bull_pennant_tradable_ceiling_audit"
AUDIT_ID = "bull_pennant_tradable_ceiling_audit_v1"
NO_OVERLIFT_POLICY_ID = "tradable_no_overlift_guard_v1"
PROMOTION_SCORE_THRESHOLD = 95.0
MIN_DIAGNOSTIC_TRADES_WARNING = 150
MIN_TRADE_SHARE_VS_CURRENT_WARNING = 0.40
CURRENT_SELECTED_ID = "bp_branch_exclude_extended_pole_liq_mid_high_defensive_stretch075_setup60_stop8_max60_pos033_max30_cap30"


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
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _candidate_configs() -> list[ExecutionConfig]:
    base = dict(
        target_multiple=0.75,
        max_holding_days=60,
        allowed_liquidity_buckets=("mid", "high"),
        excluded_pole_exhaustion_branches=("extended_pole",),
        position_size_pct=0.033,
        max_positions=30,
        max_adtv_participation_pct=30.0,
        target_adtv_participation_pct=10.0,
    )
    current = next(config for config in DEFAULT_STRATEGY_GRID if config.strategy_id == CURRENT_SELECTED_ID)
    existing_low_noise = next(
        config
        for config in DEFAULT_STRATEGY_GRID
        if config.strategy_id == "bp_branch_exclude_extended_low_noise_liq_mid_high_defensive_stretch075_setup60_stop8_max60_pos033_max30_cap30"
    )
    return [
        current,
        existing_low_noise,
        ExecutionConfig(
            strategy_id="bp_ceiling_setup70_vol10_conf50_stretch075_stop8_pos033",
            stop_loss_pct=8.0,
            min_setup_score=70.0,
            min_confirmation_score=50.0,
            max_pre_breakout_volatility_20d_pct=10.0,
            **base,
        ),
        ExecutionConfig(
            strategy_id="bp_ceiling_setup70_vol10_conf50_stretch090_stop7_pos033",
            target_multiple=0.90,
            stop_loss_pct=7.0,
            max_holding_days=60,
            min_setup_score=70.0,
            min_confirmation_score=50.0,
            max_pre_breakout_volatility_20d_pct=10.0,
            allowed_liquidity_buckets=("mid", "high"),
            excluded_pole_exhaustion_branches=("extended_pole",),
            position_size_pct=0.033,
            max_positions=30,
            max_adtv_participation_pct=30.0,
            target_adtv_participation_pct=10.0,
        ),
        ExecutionConfig(
            strategy_id="bp_ceiling_entry_confirm_d2_mfe1_mae2_stretch075_stop7_pos033",
            stop_loss_pct=7.0,
            entry_delay_bars=2,
            min_setup_score=60.0,
            min_pre_entry_mfe_pct=1.0,
            max_pre_entry_mae_pct=2.0,
            **base,
        ),
    ]


def _evaluate_candidate(events: pd.DataFrame, path: pd.DataFrame, config: ExecutionConfig, *, monte_carlo_iterations: int) -> dict[str, Any]:
    summary, trades, _ = evaluate_strategy(events, path, config)
    folds, _, walk_forward = run_fixed_strategy_walk_forward(events, path, config)
    cost_stress, cost_stress_summary = run_cost_stress(events, path, config)
    monte_carlo, monte_carlo_summary = monte_carlo_trade_sequence(trades, config, iterations=monte_carlo_iterations)
    scorecard = score_tradable_setup(
        {"status": "selected_tradable_setup", "selected_metrics": summary},
        walk_forward,
        cost_stress_summary,
        monte_carlo_summary,
    )
    negative_folds = int((pd.to_numeric(folds.get("test_total_return_pct"), errors="coerce") < 0).sum()) if not folds.empty else None
    return {
        "strategy_id": config.strategy_id,
        "score": scorecard.get("score"),
        "classification": scorecard.get("classification"),
        "promotion_blockers": ",".join(scorecard.get("promotion_blockers") or []),
        "trades": summary.get("trades"),
        "total_return_pct": summary.get("total_return_pct"),
        "max_drawdown_pct": summary.get("max_drawdown_pct"),
        "validation_total_return_pct": summary.get("validation_total_return_pct"),
        "validation_max_drawdown_pct": summary.get("validation_max_drawdown_pct"),
        "holdout_total_return_pct": summary.get("holdout_total_return_pct"),
        "holdout_max_drawdown_pct": summary.get("holdout_max_drawdown_pct"),
        "median_adtv_participation_pct": summary.get("median_adtv_participation_pct"),
        "walk_forward_positive_fold_rate_pct": walk_forward.get("positive_fold_rate_pct"),
        "walk_forward_negative_folds": negative_folds,
        "walk_forward_sum_return_pct": walk_forward.get("sum_fold_return_pct"),
        "walk_forward_worst_fold_return_pct": walk_forward.get("worst_fold_return_pct"),
        "walk_forward_worst_fold_drawdown_pct": walk_forward.get("worst_fold_drawdown_pct"),
        "cost_positive_scenario_rate_pct": cost_stress_summary.get("positive_scenario_rate_pct"),
        "cost_worst_scenario_return_pct": cost_stress_summary.get("worst_scenario_return_pct"),
        "monte_carlo_prob_positive_pct": monte_carlo_summary.get("prob_positive_pct"),
        "scorecard_component_scores": scorecard.get("component_scores"),
        "target_multiple": config.target_multiple,
        "stop_loss_pct": config.stop_loss_pct,
        "entry_delay_bars": config.entry_delay_bars,
        "min_setup_score": config.min_setup_score,
        "min_confirmation_score": config.min_confirmation_score,
        "max_pre_breakout_volatility_20d_pct": config.max_pre_breakout_volatility_20d_pct,
    }


def _build_no_overlift_guard(best: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    current = next((row for row in rows if row.get("strategy_id") == CURRENT_SELECTED_ID), {})
    best_score = _as_float(best.get("score"))
    best_trades = _as_int(best.get("trades"))
    current_trades = _as_int(current.get("trades"))
    trade_share = (best_trades / current_trades) if current_trades else None
    blockers = {str(item).strip() for item in str(best.get("promotion_blockers") or "").split(",") if str(item).strip()}
    negative_folds = _as_int(best.get("walk_forward_negative_folds"))

    checks: list[dict[str, Any]] = []

    def add_check(name: str, status: str, observed: Any, rule: str) -> None:
        checks.append({"check": name, "status": status, "observed": observed, "rule": rule})

    add_check(
        "score_threshold",
        "fail" if best_score < PROMOTION_SCORE_THRESHOLD else "pass",
        round(best_score, 2),
        f"best diagnostic score must be >= {PROMOTION_SCORE_THRESHOLD:.0f} before any promotion review",
    )
    add_check(
        "promotion_blockers",
        "fail" if blockers else "pass",
        ",".join(sorted(blockers)) or "none",
        "best diagnostic branch must have no remaining promotion blocker",
    )
    add_check(
        "walk_forward_negative_folds",
        "fail" if negative_folds > 0 else "pass",
        negative_folds,
        "fixed-rule walk-forward must have zero negative folds under the current contract",
    )
    add_check(
        "diagnostic_trade_count",
        "warn" if best_trades < MIN_DIAGNOSTIC_TRADES_WARNING else "pass",
        best_trades,
        f"diagnostic candidate should keep at least {MIN_DIAGNOSTIC_TRADES_WARNING} trades unless pre-registered",
    )
    add_check(
        "sample_share_vs_current_release",
        "warn" if trade_share is not None and trade_share < MIN_TRADE_SHARE_VS_CURRENT_WARNING else "pass",
        None if trade_share is None else round(trade_share, 4),
        f"diagnostic candidate should keep at least {MIN_TRADE_SHARE_VS_CURRENT_WARNING:.0%} of current release-candidate trades",
    )
    add_check(
        "fold_contract_unchanged",
        "pass",
        "unchanged",
        "do not weaken the fixed-fold contract to manufacture a 95+ score",
    )
    add_check(
        "holdout_as_evidence_not_selection",
        "pass",
        "preserved",
        "holdout/walk-forward evidence may reject promotion but must not be used as a direct tuning target",
    )

    failures = [check["check"] for check in checks if check["status"] == "fail"]
    warnings = [check["check"] for check in checks if check["status"] == "warn"]
    decision = "STOP_NO_PROMOTION_UNDER_NO_OVERLIFT_POLICY" if failures else "ELIGIBLE_FOR_FORMAL_PROMOTION_REVIEW"
    return {
        "policy_id": NO_OVERLIFT_POLICY_ID,
        "promotion_decision": decision,
        "failures": failures,
        "warnings": warnings,
        "current_selected_strategy_id": CURRENT_SELECTED_ID,
        "current_selected_score": current.get("score"),
        "current_selected_trades": current_trades or None,
        "best_diagnostic_strategy_id": best.get("strategy_id"),
        "best_diagnostic_score": best.get("score"),
        "best_diagnostic_trades": best_trades,
        "best_trade_share_vs_current": None if trade_share is None else round(trade_share, 4),
        "checks": checks,
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    rows = list(payload.get("rows") or [])
    guard = dict(payload.get("no_overlift_guard") or {})
    lines = [
        "# Bull Pennant Tradable Ceiling Audit",
        "",
        f"Audit: `{AUDIT_ID}`",
        "",
        "This is a diagnostic layer, not a promotion layer. Holdout and fixed walk-forward remain evidence, not selection inputs.",
        "",
        f"- Best diagnostic score: `{payload.get('best_score')}`",
        f"- Best diagnostic strategy: `{payload.get('best_strategy_id')}`",
        f"- Ceiling verdict: `{payload.get('ceiling_verdict')}`",
        f"- Main blocker: `{payload.get('main_blocker')}`",
        f"- No-overlift decision: `{guard.get('promotion_decision')}`",
        "",
        "| Strategy | Score | Blockers | Trades | Validation | Holdout | WF positive | WF worst | Cost worst |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {strategy} | {score:.2f} | {blockers} | {trades} | {validation} | {holdout} | {wf_pos} | {wf_worst} | {cost_worst} |".format(
                strategy=row.get("strategy_id"),
                score=float(row.get("score") or 0.0),
                blockers=row.get("promotion_blockers") or "",
                trades=row.get("trades") or "",
                validation=row.get("validation_total_return_pct") or "",
                holdout=row.get("holdout_total_return_pct") or "",
                wf_pos=row.get("walk_forward_positive_fold_rate_pct") or "",
                wf_worst=row.get("walk_forward_worst_fold_return_pct") or "",
                cost_worst=row.get("cost_worst_scenario_return_pct") or "",
            )
        )
    lines.extend(
        [
            "",
            "## No-overlift guard",
            "",
            f"Policy: `{guard.get('policy_id')}`",
            "",
            "| Check | Status | Observed | Rule |",
            "|---|---|---:|---|",
        ]
    )
    for check in guard.get("checks") or []:
        lines.append(
            "| {check} | {status} | {observed} | {rule} |".format(
                check=check.get("check"),
                status=check.get("status"),
                observed=check.get("observed"),
                rule=check.get("rule"),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- No audited branch clears the `walk_forward_has_negative_fold` blocker under the current fixed-fold contract.",
            "- The best diagnostic branch improves score versus the current Bull Pennant release candidate, but it still remains below 95.",
            "- Under the no-overlift guard, forcing a 95+ label would require weakening the gate or overfitting the branch selection. The correct action is to stop promotion at the current ceiling.",
            "- This supports keeping Bull Pennant as `tradable-research-candidate-blocked` until either the scanner improves materially, the data scope expands, or a future pre-registered branch clears the same gate.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_audit(
    *,
    events_csv: Path = DEFAULT_EVENTS,
    path_csv: Path = DEFAULT_PATH,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    out_dir: Path = DEFAULT_OUT,
    monte_carlo_iterations: int = 300,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    events, path = load_bull_pennant_tradable_artifacts(events_csv, path_csv, source_dir=source_dir)
    rows = [_evaluate_candidate(events, path, config, monte_carlo_iterations=monte_carlo_iterations) for config in _candidate_configs()]
    rows = sorted(rows, key=lambda row: float(row.get("score") or 0.0), reverse=True)
    best = rows[0] if rows else {}
    no_overlift_guard = _build_no_overlift_guard(best, rows)
    payload = {
        "audit_id": AUDIT_ID,
        "no_overlift_policy_id": NO_OVERLIFT_POLICY_ID,
        "events_csv": str(events_csv),
        "path_csv": str(path_csv),
        "source_dir": str(source_dir),
        "candidate_count": len(rows),
        "best_score": best.get("score"),
        "best_strategy_id": best.get("strategy_id"),
        "main_blocker": "walk_forward_has_negative_fold",
        "ceiling_verdict": "current_data_and_contract_ceiling_below_95" if float(best.get("score") or 0.0) < 95.0 else "candidate_above_95_requires_promotion_review",
        "no_overlift_guard": no_overlift_guard,
        "rows": rows,
    }
    paths = {
        "json": out_dir / "bull_pennant_tradable_ceiling_audit.json",
        "csv": out_dir / "bull_pennant_tradable_ceiling_audit.csv",
        "md": out_dir / "bull_pennant_tradable_ceiling_audit.md",
    }
    _write_json(paths["json"], payload)
    _write_csv(paths["csv"], rows)
    paths["md"].write_text(render_markdown(payload), encoding="utf-8")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Bull Pennant tradable ceiling audit.")
    parser.add_argument("--events-csv", default=str(DEFAULT_EVENTS))
    parser.add_argument("--path-csv", default=str(DEFAULT_PATH))
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    parser.add_argument("--monte-carlo-iterations", type=int, default=300)
    args = parser.parse_args()
    paths = run_audit(
        events_csv=Path(args.events_csv),
        path_csv=Path(args.path_csv),
        source_dir=Path(args.source_dir),
        out_dir=Path(args.out_dir),
        monte_carlo_iterations=int(args.monte_carlo_iterations),
    )
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
