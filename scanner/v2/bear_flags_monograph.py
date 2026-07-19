"""Bear Flag Scanner V2 defensive-reference chapter pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import pandas as pd

from .bull_flags_monograph import (
    BULL_FLAG_EVENT_FIELDS,
    DEFAULT_MARKET_STATS_JSON,
    _add_sensitivity_tables,
    _apply_event_filter,
    _enrich_events,
    _load_active_symbols,
    _restrict_scan_to_active_universe,
    _render_pdf,
)
from .flags_experiment import (
    DEFAULT_INDEX_DB,
    DEFAULT_INDEX_SYMBOL,
    EVENT_FIELDS,
    FlagDetectorConfig,
    _path_rows,
    _write_csv,
    _write_json,
    scan_market_stats,
    summarize,
)
from .source_data import DEFAULT_SOURCE_DIR


PATTERN_KEY = "bear_flags"
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bear_flags")

BEAR_FLAG_EVENT_FIELDS = [
    *BULL_FLAG_EVENT_FIELDS,
    "bear_branch_id",
    "bear_branch_lane",
    "bear_branch_reason",
    "bear_branch_is_headline_candidate",
]


def _filter_bear_flags(scan: Mapping[str, Any]) -> Dict[str, Any]:
    detections = [
        {**row, "pattern_key": PATTERN_KEY}
        for row in scan.get("detections") or []
        if row.get("variant") == "bear_flag" and row.get("breakout_direction") == "down"
    ]
    for i, row in enumerate(detections):
        row["detection_id"] = f"{PATTERN_KEY}:{i + 1:06d}"
    return {
        **dict(scan),
        "pattern_key": PATTERN_KEY,
        "detections": detections,
        "experiment_status": "promoted_defensive_candidate_from_flags_experiment",
        "chapter_lane": "informational/defensive-reference candidate",
    }


def _safe_float(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(out):
        return None
    return out


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _assign_bear_branch(row: Mapping[str, Any]) -> tuple[str, str, str, bool]:
    """Assign an ex-ante Bear Flag branch.

    Branches must use fields known by the breakout bar or static current-scope
    metadata. Post-breakout path-quality fields are intentionally excluded from
    this scanner branch and remain QA/robustness diagnostics only.
    """

    liquidity = str(row.get("liquidity_bucket") or "unknown")
    market_group = str(row.get("market_group") or "unknown")
    regime = str(row.get("market_regime") or "unknown")
    gap = abs(_safe_float(row.get("breakout_gap_pct")) or 0.0)
    yearly_pos = _safe_float(row.get("yearly_range_position_pct"))
    body_to_range = _safe_float(row.get("breakout_body_to_range")) or 0.0
    close_location = _safe_float(row.get("breakout_close_location")) or 0.0
    volume_confirmed = _truthy(row.get("volume_confirmed"))
    high_liquidity = liquidity == "high"
    in_vn100 = market_group in {"VN30", "VN100 ex VN30"}
    no_large_gap = gap <= 0.5
    mid_or_lower_year = yearly_pos is not None and yearly_pos <= 66.67
    strong_body = body_to_range >= 0.40
    strong_close = close_location >= 0.65

    if high_liquidity and no_large_gap:
        return (
            "defensive_core_high_liquidity_no_gap",
            "defensive-core",
            "high liquidity and no large breakout gap; strongest ex-ante Bear Flag branch in current audit",
            True,
        )
    if high_liquidity and mid_or_lower_year and (strong_body or regime == "bull"):
        return (
            "defensive_core_high_liquidity_context",
            "defensive-core",
            "high liquidity with supportive yearly-position/context filter",
            True,
        )
    if high_liquidity or (in_vn100 and (no_large_gap or volume_confirmed or strong_body)):
        return (
            "defensive_watchlist_liquid_or_vn100",
            "defensive-watchlist",
            "liquid/VN100 branch; keep as defensive watchlist, not headline investment evidence",
            False,
        )
    if no_large_gap and (strong_body or strong_close or volume_confirmed):
        return (
            "informational_clean_breakout",
            "informational",
            "breakout looks usable but lacks high-liquidity/VN100 support",
            False,
        )
    return (
        "informational_broad",
        "informational",
        "broad active-series Bear Flag event; included for atlas completeness but not headline quality",
        False,
    )


def _assign_bear_branches(scan: Mapping[str, Any]) -> None:
    for row in scan.get("detections") or []:
        branch_id, lane, reason, headline = _assign_bear_branch(row)
        row["bear_branch_id"] = branch_id
        row["bear_branch_lane"] = lane
        row["bear_branch_reason"] = reason
        row["bear_branch_is_headline_candidate"] = bool(headline)


def _find_target_row(stats: Mapping[str, Any], multiple: float, label: str = PATTERN_KEY) -> Mapping[str, Any]:
    for row in stats.get("target_family_sensitivity") or []:
        if row.get("label") == label and float(row.get("target_multiple") or -1) == float(multiple):
            return row
    return {}


def _build_bear_flag_robustness_checks(stats: Mapping[str, Any]) -> list[dict[str, Any]]:
    base = _find_target_row(stats, 0.46)
    legacy = _find_target_row(stats, 1.0)
    checks: list[dict[str, Any]] = []
    n = int(base.get("n") or 0)
    checks.append(
        {
            "check_id": "defensive_base_target_sample",
            "status": "PASS" if n >= 100 else "WARN",
            "evidence": {"n": n, "target_multiple": 0.46},
            "note": "Bear Flag is evaluated as a defensive/informational reference; thin samples stay exploratory.",
        }
    )
    base_hit = base.get("target_hit_rate")
    legacy_hit = legacy.get("target_hit_rate")
    checks.append(
        {
            "check_id": "fractional_target_improves_attainment",
            "status": "PASS" if base_hit is not None and legacy_hit is not None and float(base_hit) >= float(legacy_hit) else "WARN",
            "evidence": {"base_target_hit_rate": base_hit, "legacy_target_hit_rate": legacy_hit},
        }
    )
    ratio = base.get("mfe_mae_median_ratio")
    checks.append(
        {
            "check_id": "downside_path_asymmetry",
            "status": "PASS" if ratio is not None and float(ratio) >= 1.0 else "WARN",
            "evidence": {"mfe_mae_median_ratio": ratio},
            "note": "For Bear Flag, favorable move means downside continuation; this is not a short-sale implementation claim.",
        }
    )
    checks.append(
        {
            "check_id": "classification_after_robustness",
            "status": "PASS",
            "evidence": {"classification": "informational/defensive-reference candidate"},
            "note": "Cash-equity downside patterns are framed as risk-reference unless execution research proves otherwise.",
        }
    )
    branch = stats.get("bear_branch_headline") if isinstance(stats.get("bear_branch_headline"), Mapping) else {}
    branch_base = branch.get("base_target_hit_rate")
    branch_failure = branch.get("failure_5pct_rate")
    checks.append(
        {
            "check_id": "branch_headline_quality",
            "status": "PASS"
            if branch.get("n", 0) and branch_base is not None and float(branch_base) >= 65.0 and branch_failure is not None and float(branch_failure) <= 20.0
            else "WARN",
            "evidence": {
                "branch_id": branch.get("branch_id") or branch.get("aggregate_id"),
                "n": branch.get("n"),
                "base_target_hit_rate": branch_base,
                "failure_5pct_rate": branch_failure,
            },
            "note": "Bear Flag headline should be branch-based; broad sample remains informational.",
        }
    )
    return checks


def _branch_target_row(events: pd.DataFrame, path: pd.DataFrame, label: str) -> Dict[str, Any]:
    from ..research_support_analysis import PatternArtifacts, target_sensitivity

    rows = target_sensitivity(PatternArtifacts(label, events.copy(), path), label)
    for row in rows:
        if float(row.get("target_multiple") or -1) == 0.46:
            return dict(row)
    return {"label": label, "target_multiple": 0.46, "n": int(len(events))}


def _build_branch_table(events: pd.DataFrame, path: pd.DataFrame) -> list[dict[str, Any]]:
    if events.empty or "bear_branch_id" not in events.columns:
        return []
    out: list[dict[str, Any]] = []
    for branch_id, group in events.groupby("bear_branch_id", dropna=False):
        event_ids = set(group["event_id"].astype(str)) if "event_id" in group.columns else set()
        path_group = path[path["event_id"].astype(str).isin(event_ids)].copy() if event_ids and "event_id" in path.columns else path.iloc[0:0].copy()
        label = f"{PATTERN_KEY}:branch={branch_id}"
        base = _branch_target_row(group, path_group, label)
        lane = str(group["bear_branch_lane"].iloc[0]) if "bear_branch_lane" in group.columns and not group.empty else "unknown"
        out.append(
            {
                "branch_id": str(branch_id),
                "lane": lane,
                "n": int(len(group)),
                "n_symbols": int(group["symbol"].nunique()) if "symbol" in group.columns else 0,
                "share_of_events_pct": round(float(len(group) / max(1, len(events)) * 100.0), 2),
                "base_target_hit_rate": base.get("target_hit_rate"),
                "base_target_first_before_adverse_5pct_rate": base.get("target_first_before_adverse_5pct_rate"),
                "failure_5pct_rate": base.get("failure_5pct_rate"),
                "mfe_mae_median_ratio": base.get("mfe_mae_median_ratio"),
                "median_mfe_pct": round(float(group["mfe_pct"].median()), 2) if "mfe_pct" in group.columns else None,
                "median_mae_pct": round(float(group["mae_pct"].median()), 2) if "mae_pct" in group.columns else None,
                "headline_candidate": bool(group["bear_branch_is_headline_candidate"].map(_truthy).any())
                if "bear_branch_is_headline_candidate" in group.columns
                else False,
            }
        )
    return sorted(
        out,
        key=lambda row: (
            row.get("headline_candidate") is True,
            float(row.get("base_target_hit_rate") or -1),
            -(float(row.get("failure_5pct_rate") or 1000)),
            int(row.get("n") or 0),
        ),
        reverse=True,
    )


def _aggregate_branch_metrics(events: pd.DataFrame, path: pd.DataFrame, *, aggregate_id: str, lane: str, mask: pd.Series, note: str) -> Dict[str, Any]:
    group = events[mask.fillna(False)].copy()
    if group.empty:
        return {
            "aggregate_id": aggregate_id,
            "lane": lane,
            "n": 0,
            "n_symbols": 0,
            "selected_headline": False,
            "note": note,
        }
    event_ids = set(group["event_id"].astype(str)) if "event_id" in group.columns else set()
    path_group = path[path["event_id"].astype(str).isin(event_ids)].copy() if event_ids and "event_id" in path.columns else path.iloc[0:0].copy()
    label = f"{PATTERN_KEY}:aggregate={aggregate_id}"
    base = _branch_target_row(group, path_group, label)
    return {
        "aggregate_id": aggregate_id,
        "lane": lane,
        "n": int(len(group)),
        "n_symbols": int(group["symbol"].nunique()) if "symbol" in group.columns else 0,
        "share_of_events_pct": round(float(len(group) / max(1, len(events)) * 100.0), 2),
        "base_target_hit_rate": base.get("target_hit_rate"),
        "base_target_first_before_adverse_5pct_rate": base.get("target_first_before_adverse_5pct_rate"),
        "base_target_hit_ci_low": base.get("target_hit_ci_low"),
        "base_target_hit_ci_high": base.get("target_hit_ci_high"),
        "failure_5pct_rate": base.get("failure_5pct_rate"),
        "failure_5pct_ci_low": base.get("failure_5pct_ci_low"),
        "failure_5pct_ci_high": base.get("failure_5pct_ci_high"),
        "mfe_mae_median_ratio": base.get("mfe_mae_median_ratio"),
        "median_mfe_pct": round(float(group["mfe_pct"].median()), 2) if "mfe_pct" in group.columns else None,
        "median_mae_pct": round(float(group["mae_pct"].median()), 2) if "mae_pct" in group.columns else None,
        "selected_headline": False,
        "note": note,
    }


def _headline_candidate_score(row: Mapping[str, Any]) -> float:
    n = float(row.get("n") or 0)
    hit = float(row.get("base_target_hit_rate") or 0)
    first = float(row.get("base_target_first_before_adverse_5pct_rate") or 0)
    failure = float(row.get("failure_5pct_rate") or 100)
    ratio = float(row.get("mfe_mae_median_ratio") or 0)
    # Reward sample recovery without letting a large weak bucket win.
    return n * 1.8 + hit * 1.0 + first * 0.55 + min(30.0, ratio * 8.0) - failure * 1.15


def _build_headline_aggregates(events: pd.DataFrame, path: pd.DataFrame) -> list[dict[str, Any]]:
    if events.empty or "bear_branch_lane" not in events.columns:
        return []
    lane = events["bear_branch_lane"].astype(str)
    branch = events["bear_branch_id"].astype(str)
    liquidity = events["liquidity_bucket"].astype(str) if "liquidity_bucket" in events.columns else pd.Series("", index=events.index)
    candidates = [
        _aggregate_branch_metrics(
            events,
            path,
            aggregate_id="defensive_core",
            lane="defensive-core",
            mask=lane == "defensive-core",
            note="Strict headline: only the defensive-core branches.",
        ),
        _aggregate_branch_metrics(
            events,
            path,
            aggregate_id="defensive_expanded",
            lane="defensive-core-plus-watchlist",
            mask=lane.isin(["defensive-core", "defensive-watchlist"]),
            note="Selected when it recovers sample size while preserving hit/failure quality.",
        ),
        _aggregate_branch_metrics(
            events,
            path,
            aggregate_id="high_liquidity_all",
            lane="high-liquidity-diagnostic",
            mask=liquidity == "high",
            note="Diagnostic aggregate matching the strongest data-quality signal from the drop audit.",
        ),
        _aggregate_branch_metrics(
            events,
            path,
            aggregate_id="strict_no_gap_core",
            lane="defensive-core-strict",
            mask=branch == "defensive_core_high_liquidity_no_gap",
            note="Strictest branch; high quality but thinner sample.",
        ),
    ]
    eligible = [
        row
        for row in candidates
        if int(row.get("n") or 0) >= 15
        and float(row.get("base_target_hit_rate") or 0.0) >= 65.0
        and float(row.get("failure_5pct_rate") or 100.0) <= 20.0
        and float(row.get("mfe_mae_median_ratio") or 0.0) >= 1.2
    ]
    selected = (
        max(
            eligible,
            key=lambda row: (
                int(row.get("n") or 0),
                float(row.get("base_target_hit_rate") or 0.0),
                -(float(row.get("failure_5pct_rate") or 100.0)),
                float(row.get("mfe_mae_median_ratio") or 0.0),
            ),
        )
        if eligible
        else (max(candidates, key=_headline_candidate_score) if candidates else None)
    )
    for row in candidates:
        row["headline_score"] = round(_headline_candidate_score(row), 2)
        row["selected_headline"] = bool(selected and row["aggregate_id"] == selected["aggregate_id"])
    return sorted(candidates, key=lambda row: (row.get("selected_headline") is True, float(row.get("headline_score") or 0.0)), reverse=True)


def _add_target_calibration(stats: Dict[str, Any], scan: Mapping[str, Any], path_rows: list[Mapping[str, Any]]) -> None:
    from ..research_support_analysis import (
        PatternArtifacts,
        _flag_subgroups,
        build_target_calibration_decisions,
        target_sensitivity,
    )

    events = pd.DataFrame(list(scan.get("detections") or []))
    path = pd.DataFrame(list(path_rows))
    if events.empty:
        stats["target_family_sensitivity"] = []
        stats["target_calibration_decision"] = None
        stats["robustness_checks"] = _build_bear_flag_robustness_checks(stats)
        return
    if "event_id" not in events.columns and "detection_id" in events.columns:
        events["event_id"] = events["detection_id"]
    sensitivity: list[dict[str, Any]] = []
    for label, subgroup in _flag_subgroups(events, PATTERN_KEY):
        sensitivity.extend(target_sensitivity(PatternArtifacts(label, subgroup.copy(), path), label))
    branch_table = _build_branch_table(events, path)
    for row in branch_table:
        branch_events = events[events["bear_branch_id"].astype(str) == str(row["branch_id"])].copy()
        ids = set(branch_events["event_id"].astype(str))
        branch_path = path[path["event_id"].astype(str).isin(ids)].copy() if ids and "event_id" in path.columns else path.iloc[0:0].copy()
        sensitivity.extend(target_sensitivity(PatternArtifacts(f"{PATTERN_KEY}:branch={row['branch_id']}", branch_events, branch_path), f"{PATTERN_KEY}:branch={row['branch_id']}"))
    decisions = build_target_calibration_decisions(sensitivity, family_labels=(PATTERN_KEY,))
    stats["target_family_sensitivity"] = sensitivity
    stats["target_calibration_decision"] = decisions[0] if decisions else None
    stats["bear_branch_table"] = branch_table
    headline_aggregates = _build_headline_aggregates(events, path)
    stats["bear_branch_headline_candidates"] = headline_aggregates
    stats["bear_branch_headline"] = next((row for row in headline_aggregates if row.get("selected_headline")), headline_aggregates[0] if headline_aggregates else {})
    stats["bear_branch_policy"] = {
        "branching_uses_post_breakout_path": False,
        "headline_scope": "selected ex-ante defensive aggregate; full sample remains informational atlas context",
        "headline_selection_rule": "choose the largest quality-preserving aggregate with N>=15, hit>=65%, failure<=20%, MFE/MAE>=1.2; otherwise fall back to best score",
        "post_breakout_path_quality_usage": "QA/robustness only, not scanner branch selection",
    }
    stats["robustness_checks"] = _build_bear_flag_robustness_checks(stats)


def run_pipeline(
    *,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    out_dir: Path = DEFAULT_OUT_DIR,
    limit_symbols: Optional[int] = None,
    index_db: Path = DEFAULT_INDEX_DB,
    index_symbol: str = DEFAULT_INDEX_SYMBOL,
    market_stats_json: Optional[Path] = DEFAULT_MARKET_STATS_JSON,
    detector_config: Optional[FlagDetectorConfig | Mapping[str, Any]] = None,
    event_filter_config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    active_meta = _load_active_symbols(market_stats_json)
    allowed_symbols = active_meta.get("active_symbols") if active_meta.get("enabled") else None
    raw_scan = scan_market_stats(
        source_dir,
        limit_symbols=limit_symbols,
        index_db=index_db,
        index_symbol=index_symbol,
        allowed_symbols=allowed_symbols,
        detector_config=detector_config,
    )
    raw_scan = _restrict_scan_to_active_universe(raw_scan, market_stats_json)
    scan = _filter_bear_flags(raw_scan)
    _enrich_events(scan, source_dir=source_dir, corporate_db=index_db)
    _assign_bear_branches(scan)
    _apply_event_filter(scan, event_filter_config)
    stats = summarize(scan)
    stats["pattern_key"] = PATTERN_KEY
    stats["chapter_lane"] = "informational/defensive-reference candidate"
    stats["detector_config"] = FlagDetectorConfig.from_mapping(detector_config).to_dict()
    stats["event_filter_config"] = dict(event_filter_config or {})
    stats["event_filter_report"] = scan.get("event_filter_report")
    stats["target_family"] = {
        "bulkowski_adjusted_base": 0.46,
        "rounded_local_base": 0.5,
        "local_stretch": 0.75,
        "legacy_full_pole": 1.0,
    }
    stats["interpretation_boundary"] = {
        "default_lane": "informational/defensive-reference",
        "reason": "Vietnam cash equities do not make downside breakout statistics automatically executable as short-sale opportunities.",
    }
    _add_sensitivity_tables(stats, scan)
    path_rows = _path_rows(scan, source_dir=source_dir)
    _add_target_calibration(stats, scan, path_rows)
    paths = {
        "detections": out_dir / "detections.json",
        "statistics": out_dir / "statistics.json",
        "events_csv": out_dir / "events.csv",
        "post_breakout_path_csv": out_dir / "post_breakout_path.csv",
        "pdf": out_dir / "bear_flags.pdf",
    }
    _write_json(paths["detections"], scan)
    _write_json(paths["statistics"], stats)
    _write_csv(paths["events_csv"], scan.get("detections") or [], BEAR_FLAG_EVENT_FIELDS)
    _write_csv(
        paths["post_breakout_path_csv"],
        path_rows,
        [
            "event_id",
            "symbol",
            "trade_date",
            "bar_after_breakout",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "signed_close_return_pct",
            "signed_high_excursion_pct",
            "signed_low_excursion_pct",
        ],
    )
    _render_pdf(paths["pdf"], stats)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Bear Flag V2 defensive-reference pipeline.")
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--limit-symbols", type=int, default=None)
    parser.add_argument("--index-db", default=str(DEFAULT_INDEX_DB))
    parser.add_argument("--index-symbol", default=DEFAULT_INDEX_SYMBOL)
    parser.add_argument("--market-stats-json", default=str(DEFAULT_MARKET_STATS_JSON))
    args = parser.parse_args()
    paths = run_pipeline(
        source_dir=Path(args.source_dir),
        out_dir=Path(args.out_dir),
        limit_symbols=args.limit_symbols,
        index_db=Path(args.index_db),
        index_symbol=args.index_symbol,
        market_stats_json=Path(args.market_stats_json) if args.market_stats_json else None,
    )
    for key, path in paths.items():
        print(f"{key}: {path}")


__all__ = ["DEFAULT_OUT_DIR", "PATTERN_KEY", "run_pipeline"]


if __name__ == "__main__":
    main()
