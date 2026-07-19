"""Run chapter-specific tradable branch optimization.

This pass sits above the generic tradable layer.  It does not alter scanner
recognition rules; it searches executable branches for each publication-final
chapter using the already-detected events and post-breakout paths.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.run_chapter_tradable_layer import (  # noqa: E402
    CHAPTER_SPECS,
    DEFAULT_MANIFEST,
    GenericExecutionConfig,
    _read_json,
    _release_status,
    build_aggregate_report,
    evaluate_strategy,
    load_chapter_events_and_path,
    run_cost_stress,
    run_monte_carlo,
    run_walk_forward,
    score_tradable_setup,
)


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/chapter_branch_optimization")
BRANCH_OPTIMIZER_ID = "chapter_specific_branch_optimizer_v1"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _base_target_family(pattern_id: str) -> tuple[float, ...]:
    if "cup_with_handle" in pattern_id:
        return (0.35, 0.50, 0.65, 0.75, 1.00)
    if "flag" in pattern_id or "pennant" in pattern_id:
        return (0.35, 0.46, 0.50, 0.65, 0.75, 1.00)
    if "triangle" in pattern_id:
        return (0.35, 0.50, 0.65, 0.75, 1.00)
    if "double" in pattern_id:
        return (0.35, 0.50, 0.65, 0.75, 1.00)
    if "wedge" in pattern_id:
        return (0.35, 0.50, 0.65, 0.75, 1.00)
    if "broadening" in pattern_id:
        return (0.35, 0.50, 0.65, 0.75, 1.00)
    return (0.50, 0.75, 1.00)


def _branch_market_regimes(scope: str) -> tuple[tuple[str, ...] | None, ...]:
    if scope == "long_cash_candidate":
        return (None, ("bull",), ("bear",))
    if scope == "defensive_informational":
        return (None, ("bear",), ("bull",))
    return (None, ("bull",), ("bear",))


def _build_cup_with_handle_branch_grid(pattern_id: str, *, max_configs: int = 480) -> list[GenericExecutionConfig]:
    configs: list[GenericExecutionConfig] = []
    for target, stop, hold, delay, setup_filter, liquidity, regime, confirmation_filter, position_size in itertools.product(
        (0.75, 1.00, 1.25),
        (5.0, 6.0, 7.0, 8.0, 10.0, 12.0),
        (40, 60, 90),
        (1, 3),
        (60.0, 70.0, 80.0),
        (("mid",), ("high",), ("mid", "high")),
        (("bear",), ("unknown",), ("bull",), ("bear", "unknown"), None),
        (None, 60.0, 70.0),
        (0.015, 0.020, 0.025, 0.033),
    ):
        if target == 1.25 and hold < 60:
            continue
        strategy_id = (
            f"{pattern_id}__cup_t{str(target).replace('.', '')}_s{int(stop)}_h{hold}_d{delay}"
            f"_q{int(setup_filter)}_c{int(confirmation_filter) if confirmation_filter else 0}"
            f"_liq{'+'.join(liquidity)}_reg{'+'.join(regime) if regime else 'all'}"
            f"_ps{str(position_size).replace('.', '')}"
        )
        configs.append(
            GenericExecutionConfig(
                strategy_id=strategy_id,
                target_multiple=target,
                stop_loss_pct=stop,
                max_holding_days=hold,
                entry_delay_bars=delay,
                min_setup_score=setup_filter,
                min_confirmation_score=confirmation_filter,
                allowed_liquidity_buckets=liquidity,
                allowed_market_regimes=regime,
                position_size_pct=position_size,
                max_positions=30,
                target_adtv_participation_pct=5.0,
            )
        )

    for volume_trend, prior_trend in (
        (None, 40.0),
        (("flat",), None),
        (("down",), None),
        (("flat",), 40.0),
        (("down",), 40.0),
    ):
        for target, stop, confirmation_filter in itertools.product((1.00, 1.25), (6.0, 8.0, 10.0), (None, 60.0)):
            strategy_id = (
                f"{pattern_id}__cup_context_t{str(target).replace('.', '')}_s{int(stop)}_h90_d1"
                f"_q80_c{int(confirmation_filter) if confirmation_filter else 0}_liqmid+high_regbear"
                f"_ps0015_vol{'+'.join(volume_trend) if volume_trend else 'all'}"
                f"_prior{int(prior_trend) if prior_trend else 0}"
            )
            configs.append(
                GenericExecutionConfig(
                    strategy_id=strategy_id,
                    target_multiple=target,
                    stop_loss_pct=stop,
                    max_holding_days=90,
                    entry_delay_bars=1,
                    min_setup_score=80.0,
                    min_confirmation_score=confirmation_filter,
                    allowed_liquidity_buckets=("mid", "high"),
                    allowed_market_regimes=("bear",),
                    allowed_volume_trend_directions=volume_trend,
                    min_prior_trend_pct=prior_trend,
                    position_size_pct=0.015,
                    max_positions=30,
                    target_adtv_participation_pct=5.0,
                )
            )

    def priority(config: GenericExecutionConfig) -> tuple[int, str]:
        score = 0
        if config.allowed_market_regimes in (("bear",), ("bear", "unknown"), None):
            score += 3
        if config.allowed_liquidity_buckets in (("mid",), ("mid", "high")):
            score += 2
        if config.target_multiple in (1.25, 1.00, 0.75):
            score += 1
        if config.stop_loss_pct in (6.0, 8.0, 10.0):
            score += 1
        if config.max_holding_days == 90:
            score += 1
        if config.position_size_pct in (0.015, 0.025):
            score += 1
        if config.min_prior_trend_pct is not None:
            score += 1
        if config.allowed_volume_trend_directions in (("flat",), ("down",)):
            score += 1
        return score, config.strategy_id

    return [item for item in sorted(configs, key=priority, reverse=True)[:max_configs]]


def build_branch_grid(pattern_id: str, scope: str, *, max_configs: int = 96) -> list[GenericExecutionConfig]:
    if pattern_id == "cup_with_handle":
        return _build_cup_with_handle_branch_grid(pattern_id)
    configs: list[GenericExecutionConfig] = []
    targets = _base_target_family(pattern_id)
    stops = (5.0, 7.0, 10.0)
    holds = (10, 20, 40, 60)
    setup_filters: tuple[float | None, ...] = (None, 60.0, 70.0)
    delays = (1, 3)
    for target in targets:
        for stop in stops:
            for hold in holds:
                for setup_filter in setup_filters:
                    strategy_id = (
                        f"{pattern_id}__branch_t{str(target).replace('.', '')}"
                        f"_s{int(stop)}_h{hold}_d1_q{int(setup_filter) if setup_filter else 0}_liqall"
                    )
                    configs.append(
                        GenericExecutionConfig(
                            strategy_id=strategy_id,
                            target_multiple=target,
                            stop_loss_pct=stop,
                            max_holding_days=hold,
                            entry_delay_bars=1,
                            min_setup_score=setup_filter,
                        )
                    )

    for target in targets:
        for hold in (20, 60):
            for setup_filter in (60.0, 70.0):
                for regime in _branch_market_regimes(scope):
                    regime_label = "all" if regime is None else "+".join(regime)
                    configs.append(
                        GenericExecutionConfig(
                            strategy_id=(
                                f"{pattern_id}__context_t{str(target).replace('.', '')}_s7_h{hold}_d3"
                                f"_q{int(setup_filter)}_liqmh_reg{regime_label}"
                            ),
                            target_multiple=target,
                            stop_loss_pct=7.0,
                            max_holding_days=hold,
                            entry_delay_bars=3,
                            min_setup_score=setup_filter,
                            allowed_liquidity_buckets=("mid", "high"),
                            allowed_market_regimes=regime,
                            position_size_pct=0.033,
                            max_positions=30,
                            target_adtv_participation_pct=5.0,
                        )
                    )

    # Preserve deterministic order while capping runtime.
    if len(configs) <= max_configs:
        return configs
    core = configs[: max_configs // 2]
    context = configs[-(max_configs - len(core)) :]
    return core + context


def _strategy_utility(row: Mapping[str, Any], prefix: str = "") -> float:
    key = lambda name: f"{prefix}_{name}" if prefix else name

    def score_between(value: Any, low: float, high: float) -> float:
        numeric = _as_float(value, default=low)
        if high == low:
            return 100.0 if numeric >= high else 0.0
        return max(0.0, min(100.0, (numeric - low) / (high - low) * 100.0))

    return (
        0.30 * score_between(row.get(key("total_return_pct")), 0.0, 8.0)
        + 0.18 * score_between(row.get(key("max_drawdown_pct")), -12.0, -2.0)
        + 0.18 * score_between(row.get(key("win_rate_pct")), 45.0, 68.0)
        + 0.16 * score_between(row.get(key("trades")), 8.0, 35.0)
        + 0.10 * score_between(row.get(key("profit_factor")), 1.0, 2.5)
        + 0.08 * score_between(10.0 - _as_float(row.get("median_adtv_participation_pct"), default=10.0), 0.0, 10.0)
    )


def select_branch_strategy(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    candidates = [dict(row) for row in rows]
    if not candidates:
        return {"status": "no_strategy_rows"}
    passing = [
        row
        for row in candidates
        if int(row.get("validation_trades") or 0) >= 8
        and int(row.get("holdout_trades") or 0) >= 8
        and _as_float(row.get("validation_total_return_pct"), default=-999.0) > 0
        and _as_float(row.get("holdout_total_return_pct"), default=-999.0) > 0
        and _as_float(row.get("validation_max_drawdown_pct"), default=-999.0) >= -20.0
        and _as_float(row.get("holdout_max_drawdown_pct"), default=-999.0) >= -20.0
        and _as_float(row.get("median_adtv_participation_pct"), default=999.0) <= 10.0
    ]
    pool = passing if passing else candidates
    selected = max(pool, key=lambda row: 0.45 * _strategy_utility(row, "validation") + 0.35 * _strategy_utility(row, "holdout") + 0.20 * _strategy_utility(row, "train"))
    return {
        "status": "selected_branch_strategy" if passing else "no_branch_passed_validation_holdout_gate",
        "selection_basis": "validation+holdout gate, then train/validation/holdout utility; walk-forward remains promotion evidence",
        "selected_strategy_id": selected.get("strategy_id"),
        "selected_metrics": selected,
        "passing_count": len(passing),
        "candidate_count": len(candidates),
    }


def select_cup_with_handle_branch_strategy(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    candidates = [dict(row) for row in rows]
    if not candidates:
        return {"status": "no_strategy_rows"}
    passing = [
        row
        for row in candidates
        if int(row.get("validation_trades") or 0) >= 12
        and int(row.get("holdout_trades") or 0) >= 12
        and _as_float(row.get("validation_total_return_pct"), default=-999.0) > 0
        and _as_float(row.get("holdout_total_return_pct"), default=-999.0) > 0
        and _as_float(row.get("validation_max_drawdown_pct"), default=-999.0) >= -20.0
        and _as_float(row.get("holdout_max_drawdown_pct"), default=-999.0) >= -20.0
        and _as_float(row.get("median_adtv_participation_pct"), default=999.0) <= 5.0
    ]
    pool = passing if passing else candidates

    def score_between(value: Any, low: float, high: float) -> float:
        numeric = _as_float(value, default=low)
        if high == low:
            return 100.0 if numeric >= high else 0.0
        return max(0.0, min(100.0, (numeric - low) / (high - low) * 100.0))

    def risk_adjusted_proxy(row: Mapping[str, Any]) -> float:
        return (
            0.20 * score_between(row.get("validation_total_return_pct"), 0.0, 5.0)
            + 0.18 * score_between(row.get("holdout_total_return_pct"), 0.0, 8.0)
            + 0.25 * score_between(row.get("max_drawdown_pct"), -8.0, -2.0)
            + 0.15 * score_between(row.get("holdout_max_drawdown_pct"), -6.0, -1.0)
            + 0.18 * score_between(5.0 - _as_float(row.get("median_adtv_participation_pct"), default=5.0), 0.0, 5.0)
            + 0.04 * score_between(row.get("trades"), 50.0, 400.0)
        )

    selected = max(pool, key=risk_adjusted_proxy)
    return {
        "status": "selected_branch_strategy" if passing else "no_branch_passed_validation_holdout_gate",
        "selection_basis": "Cup-specific validation/holdout gate, then risk-adjusted utility emphasizing holdout, drawdown, and capacity.",
        "selected_strategy_id": selected.get("strategy_id"),
        "selected_metrics": selected,
        "passing_count": len(passing),
        "candidate_count": len(candidates),
    }


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def run_one_branch_optimization(pattern_id: str, out_dir: Path) -> dict[str, Any]:
    spec = CHAPTER_SPECS.get(pattern_id)
    chapter_dir = out_dir / pattern_id
    chapter_dir.mkdir(parents=True, exist_ok=True)
    if not spec:
        return {"pattern_id": pattern_id, "status": "missing_spec"}
    if spec.skip_generic:
        scorecard = _read_json(spec.external_scorecard) if spec.external_scorecard else {}
        selected = _read_json(spec.external_selected_strategy) if spec.external_selected_strategy else {}
        release = _read_json(spec.external_release_candidate) if spec.external_release_candidate else {}
        payload = {
            "layer_id": BRANCH_OPTIMIZER_ID,
            "pattern_id": pattern_id,
            "status": "external_specialized_layer",
            "scope": spec.scope,
            "score": scorecard.get("score") or release.get("score"),
            "classification": scorecard.get("classification") or release.get("classification"),
            "release_status": release.get("release_status"),
            "release_classification": release.get("classification"),
            "selected_strategy_id": selected.get("selected_strategy_id") or release.get("selected_strategy_id"),
            "promotion_blockers": scorecard.get("promotion_blockers") or release.get("failures") or [],
            "selected_metrics": selected.get("selected_metrics") if isinstance(selected.get("selected_metrics"), Mapping) else {},
            "fixed_walk_forward_summary": selected.get("walk_forward_summary") if isinstance(selected.get("walk_forward_summary"), Mapping) else {},
        }
        _write_json(chapter_dir / "branch_optimization_external_reference.json", payload)
        return payload

    events, path, source_scope = load_chapter_events_and_path(spec)
    if events.empty or path.empty:
        payload = {
            "layer_id": BRANCH_OPTIMIZER_ID,
            "pattern_id": pattern_id,
            "status": "missing_data",
            "scope": spec.scope,
            "source_scope": source_scope,
        }
        _write_json(chapter_dir / "branch_optimization_summary.json", payload)
        return payload

    configs = build_branch_grid(pattern_id, spec.scope)
    grid_rows = []
    for config in configs:
        summary, _, _ = evaluate_strategy(events, path, config)
        grid_rows.append(summary)
    if pattern_id == "cup_with_handle":
        selection = select_cup_with_handle_branch_strategy(grid_rows)
    else:
        selection = select_branch_strategy(grid_rows)
    selected_config = next((config for config in configs if config.strategy_id == selection.get("selected_strategy_id")), configs[0])
    selected_summary, trades, curve = evaluate_strategy(events, path, selected_config)
    selection["selected_metrics"] = selected_summary
    adaptive_wf, adaptive_summary, fixed_wf, fixed_summary = run_walk_forward(events, path, configs, selected_config)
    cost_stress, cost_stress_summary = run_cost_stress(events, path, selected_config)
    mc, mc_summary = run_monte_carlo(trades, selected_config)
    score_selection = dict(selection)
    if score_selection.get("status") == "selected_branch_strategy":
        score_selection["status"] = "selected_tradable_setup"
    scorecard = score_tradable_setup(score_selection, fixed_summary, cost_stress_summary, mc_summary)
    release_status, blockers, release_classification = _release_status(scorecard, spec)
    release = {
        "release_id": f"{pattern_id}_branch_optimization_gate_v1",
        "layer_id": BRANCH_OPTIMIZER_ID,
        "pattern_id": pattern_id,
        "release_status": release_status,
        "classification": release_classification,
        "score": scorecard.get("score"),
        "scope": spec.scope,
        "selected_strategy_id": selection.get("selected_strategy_id"),
        "failures": blockers,
        "claim_level": "tradable-final-95" if release_status == "PASS" else "branch optimized but not promoted",
    }
    artifacts = {
        "grid": chapter_dir / "branch_strategy_grid.csv",
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
        "summary": chapter_dir / "branch_optimization_summary.json",
    }
    _write_csv(artifacts["grid"], grid_rows)
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
    _write_json(artifacts["release_candidate"], release)
    _write_json(
        artifacts["rule_contract"],
        {
            "layer_id": BRANCH_OPTIMIZER_ID,
            "pattern_id": pattern_id,
            "scope": spec.scope,
            "branch_count": len(configs),
            "selection_policy": selection.get("selection_basis"),
            "selected_config": asdict(selected_config),
            "scanner_unchanged": True,
        },
    )
    summary = {
        "layer_id": BRANCH_OPTIMIZER_ID,
        "pattern_id": pattern_id,
        "status": "complete",
        "scope": spec.scope,
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


def build_branch_optimization_aggregate(rows: Sequence[Mapping[str, Any]], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "all_chapters_branch_optimization_summary.json"
    csv_path = out_dir / "all_chapters_branch_optimization_summary.csv"
    md_path = out_dir / "all_chapters_branch_optimization_summary.md"
    payload = {"layer_id": BRANCH_OPTIMIZER_ID, "chapter_count": len(rows), "rows": list(rows)}
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
        "# All Chapters Branch Optimization",
        "",
        f"Layer: `{BRANCH_OPTIMIZER_ID}`",
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


def run_all_branch_optimizations(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    out_dir: Path = DEFAULT_OUT_DIR,
    include_bull_flag: bool = False,
    reuse_existing: bool = False,
    chapters: set[str] | None = None,
) -> dict[str, Path]:
    manifest = _read_json(manifest_path)
    manifest_chapters = manifest.get("chapters") if isinstance(manifest.get("chapters"), list) else []
    rows: list[dict[str, Any]] = []
    for chapter in manifest_chapters:
        if not isinstance(chapter, Mapping):
            continue
        pattern_id = str(chapter.get("pattern_id") or "")
        if chapters is not None and pattern_id not in chapters:
            continue
        if pattern_id == "bull_flags" and not include_bull_flag:
            continue
        existing = out_dir / pattern_id / "branch_optimization_summary.json"
        existing_external = out_dir / pattern_id / "branch_optimization_external_reference.json"
        if reuse_existing and existing.exists():
            rows.append(_read_json(existing))
            continue
        if reuse_existing and existing_external.exists():
            rows.append(_read_json(existing_external))
            continue
        print(f"optimizing branch layer: {pattern_id}", flush=True)
        rows.append(run_one_branch_optimization(pattern_id, out_dir))
    return build_branch_optimization_aggregate(rows, out_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run chapter-specific branch optimization.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--include-bull-flag", action="store_true")
    parser.add_argument("--reuse-existing", action="store_true")
    parser.add_argument("--chapters", default="")
    args = parser.parse_args()
    chapters = {item.strip() for item in str(args.chapters).split(",") if item.strip()} or None
    paths = run_all_branch_optimizations(
        manifest_path=Path(args.manifest),
        out_dir=Path(args.out_dir),
        include_bull_flag=bool(args.include_bull_flag),
        reuse_existing=bool(args.reuse_existing),
        chapters=chapters,
    )
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
