"""Run Bull Flag frozen-rule checks on wider or fresh source snapshots.

This script deliberately separates two evidence types:

* same-snapshot temporal checks: useful diagnostics, not fresh OOS evidence.
* fresh snapshot checks: valid only when the supplied source snapshot was not
  used in the scanner/profile tuning cycle.

The scanner profile and tradable rule are fixed. This file must not select a
new detector, target, stop, or portfolio configuration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.run_bull_flag_tradable_robustness import normalize_profile_schema  # noqa: E402
from scanner.v2.bull_flag_localization import (  # noqa: E402
    BULL_FLAG_V2_SPLIT_STABLE_PROFILE_ID,
    _apply_post_score_filter,
    _apply_three_layer_scores,
    _filter_path_to_events,
    _scan_adaptive_profile,
    adaptive_detector_profiles,
)
from scanner.v2.bull_flags_monograph import DEFAULT_MARKET_STATS_JSON  # noqa: E402
from scanner.v2.flags_experiment import DEFAULT_INDEX_DB, DEFAULT_INDEX_SYMBOL  # noqa: E402
from scanner.v2.source_data import DEFAULT_SOURCE_DIR  # noqa: E402
from scanner.v2.bull_flag_tradable_setup import (  # noqa: E402
    DEFAULT_STRATEGY_GRID,
    FROZEN_STRATEGY_ID,
    apply_event_scope,
    evaluate_strategy,
    monte_carlo_trade_sequence,
    run_cost_stress,
    run_fixed_strategy_walk_forward,
    score_tradable_setup,
)


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bull_flags_wider_oos")
DEFAULT_PROFILE_ID = BULL_FLAG_V2_SPLIT_STABLE_PROFILE_ID
TUNED_SNAPSHOT_LABEL = "market_stats_2026-05-15_current_tuning_snapshot"
DEFAULT_TEMPORAL_SLICES = (
    ("post_2024", "2024-01-01", None),
    ("post_2025", "2025-01-01", None),
    ("latest_holdout_window", "2025-07-01", None),
)
CONTEXT_DIMENSIONS = (
    "time_split",
    "market_regime",
    "liquidity_bucket",
    "adaptive_branch_id",
    "breakout_year",
)


def _safe_json_load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _metadata_summary(market_stats_json: Optional[Path]) -> Dict[str, Any]:
    if market_stats_json is None or not market_stats_json.exists():
        return {"available": False}
    data = _safe_json_load(market_stats_json)
    membership = data.get("membership_version") if isinstance(data.get("membership_version"), Mapping) else {}
    classification = data.get("classification_version") if isinstance(data.get("classification_version"), Mapping) else {}
    data_basis = data.get("data_basis") if isinstance(data.get("data_basis"), Mapping) else {}
    return {
        "available": True,
        "path": str(market_stats_json),
        "schema_version": data.get("schema_version"),
        "generated_at": data.get("generated_at"),
        "stock_count": len(data.get("stocks") or []) if isinstance(data.get("stocks"), list) else None,
        "index_count": len(data.get("indices") or []) if isinstance(data.get("indices"), list) else None,
        "membership_mode": membership.get("mode"),
        "membership_snapshot_date": membership.get("snapshot_date"),
        "membership_has_history": membership.get("has_history"),
        "membership_point_in_time_ready": membership.get("point_in_time_ready"),
        "classification_point_in_time_ready": classification.get("point_in_time_ready"),
        "adjustment_label": data_basis.get("adjustment_label"),
        "adjustment_guardrail": data_basis.get("adjustment_guardrail"),
    }


def build_source_manifest(source_dir: Path, market_stats_json: Optional[Path] = DEFAULT_MARKET_STATS_JSON) -> Dict[str, Any]:
    """Build a lightweight manifest for a Market Stats stock_series snapshot."""

    files = sorted(source_dir.glob("*.json")) if source_dir.exists() else []
    rows = 0
    min_date: Optional[str] = None
    max_date: Optional[str] = None
    bad_files = []
    hash_input = hashlib.sha256()
    for path in files:
        hash_input.update(path.name.encode("utf-8"))
        hash_input.update(str(path.stat().st_size).encode("ascii"))
        try:
            data = _safe_json_load(path)
        except Exception as exc:  # pragma: no cover - defensive audit path
            bad_files.append({"path": str(path), "error": str(exc)})
            continue
        if not isinstance(data, list):
            bad_files.append({"path": str(path), "error": "expected_list_rows"})
            continue
        rows += len(data)
        for item in data[:1] + data[-1:]:
            date = item.get("date") if isinstance(item, Mapping) else None
            if not date:
                continue
            min_date = date if min_date is None or date < min_date else min_date
            max_date = date if max_date is None or date > max_date else max_date
    metadata = _metadata_summary(market_stats_json)
    hash_input.update(json.dumps(metadata, sort_keys=True, ensure_ascii=True, default=str).encode("utf-8"))
    return {
        "source_dir": str(source_dir),
        "symbol_files": len(files),
        "total_rows": rows,
        "min_date": min_date,
        "max_date": max_date,
        "bad_file_count": len(bad_files),
        "bad_files_sample": bad_files[:10],
        "metadata": metadata,
        "snapshot_fingerprint": hash_input.hexdigest(),
    }


def _records(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    if frame.empty:
        return []
    return json.loads(frame.to_json(orient="records"))


def provenance_audit(manifest: Mapping[str, Any], scope: Mapping[str, Any]) -> Dict[str, Any]:
    """Summarize what the current data can and cannot support."""

    metadata = manifest.get("metadata") if isinstance(manifest.get("metadata"), Mapping) else {}
    limitations: List[str] = []
    pass_flags = {
        "source_json_ok": int(manifest.get("bad_file_count") or 0) == 0,
        "source_has_rows": int(manifest.get("total_rows") or 0) > 0,
        "source_has_date_range": bool(manifest.get("min_date") and manifest.get("max_date")),
        "fresh_oos_snapshot": bool(scope.get("is_fresh_oos")),
        "membership_point_in_time": metadata.get("membership_point_in_time_ready") is True,
        "classification_point_in_time": metadata.get("classification_point_in_time_ready") is True,
    }
    if not pass_flags["fresh_oos_snapshot"]:
        limitations.append("same_snapshot_only_not_independent_fresh_oos")
    if not pass_flags["membership_point_in_time"]:
        limitations.append("membership_is_current_snapshot_not_historical_pti")
    if not pass_flags["classification_point_in_time"]:
        limitations.append("classification_is_current_snapshot_not_historical_pti")
    adjustment_label = str(metadata.get("adjustment_label") or "").strip()
    if adjustment_label and "provider" in adjustment_label.lower():
        limitations.append("provider_adjusted_ohlcv_without_official_factor_log")
    if not pass_flags["source_json_ok"]:
        limitations.append("source_json_errors_present")
    if not pass_flags["source_has_rows"]:
        limitations.append("source_empty")
    if pass_flags["fresh_oos_snapshot"] and pass_flags["source_json_ok"]:
        ceiling = "fresh-oos-candidate"
    elif pass_flags["source_json_ok"] and pass_flags["source_has_rows"]:
        ceiling = "same-snapshot-diagnostic"
    else:
        ceiling = "blocked"
    return {
        "audit_id": "bull_flag_data_provenance_v1",
        "pass_flags": pass_flags,
        "limitations": limitations,
        "classification_ceiling": ceiling,
        "allowed_claim": (
            "frozen-rule diagnostic on current available Market Stats stock_series"
            if ceiling == "same-snapshot-diagnostic"
            else "fresh OOS candidate if snapshot provenance is externally confirmed"
            if ceiling == "fresh-oos-candidate"
            else "blocked until source issues are fixed"
        ),
        "forbidden_claims": [
            "historical VN30/VN100 point-in-time membership conclusion",
            "whole-market point-in-time universe conclusion",
            "fresh OOS conclusion from same snapshot",
            "official corporate-action factor audit",
        ],
    }


def classify_snapshot_scope(
    manifest: Mapping[str, Any],
    *,
    source_snapshot_id: Optional[str] = None,
    tuned_snapshot_id: str = TUNED_SNAPSHOT_LABEL,
) -> Dict[str, Any]:
    metadata = manifest.get("metadata") if isinstance(manifest.get("metadata"), Mapping) else {}
    failures = []
    warnings = []
    if int(manifest.get("bad_file_count") or 0) > 0:
        failures.append("source_json_errors")
    if metadata.get("membership_point_in_time_ready") is False:
        warnings.append("membership_not_point_in_time")
    if source_snapshot_id is None:
        return {
            "scope_status": "same_snapshot_temporal_check",
            "is_fresh_oos": False,
            "tuned_snapshot_id": tuned_snapshot_id,
            "source_snapshot_id": source_snapshot_id,
            "warnings": warnings + ["source_snapshot_id_not_provided"],
            "failures": failures,
            "scope_note": "Diagnostic only. This source cannot be claimed as fresh OOS without an unseen snapshot id.",
        }
    if source_snapshot_id == tuned_snapshot_id:
        return {
            "scope_status": "same_snapshot_temporal_check",
            "is_fresh_oos": False,
            "tuned_snapshot_id": tuned_snapshot_id,
            "source_snapshot_id": source_snapshot_id,
            "warnings": warnings + ["source_snapshot_id_matches_tuned_snapshot"],
            "failures": failures,
            "scope_note": "Diagnostic only. Snapshot id matches the tuning snapshot.",
        }
    return {
        "scope_status": "fresh_snapshot_candidate",
        "is_fresh_oos": not failures,
        "tuned_snapshot_id": tuned_snapshot_id,
        "source_snapshot_id": source_snapshot_id,
        "warnings": warnings,
        "failures": failures,
        "scope_note": "Fresh OOS candidate if the supplied snapshot was not used for tuning and includes no hidden reselection.",
    }


def _profile_by_id(profile_id: str) -> Dict[str, Any]:
    for profile in adaptive_detector_profiles():
        if profile.get("profile_id") == profile_id:
            return dict(profile)
    raise ValueError(f"Unknown adaptive profile id: {profile_id}")


def scan_fixed_profile(
    *,
    profile_id: str,
    source_dir: Path,
    market_stats_json: Optional[Path],
    index_db: Path,
    index_symbol: str,
    limit_symbols: Optional[int],
) -> tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """Rescan one fixed profile from source without profile reselection."""

    profile = _profile_by_id(profile_id)
    scan, events_rows, path_rows = _scan_adaptive_profile(
        profile,
        source_dir=source_dir,
        market_stats_json=market_stats_json,
        index_db=index_db,
        index_symbol=index_symbol,
        limit_symbols=limit_symbols,
        cache={},
    )
    events = pd.DataFrame(events_rows)
    path = pd.DataFrame(path_rows)
    if not events.empty and "event_id" not in events.columns and "detection_id" in events.columns:
        events["event_id"] = events["detection_id"]
    events = _apply_three_layer_scores(events, path, source_dir=source_dir)
    events, post_score_report = _apply_post_score_filter(events, profile)
    path = _filter_path_to_events(path, events)
    scan_summary = {
        "profile": profile,
        "raw_bull_flag_detection_count": scan.get("raw_bull_flag_detection_count"),
        "branch_candidate_count": scan.get("branch_candidate_count"),
        "adaptive_overlap_report": scan.get("adaptive_overlap_report"),
        "post_score_filter_report": post_score_report,
    }
    return events, path, scan_summary


def _fixed_selection(strategy_id: str, summary: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": "selected_tradable_setup",
        "selection_basis": "fixed_strategy_no_reselection",
        "selected_strategy_id": strategy_id,
        "selected_metrics": summary,
        "passing_count": 1,
        "candidate_count": 1,
    }


def _frozen_config():
    config = next((item for item in DEFAULT_STRATEGY_GRID if item.strategy_id == FROZEN_STRATEGY_ID), None)
    if config is None:
        raise RuntimeError(f"Frozen strategy not found: {FROZEN_STRATEGY_ID}")
    return config


def _filter_by_breakout_date(events: pd.DataFrame, path: pd.DataFrame, *, start_date: Optional[str], end_date: Optional[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    if events.empty or "breakout_date" not in events.columns:
        return events.copy(), path.copy()
    filtered = events.copy()
    dates = pd.to_datetime(filtered["breakout_date"], errors="coerce")
    mask = pd.Series(True, index=filtered.index)
    if start_date:
        mask &= dates >= pd.Timestamp(start_date)
    if end_date:
        mask &= dates <= pd.Timestamp(end_date)
    filtered = filtered[mask].copy()
    return filtered, _filter_path_to_events(path, filtered)


def evaluate_fixed_strategy(
    events: pd.DataFrame,
    path: pd.DataFrame,
    *,
    source_dir: Path,
    monte_carlo_iterations: int,
) -> Dict[str, Any]:
    config = _frozen_config()
    events, schema_info = normalize_profile_schema(events, path, source_dir=source_dir)
    events, path = apply_event_scope(events, path, config)
    summary, trades, _ = evaluate_strategy(events, path, config)
    selection = _fixed_selection(config.strategy_id, summary)
    walk_forward_folds, walk_forward_trades, walk_forward_summary = run_fixed_strategy_walk_forward(events, path, config)
    cost_stress_table, cost_stress_summary = run_cost_stress(events, path, config)
    _, monte_carlo_summary = monte_carlo_trade_sequence(trades, config, iterations=monte_carlo_iterations)
    scorecard = score_tradable_setup(selection, walk_forward_summary, cost_stress_summary, monte_carlo_summary)
    return {
        "schema_status": schema_info.get("schema_status"),
        "events_n": int(len(events)),
        "path_rows": int(len(path)),
        "strategy_id": config.strategy_id,
        "summary": summary,
        "walk_forward_summary": walk_forward_summary,
        "walk_forward_folds": _records(walk_forward_folds),
        "walk_forward_trades": _records(walk_forward_trades),
        "cost_stress_summary": cost_stress_summary,
        "cost_stress_rows": _records(cost_stress_table),
        "monte_carlo_summary": monte_carlo_summary,
        "scorecard": scorecard,
    }


def _diagnostic_status(summary: Mapping[str, Any], *, min_trades: int) -> str:
    trades = int(summary.get("trades") or 0)
    total_return = float(summary.get("total_return_pct") or 0.0)
    drawdown = float(summary.get("max_drawdown_pct") or 0.0)
    if trades < min_trades:
        return "underpowered"
    if total_return <= 0.0:
        return "negative_return"
    if drawdown < -10.0:
        return "drawdown_fail"
    return "pass"


def temporal_power_rows(events: pd.DataFrame, path: pd.DataFrame, *, slices: Iterable[tuple[str, Optional[str], Optional[str]]]) -> List[Dict[str, Any]]:
    config = _frozen_config()
    rows: List[Dict[str, Any]] = []
    for slice_id, start, end in slices:
        subset, subset_path = _filter_by_breakout_date(events, path, start_date=start, end_date=end)
        summary, _, _ = evaluate_strategy(subset, subset_path, config)
        rows.append(
            {
                "slice_id": slice_id,
                "start_date": start,
                "end_date": end,
                "events": int(len(subset)),
                "path_rows": int(len(subset_path)),
                "trades": summary.get("trades"),
                "total_return_pct": summary.get("total_return_pct"),
                "max_drawdown_pct": summary.get("max_drawdown_pct"),
                "win_rate_pct": summary.get("win_rate_pct"),
                "profit_factor": summary.get("profit_factor"),
                "validation_trades": summary.get("validation_trades"),
                "validation_total_return_pct": summary.get("validation_total_return_pct"),
                "holdout_trades": summary.get("holdout_trades"),
                "holdout_total_return_pct": summary.get("holdout_total_return_pct"),
                "power_status": _diagnostic_status(summary, min_trades=25),
            }
        )
    return rows


def temporal_power_summary(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    table = pd.DataFrame(list(rows))
    if table.empty:
        return {"status": "no_temporal_rows"}
    return {
        "status": "complete",
        "slice_count": int(len(table)),
        "pass_count": int((table["power_status"].astype(str) == "pass").sum()),
        "underpowered_count": int((table["power_status"].astype(str) == "underpowered").sum()),
        "min_events": int(pd.to_numeric(table["events"], errors="coerce").min()),
        "min_trades": int(pd.to_numeric(table["trades"], errors="coerce").min()),
    }


def _context_values(events: pd.DataFrame, dimension: str) -> pd.Series:
    if dimension == "breakout_year":
        return pd.to_datetime(events.get("breakout_date"), errors="coerce").dt.year.astype("Int64").astype(str)
    if dimension in events.columns:
        return events[dimension].astype(str)
    return pd.Series(dtype=str)


def context_robustness_rows(events: pd.DataFrame, path: pd.DataFrame, *, dimensions: Iterable[str] = CONTEXT_DIMENSIONS) -> List[Dict[str, Any]]:
    config = _frozen_config()
    rows: List[Dict[str, Any]] = []
    if events.empty:
        return rows
    working = events.copy()
    for dimension in dimensions:
        values = _context_values(working, dimension)
        if values.empty:
            continue
        scoped = working.copy()
        scoped["_context_value"] = values.fillna("unknown").astype(str)
        for value, group in scoped.groupby("_context_value", dropna=False):
            if value in {"<NA>", "nan", "None", ""}:
                value = "unknown"
            subset = group.drop(columns=["_context_value"], errors="ignore").copy()
            subset_path = _filter_path_to_events(path, subset)
            summary, _, _ = evaluate_strategy(subset, subset_path, config)
            rows.append(
                {
                    "dimension": dimension,
                    "value": str(value),
                    "events": int(len(subset)),
                    "path_rows": int(len(subset_path)),
                    "trades": summary.get("trades"),
                    "total_return_pct": summary.get("total_return_pct"),
                    "max_drawdown_pct": summary.get("max_drawdown_pct"),
                    "win_rate_pct": summary.get("win_rate_pct"),
                    "profit_factor": summary.get("profit_factor"),
                    "median_adtv_participation_pct": summary.get("median_adtv_participation_pct"),
                    "diagnostic_status": _diagnostic_status(summary, min_trades=8),
                }
            )
    return rows


def context_robustness_summary(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    table = pd.DataFrame(list(rows))
    if table.empty:
        return {"status": "no_context_rows"}
    eligible = table[pd.to_numeric(table["trades"], errors="coerce").fillna(0) >= 8].copy()
    fail = eligible[eligible["diagnostic_status"].astype(str) != "pass"].copy()
    return {
        "status": "complete",
        "context_rows": int(len(table)),
        "eligible_context_rows": int(len(eligible)),
        "underpowered_context_rows": int((table["diagnostic_status"].astype(str) == "underpowered").sum()),
        "failed_eligible_context_rows": int(len(fail)),
        "pass_rate_eligible_pct": round(float((eligible["diagnostic_status"].astype(str) == "pass").mean()) * 100.0, 2) if not eligible.empty else None,
    }


def execution_stress_summary(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    table = pd.DataFrame(list(rows))
    if table.empty:
        return {"status": "no_execution_stress_rows"}
    returns = pd.to_numeric(table.get("total_return_pct"), errors="coerce").dropna()
    drawdowns = pd.to_numeric(table.get("max_drawdown_pct"), errors="coerce").dropna()
    return {
        "status": "complete",
        "scenario_count": int(len(table)),
        "positive_scenario_rate_pct": round(float((returns > 0).mean()) * 100.0, 2) if not returns.empty else None,
        "worst_scenario_return_pct": round(float(returns.min()), 2) if not returns.empty else None,
        "worst_scenario_drawdown_pct": round(float(drawdowns.min()), 2) if not drawdowns.empty else None,
    }


def _write_profile_dir(profile_dir: Path, events: pd.DataFrame, path: pd.DataFrame, scan_summary: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    events.to_csv(profile_dir / "events.csv", index=False)
    path.to_csv(profile_dir / "post_breakout_path.csv", index=False)
    profile = scan_summary.get("profile") if isinstance(scan_summary.get("profile"), Mapping) else {}
    (profile_dir / "profile.json").write_text(json.dumps(profile, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    (profile_dir / "scan_summary.json").write_text(json.dumps(scan_summary, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    (profile_dir / "source_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def render_report(payload: Mapping[str, Any]) -> str:
    scope = payload.get("scope") if isinstance(payload.get("scope"), Mapping) else {}
    manifest = payload.get("source_manifest") if isinstance(payload.get("source_manifest"), Mapping) else {}
    provenance = payload.get("data_provenance_audit") if isinstance(payload.get("data_provenance_audit"), Mapping) else {}
    full_eval = payload.get("full_profile_evaluation") if isinstance(payload.get("full_profile_evaluation"), Mapping) else {}
    full_score = full_eval.get("scorecard") if isinstance(full_eval.get("scorecard"), Mapping) else {}
    full_summary = full_eval.get("summary") if isinstance(full_eval.get("summary"), Mapping) else {}
    execution = payload.get("execution_stress_summary") if isinstance(payload.get("execution_stress_summary"), Mapping) else {}
    temporal_power = payload.get("temporal_power_summary") if isinstance(payload.get("temporal_power_summary"), Mapping) else {}
    context_summary = payload.get("context_robustness_summary") if isinstance(payload.get("context_robustness_summary"), Mapping) else {}
    temporal = payload.get("temporal_evaluation") if isinstance(payload.get("temporal_evaluation"), Mapping) else {}
    temporal_score = temporal.get("scorecard") if isinstance(temporal.get("scorecard"), Mapping) else {}
    temporal_summary = temporal.get("summary") if isinstance(temporal.get("summary"), Mapping) else {}
    lines = [
        "# Bull Flag Wider/Fresh OOS Check",
        "",
        f"- Scope status: `{scope.get('scope_status')}`",
        f"- Fresh OOS: `{scope.get('is_fresh_oos')}`",
        f"- Scope note: {scope.get('scope_note')}",
        f"- Source rows: `{manifest.get('total_rows')}` across `{manifest.get('symbol_files')}` symbol files",
        f"- Source date range: `{manifest.get('min_date')}` to `{manifest.get('max_date')}`",
        f"- Provenance ceiling: `{provenance.get('classification_ceiling')}`",
        "",
        "## Fixed Full-Profile Rerun",
        "",
        f"- Events: `{full_eval.get('events_n')}`",
        f"- Trades: `{full_summary.get('trades')}`",
        f"- Score: `{full_score.get('score')}`",
        f"- Classification: `{full_score.get('classification')}`",
        f"- Validation return: `{full_summary.get('validation_total_return_pct')}`",
        f"- Holdout return: `{full_summary.get('holdout_total_return_pct')}`",
        "",
        "## Execution Stress",
        "",
        f"- Scenarios: `{execution.get('scenario_count')}`",
        f"- Positive scenario rate: `{execution.get('positive_scenario_rate_pct')}`",
        f"- Worst scenario return: `{execution.get('worst_scenario_return_pct')}`",
        f"- Worst scenario drawdown: `{execution.get('worst_scenario_drawdown_pct')}`",
        "",
        "## Temporal Power",
        "",
        f"- Slices: `{temporal_power.get('slice_count')}`",
        f"- Passing slices: `{temporal_power.get('pass_count')}`",
        f"- Underpowered slices: `{temporal_power.get('underpowered_count')}`",
        f"- Min trades: `{temporal_power.get('min_trades')}`",
        "",
        "## Context Robustness",
        "",
        f"- Eligible context rows: `{context_summary.get('eligible_context_rows')}`",
        f"- Failed eligible context rows: `{context_summary.get('failed_eligible_context_rows')}`",
        f"- Pass rate among eligible rows: `{context_summary.get('pass_rate_eligible_pct')}`",
    ]
    if temporal:
        lines.extend(
            [
                "",
                "## Temporal Slice",
                "",
                f"- Slice: `{temporal.get('start_date')}` to `{temporal.get('end_date')}`",
                f"- Events: `{temporal.get('events_n')}`",
                f"- Trades: `{temporal_summary.get('trades')}`",
                f"- Score: `{temporal_score.get('score')}`",
                f"- Classification: `{temporal_score.get('classification')}`",
                f"- Note: {temporal.get('scope_note')}",
            ]
        )
    return "\n".join(lines) + "\n"


def run_wider_oos(
    *,
    out_dir: Path,
    source_dir: Path,
    market_stats_json: Optional[Path],
    profile_id: str,
    source_snapshot_id: Optional[str],
    start_date: Optional[str],
    end_date: Optional[str],
    index_db: Path,
    index_symbol: str,
    limit_symbols: Optional[int],
    monte_carlo_iterations: int,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_source_manifest(source_dir, market_stats_json)
    scope = classify_snapshot_scope(manifest, source_snapshot_id=source_snapshot_id)
    provenance = provenance_audit(manifest, scope)
    events, path, scan_summary = scan_fixed_profile(
        profile_id=profile_id,
        source_dir=source_dir,
        market_stats_json=market_stats_json,
        index_db=index_db,
        index_symbol=index_symbol,
        limit_symbols=limit_symbols,
    )
    profile_dir = out_dir / "profile"
    _write_profile_dir(profile_dir, events, path, scan_summary, manifest)
    full_eval = evaluate_fixed_strategy(events, path, source_dir=source_dir, monte_carlo_iterations=monte_carlo_iterations)
    execution_rows = full_eval.get("cost_stress_rows") if isinstance(full_eval.get("cost_stress_rows"), list) else []
    temporal_rows = temporal_power_rows(events, path, slices=DEFAULT_TEMPORAL_SLICES)
    context_rows = context_robustness_rows(events, path)
    execution_summary = execution_stress_summary(execution_rows)
    temporal_summary = temporal_power_summary(temporal_rows)
    context_summary = context_robustness_summary(context_rows)
    temporal_eval: Dict[str, Any] = {}
    if start_date or end_date:
        temporal_events, temporal_path = _filter_by_breakout_date(events, path, start_date=start_date, end_date=end_date)
        temporal_eval = evaluate_fixed_strategy(temporal_events, temporal_path, source_dir=source_dir, monte_carlo_iterations=monte_carlo_iterations)
        temporal_eval.update(
            {
                "start_date": start_date,
                "end_date": end_date,
                "scope_note": "Same fixed scanner/rule on a chronological slice. This is not independent fresh OOS unless scope says fresh_snapshot_candidate.",
            }
        )
        _write_profile_dir(out_dir / "temporal_profile", temporal_events, temporal_path, scan_summary, manifest)
    payload = {
        "gate_id": "bull_flag_wider_oos_gate_v1",
        "profile_id": profile_id,
        "scope": scope,
        "source_manifest": manifest,
        "data_provenance_audit": provenance,
        "scan_summary": scan_summary,
        "profile_dir": str(profile_dir),
        "full_profile_evaluation": full_eval,
        "temporal_evaluation": temporal_eval,
        "execution_stress_summary": execution_summary,
        "execution_stress_table": execution_rows,
        "temporal_power_summary": temporal_summary,
        "temporal_power_table": temporal_rows,
        "context_robustness_summary": context_summary,
        "context_robustness_table": context_rows,
        "next_required_data": {
            "fresh_snapshot": "Provide a stock_series snapshot with a source_snapshot_id different from the tuning snapshot.",
            "no_reselection": "Run this same script/profile/strategy only; do not tune detector or execution parameters on the fresh snapshot.",
        },
    }
    paths = {
        "json": out_dir / "bull_flag_wider_oos_gate.json",
        "report": out_dir / "bull_flag_wider_oos_report.md",
        "profile_dir": profile_dir,
        "execution_stress_csv": out_dir / "bull_flag_wider_oos_execution_stress.csv",
        "temporal_power_csv": out_dir / "bull_flag_wider_oos_temporal_power.csv",
        "context_robustness_csv": out_dir / "bull_flag_wider_oos_context_robustness.csv",
        "walk_forward_folds_csv": out_dir / "bull_flag_wider_oos_walk_forward_folds.csv",
        "walk_forward_trades_csv": out_dir / "bull_flag_wider_oos_walk_forward_trades.csv",
    }
    paths["json"].write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    paths["report"].write_text(render_report(payload), encoding="utf-8")
    pd.DataFrame(execution_rows).to_csv(paths["execution_stress_csv"], index=False)
    pd.DataFrame(temporal_rows).to_csv(paths["temporal_power_csv"], index=False)
    pd.DataFrame(context_rows).to_csv(paths["context_robustness_csv"], index=False)
    pd.DataFrame(full_eval.get("walk_forward_folds") or []).to_csv(paths["walk_forward_folds_csv"], index=False)
    pd.DataFrame(full_eval.get("walk_forward_trades") or []).to_csv(paths["walk_forward_trades_csv"], index=False)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Run fixed Bull Flag scanner/strategy on wider or fresh source data.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR))
    parser.add_argument("--market-stats-json", default=str(DEFAULT_MARKET_STATS_JSON))
    parser.add_argument("--profile-id", default=DEFAULT_PROFILE_ID)
    parser.add_argument("--source-snapshot-id", default=None)
    parser.add_argument("--start-date", default="2025-01-01")
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--index-db", default=str(DEFAULT_INDEX_DB))
    parser.add_argument("--index-symbol", default=DEFAULT_INDEX_SYMBOL)
    parser.add_argument("--limit-symbols", type=int, default=None)
    parser.add_argument("--monte-carlo-iterations", type=int, default=500)
    args = parser.parse_args()
    market_stats_json = Path(args.market_stats_json) if args.market_stats_json else None
    paths = run_wider_oos(
        out_dir=Path(args.out_dir),
        source_dir=Path(args.source_dir),
        market_stats_json=market_stats_json,
        profile_id=args.profile_id,
        source_snapshot_id=args.source_snapshot_id,
        start_date=args.start_date,
        end_date=args.end_date,
        index_db=Path(args.index_db),
        index_symbol=args.index_symbol,
        limit_symbols=args.limit_symbols,
        monte_carlo_iterations=args.monte_carlo_iterations,
    )
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
