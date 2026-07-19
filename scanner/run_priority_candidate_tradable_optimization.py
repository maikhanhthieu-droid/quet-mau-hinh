"""Priority tradable optimization for the strongest non-final candidates.

This runner is intentionally narrower than the generic all-chapter layer.  It
focuses on the five candidates identified by governance:

- Bull Pennant: already has a specialized layer and is referenced here.
- Symmetrical Triangle: long up-breakout branch.
- Ascending Triangle: long breakout branch.
- Falling Wedge: long reversal/continuation branch.
- Double Bottom Adam & Adam: long reversal branch.

Rule selection uses train+validation only.  Holdout, fixed walk-forward, cost
stress, and Monte Carlo remain promotion evidence.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.run_chapter_tradable_layer import (  # noqa: E402
    CHAPTER_SPECS,
    GenericExecutionConfig,
    _read_json,
    evaluate_strategy,
    load_chapter_events_and_path,
    run_cost_stress,
    run_monte_carlo,
    run_walk_forward,
    score_tradable_setup,
)


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/priority_candidate_tradable_optimization")
PRIORITY_LAYER_ID = "priority_candidate_tradable_optimizer_v1"
PRIORITY_PATTERNS = (
    "bull_pennants",
    "triangles_symmetrical",
    "triangles_ascending",
    "wedges_falling",
    "double_bottoms_adam_adam",
)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


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


def _utility(row: Mapping[str, Any], prefix: str = "") -> float:
    key = lambda name: f"{prefix}_{name}" if prefix else name
    return (
        0.28 * _score_between(row.get(key("total_return_pct")), 0.0, 8.0)
        + 0.20 * _score_between(row.get(key("max_drawdown_pct")), -10.0, -2.0)
        + 0.18 * _score_between(row.get(key("win_rate_pct")), 45.0, 68.0)
        + 0.14 * _score_between(row.get(key("trades")), 10.0, 50.0)
        + 0.10 * _score_between(row.get(key("profit_factor")), 1.0, 2.4)
        + 0.10 * _score_between(8.0 - _as_float(row.get("median_adtv_participation_pct"), default=8.0), 0.0, 8.0)
    )


def _target_family(pattern_id: str) -> tuple[float, ...]:
    if pattern_id in {"triangles_ascending", "triangles_symmetrical", "wedges_falling", "double_bottoms_adam_adam"}:
        return (0.50, 0.75, 1.00)
    return (0.50, 0.75, 1.00)


def _scope_override(pattern_id: str) -> str:
    if pattern_id == "triangles_symmetrical":
        return "long_up_breakout_branch"
    return "long_cash_candidate"


def build_priority_grid(pattern_id: str) -> list[GenericExecutionConfig]:
    configs: list[GenericExecutionConfig] = []
    directions = ("up",)
    for target in _target_family(pattern_id):
        for hold in (20, 60):
            configs.append(
                GenericExecutionConfig(
                    strategy_id=f"{pattern_id}__priority_base_t{str(target).replace('.', '')}_s7_h{hold}",
                    target_multiple=target,
                    stop_loss_pct=7.0,
                    max_holding_days=hold,
                    allowed_breakout_directions=directions,
                )
            )
    for target in _target_family(pattern_id):
        for hold in (20, 60):
            for setup in (65.0, 75.0):
                configs.append(
                    GenericExecutionConfig(
                        strategy_id=f"{pattern_id}__priority_quality_t{str(target).replace('.', '')}_h{hold}_d1_q{int(setup)}",
                        target_multiple=target,
                        stop_loss_pct=7.0,
                        max_holding_days=hold,
                        entry_delay_bars=1,
                        min_setup_score=setup,
                        allowed_breakout_directions=directions,
                        allowed_liquidity_buckets=("mid", "high"),
                        position_size_pct=0.033,
                        max_positions=30,
                        target_adtv_participation_pct=5.0,
                    )
                )
    for target in (0.50, 0.75):
        for regime in (("bull",), ("bear",)):
            configs.append(
                GenericExecutionConfig(
                    strategy_id=f"{pattern_id}__priority_regime_{regime[0]}_t{str(target).replace('.', '')}_q65",
                    target_multiple=target,
                    stop_loss_pct=7.0,
                    max_holding_days=60,
                    entry_delay_bars=3,
                    min_setup_score=65.0,
                    allowed_breakout_directions=directions,
                    allowed_market_regimes=regime,
                    allowed_liquidity_buckets=("mid", "high"),
                    position_size_pct=0.02,
                    max_positions=40,
                    target_adtv_participation_pct=3.0,
                )
            )
    # A small liquidity branch catches cases where the tradable edge survives
    # only after excluding thin issues without letting liquidity become an
    # unbounded search dimension.
    for target in (0.50, 0.75):
        for hold in (20, 60):
            configs.append(
                GenericExecutionConfig(
                    strategy_id=f"{pattern_id}__priority_liquidity_mid_high_t{str(target).replace('.', '')}_h{hold}",
                    target_multiple=target,
                    stop_loss_pct=7.0,
                    max_holding_days=hold,
                    entry_delay_bars=1,
                    allowed_breakout_directions=directions,
                    allowed_liquidity_buckets=("mid", "high"),
                    position_size_pct=0.033,
                    max_positions=30,
                    target_adtv_participation_pct=5.0,
                )
            )
    return configs


def select_priority_strategy(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    candidates = [dict(row) for row in rows]
    if not candidates:
        return {"status": "no_strategy_rows"}
    passing = [
        row
        for row in candidates
        if int(row.get("validation_trades") or 0) >= 10
        and _as_float(row.get("validation_total_return_pct"), default=-999.0) > 0.0
        and _as_float(row.get("validation_max_drawdown_pct"), default=-999.0) >= -18.0
        and _as_float(row.get("median_adtv_participation_pct"), default=999.0) <= 6.0
    ]
    pool = passing if passing else candidates
    selected = max(pool, key=lambda row: 0.62 * _utility(row, "validation") + 0.38 * _utility(row, "train"))
    optimizer_status = "selected_priority_strategy" if passing else "no_priority_strategy_passed_validation_gate"
    return {
        "status": "selected_tradable_setup" if passing else "no_strategy_passed_validation_gate",
        "optimizer_status": optimizer_status,
        "selection_basis": "validation-gated train+validation utility; holdout and fixed walk-forward are never used for selection",
        "selected_strategy_id": selected.get("strategy_id"),
        "selected_metrics": selected,
        "passing_count": len(passing),
        "candidate_count": len(candidates),
    }


def _release_status(scorecard: Mapping[str, Any], *, scope: str) -> tuple[str, list[str], str]:
    blockers = list(scorecard.get("promotion_blockers") or [])
    score = _as_float(scorecard.get("score"), default=0.0)
    if scope not in {"long_cash_candidate", "long_up_breakout_branch"}:
        blockers.append("scope_not_direct_long_cash_equity")
    if score < 95.0:
        blockers.append("score_below_95")
    status = "PASS" if not blockers else "BLOCK"
    if status == "PASS":
        classification = "tradable-final-95"
    elif score >= 90.0:
        classification = "tradable-research-candidate-blocked"
    elif score >= 80.0:
        classification = "tradable-watchlist"
    else:
        classification = "tradable-research-only"
    return status, sorted(set(str(item) for item in blockers if item)), classification


def _write_grid_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def run_external_bull_pennant(out_dir: Path) -> dict[str, Any]:
    spec = CHAPTER_SPECS["bull_pennants"]
    chapter_dir = out_dir / "bull_pennants"
    chapter_dir.mkdir(parents=True, exist_ok=True)
    scorecard = _read_json(spec.external_scorecard) if spec.external_scorecard else {}
    selected = _read_json(spec.external_selected_strategy) if spec.external_selected_strategy else {}
    release = _read_json(spec.external_release_candidate) if spec.external_release_candidate else {}
    payload = {
        "layer_id": PRIORITY_LAYER_ID,
        "pattern_id": "bull_pennants",
        "status": "external_specialized_layer",
        "scope": "long_cash_candidate",
        "score": scorecard.get("score") or release.get("score"),
        "classification": scorecard.get("classification") or release.get("classification"),
        "release_status": release.get("release_status"),
        "release_classification": release.get("classification"),
        "selected_strategy_id": selected.get("selected_strategy_id") or release.get("selected_strategy_id"),
        "promotion_blockers": scorecard.get("promotion_blockers") or release.get("failures") or [],
        "selected_metrics": selected.get("selected_metrics") if isinstance(selected.get("selected_metrics"), Mapping) else {},
        "fixed_walk_forward_summary": selected.get("walk_forward_summary") if isinstance(selected.get("walk_forward_summary"), Mapping) else {},
        "note": "Bull Pennant already has a specialized priority branch layer; this pass references that evidence.",
    }
    _write_json(chapter_dir / "priority_optimization_external_reference.json", payload)
    return payload


def run_one_priority(pattern_id: str, out_dir: Path) -> dict[str, Any]:
    if pattern_id == "bull_pennants":
        return run_external_bull_pennant(out_dir)
    spec = CHAPTER_SPECS[pattern_id]
    scope = _scope_override(pattern_id)
    chapter_dir = out_dir / pattern_id
    chapter_dir.mkdir(parents=True, exist_ok=True)
    events, path, source_scope = load_chapter_events_and_path(spec)
    if events.empty or path.empty:
        payload = {"layer_id": PRIORITY_LAYER_ID, "pattern_id": pattern_id, "status": "missing_data", "scope": scope}
        _write_json(chapter_dir / "priority_optimization_summary.json", payload)
        return payload
    configs = build_priority_grid(pattern_id)
    rows = []
    for config in configs:
        summary, _, _ = evaluate_strategy(events, path, config)
        rows.append(summary)
    selection = select_priority_strategy(rows)
    selected_config = next((config for config in configs if config.strategy_id == selection.get("selected_strategy_id")), configs[0])
    selected_summary, trades, curve = evaluate_strategy(events, path, selected_config)
    selection["selected_metrics"] = selected_summary
    adaptive_wf, adaptive_summary, fixed_wf, fixed_summary = run_walk_forward(events, path, configs[:8], selected_config)
    cost_stress, cost_stress_summary = run_cost_stress(events, path, selected_config)
    mc, mc_summary = run_monte_carlo(trades, selected_config)
    scorecard = score_tradable_setup(selection, fixed_summary, cost_stress_summary, mc_summary)
    release_status, blockers, release_classification = _release_status(scorecard, scope=scope)
    artifacts = {
        "grid": chapter_dir / "priority_strategy_grid.csv",
        "selected_strategy": chapter_dir / "selected_strategy.json",
        "scorecard": chapter_dir / "scorecard.json",
        "release_candidate": chapter_dir / "release_candidate.json",
        "rule_contract": chapter_dir / "rule_contract.json",
        "trades": chapter_dir / "selected_trades.csv",
        "equity_curve": chapter_dir / "selected_equity_curve.csv",
        "adaptive_walk_forward": chapter_dir / "adaptive_walk_forward.csv",
        "fixed_walk_forward": chapter_dir / "fixed_walk_forward.csv",
        "cost_stress": chapter_dir / "cost_stress.csv",
        "monte_carlo": chapter_dir / "monte_carlo.csv",
        "summary": chapter_dir / "priority_optimization_summary.json",
    }
    _write_grid_csv(artifacts["grid"], rows)
    trades.to_csv(artifacts["trades"], index=False)
    curve.to_csv(artifacts["equity_curve"], index=False)
    adaptive_wf.to_csv(artifacts["adaptive_walk_forward"], index=False)
    fixed_wf.to_csv(artifacts["fixed_walk_forward"], index=False)
    cost_stress.to_csv(artifacts["cost_stress"], index=False)
    mc.to_csv(artifacts["monte_carlo"], index=False)
    _write_json(
        artifacts["selected_strategy"],
        selection
        | {
            "adaptive_walk_forward_summary": adaptive_summary,
            "fixed_walk_forward_summary": fixed_summary,
            "cost_stress_summary": cost_stress_summary,
            "monte_carlo_summary": mc_summary,
            "source_scope": source_scope,
        },
    )
    _write_json(artifacts["scorecard"], scorecard)
    release = {
        "release_id": f"{pattern_id}_priority_tradable_gate_v1",
        "layer_id": PRIORITY_LAYER_ID,
        "pattern_id": pattern_id,
        "release_status": release_status,
        "classification": release_classification,
        "score": scorecard.get("score"),
        "scope": scope,
        "selected_strategy_id": selection.get("selected_strategy_id"),
        "failures": blockers,
        "claim_level": "tradable-final-95" if release_status == "PASS" else "priority optimized but not promoted",
    }
    _write_json(artifacts["release_candidate"], release)
    _write_json(
        artifacts["rule_contract"],
        {
            "layer_id": PRIORITY_LAYER_ID,
            "pattern_id": pattern_id,
            "scope": scope,
            "branch_count": len(configs),
            "selection_policy": selection.get("selection_basis"),
            "selected_config": asdict(selected_config),
            "scanner_unchanged": True,
            "holdout_used_for_selection": False,
        },
    )
    summary = {
        "layer_id": PRIORITY_LAYER_ID,
        "pattern_id": pattern_id,
        "status": "complete",
        "scope": scope,
        "source_scope": source_scope,
        "branch_count": len(configs),
        "selected_strategy_id": selection.get("selected_strategy_id"),
        "score": scorecard.get("score"),
        "classification": scorecard.get("classification"),
        "release_status": release_status,
        "release_classification": release_classification,
        "promotion_blockers": blockers,
        "selected_metrics": selected_summary,
        "fixed_walk_forward_summary": fixed_summary,
        "adaptive_walk_forward_summary": adaptive_summary,
        "cost_stress_summary": cost_stress_summary,
        "monte_carlo_summary": mc_summary,
        "artifacts": {key: str(value) for key, value in artifacts.items()},
    }
    _write_json(artifacts["summary"], summary)
    return summary


def build_priority_aggregate(rows: Sequence[Mapping[str, Any]], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "priority_candidates_summary.json"
    csv_path = out_dir / "priority_candidates_summary.csv"
    md_path = out_dir / "priority_candidates_summary.md"
    payload = {"layer_id": PRIORITY_LAYER_ID, "chapter_count": len(rows), "rows": list(rows)}
    _write_json(json_path, payload)
    fieldnames = [
        "pattern_id",
        "status",
        "scope",
        "branch_count",
        "score",
        "classification",
        "release_status",
        "release_classification",
        "selected_strategy_id",
        "promotion_blockers",
        "trades",
        "validation_total_return_pct",
        "holdout_total_return_pct",
        "fixed_positive_fold_rate_pct",
        "fixed_worst_fold_return_pct",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            metrics = row.get("selected_metrics") if isinstance(row.get("selected_metrics"), Mapping) else {}
            fixed = row.get("fixed_walk_forward_summary") if isinstance(row.get("fixed_walk_forward_summary"), Mapping) else {}
            writer.writerow(
                {
                    "pattern_id": row.get("pattern_id"),
                    "status": row.get("status"),
                    "scope": row.get("scope"),
                    "branch_count": row.get("branch_count"),
                    "score": row.get("score"),
                    "classification": row.get("classification"),
                    "release_status": row.get("release_status"),
                    "release_classification": row.get("release_classification"),
                    "selected_strategy_id": row.get("selected_strategy_id"),
                    "promotion_blockers": ",".join(row.get("promotion_blockers") or row.get("failures") or []),
                    "trades": metrics.get("trades"),
                    "validation_total_return_pct": metrics.get("validation_total_return_pct"),
                    "holdout_total_return_pct": metrics.get("holdout_total_return_pct"),
                    "fixed_positive_fold_rate_pct": fixed.get("positive_fold_rate_pct"),
                    "fixed_worst_fold_return_pct": fixed.get("worst_fold_return_pct"),
                }
            )
    lines = [
        "# Priority Candidate Tradable Optimization",
        "",
        f"Layer: `{PRIORITY_LAYER_ID}`",
        "",
        "| Pattern | Scope | Branches | Score | Release | Selected strategy | Blockers |",
        "|---|---|---:|---:|---|---|---|",
    ]
    for row in rows:
        score = "" if row.get("score") is None else f"{float(row.get('score')):.2f}"
        blockers = ", ".join(row.get("promotion_blockers") or row.get("failures") or [])
        lines.append(
            f"| {row.get('pattern_id')} | {row.get('scope')} | {row.get('branch_count') or ''} | {score} | {row.get('release_status')} / {row.get('release_classification')} | {row.get('selected_strategy_id')} | {blockers} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "csv": csv_path, "md": md_path}


def run_priority_candidates(
    *,
    out_dir: Path = DEFAULT_OUT_DIR,
    chapters: set[str] | None = None,
    reuse_existing: bool = False,
) -> dict[str, Path]:
    selected = tuple(pattern for pattern in PRIORITY_PATTERNS if chapters is None or pattern in chapters)
    rows = []
    for pattern_id in selected:
        existing = out_dir / pattern_id / "priority_optimization_summary.json"
        existing_external = out_dir / pattern_id / "priority_optimization_external_reference.json"
        if reuse_existing and existing.exists():
            rows.append(_read_json(existing))
            continue
        if reuse_existing and existing_external.exists():
            rows.append(_read_json(existing_external))
            continue
        print(f"priority optimizing: {pattern_id}", flush=True)
        rows.append(run_one_priority(pattern_id, out_dir))
    return build_priority_aggregate(rows, out_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run priority candidate tradable optimization.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--chapters", default="")
    parser.add_argument("--reuse-existing", action="store_true")
    args = parser.parse_args()
    chapters = {item.strip() for item in str(args.chapters).split(",") if item.strip()} or None
    paths = run_priority_candidates(out_dir=Path(args.out_dir), chapters=chapters, reuse_existing=bool(args.reuse_existing))
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
