"""Audit the defensive ceiling for Double Top Adam & Adam.

This is not a long-cash promotion script. Double Top Adam & Adam is a
down-breakout / defensive reference chapter in Vietnam cash equities.  The goal
is to test whether the existing branch can be upgraded from a weak blocked
tradable layer to a strong defensive-reference evidence layer without changing
the scanner or weakening the no-overlift contract.
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


PATTERN_ID = "double_tops_adam_adam"
OUT_DIR = Path("artifacts/scanner_v2/double_top_aa_defensive_branch_audit")
AUDIT_ID = "double_top_aa_defensive_branch_audit_v1"
NO_OVERLIFT_POLICY_ID = "defensive_reference_no_overlift_guard_v1"


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


def build_configs() -> list[GenericExecutionConfig]:
    configs: list[GenericExecutionConfig] = []
    for liquidity in (None, ("mid", "high"), ("high",)):
        liquidity_label = "all" if liquidity is None else "".join(liquidity)
        for position_size, max_positions in ((0.033, 30), (0.075, 10), (0.10, 10)):
            pos_label = str(position_size).replace(".", "")
            for setup in (None, 60.0, 65.0):
                configs.append(
                    GenericExecutionConfig(
                        strategy_id=(
                            f"{PATTERN_ID}__defensive_t035_s10_h40_d1_q{int(setup or 0)}"
                            f"_liq{liquidity_label}_p{pos_label}_m{max_positions}"
                        ),
                        target_multiple=0.35,
                        stop_loss_pct=10.0,
                        max_holding_days=40,
                        entry_delay_bars=1,
                        min_setup_score=setup,
                        allowed_breakout_directions=("down",),
                        allowed_liquidity_buckets=liquidity,
                        position_size_pct=position_size,
                        max_positions=max_positions,
                        max_adtv_participation_pct=30.0,
                        target_adtv_participation_pct=5.0,
                    )
                )
    return configs


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


def _guard(best: Mapping[str, Any]) -> dict[str, Any]:
    blockers = {item.strip() for item in str(best.get("promotion_blockers") or "").split(",") if item.strip()}
    checks = [
        {
            "check": "defensive_reference_score_90",
            "status": "fail" if _as_float(best.get("score")) < 90.0 else "pass",
            "observed": best.get("score"),
            "rule": "defensive reference upgrade requires score >= 90",
        },
        {
            "check": "fixed_walk_forward_positive",
            "status": "fail" if _as_float(best.get("walk_forward_positive_fold_rate_pct")) < 100.0 else "pass",
            "observed": best.get("walk_forward_positive_fold_rate_pct"),
            "rule": "fixed walk-forward should have no negative fold for a strong defensive reference",
        },
        {
            "check": "tradable_final_not_claimed",
            "status": "pass",
            "observed": "defensive_informational_scope",
            "rule": "do not promote downside cash-equity reference as direct long-cash tradable final",
        },
    ]
    failures = [item["check"] for item in checks if item["status"] == "fail"]
    return {
        "policy_id": NO_OVERLIFT_POLICY_ID,
        "promotion_decision": "DEFENSIVE_REFERENCE_UPGRADE" if not failures else "KEEP_DEFENSIVE_REFERENCE_BLOCKED",
        "failures": failures,
        "remaining_tradable_blockers": sorted(blockers | {"scope_not_direct_long_cash_equity", "score_below_95"}),
        "checks": checks,
    }


def run_audit(*, out_dir: Path = OUT_DIR) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    events, path, source_scope = load_chapter_events_and_path(CHAPTER_SPECS[PATTERN_ID])
    rows = [evaluate_full_candidate(events, path, config) for config in build_configs()]
    rows = sorted(rows, key=lambda row: _as_float(row.get("score")), reverse=True)
    best = rows[0] if rows else {}
    payload = {
        "audit_id": AUDIT_ID,
        "pattern_id": PATTERN_ID,
        "scope": "defensive_informational",
        "source_scope": source_scope,
        "candidate_count": len(rows),
        "best_score": best.get("score"),
        "best_strategy_id": best.get("strategy_id"),
        "no_overlift_guard": _guard(best),
        "rows": rows,
    }
    paths = {
        "json": out_dir / "double_top_aa_defensive_branch_audit.json",
        "csv": out_dir / "double_top_aa_defensive_branch_audit.csv",
        "md": out_dir / "double_top_aa_defensive_branch_audit.md",
    }
    _write_json(paths["json"], payload)
    _write_csv(paths["csv"], rows)
    paths["md"].write_text(render_markdown(payload), encoding="utf-8")
    return paths


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Double Top Adam & Adam Defensive Branch Audit",
        "",
        f"Audit: `{AUDIT_ID}`",
        "",
        f"- Best score: `{payload.get('best_score')}`",
        f"- Best strategy: `{payload.get('best_strategy_id')}`",
        f"- Decision: `{(payload.get('no_overlift_guard') or {}).get('promotion_decision')}`",
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Double Top Adam & Adam defensive branch audit.")
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    args = parser.parse_args()
    for key, path in run_audit(out_dir=Path(args.out_dir)).items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
