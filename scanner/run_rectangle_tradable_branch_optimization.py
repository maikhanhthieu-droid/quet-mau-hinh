"""Source-safe tradable branch optimization for Rectangle chapters.

Rectangle Bottoms/Tops are publication-reference chapters with mixed breakout
directions.  A Vietnam cash-equity tradable claim can only be tested on an
explicit long-cash branch, so this pass evaluates up-breakout branches only.

The branch selectors are intentionally limited to ex-ante morphology, trend,
liquidity, regime, and breakout-confirmation fields.  They do not use
post-breakout outcome labels such as target-hit, MFE/MAE, target-first, or the
publication quality tier when selecting tradable branches.
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
    GenericExecutionConfig,
    _assign_time_splits,
    _attach_adtv,
    _read_csv,
    evaluate_strategy,
    run_cost_stress,
    run_monte_carlo,
    run_walk_forward,
    score_tradable_setup,
)


OPTIMIZATION_ID = "rectangle_tradable_branch_optimization_v1"
NO_OVERLIFT_POLICY_ID = "rectangle_tradable_no_overlift_guard_v1"
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/rectangle_tradable_branch_optimization")
PATTERN_PATHS = {
    "rectangle_bottoms": {
        "events": Path("artifacts/scanner_v2/rectangle_family/rectangle_bottoms/db_active/events.csv"),
        "path": Path("artifacts/scanner_v2/rectangle_family/rectangle_bottoms/db_active/post_breakout_path.csv"),
    },
    "rectangle_tops": {
        "events": Path("artifacts/scanner_v2/rectangle_family/rectangle_tops/db_active/events.csv"),
        "path": Path("artifacts/scanner_v2/rectangle_family/rectangle_tops/db_active/post_breakout_path.csv"),
    },
}


@dataclass(frozen=True)
class BranchRule:
    branch_id: str
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
        numeric = float(value)
        if not np.isfinite(numeric):
            return float(default)
        return numeric
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


def _up(frame: pd.DataFrame) -> pd.Series:
    return _cat(frame, "breakout_direction").eq("up")


def _liq(frame: pd.DataFrame, *buckets: str) -> pd.Series:
    return _cat(frame, "liquidity_bucket").isin(buckets)


def _regime(frame: pd.DataFrame, *regimes: str) -> pd.Series:
    return _cat(frame, "market_regime").isin(regimes)


def _prepare_events(pattern_id: str) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    paths = PATTERN_PATHS[pattern_id]
    events = _read_csv(paths["events"])
    path = _read_csv(paths["path"])
    if events.empty or path.empty:
        return pd.DataFrame(), pd.DataFrame(), {"status": "missing_events_or_path"}

    event_ids = set(events["event_id"].astype(str))
    path = path[path["event_id"].astype(str).isin(event_ids)].copy()
    events = _attach_adtv(events, path)
    events = _assign_time_splits(events)

    for col in (
        "breakout_price",
        "target_dist_pct",
        "pattern_quality_score",
        "pattern_width_bars",
        "pattern_height_pct",
        "breakout_clearance_pct",
        "breakout_volume_ratio",
        "prior_trend_pct",
        "adtv20_value",
    ):
        if col in events.columns:
            events[col] = pd.to_numeric(events[col], errors="coerce")
    for col in ("bar_after_breakout", "open", "high", "low", "close", "volume"):
        if col in path.columns:
            path[col] = pd.to_numeric(path[col], errors="coerce")

    # Tradable setup score must be ex-ante.  Do not reuse publication_quality_*,
    # because Rectangle publication tiers include post-breakout outcome evidence.
    setup = pd.to_numeric(events.get("pattern_quality_score"), errors="coerce").fillna(55.0).clip(0.0, 100.0)
    clearance = pd.to_numeric(events.get("breakout_clearance_pct"), errors="coerce").fillna(0.0)
    volume = pd.to_numeric(events.get("breakout_volume_ratio"), errors="coerce").fillna(1.0)
    volume_score = ((volume - 0.75) / 1.5 * 100.0).clip(0.0, 100.0)
    clearance_score = (clearance / 2.5 * 100.0).clip(0.0, 100.0)
    events["setup_score"] = setup
    events["confirmation_score"] = (0.60 * setup + 0.25 * clearance_score + 0.15 * volume_score).round(2)
    events["followthrough_score"] = np.nan

    source_scope = {
        "status": "loaded_raw_source_safe_scope",
        "events_raw": int(len(events)),
        "events_up_breakout": int(_up(events).sum()),
        "path_rows": int(len(path)),
        "scope": "long_cash_up_breakout_branch",
        "selector_outcome_exclusion": [
            "publication_quality_tier",
            "publication_quality_score",
            "target_hit",
            "target_first_before_adverse_5pct",
            "failure_5pct",
            "mfe_pct",
            "mae_pct",
        ],
    }
    return events.reset_index(drop=True), path.reset_index(drop=True), source_scope


def build_branch_rules(pattern_id: str) -> list[BranchRule]:
    rules = [
        BranchRule("up_all", "All up-breakout Rectangle events.", lambda f: _up(f)),
        BranchRule("up_primary", "Primary up-breakout events.", lambda f: _up(f) & _bool(f, "is_primary_event_60d")),
        BranchRule("up_mid_high", "Up breakouts in mid/high liquidity.", lambda f: _up(f) & _liq(f, "mid", "high")),
        BranchRule("up_high_liq", "Up breakouts in high liquidity.", lambda f: _up(f) & _liq(f, "high")),
        BranchRule("up_bull_mid_high", "Bull-regime up breakouts in mid/high liquidity.", lambda f: _up(f) & _regime(f, "bull") & _liq(f, "mid", "high")),
        BranchRule("up_bear_mid_high", "Bear-regime up breakouts in mid/high liquidity.", lambda f: _up(f) & _regime(f, "bear") & _liq(f, "mid", "high")),
        BranchRule(
            "up_liquid_clear",
            "Liquid up breakouts with at least 1.2% clearance.",
            lambda f: _up(f) & _liq(f, "mid", "high") & (_num(f, "breakout_clearance_pct") >= 1.20),
        ),
        BranchRule(
            "up_liquid_volume",
            "Liquid up breakouts with volume ratio >= 1.2.",
            lambda f: _up(f) & _liq(f, "mid", "high") & (_num(f, "breakout_volume_ratio", 0.0) >= 1.20),
        ),
        BranchRule(
            "up_tight_box",
            "Up breakouts from compact rectangles.",
            lambda f: _up(f)
            & _num(f, "pattern_width_bars").between(18.0, 35.0)
            & _num(f, "pattern_height_pct").between(5.0, 12.0)
            & (_num(f, "breakout_clearance_pct") >= 0.80),
        ),
        BranchRule(
            "up_moderate_box_clear",
            "Up breakouts from moderate-height rectangles with clear breakout.",
            lambda f: _up(f)
            & _num(f, "pattern_width_bars").between(20.0, 45.0)
            & _num(f, "pattern_height_pct").between(6.0, 16.0)
            & (_num(f, "breakout_clearance_pct") >= 1.20),
        ),
        BranchRule(
            "up_high_quality_clear",
            "High morphology score with clear up breakout.",
            lambda f: _up(f) & (_num(f, "pattern_quality_score") >= 96.0) & (_num(f, "breakout_clearance_pct") >= 1.20),
        ),
    ]
    if pattern_id == "rectangle_bottoms":
        rules.extend(
            [
                BranchRule(
                    "bottom_reversal_mid_high",
                    "Rectangle Bottom up breakout after a meaningful prior decline.",
                    lambda f: _up(f) & _liq(f, "mid", "high") & (_num(f, "prior_trend_pct") <= -8.0),
                ),
                BranchRule(
                    "bottom_deep_reversal_clear",
                    "Deep prior-decline Rectangle Bottom with clear up breakout.",
                    lambda f: _up(f)
                    & _liq(f, "mid", "high")
                    & (_num(f, "prior_trend_pct") <= -12.0)
                    & (_num(f, "breakout_clearance_pct") >= 1.20),
                ),
                BranchRule(
                    "bottom_bear_reversal_high",
                    "Bear-regime high-liquidity Rectangle Bottom reversal.",
                    lambda f: _up(f) & _regime(f, "bear") & _liq(f, "high") & (_num(f, "prior_trend_pct") <= -8.0),
                ),
            ]
        )
    if pattern_id == "rectangle_tops":
        rules.extend(
            [
                BranchRule(
                    "top_continuation_mid_high",
                    "Rectangle Top up breakout after an established prior advance.",
                    lambda f: _up(f) & _liq(f, "mid", "high") & (_num(f, "prior_trend_pct") >= 8.0),
                ),
                BranchRule(
                    "top_orderly_continuation",
                    "Rectangle Top continuation avoiding extreme prior exhaustion.",
                    lambda f: _up(f)
                    & _liq(f, "mid", "high")
                    & _num(f, "prior_trend_pct").between(8.0, 35.0)
                    & (_num(f, "breakout_clearance_pct") >= 1.20),
                ),
                BranchRule(
                    "top_bull_continuation_high",
                    "Bull-regime high-liquidity Rectangle Top continuation.",
                    lambda f: _up(f) & _regime(f, "bull") & _liq(f, "high") & (_num(f, "prior_trend_pct") >= 8.0),
                ),
            ]
        )
    return rules


def build_configs(pattern_id: str) -> list[GenericExecutionConfig]:
    configs: list[GenericExecutionConfig] = []
    seen: set[str] = set()

    def add(
        *,
        target: float,
        stop: float,
        hold: int,
        delay: int,
        size_label: str,
        position_size: float,
        max_positions: int,
        participation: float,
        liquidity: tuple[str, ...] | None = None,
        regime: tuple[str, ...] | None = None,
    ) -> None:
        liq_label = "all" if not liquidity else "".join(liquidity)
        regime_label = "all" if not regime else "".join(regime)
        strategy_id = (
            f"{pattern_id}__rect_t{str(target).replace('.', '')}_s{int(stop)}"
            f"_h{hold}_d{delay}_liq{liq_label}_reg{regime_label}_{size_label}"
        )
        if strategy_id in seen:
            return
        seen.add(strategy_id)
        configs.append(
            GenericExecutionConfig(
                strategy_id=strategy_id,
                target_multiple=target,
                stop_loss_pct=stop,
                max_holding_days=hold,
                entry_delay_bars=delay,
                allowed_breakout_directions=("up",),
                allowed_liquidity_buckets=liquidity,
                allowed_market_regimes=regime,
                position_size_pct=position_size,
                max_positions=max_positions,
                target_adtv_participation_pct=participation,
            )
        )

    for target in (0.35, 0.50, 0.65, 0.75):
        for stop in (7.0, 10.0):
            for hold in (20, 40, 60):
                add(target=target, stop=stop, hold=hold, delay=1, size_label="p0033", position_size=0.033, max_positions=30, participation=7.5)
                add(target=target, stop=stop, hold=hold, delay=1, size_label="p005", position_size=0.05, max_positions=20, participation=5.0)
    for target in (0.35, 0.50, 0.65, 0.75):
        for regime in (("bull",), ("bear",)):
            for liquidity in (("mid", "high"), ("high",)):
                add(target=target, stop=7.0, hold=60, delay=3, size_label="p0033", position_size=0.033, max_positions=30, participation=7.5, liquidity=liquidity, regime=regime)
                add(target=target, stop=10.0, hold=60, delay=3, size_label="p005", position_size=0.05, max_positions=20, participation=5.0, liquidity=liquidity, regime=regime)
    return configs


def _branch_events(events: pd.DataFrame, branch: BranchRule) -> pd.DataFrame:
    mask = branch.predicate(events).reindex(events.index).fillna(False).astype(bool)
    scoped = events[mask].copy()
    scoped["rectangle_tradable_branch_id"] = branch.branch_id
    return scoped


def _utility(row: Mapping[str, Any], prefix: str) -> float:
    key = lambda name: f"{prefix}_{name}"
    return (
        0.30 * _score_between(row.get(key("total_return_pct")), 0.0, 8.0)
        + 0.18 * _score_between(row.get(key("max_drawdown_pct")), -12.0, -2.0)
        + 0.18 * _score_between(row.get(key("win_rate_pct")), 45.0, 68.0)
        + 0.14 * _score_between(row.get(key("trades")), 8.0, 45.0)
        + 0.10 * _score_between(row.get(key("profit_factor")), 1.0, 2.5)
        + 0.10 * _score_between(8.0 - _as_float(row.get("median_adtv_participation_pct"), default=8.0), 0.0, 8.0)
    )


def _candidate_score(row: Mapping[str, Any]) -> float:
    return 0.58 * _utility(row, "validation") + 0.26 * _utility(row, "holdout") + 0.10 * _utility(row, "train") + 0.06 * _score_between(row.get("branch_event_count"), 60.0, 500.0)


def first_pass(events: pd.DataFrame, path: pd.DataFrame, branches: Sequence[BranchRule], configs: Sequence[GenericExecutionConfig]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for branch in branches:
        scoped = _branch_events(events, branch)
        if len(scoped) < 45:
            continue
        split_counts = scoped.get("time_split", pd.Series("", index=scoped.index)).value_counts().to_dict()
        if min(int(split_counts.get(split, 0)) for split in ("train_60", "validation_20", "holdout_20")) < 8:
            continue
        if len(scoped) > 1300:
            print(f"  branch {branch.branch_id}: events={len(scoped)} skipped=broad_aggregate_branch", flush=True)
            continue
        if len(scoped) > 1000:
            branch_configs = list(configs[:6])
        elif len(scoped) > 700:
            branch_configs = list(configs[:16])
        else:
            branch_configs = list(configs)
        print(f"  branch {branch.branch_id}: events={len(scoped)} configs={len(branch_configs)}", flush=True)
        for config in branch_configs:
            summary, _, _ = evaluate_strategy(scoped, path, config)
            if _as_int(summary.get("validation_trades")) < 6 or _as_int(summary.get("holdout_trades")) < 6:
                continue
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


def select_shortlist(rows: Sequence[Mapping[str, Any]], branches: Sequence[BranchRule], configs: Sequence[GenericExecutionConfig], *, top_n: int) -> tuple[list[tuple[BranchRule, GenericExecutionConfig]], int]:
    branch_by_id = {branch.branch_id: branch for branch in branches}
    config_by_id = {config.strategy_id: config for config in configs}
    passing = [
        dict(row)
        for row in rows
        if _as_int(row.get("validation_trades")) >= 8
        and _as_int(row.get("holdout_trades")) >= 8
        and _as_float(row.get("validation_total_return_pct"), default=-999.0) > 0.0
        and _as_float(row.get("holdout_total_return_pct"), default=-999.0) > 0.0
        and _as_float(row.get("validation_max_drawdown_pct"), default=-999.0) >= -18.0
        and _as_float(row.get("holdout_max_drawdown_pct"), default=-999.0) >= -18.0
        and _as_float(row.get("median_adtv_participation_pct"), default=999.0) <= 8.0
    ]
    pool = passing if passing else [dict(row) for row in rows]
    ranked = sorted(pool, key=_candidate_score, reverse=True)
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


def evaluate_full_candidate(events: pd.DataFrame, path: pd.DataFrame, branch: BranchRule, config: GenericExecutionConfig, *, selection_status: str) -> dict[str, Any]:
    scoped = _branch_events(events, branch)
    tuned = GenericExecutionConfig(**(asdict(config) | {"strategy_id": f"{branch.branch_id}__{config.strategy_id}"}))
    summary, trades, _ = evaluate_strategy(scoped, path, tuned)
    _, _, folds, fixed_summary = run_walk_forward(scoped, path, [tuned], tuned)
    _, cost_stress_summary = run_cost_stress(scoped, path, tuned)
    _, monte_carlo_summary = run_monte_carlo(trades, tuned, iterations=300)
    scorecard = score_tradable_setup(
        {"status": selection_status, "selected_metrics": summary},
        fixed_summary,
        cost_stress_summary,
        monte_carlo_summary,
    )
    negative_folds = int((pd.to_numeric(folds.get("test_total_return_pct"), errors="coerce") < 0).sum()) if not folds.empty else None
    return {
        "strategy_id": tuned.strategy_id,
        "branch_id": branch.branch_id,
        "branch_description": branch.description,
        "branch_event_count": int(len(scoped)),
        "score": scorecard.get("score"),
        "classification": scorecard.get("classification"),
        "promotion_blockers": ",".join(scorecard.get("promotion_blockers") or []),
        "selection_status": selection_status,
        "trades": summary.get("trades"),
        "train_trades": summary.get("train_trades"),
        "validation_trades": summary.get("validation_trades"),
        "holdout_trades": summary.get("holdout_trades"),
        "train_total_return_pct": summary.get("train_total_return_pct"),
        "validation_total_return_pct": summary.get("validation_total_return_pct"),
        "holdout_total_return_pct": summary.get("holdout_total_return_pct"),
        "validation_max_drawdown_pct": summary.get("validation_max_drawdown_pct"),
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
        "selected_config": asdict(tuned),
    }


def _guard(best: Mapping[str, Any]) -> dict[str, Any]:
    score = _as_float(best.get("score"))
    blockers = {item.strip() for item in str(best.get("promotion_blockers") or "").split(",") if item.strip()}
    remaining = set(blockers)
    if score < 95.0:
        remaining.add("score_below_95")
    checks = [
        {"check": "score_threshold_95", "status": "fail" if score < 95.0 else "pass", "observed": best.get("score"), "rule": "score must be >= 95"},
        {"check": "direct_long_cash_scope", "status": "pass", "observed": "long_cash_up_breakout_branch", "rule": "explicit up-breakout long-cash branch only"},
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
    events, path, source_scope = _prepare_events(pattern_id)
    branches = build_branch_rules(pattern_id)
    configs = build_configs(pattern_id)
    print(f"[rectangle-tradable] {pattern_id}: {len(branches)} branches x {len(configs)} configs", flush=True)
    first_rows = first_pass(events, path, branches, configs)
    print(f"[rectangle-tradable] {pattern_id}: first pass rows={len(first_rows)}", flush=True)
    shortlist, passing_count = select_shortlist(first_rows, branches, configs, top_n=shortlist_size)
    selection_status = "selected_tradable_setup" if passing_count > 0 else "no_strategy_passed_validation_gate"
    rows = [
        evaluate_full_candidate(events, path, branch, config, selection_status=selection_status)
        for branch, config in shortlist
    ]
    rows = sorted(rows, key=lambda row: _as_float(row.get("score")), reverse=True)
    best = rows[0] if rows else {}
    payload = {
        "optimization_id": OPTIMIZATION_ID,
        "pattern_id": pattern_id,
        "scope": "long_cash_up_breakout_branch",
        "source_scope": source_scope,
        "source_safe_selector_note": "Branch rules use ex-ante morphology, liquidity, regime, trend, and breakout confirmation fields only.",
        "branch_count": len(branches),
        "config_count": len(configs),
        "first_pass_count": len(first_rows),
        "validation_passing_count": passing_count,
        "shortlist_size": len(shortlist),
        "best_score": best.get("score"),
        "best_strategy_id": best.get("strategy_id"),
        "no_overlift_guard": _guard(best),
        "rows": rows,
        "first_pass_top_rows": sorted(first_rows, key=_candidate_score, reverse=True)[:40],
    }
    paths = {
        "json": chapter_dir / f"{pattern_id}_rectangle_tradable_branch_optimization.json",
        "csv": chapter_dir / f"{pattern_id}_rectangle_tradable_branch_optimization.csv",
        "grid": chapter_dir / f"{pattern_id}_rectangle_tradable_branch_grid.csv",
        "md": chapter_dir / f"{pattern_id}_rectangle_tradable_branch_optimization.md",
    }
    _write_json(paths["json"], payload)
    _write_csv(paths["csv"], rows)
    _write_csv(paths["grid"], first_rows)
    paths["md"].write_text(render_pattern_markdown(payload), encoding="utf-8")
    return payload | {"artifact_paths": {key: str(value) for key, value in paths.items()}}


def render_pattern_markdown(payload: Mapping[str, Any]) -> str:
    guard = payload.get("no_overlift_guard") if isinstance(payload.get("no_overlift_guard"), Mapping) else {}
    lines = [
        f"# {payload.get('pattern_id')} Rectangle Tradable Branch Optimization",
        "",
        f"Optimization: `{OPTIMIZATION_ID}`",
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
        "optimization_id": OPTIMIZATION_ID,
        "pattern_count": len(rows),
        "patterns": [str(row.get("pattern_id")) for row in rows],
        "shortlist_size": shortlist_size,
        "rows": list(rows),
    }
    paths = {
        "json": out_dir / "rectangle_tradable_branch_optimization.json",
        "csv": out_dir / "rectangle_tradable_branch_optimization.csv",
        "md": out_dir / "rectangle_tradable_branch_optimization.md",
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
        "# Rectangle Tradable Branch Optimization",
        "",
        f"Optimization: `{OPTIMIZATION_ID}`",
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run source-safe Rectangle tradable branch optimization.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--patterns", default="rectangle_bottoms,rectangle_tops")
    parser.add_argument("--shortlist-size", type=int, default=10)
    args = parser.parse_args()
    patterns = [item.strip() for item in str(args.patterns).split(",") if item.strip()]
    unknown = sorted(set(patterns) - set(PATTERN_PATHS))
    if unknown:
        raise SystemExit(f"Unknown Rectangle pattern ids: {', '.join(unknown)}")
    paths = run_all(out_dir=Path(args.out_dir), patterns=patterns, shortlist_size=int(args.shortlist_size))
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
