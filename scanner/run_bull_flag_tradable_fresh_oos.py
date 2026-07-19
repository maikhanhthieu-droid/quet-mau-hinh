"""Evaluate the frozen Bull Flag tradable setup on a fresh OOS profile.

Fresh OOS means a profile directory produced from a data snapshot not used in
the current scanner/profile tuning cycle. When no profile is provided, this
script writes a pending gate artifact instead of pretending that existing
profiles are fresh data.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.run_bull_flag_tradable_robustness import normalize_profile_schema  # noqa: E402
from scanner.v2.bull_flag_tradable_setup import (  # noqa: E402
    DEFAULT_STRATEGY_GRID,
    FROZEN_STRATEGY_ID,
    evaluate_strategy,
    load_bull_flag_v2_artifacts,
    monte_carlo_trade_sequence,
    run_cost_stress,
    run_fixed_strategy_walk_forward,
    score_tradable_setup,
)
from scanner.v2.source_data import DEFAULT_SOURCE_DIR  # noqa: E402


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bull_flags_tradable_fresh_oos")


def _fixed_selection(strategy_id: str, summary: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": "selected_tradable_setup",
        "selection_basis": "fixed_frozen_strategy_fresh_oos_no_reselection",
        "selected_strategy_id": strategy_id,
        "selected_metrics": summary,
        "passing_count": 1,
        "candidate_count": 1,
    }


def pending_payload(reason: str) -> Dict[str, Any]:
    return {
        "gate_id": "bull_flag_fresh_oos_gate_v1",
        "status": "pending_data",
        "reason": reason,
        "requirements": {
            "profile_dir": "Directory containing events.csv and post_breakout_path.csv from an unseen data snapshot.",
            "selection": "Frozen strategy only; no grid search or reselection on fresh OOS.",
            "minimum_gate": "score >= 90, validation/holdout trades >= 12 if split labels exist, no promotion blockers.",
        },
    }


def evaluate_fresh_profile(profile_dir: Path, *, source_dir: Path, monte_carlo_iterations: int) -> Dict[str, Any]:
    config = next((item for item in DEFAULT_STRATEGY_GRID if item.strategy_id == FROZEN_STRATEGY_ID), None)
    if config is None:
        raise RuntimeError(f"Frozen strategy not found: {FROZEN_STRATEGY_ID}")
    events, path = load_bull_flag_v2_artifacts(profile_dir)
    events, schema_info = normalize_profile_schema(events, path, source_dir=source_dir)
    summary, trades, _ = evaluate_strategy(events, path, config)
    selection = _fixed_selection(config.strategy_id, summary)
    _, _, walk_forward_summary = run_fixed_strategy_walk_forward(events, path, config)
    _, cost_stress_summary = run_cost_stress(events, path, config)
    _, monte_carlo_summary = monte_carlo_trade_sequence(trades, config, iterations=monte_carlo_iterations)
    scorecard = score_tradable_setup(selection, walk_forward_summary, cost_stress_summary, monte_carlo_summary)
    blockers = scorecard.get("promotion_blockers") or []
    gate_failures = []
    if float(scorecard.get("score") or 0.0) < 90.0:
        gate_failures.append("score_below_90")
    if blockers:
        gate_failures.extend(blockers)
    return {
        "gate_id": "bull_flag_fresh_oos_gate_v1",
        "status": "pass" if not gate_failures else "fail",
        "profile_dir": str(profile_dir),
        "schema_status": schema_info.get("schema_status"),
        "derived_columns": schema_info.get("derived_columns"),
        "events_n": int(len(events)),
        "path_rows": int(len(path)),
        "strategy_id": config.strategy_id,
        "summary": summary,
        "walk_forward_summary": walk_forward_summary,
        "cost_stress_summary": cost_stress_summary,
        "monte_carlo_summary": monte_carlo_summary,
        "scorecard": scorecard,
        "gate_failures": gate_failures,
        "scope_note": "Valid only if profile_dir comes from an unseen data snapshot. Do not use existing tuned artifacts as fresh OOS evidence.",
    }


def render_report(payload: Dict[str, Any]) -> str:
    lines = [
        "# Bull Flag Fresh OOS Gate",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- Gate: `{payload.get('gate_id')}`",
    ]
    if payload.get("status") == "pending_data":
        lines.extend(["", f"Reason: {payload.get('reason')}"])
        return "\n".join(lines) + "\n"
    scorecard = payload.get("scorecard") if isinstance(payload.get("scorecard"), dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    lines.extend(
        [
            f"- Score: `{scorecard.get('score')}`",
            f"- Classification: `{scorecard.get('classification')}`",
            f"- Failures: `{', '.join(payload.get('gate_failures') or []) or 'none'}`",
            "",
            "| Metric | Value |",
            "|---|---:|",
        ]
    )
    for key in ("events_n", "trades", "validation_trades", "validation_total_return_pct", "holdout_trades", "holdout_total_return_pct", "median_adtv_participation_pct"):
        value = payload.get(key) if key == "events_n" else summary.get(key)
        lines.append(f"| {key} | {value} |")
    return "\n".join(lines) + "\n"


def run_fresh_oos(*, profile_dir: Path | None, out_dir: Path, source_dir: Path, monte_carlo_iterations: int) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if profile_dir is None:
        payload = pending_payload("No fresh profile directory was provided.")
    else:
        payload = evaluate_fresh_profile(profile_dir, source_dir=source_dir, monte_carlo_iterations=monte_carlo_iterations)
    paths = {
        "fresh_oos_json": out_dir / "bull_flag_tradable_fresh_oos_gate.json",
        "fresh_oos_report": out_dir / "bull_flag_tradable_fresh_oos_report.md",
    }
    paths["fresh_oos_json"].write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    paths["fresh_oos_report"].write_text(render_report(payload), encoding="utf-8")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Run frozen Bull Flag tradable setup on a fresh OOS profile.")
    parser.add_argument("--profile-dir", default=None)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR))
    parser.add_argument("--monte-carlo-iterations", type=int, default=500)
    args = parser.parse_args()
    profile_dir = Path(args.profile_dir) if args.profile_dir else None
    paths = run_fresh_oos(profile_dir=profile_dir, out_dir=Path(args.out_dir), source_dir=Path(args.source_dir), monte_carlo_iterations=args.monte_carlo_iterations)
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
