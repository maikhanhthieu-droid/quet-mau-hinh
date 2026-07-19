"""Run fixed Bull Flag tradable setup across available detector profiles."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.v2.bull_flag_tradable_setup import (  # noqa: E402
    DEFAULT_STRATEGY_GRID,
    FROZEN_STRATEGY_ID,
    ExecutionConfig,
    build_signal_trades,
    evaluate_strategy,
    load_bull_flag_v2_artifacts,
    monte_carlo_trade_sequence,
    run_portfolio,
    run_cost_stress,
    run_fixed_strategy_walk_forward,
    summarize_trades,
    score_tradable_setup,
)
from scanner.v2.bull_flag_localization import _apply_three_layer_scores  # noqa: E402
from scanner.v2.source_data import DEFAULT_SOURCE_DIR  # noqa: E402


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bull_flags_tradable_robustness")

NUMERIC_DIAGNOSTIC_COLUMNS = (
    "net_return_pct",
    "setup_score",
    "confirmation_score",
    "followthrough_score",
    "bull_flag_score_total",
    "flag_to_pole_pct",
    "pole_move_pct",
    "pattern_height_pct",
    "breakout_volume_ratio_20",
    "breakout_close_location",
    "breakout_body_to_range",
    "flag_range_to_pole_ratio",
    "entry_gap_pct",
    "pre_entry_close_return_pct",
    "pre_entry_mfe_pct",
    "pre_entry_mae_pct",
    "pre_entry_positive_close_share",
    "pre_entry_gain_capture_pct",
    "pre_entry_continuation_score",
    "risk_size_multiplier",
)
CATEGORICAL_DIAGNOSTIC_COLUMNS = (
    "market_regime",
    "liquidity_bucket",
    "bull_flag_tier",
    "setup_tier",
    "confirmation_tier",
    "followthrough_tier",
    "bull_flag_scanner_branch",
    "volume_confirmed",
    "retest_recovered_20d",
    "early_adverse_3pct_20d",
    "path_quality_bucket",
    "risk_size_reason",
    "exit_reason",
)


def discover_profile_dirs(root: Path) -> List[Path]:
    profile_dirs: List[Path] = []
    for events_path in root.glob("bull_flags*/**/events.csv"):
        profile_dir = events_path.parent
        if "smoke" in str(profile_dir):
            continue
        if "tradable_" in str(profile_dir):
            continue
        if not (profile_dir / "post_breakout_path.csv").exists():
            continue
        profile_dirs.append(profile_dir)
    return sorted(set(profile_dirs))


def _profile_id(profile_dir: Path, root: Path) -> str:
    try:
        return str(profile_dir.relative_to(root)).replace("/", "__")
    except ValueError:
        return profile_dir.name


def _fixed_selection(strategy_id: str, summary: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": "selected_tradable_setup",
        "selection_basis": "fixed_frozen_strategy_profile_robustness_no_reselection",
        "selected_strategy_id": strategy_id,
        "selected_metrics": summary,
        "passing_count": 1,
        "candidate_count": 1,
    }


def _classify_row(row: Dict[str, Any]) -> str:
    if int(row.get("validation_trades") or 0) < 12 or int(row.get("holdout_trades") or 0) < 12:
        return "underpowered"
    if row.get("promotion_blockers"):
        return "blocked"
    score = float(row.get("score") or 0.0)
    if score >= 95.0:
        return "pass_95"
    if score >= 90.0:
        return "pass_90"
    return "fail"


def normalize_profile_schema(events: pd.DataFrame, path: pd.DataFrame, *, source_dir: Path) -> tuple[pd.DataFrame, Dict[str, Any]]:
    if events.empty:
        return events.copy(), {"schema_status": "empty_events", "derived_columns": ""}
    required_scores = {"setup_score", "confirmation_score", "followthrough_score"}
    missing_scores = sorted(required_scores - set(events.columns))
    if not missing_scores:
        return events.copy(), {"schema_status": "native_v2_scores", "derived_columns": ""}
    scored = _apply_three_layer_scores(events, path, source_dir=source_dir)
    still_missing = sorted(required_scores - set(scored.columns))
    if still_missing:
        return scored, {"schema_status": "incompatible_schema", "derived_columns": ",".join(sorted(set(missing_scores) - set(still_missing))), "missing_required_columns": ",".join(still_missing)}
    return scored, {"schema_status": "derived_v2_scores", "derived_columns": ",".join(missing_scores)}


def _frozen_config() -> ExecutionConfig:
    config = next((item for item in DEFAULT_STRATEGY_GRID if item.strategy_id == FROZEN_STRATEGY_ID), None)
    if config is None:
        raise RuntimeError(f"Frozen strategy not found in DEFAULT_STRATEGY_GRID: {FROZEN_STRATEGY_ID}")
    return config


def candidate_screen_configs(config: ExecutionConfig) -> List[ExecutionConfig]:
    """Small causal-entry screen for diagnosing broad-profile fragility.

    These candidates only use fields available by the delayed entry bar. They
    are diagnostics, not a new frozen rule-selection process.
    """

    return [
        config,
        replace(config, strategy_id=f"{config.strategy_id}__delay4", entry_delay_bars=4),
        replace(config, strategy_id=f"{config.strategy_id}__gap3", max_entry_gap_pct=3.0),
        replace(config, strategy_id=f"{config.strategy_id}__gap25", max_entry_gap_pct=2.5),
        replace(config, strategy_id=f"{config.strategy_id}__delay4_gap3", entry_delay_bars=4, max_entry_gap_pct=3.0),
        replace(config, strategy_id=f"{config.strategy_id}__delay4_gap25", entry_delay_bars=4, max_entry_gap_pct=2.5),
        replace(config, strategy_id=f"{config.strategy_id}__pre_mae3", max_pre_entry_mae_pct=3.0),
        replace(config, strategy_id=f"{config.strategy_id}__pre_mae3_gap3", max_pre_entry_mae_pct=3.0, max_entry_gap_pct=3.0),
        replace(
            config,
            strategy_id=f"{config.strategy_id}__stage4_confirm50",
            entry_delay_bars=4,
            min_pre_entry_close_return_pct=0.0,
            max_pre_entry_mae_pct=4.0,
            min_pre_entry_positive_close_share=0.50,
            min_pre_entry_gain_capture_pct=35.0,
            min_pre_entry_continuation_score=50.0,
        ),
        replace(
            config,
            strategy_id=f"{config.strategy_id}__stage4_quality_sized",
            entry_delay_bars=4,
            risk_high_continuation_score_threshold=45.0,
            risk_low_continuation_score_threshold=60.0,
        ),
        replace(
            config,
            strategy_id=f"{config.strategy_id}__stage5_confirm55",
            entry_delay_bars=5,
            min_pre_entry_close_return_pct=0.25,
            max_pre_entry_mae_pct=4.0,
            min_pre_entry_positive_close_share=0.60,
            min_pre_entry_gain_capture_pct=40.0,
            min_pre_entry_continuation_score=55.0,
        ),
        replace(
            config,
            strategy_id=f"{config.strategy_id}__stage5_quality_sized",
            entry_delay_bars=5,
            risk_high_continuation_score_threshold=45.0,
            risk_low_continuation_score_threshold=60.0,
        ),
    ]


def _prefix_split_summary(summary: Dict[str, Any], split: str) -> Dict[str, Any]:
    return {f"{split}_{key}": value for key, value in summary.items() if key != "split"}


def _evaluate_signal_subset(signal_trades: pd.DataFrame, config: ExecutionConfig) -> Dict[str, Any]:
    portfolio, curve = run_portfolio(signal_trades, config)
    out = summarize_trades(portfolio, curve, split="all")
    for split_name, prefix in (("validation_20", "validation"), ("holdout_20", "holdout")):
        split_signals = signal_trades[signal_trades["time_split"].astype(str) == split_name].copy() if not signal_trades.empty else pd.DataFrame()
        split_portfolio, split_curve = run_portfolio(split_signals, config)
        out.update(_prefix_split_summary(summarize_trades(split_portfolio, split_curve, split=split_name), prefix))
    return out


def evaluate_candidate_screen(profile_dirs: Iterable[Path], root: Path, *, source_dir: Path) -> List[Dict[str, Any]]:
    base_config = _frozen_config()
    configs = candidate_screen_configs(base_config)
    normalized_profiles: List[tuple[str, pd.DataFrame, pd.DataFrame]] = []
    for profile_dir in profile_dirs:
        events, path = load_bull_flag_v2_artifacts(profile_dir)
        events, schema_info = normalize_profile_schema(events, path, source_dir=source_dir)
        if schema_info.get("schema_status") == "incompatible_schema":
            continue
        normalized_profiles.append((_profile_id(profile_dir, root), events, path))

    rows: List[Dict[str, Any]] = []
    for config in configs:
        profile_rows: List[Dict[str, Any]] = []
        for profile_id, events, path in normalized_profiles:
            signal_trades = build_signal_trades(events, path, config)
            summary = _evaluate_signal_subset(signal_trades, config)
            validation_trades = int(summary.get("validation_trades") or 0)
            holdout_trades = int(summary.get("holdout_trades") or 0)
            profile_rows.append(
                {
                    "profile_id": profile_id,
                    "eligible": validation_trades >= 12 and holdout_trades >= 12,
                    "trades": int(summary.get("trades") or 0),
                    "validation_trades": validation_trades,
                    "validation_total_return_pct": summary.get("validation_total_return_pct"),
                    "holdout_trades": holdout_trades,
                    "holdout_total_return_pct": summary.get("holdout_total_return_pct"),
                }
            )
        table = pd.DataFrame(profile_rows)
        eligible = table[table["eligible"]].copy() if not table.empty else pd.DataFrame()
        validation_returns = pd.to_numeric(eligible.get("validation_total_return_pct"), errors="coerce") if not eligible.empty else pd.Series(dtype=float)
        holdout_returns = pd.to_numeric(eligible.get("holdout_total_return_pct"), errors="coerce") if not eligible.empty else pd.Series(dtype=float)
        rows.append(
            {
                "strategy_id": config.strategy_id,
                "entry_delay_bars": config.entry_delay_bars,
                "max_entry_gap_pct": config.max_entry_gap_pct,
                "max_pre_entry_mae_pct": config.max_pre_entry_mae_pct,
                "min_pre_entry_positive_close_share": config.min_pre_entry_positive_close_share,
                "min_pre_entry_gain_capture_pct": config.min_pre_entry_gain_capture_pct,
                "min_pre_entry_continuation_score": config.min_pre_entry_continuation_score,
                "risk_high_continuation_score_threshold": config.risk_high_continuation_score_threshold,
                "risk_low_continuation_score_threshold": config.risk_low_continuation_score_threshold,
                "eligible_profiles": int(len(eligible)),
                "underpowered_profiles": int(len(table) - len(eligible)),
                "validation_positive_profiles": int((validation_returns > 0).sum()) if not validation_returns.empty else 0,
                "validation_positive_rate_pct": round(float((validation_returns > 0).mean()) * 100.0, 2) if not validation_returns.empty else None,
                "median_validation_return_pct": round(float(validation_returns.median()), 2) if not validation_returns.empty else None,
                "sum_validation_return_pct": round(float(validation_returns.sum()), 2) if not validation_returns.empty else None,
                "median_holdout_return_pct": round(float(holdout_returns.median()), 2) if not holdout_returns.empty else None,
                "sum_holdout_return_pct": round(float(holdout_returns.sum()), 2) if not holdout_returns.empty else None,
                "note": "diagnostic_screen_only_no_holdout_selection",
            }
        )
    return rows


def validation_trade_diagnostics(profile_dirs: Iterable[Path], root: Path, *, source_dir: Path) -> Dict[str, pd.DataFrame]:
    config = _frozen_config()
    trade_frames: List[pd.DataFrame] = []
    for profile_dir in profile_dirs:
        events, path = load_bull_flag_v2_artifacts(profile_dir)
        events, schema_info = normalize_profile_schema(events, path, source_dir=source_dir)
        if schema_info.get("schema_status") == "incompatible_schema":
            continue
        signal_trades = build_signal_trades(events, path, config)
        portfolio_trades, _ = run_portfolio(signal_trades, config)
        if portfolio_trades.empty:
            continue
        event_columns = [
            column
            for column in (
                "event_id",
                "bull_flag_score_total",
                "bull_flag_tier",
                "setup_tier",
                "confirmation_tier",
                "followthrough_tier",
                "bull_flag_scanner_branch",
                "flag_to_pole_pct",
                "pole_move_pct",
                "pattern_height_pct",
                "breakout_volume_ratio_20",
                "breakout_close_location",
                "breakout_body_to_range",
                "flag_range_to_pole_ratio",
                "volume_confirmed",
                "retest_recovered_20d",
                "early_adverse_3pct_20d",
                "path_quality_bucket",
            )
            if column in events.columns
        ]
        merged = portfolio_trades.merge(events[event_columns], on="event_id", how="left") if event_columns else portfolio_trades.copy()
        merged["profile_id"] = _profile_id(profile_dir, root)
        trade_frames.append(merged)
    all_trades = pd.concat(trade_frames, ignore_index=True) if trade_frames else pd.DataFrame()
    validation = all_trades[
        (all_trades.get("time_split", pd.Series(dtype=str)).astype(str) == "validation_20")
        & (all_trades.get("executed", pd.Series(False, index=all_trades.index)) == True)
    ].copy()
    if validation.empty:
        return {"validation_trades": validation, "numeric_diagnostics": pd.DataFrame(), "categorical_diagnostics": pd.DataFrame(), "profile_diagnostics": pd.DataFrame()}
    validation["is_win"] = pd.to_numeric(validation.get("net_return_pct"), errors="coerce") > 0.0
    numeric_rows: List[Dict[str, Any]] = []
    for column in NUMERIC_DIAGNOSTIC_COLUMNS:
        if column not in validation.columns:
            continue
        values = pd.to_numeric(validation[column], errors="coerce")
        losers = values[~validation["is_win"]].dropna()
        winners = values[validation["is_win"]].dropna()
        numeric_rows.append(
            {
                "metric": column,
                "loser_median": round(float(losers.median()), 4) if not losers.empty else None,
                "winner_median": round(float(winners.median()), 4) if not winners.empty else None,
                "median_spread_winner_minus_loser": round(float(winners.median() - losers.median()), 4) if not winners.empty and not losers.empty else None,
            }
        )
    categorical_rows: List[Dict[str, Any]] = []
    for column in CATEGORICAL_DIAGNOSTIC_COLUMNS:
        if column not in validation.columns:
            continue
        grouped = (
            validation.groupby(column, dropna=False)
            .agg(
                n=("net_return_pct", "size"),
                return_sum_pct=("net_return_pct", "sum"),
                return_mean_pct=("net_return_pct", "mean"),
                win_rate_pct=("is_win", "mean"),
            )
            .reset_index()
        )
        for _, row in grouped.iterrows():
            categorical_rows.append(
                {
                    "dimension": column,
                    "value": row[column],
                    "n": int(row["n"]),
                    "return_sum_pct": round(float(row["return_sum_pct"]), 4),
                    "return_mean_pct": round(float(row["return_mean_pct"]), 4),
                    "win_rate_pct": round(float(row["win_rate_pct"]) * 100.0, 2),
                }
            )
    profile_rows = (
        validation.groupby("profile_id")
        .agg(
            validation_trades=("net_return_pct", "size"),
            validation_return_sum_pct=("net_return_pct", "sum"),
            validation_mean_return_pct=("net_return_pct", "mean"),
            validation_win_rate_pct=("is_win", "mean"),
        )
        .reset_index()
    )
    profile_rows["validation_return_sum_pct"] = profile_rows["validation_return_sum_pct"].round(4)
    profile_rows["validation_mean_return_pct"] = profile_rows["validation_mean_return_pct"].round(4)
    profile_rows["validation_win_rate_pct"] = (profile_rows["validation_win_rate_pct"] * 100.0).round(2)
    return {
        "validation_trades": validation,
        "numeric_diagnostics": pd.DataFrame(numeric_rows),
        "categorical_diagnostics": pd.DataFrame(categorical_rows),
        "profile_diagnostics": profile_rows,
    }


def evaluate_profile(profile_dir: Path, root: Path, *, source_dir: Path, monte_carlo_iterations: int) -> Dict[str, Any]:
    config = _frozen_config()

    events, path = load_bull_flag_v2_artifacts(profile_dir)
    events, schema_info = normalize_profile_schema(events, path, source_dir=source_dir)
    if schema_info.get("schema_status") == "incompatible_schema":
        return {
            "profile_id": _profile_id(profile_dir, root),
            "profile_dir": str(profile_dir),
            "events_n": int(len(events)),
            "path_rows": int(len(path)),
            "fixed_strategy_id": config.strategy_id,
            "score": None,
            "classification": None,
            "promotion_blockers": "incompatible_schema",
            "missing_required_columns": schema_info.get("missing_required_columns"),
            "schema_status": schema_info.get("schema_status"),
            "derived_columns": schema_info.get("derived_columns"),
            "robustness_status": "incompatible_schema",
        }

    summary, trades, _ = evaluate_strategy(events, path, config)
    selection = _fixed_selection(config.strategy_id, summary)
    _, _, walk_forward_summary = run_fixed_strategy_walk_forward(events, path, config)
    _, cost_stress_summary = run_cost_stress(events, path, config)
    _, monte_carlo_summary = monte_carlo_trade_sequence(trades, config, iterations=monte_carlo_iterations)
    scorecard = score_tradable_setup(selection, walk_forward_summary, cost_stress_summary, monte_carlo_summary)

    row: Dict[str, Any] = {
        "profile_id": _profile_id(profile_dir, root),
        "profile_dir": str(profile_dir),
        "events_n": int(len(events)),
        "path_rows": int(len(path)),
        "fixed_strategy_id": config.strategy_id,
        "schema_status": schema_info.get("schema_status"),
        "derived_columns": schema_info.get("derived_columns"),
        "score": scorecard.get("score"),
        "classification": scorecard.get("classification"),
        "promotion_blockers": ",".join(scorecard.get("promotion_blockers") or []),
    }
    for key, value in (scorecard.get("component_scores") or {}).items():
        row[f"component_{key}"] = value
    for key in (
        "trades",
        "total_return_pct",
        "max_drawdown_pct",
        "win_rate_pct",
        "profit_factor",
        "median_adtv_participation_pct",
        "capacity_limited_rate_pct",
        "validation_trades",
        "validation_total_return_pct",
        "validation_max_drawdown_pct",
        "holdout_trades",
        "holdout_total_return_pct",
        "holdout_max_drawdown_pct",
        "risk_reduced_rate_pct",
        "risk_boosted_rate_pct",
    ):
        row[key] = summary.get(key)
    for key in ("folds", "test_trades", "positive_fold_rate_pct", "sum_fold_return_pct", "worst_fold_return_pct", "worst_fold_drawdown_pct"):
        row[f"walk_forward_{key}"] = walk_forward_summary.get(key)
    for key in ("positive_scenario_rate_pct", "worst_scenario_return_pct", "worst_scenario_drawdown_pct"):
        row[f"cost_stress_{key}"] = cost_stress_summary.get(key)
    for key in ("prob_positive_pct", "total_return_p05_pct", "total_return_p50_pct", "max_drawdown_p50_pct"):
        row[f"monte_carlo_{key}"] = monte_carlo_summary.get(key)
    row["robustness_status"] = _classify_row(row)
    return row


def summarize_rows(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    table = pd.DataFrame(list(rows))
    if table.empty:
        return {"status": "no_profiles"}
    eligible = table[~table["robustness_status"].isin(["underpowered", "incompatible_schema"])].copy()
    pass_90 = eligible[eligible["robustness_status"].isin(["pass_90", "pass_95"])]
    pass_95 = eligible[eligible["robustness_status"] == "pass_95"]
    return {
        "status": "complete",
        "profiles": int(len(table)),
        "eligible_profiles": int(len(eligible)),
        "underpowered_profiles": int((table["robustness_status"] == "underpowered").sum()),
        "incompatible_schema_profiles": int((table["robustness_status"] == "incompatible_schema").sum()),
        "pass_90_profiles": int(len(pass_90)),
        "pass_95_profiles": int(len(pass_95)),
        "pass_90_rate_pct": round(float(len(pass_90) / len(eligible) * 100.0), 2) if len(eligible) else None,
        "pass_95_rate_pct": round(float(len(pass_95) / len(eligible) * 100.0), 2) if len(eligible) else None,
        "median_score": round(float(pd.to_numeric(table["score"], errors="coerce").median()), 2),
        "min_score": round(float(pd.to_numeric(table["score"], errors="coerce").min()), 2),
        "max_score": round(float(pd.to_numeric(table["score"], errors="coerce").max()), 2),
        "derived_schema_profiles": int((table["schema_status"] == "derived_v2_scores").sum()) if "schema_status" in table.columns else 0,
        "scope_note": "Profile robustness uses existing detector-profile artifacts. It is broader than one selected profile, but it is not a fresh market-data snapshot.",
    }


def robustness_gate(summary: Dict[str, Any]) -> Dict[str, Any]:
    failures: List[str] = []
    eligible = int(summary.get("eligible_profiles") or 0)
    if eligible < 8:
        failures.append("eligible_profiles_below_8")
    pass_90_rate = float(summary.get("pass_90_rate_pct") or 0.0)
    pass_95_rate = float(summary.get("pass_95_rate_pct") or 0.0)
    if pass_90_rate < 60.0:
        failures.append("pass_90_rate_below_60pct")
    if pass_95_rate < 40.0:
        failures.append("pass_95_rate_below_40pct")
    if int(summary.get("incompatible_schema_profiles") or 0) > 0:
        failures.append("incompatible_schema_profiles_remaining")
    return {
        "gate_id": "bull_flag_profile_robustness_gate_v1",
        "status": "pass" if not failures else "fail",
        "failures": failures,
        "criteria": {
            "eligible_profiles_min": 8,
            "pass_90_rate_pct_min": 60.0,
            "pass_95_rate_pct_min": 40.0,
            "incompatible_schema_profiles_max": 0,
        },
        "summary": summary,
    }


def blocked_diagnostics(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        if row.get("robustness_status") != "blocked":
            continue
        blockers = [item for item in str(row.get("promotion_blockers") or "").split(",") if item]
        out.append(
            {
                "profile_id": row.get("profile_id"),
                "schema_status": row.get("schema_status"),
                "score": row.get("score"),
                "events_n": row.get("events_n"),
                "trades": row.get("trades"),
                "validation_trades": row.get("validation_trades"),
                "validation_total_return_pct": row.get("validation_total_return_pct"),
                "holdout_trades": row.get("holdout_trades"),
                "holdout_total_return_pct": row.get("holdout_total_return_pct"),
                "walk_forward_sum_fold_return_pct": row.get("walk_forward_sum_fold_return_pct"),
                "walk_forward_worst_fold_return_pct": row.get("walk_forward_worst_fold_return_pct"),
                "median_adtv_participation_pct": row.get("median_adtv_participation_pct"),
                "blockers": ",".join(blockers),
                "primary_failure_axis": (
                    "validation_negative"
                    if float(row.get("validation_total_return_pct") or 0.0) < 0.0
                    else "walk_forward_weak"
                    if "walk_forward_sum_return_below_8pct" in blockers
                    else "walk_forward_negative_fold"
                    if "walk_forward_has_negative_fold" in blockers
                    else "mixed"
                ),
            }
        )
    return out


def render_report(
    rows: List[Dict[str, Any]],
    summary: Dict[str, Any],
    gate: Dict[str, Any],
    *,
    candidate_rows: List[Dict[str, Any]] | None = None,
    diagnostic_tables: Dict[str, pd.DataFrame] | None = None,
) -> str:
    blocked_rows = blocked_diagnostics(rows)
    lines = [
        "# Bull Flag Tradable Robustness",
        "",
        "Scope: fixed frozen strategy evaluated across available Bull Flag detector/profile artifacts. No per-profile strategy reselection is used.",
        "",
        "Important caveat: this is broader detector-profile robustness on existing artifacts, not fresh OOS from a new market-data snapshot.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for key, value in summary.items():
        lines.append(f"| {key} | {value} |")
    lines.extend(
        [
            "",
            "## Robustness Gate",
            "",
            f"- Gate: `{gate.get('gate_id')}`",
            f"- Status: `{gate.get('status')}`",
            f"- Failures: `{', '.join(gate.get('failures') or []) or 'none'}`",
        ]
    )
    lines.extend(
        [
            "",
            "## Profiles",
            "",
            "| Profile | Status | Schema | Score | Events | Trades | Val trades | Val return | Holdout trades | Holdout return | WF return | Median ADTV participation |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in sorted(rows, key=lambda item: (str(item.get("robustness_status")), -float(item.get("score") or 0.0))):
        lines.append(
            "| {profile} | {status} | {schema} | {score} | {events} | {trades} | {vt} | {vr} | {ht} | {hr} | {wf} | {adtv} |".format(
                profile=row.get("profile_id"),
                status=row.get("robustness_status"),
                schema=row.get("schema_status"),
                score=row.get("score"),
                events=row.get("events_n"),
                trades=row.get("trades"),
                vt=row.get("validation_trades"),
                vr=row.get("validation_total_return_pct"),
                ht=row.get("holdout_trades"),
                hr=row.get("holdout_total_return_pct"),
                wf=row.get("walk_forward_sum_fold_return_pct"),
                adtv=row.get("median_adtv_participation_pct"),
            )
        )
    if blocked_rows:
        lines.extend(
            [
                "",
                "## Blocked Profile Diagnostics",
                "",
                "| Profile | Failure axis | Score | Val return | Holdout return | WF return | Blockers |",
                "|---|---|---:|---:|---:|---:|---|",
            ]
        )
        for row in sorted(blocked_rows, key=lambda item: float(item.get("score") or 0.0), reverse=True):
            lines.append(
                "| {profile} | {axis} | {score} | {val} | {holdout} | {wf} | {blockers} |".format(
                    profile=row.get("profile_id"),
                    axis=row.get("primary_failure_axis"),
                    score=row.get("score"),
                    val=row.get("validation_total_return_pct"),
                    holdout=row.get("holdout_total_return_pct"),
                    wf=row.get("walk_forward_sum_fold_return_pct"),
                    blockers=row.get("blockers"),
                )
            )
    if candidate_rows:
        lines.extend(
            [
                "",
                "## Causal Entry Candidate Screen",
                "",
                "Scope: diagnostic screen only. Candidates use delayed-entry information such as entry gap and pre-entry MAE; no candidate is selected by holdout here.",
                "",
                "| Strategy | Eligible profiles | Val positive rate | Median val return | Sum val return | Median holdout return | Underpowered profiles |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in sorted(candidate_rows, key=lambda item: (-(item.get("validation_positive_rate_pct") or -1), -(item.get("eligible_profiles") or 0), -(item.get("sum_validation_return_pct") or -999))):
            lines.append(
                "| {sid} | {eligible} | {rate} | {median_val} | {sum_val} | {median_holdout} | {underpowered} |".format(
                    sid=row.get("strategy_id"),
                    eligible=row.get("eligible_profiles"),
                    rate=row.get("validation_positive_rate_pct"),
                    median_val=row.get("median_validation_return_pct"),
                    sum_val=row.get("sum_validation_return_pct"),
                    median_holdout=row.get("median_holdout_return_pct"),
                    underpowered=row.get("underpowered_profiles"),
                )
            )
    if diagnostic_tables:
        numeric = diagnostic_tables.get("numeric_diagnostics", pd.DataFrame())
        categorical = diagnostic_tables.get("categorical_diagnostics", pd.DataFrame())
        if not numeric.empty:
            lines.extend(
                [
                    "",
                    "## Validation Trade Numeric Diagnostics",
                    "",
                    "| Metric | Loser median | Winner median | Winner-loser spread |",
                    "|---|---:|---:|---:|",
                ]
            )
            for _, row in numeric.iterrows():
                lines.append(
                    f"| {row.get('metric')} | {row.get('loser_median')} | {row.get('winner_median')} | {row.get('median_spread_winner_minus_loser')} |"
                )
        if not categorical.empty:
            top_bad = categorical.sort_values("return_sum_pct").head(12)
            lines.extend(
                [
                    "",
                    "## Weakest Validation Buckets",
                    "",
                    "| Dimension | Value | N | Return sum | Mean return | Win rate |",
                    "|---|---|---:|---:|---:|---:|",
                ]
            )
            for _, row in top_bad.iterrows():
                lines.append(
                    "| {dimension} | {value} | {n} | {ret_sum} | {ret_mean} | {win_rate} |".format(
                        dimension=row.get("dimension"),
                        value=row.get("value"),
                        n=row.get("n"),
                        ret_sum=row.get("return_sum_pct"),
                        ret_mean=row.get("return_mean_pct"),
                        win_rate=row.get("win_rate_pct"),
                    )
                )
    return "\n".join(lines) + "\n"


def run_robustness(*, root: Path, out_dir: Path, source_dir: Path = DEFAULT_SOURCE_DIR, monte_carlo_iterations: int = 500) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    profile_dirs = discover_profile_dirs(root)
    rows = [evaluate_profile(profile_dir, root, source_dir=source_dir, monte_carlo_iterations=monte_carlo_iterations) for profile_dir in profile_dirs]
    summary = summarize_rows(rows)
    gate = robustness_gate(summary)
    blocked_rows = blocked_diagnostics(rows)
    candidate_rows = evaluate_candidate_screen(profile_dirs, root, source_dir=source_dir)
    diagnostic_tables = validation_trade_diagnostics(profile_dirs, root, source_dir=source_dir)
    table = pd.DataFrame(rows)
    paths = {
        "robustness_csv": out_dir / "bull_flag_tradable_profile_robustness.csv",
        "robustness_json": out_dir / "bull_flag_tradable_profile_robustness.json",
        "blocked_diagnostics_csv": out_dir / "bull_flag_tradable_blocked_diagnostics.csv",
        "candidate_screen_csv": out_dir / "bull_flag_tradable_candidate_screen.csv",
        "validation_numeric_diagnostics_csv": out_dir / "bull_flag_tradable_validation_numeric_diagnostics.csv",
        "validation_bucket_diagnostics_csv": out_dir / "bull_flag_tradable_validation_bucket_diagnostics.csv",
        "validation_profile_diagnostics_csv": out_dir / "bull_flag_tradable_validation_profile_diagnostics.csv",
        "summary_json": out_dir / "bull_flag_tradable_profile_robustness_summary.json",
        "gate_json": out_dir / "bull_flag_tradable_profile_robustness_gate.json",
        "report_md": out_dir / "bull_flag_tradable_profile_robustness_report.md",
    }
    table.to_csv(paths["robustness_csv"], index=False)
    pd.DataFrame(blocked_rows).to_csv(paths["blocked_diagnostics_csv"], index=False)
    pd.DataFrame(candidate_rows).to_csv(paths["candidate_screen_csv"], index=False)
    diagnostic_tables.get("numeric_diagnostics", pd.DataFrame()).to_csv(paths["validation_numeric_diagnostics_csv"], index=False)
    diagnostic_tables.get("categorical_diagnostics", pd.DataFrame()).to_csv(paths["validation_bucket_diagnostics_csv"], index=False)
    diagnostic_tables.get("profile_diagnostics", pd.DataFrame()).to_csv(paths["validation_profile_diagnostics_csv"], index=False)
    paths["robustness_json"].write_text(json.dumps(rows, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    paths["summary_json"].write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    paths["gate_json"].write_text(json.dumps(gate, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    paths["report_md"].write_text(render_report(rows, summary, gate, candidate_rows=candidate_rows, diagnostic_tables=diagnostic_tables), encoding="utf-8")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Run frozen Bull Flag tradable setup across detector-profile artifacts.")
    parser.add_argument("--root", default="artifacts/scanner_v2")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR))
    parser.add_argument("--monte-carlo-iterations", type=int, default=500)
    args = parser.parse_args()
    paths = run_robustness(root=Path(args.root), out_dir=Path(args.out_dir), source_dir=Path(args.source_dir), monte_carlo_iterations=args.monte_carlo_iterations)
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
