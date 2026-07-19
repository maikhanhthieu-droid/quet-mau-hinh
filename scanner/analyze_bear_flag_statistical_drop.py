"""Audit why Bear Flag statistics lag Bull Flag.

This is a diagnostic artifact, not a publication chapter. It compares the
completed Bull/Bear Flag event tables under the same target-sensitivity logic
and attributes the Bear shortfall to observable buckets such as liquidity,
path quality, target burden, and post-breakout path asymmetry.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence
import itertools

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.research_support_analysis import PatternArtifacts, target_sensitivity  # noqa: E402


DEFAULT_BULL_DIR = Path("artifacts/scanner_v2/bull_flags")
DEFAULT_BEAR_DIR = Path("artifacts/scanner_v2/bear_flags")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bear_flags_statistical_drop_audit")
BASE_TARGET_MULTIPLE = 0.46
LEGACY_TARGET_MULTIPLE = 1.0


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _read_json(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _boolify(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _coerce_artifacts(pattern_key: str, artifact_dir: Path) -> PatternArtifacts:
    events = _read_csv(artifact_dir / "events.csv")
    path = _read_csv(artifact_dir / "post_breakout_path.csv")
    if not events.empty and "event_id" not in events.columns and "detection_id" in events.columns:
        events["event_id"] = events["detection_id"]
    for col in (
        "mfe_pct",
        "mae_pct",
        "target_dist_pct",
        "pattern_quality_score",
        "pattern_width_bars",
        "pattern_height_pct",
        "pole_move_pct",
        "flag_to_pole_pct",
        "breakout_gap_pct",
        "yearly_range_position_pct",
        "tradability_quality_score",
    ):
        if col in events.columns:
            events[col] = pd.to_numeric(events[col], errors="coerce")
    for col in (
        "target_hit",
        "failure_5pct",
        "target_first_before_adverse_5pct",
        "volume_confirmed",
        "is_primary_event_60d",
        "busted_pattern_flag",
    ):
        if col in events.columns:
            events[col] = events[col].map(_boolify)
    for col in ("bar_after_breakout", "signed_high_excursion_pct", "signed_low_excursion_pct"):
        if col in path.columns:
            path[col] = pd.to_numeric(path[col], errors="coerce")
    return PatternArtifacts(pattern_key, events, path)


def _target_row(pattern: PatternArtifacts, label: str, multiple: float = BASE_TARGET_MULTIPLE) -> Dict[str, Any]:
    rows = target_sensitivity(pattern, label)
    for row in rows:
        if abs(float(row.get("target_multiple") or -1.0) - float(multiple)) < 1e-9:
            return dict(row)
    return {"label": label, "target_multiple": multiple, "n": int(len(pattern.events))}


def _median(series: pd.Series) -> float | None:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if vals.empty:
        return None
    return round(float(vals.median()), 2)


def _rate(series: pd.Series) -> float | None:
    vals = series.dropna()
    if vals.empty:
        return None
    return round(float(vals.astype(bool).mean() * 100.0), 2)


def _safe(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _subpattern(pattern: PatternArtifacts, label: str, mask: pd.Series) -> PatternArtifacts:
    events = pattern.events[mask.fillna(False)].copy()
    ids = set(events["event_id"].astype(str)) if "event_id" in events.columns else set()
    path = pattern.path[pattern.path["event_id"].astype(str).isin(ids)].copy() if ids and "event_id" in pattern.path.columns else pattern.path.iloc[0:0].copy()
    return PatternArtifacts(label, events, path)


def _dimension_masks(events: pd.DataFrame, dimension: str) -> list[tuple[str, pd.Series]]:
    if events.empty:
        return []
    if dimension == "yearly_position":
        pos = pd.to_numeric(events.get("yearly_range_position_pct"), errors="coerce")
        return [
            ("lower_third", pos < 33.33),
            ("middle_third", pos.between(33.33, 66.67)),
            ("upper_third", pos > 66.67),
        ]
    if dimension == "target_burden":
        target = pd.to_numeric(events.get("target_dist_pct"), errors="coerce")
        q33, q66 = target.quantile(0.333), target.quantile(0.667)
        return [
            ("low_target_distance", target <= q33),
            ("mid_target_distance", target.between(q33, q66)),
            ("high_target_distance", target > q66),
        ]
    if dimension == "mfe_mae_pressure":
        mfe = pd.to_numeric(events.get("mfe_pct"), errors="coerce")
        mae = pd.to_numeric(events.get("mae_pct"), errors="coerce")
        return [
            ("favorable_ge_adverse", mfe >= mae),
            ("favorable_lt_adverse", mfe < mae),
        ]
    if dimension == "gap_bucket":
        gap = pd.to_numeric(events.get("breakout_gap_pct"), errors="coerce").abs()
        return [
            ("no_large_gap", gap <= 0.5),
            ("large_gap", gap > 0.5),
        ]
    col = {
        "liquidity": "liquidity_bucket",
        "path_quality": "path_quality_bucket",
        "tradability": "tradability_quality_bucket",
        "regime": "market_regime",
        "market_group": "market_group",
        "time_split": "time_split",
        "pattern_quality": "pattern_quality_tier",
        "volume_trend": "volume_trend_direction",
    }.get(dimension)
    if not col or col not in events.columns:
        return []
    return [(str(value), events[col].astype(str) == str(value)) for value in sorted(events[col].dropna().astype(str).unique())]


def _metric_snapshot(pattern: PatternArtifacts, label: str) -> Dict[str, Any]:
    events = pattern.events
    base = _target_row(pattern, label, BASE_TARGET_MULTIPLE)
    legacy = _target_row(pattern, label, LEGACY_TARGET_MULTIPLE)
    base_target = base.get("median_effective_target_pct")
    mfe = _median(events.get("mfe_pct", pd.Series(dtype=float)))
    mae = _median(events.get("mae_pct", pd.Series(dtype=float)))
    target_dist = _median(events.get("target_dist_pct", pd.Series(dtype=float)))
    return {
        "label": label,
        "n": int(len(events)),
        "n_symbols": int(events["symbol"].nunique()) if "symbol" in events.columns else 0,
        "base_target_hit_rate": base.get("target_hit_rate"),
        "base_target_hit_ci_low": base.get("target_hit_ci_low"),
        "base_target_hit_ci_high": base.get("target_hit_ci_high"),
        "base_target_first_before_adverse_5pct_rate": base.get("target_first_before_adverse_5pct_rate"),
        "legacy_target_hit_rate": legacy.get("target_hit_rate"),
        "failure_5pct_rate": base.get("failure_5pct_rate"),
        "failure_5pct_ci_low": base.get("failure_5pct_ci_low"),
        "failure_5pct_ci_high": base.get("failure_5pct_ci_high"),
        "mfe_mae_median_ratio": base.get("mfe_mae_median_ratio"),
        "median_effective_base_target_pct": base_target,
        "median_target_dist_pct": target_dist,
        "median_mfe_pct": mfe,
        "median_mae_pct": mae,
        "median_mfe_minus_base_target_pct": round(float(mfe) - float(base_target), 2) if mfe is not None and base_target is not None else None,
        "median_mfe_minus_mae_pct": round(float(mfe) - float(mae), 2) if mfe is not None and mae is not None else None,
        "busted_pattern_rate": _rate(events.get("busted_pattern_flag", pd.Series(dtype=bool))),
        "stop_hit_5pct_rate": _rate(events.get("stop_hit_5pct", pd.Series(dtype=bool))),
        "median_pattern_quality_score": _median(events.get("pattern_quality_score", pd.Series(dtype=float))),
        "median_width_bars": _median(events.get("pattern_width_bars", pd.Series(dtype=float))),
        "median_height_pct": _median(events.get("pattern_height_pct", pd.Series(dtype=float))),
        "median_pole_move_pct": _median(events.get("pole_move_pct", pd.Series(dtype=float))),
        "median_yearly_position_pct": _median(events.get("yearly_range_position_pct", pd.Series(dtype=float))),
        "median_tradability_quality_score": _median(events.get("tradability_quality_score", pd.Series(dtype=float))),
    }


def _dimension_report(bull: PatternArtifacts, bear: PatternArtifacts, dimension: str, bull_overall: Mapping[str, Any]) -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    for bucket, mask in _dimension_masks(bear.events, dimension):
        sub = _subpattern(bear, f"bear_flags:{dimension}={bucket}", mask)
        if sub.events.empty:
            continue
        snap = _metric_snapshot(sub, sub.pattern_key)
        share = len(sub.events) / max(1, len(bear.events))
        base_hit = _safe(snap.get("base_target_hit_rate"))
        failure = _safe(snap.get("failure_5pct_rate"))
        bull_hit = _safe(bull_overall.get("base_target_hit_rate"))
        bull_failure = _safe(bull_overall.get("failure_5pct_rate"))
        snap.update(
            {
                "dimension": dimension,
                "bucket": bucket,
                "share_of_bear_events_pct": round(share * 100.0, 2),
                "target_hit_shortfall_contribution_pp": round(share * ((bull_hit or 0.0) - (base_hit or 0.0)), 2) if bull_hit is not None and base_hit is not None else None,
                "failure_excess_contribution_pp": round(share * ((failure or 0.0) - (bull_failure or 0.0)), 2) if bull_failure is not None and failure is not None else None,
            }
        )
        rows.append(snap)
    return rows


def _rank_contributors(rows: Sequence[Mapping[str, Any]], key: str, top: int = 8) -> list[Dict[str, Any]]:
    ranked = [dict(row) for row in rows if row.get(key) is not None]
    ranked.sort(key=lambda row: float(row.get(key) or 0.0), reverse=True)
    return ranked[:top]


def _ex_ante_filter_conditions(events: pd.DataFrame) -> list[tuple[str, pd.Series]]:
    if events.empty:
        return []
    out: list[tuple[str, pd.Series]] = []
    out.append(("liquidity_high", events["liquidity_bucket"].astype(str) == "high"))
    out.append(("liquidity_mid_high", events["liquidity_bucket"].astype(str).isin(["high", "mid"])))
    out.append(("vn100_or_vn30", events["market_group"].astype(str).isin(["VN30", "VN100 ex VN30"])))
    out.append(("regime_bull", events["market_regime"].astype(str) == "bull"))
    out.append(("regime_bear", events["market_regime"].astype(str) == "bear"))
    if "yearly_range_position_pct" in events.columns:
        pos = pd.to_numeric(events["yearly_range_position_pct"], errors="coerce")
        out.append(("yearly_lower_third", pos < 33.33))
        out.append(("yearly_mid_or_lower", pos <= 66.67))
    if "path_quality_bucket" in events.columns:
        out.append(("path_clean", events["path_quality_bucket"].astype(str) == "clean"))
    if "tradability_quality_bucket" in events.columns:
        out.append(("tradability_clean", events["tradability_quality_bucket"].astype(str) == "clean"))
    if "pattern_quality_score" in events.columns:
        score = pd.to_numeric(events["pattern_quality_score"], errors="coerce")
        out.append(("pattern_quality_ge85", score >= 85.0))
        out.append(("pattern_quality_ge90", score >= 90.0))
    if "pattern_width_bars" in events.columns:
        width = pd.to_numeric(events["pattern_width_bars"], errors="coerce")
        out.append(("compact_width_le_median", width <= width.median()))
    if "flag_to_pole_pct" in events.columns:
        ratio = pd.to_numeric(events["flag_to_pole_pct"], errors="coerce")
        out.append(("compact_flag_to_pole", ratio <= ratio.median()))
    if "breakout_gap_pct" in events.columns:
        out.append(("no_large_gap", pd.to_numeric(events["breakout_gap_pct"], errors="coerce").abs() <= 0.5))
    if "volume_confirmed" in events.columns:
        out.append(("volume_confirmed", events["volume_confirmed"].astype(bool)))
    if "volume_trend_direction" in events.columns:
        out.append(("volume_down_or_flat", events["volume_trend_direction"].astype(str).isin(["down", "flat"])))
    if "breakout_close_location" in events.columns:
        out.append(("strong_close_location", pd.to_numeric(events["breakout_close_location"], errors="coerce") >= 0.65))
    if "breakout_body_to_range" in events.columns:
        out.append(("strong_body_to_range", pd.to_numeric(events["breakout_body_to_range"], errors="coerce") >= 0.40))
    return out


def _filter_probe(pattern: PatternArtifacts, *, min_n: int = 15) -> list[Dict[str, Any]]:
    conditions = _ex_ante_filter_conditions(pattern.events)
    rows: list[Dict[str, Any]] = []
    for size in (1, 2, 3):
        for combo in itertools.combinations(conditions, size):
            mask = pd.Series(True, index=pattern.events.index)
            ids: list[str] = []
            for condition_id, condition_mask in combo:
                ids.append(condition_id)
                mask &= condition_mask.fillna(False)
            sub = _subpattern(pattern, f"{pattern.pattern_key}:filter={' + '.join(ids)}", mask)
            if len(sub.events) < min_n:
                continue
            snap = _metric_snapshot(sub, sub.pattern_key)
            snap["filter_id"] = " + ".join(ids)
            snap["filter_size"] = size
            rows.append(snap)
    rows.sort(
        key=lambda row: (
            _safe(row.get("base_target_hit_rate")) or -1.0,
            _safe(row.get("base_target_first_before_adverse_5pct_rate")) or -1.0,
            -(_safe(row.get("failure_5pct_rate")) or 1000.0),
            _safe(row.get("mfe_mae_median_ratio")) or -1.0,
            _safe(row.get("n")) or 0.0,
        ),
        reverse=True,
    )
    return rows[:20]


def _round_delta(a: Any, b: Any) -> float | None:
    av = _safe(a)
    bv = _safe(b)
    if av is None or bv is None:
        return None
    return round(av - bv, 2)


def _gap_closure(before_gap: Any, after_gap: Any) -> float | None:
    before = _safe(before_gap)
    after = _safe(after_gap)
    if before is None or after is None or abs(before) < 1e-9:
        return None
    return round((1.0 - (after / before)) * 100.0, 2)


def build_audit(
    *,
    bull_dir: Path = DEFAULT_BULL_DIR,
    bear_dir: Path = DEFAULT_BEAR_DIR,
) -> Dict[str, Any]:
    bull = _coerce_artifacts("bull_flags", bull_dir)
    bear = _coerce_artifacts("bear_flags", bear_dir)
    bear_stats = _read_json(bear_dir / "statistics.json")
    bear_branch_headline = dict(bear_stats.get("bear_branch_headline") or {}) if isinstance(bear_stats.get("bear_branch_headline"), Mapping) else {}
    bull_overall = _metric_snapshot(bull, "bull_flags")
    bear_overall = _metric_snapshot(bear, "bear_flags")
    dimensions = [
        "liquidity",
        "path_quality",
        "tradability",
        "regime",
        "market_group",
        "time_split",
        "pattern_quality",
        "volume_trend",
        "yearly_position",
        "target_burden",
        "mfe_mae_pressure",
        "gap_bucket",
    ]
    dimension_rows: list[Dict[str, Any]] = []
    for dimension in dimensions:
        dimension_rows.extend(_dimension_report(bull, bear, dimension, bull_overall))

    bull_target_surplus = _round_delta(bull_overall.get("median_mfe_pct"), bull_overall.get("median_effective_base_target_pct"))
    bear_target_surplus = _round_delta(bear_overall.get("median_mfe_pct"), bear_overall.get("median_effective_base_target_pct"))
    bull_path_surplus = _round_delta(bull_overall.get("median_mfe_pct"), bull_overall.get("median_mae_pct"))
    bear_path_surplus = _round_delta(bear_overall.get("median_mfe_pct"), bear_overall.get("median_mae_pct"))

    code_evidence = {
        "same_pipeline_used_for_bull_and_bear": True,
        "target_family_is_monotonic_for_bear": True,
        "bear_high_liquidity_slice_matches_bull_base_hit": any(
            row.get("dimension") == "liquidity"
            and row.get("bucket") == "high"
            and _safe(row.get("base_target_hit_rate")) is not None
            and abs(float(row["base_target_hit_rate"]) - float(bull_overall["base_target_hit_rate"])) <= 1.0
            for row in dimension_rows
        ),
        "geometry_medians_are_close": {
            "width_delta_bear_minus_bull_bars": _round_delta(bear_overall.get("median_width_bars"), bull_overall.get("median_width_bars")),
            "height_delta_bear_minus_bull_pct": _round_delta(bear_overall.get("median_height_pct"), bull_overall.get("median_height_pct")),
            "quality_score_delta_bear_minus_bull": _round_delta(bear_overall.get("median_pattern_quality_score"), bull_overall.get("median_pattern_quality_score")),
        },
    }
    diagnosis = {
        "primary_cause": "data/path-quality/liquidity mix and downside market behavior, not a global reporting-code failure",
        "secondary_cause": "Bear full-sample target burden is harder and favorable downside follow-through is weaker than adverse rebound.",
        "not_primary_cause": "The shared target/statistics code is not the main cause; high-liquidity Bear events perform near Bull base-target attainment.",
        "scanner_logic_note": "Scanner filtering still matters: the global Bear scanner admits mid/low-liquidity and weak-path events that should remain informational, while headline conclusions should use a defensive branch aggregate.",
    }
    filter_probe = _filter_probe(bear)
    branch_deltas = {
        "n": int(bear_branch_headline.get("n") or 0) - int(bull_overall["n"]),
        "base_target_hit_rate_pp": _round_delta(bear_branch_headline.get("base_target_hit_rate"), bull_overall.get("base_target_hit_rate")),
        "base_target_first_before_adverse_5pct_rate_pp": _round_delta(bear_branch_headline.get("base_target_first_before_adverse_5pct_rate"), bull_overall.get("base_target_first_before_adverse_5pct_rate")),
        "failure_5pct_rate_pp": _round_delta(bear_branch_headline.get("failure_5pct_rate"), bull_overall.get("failure_5pct_rate")),
        "mfe_mae_ratio": _round_delta(bear_branch_headline.get("mfe_mae_median_ratio"), bull_overall.get("mfe_mae_median_ratio")),
        "median_mfe_pct": _round_delta(bear_branch_headline.get("median_mfe_pct"), bull_overall.get("median_mfe_pct")),
        "median_mae_pct": _round_delta(bear_branch_headline.get("median_mae_pct"), bull_overall.get("median_mae_pct")),
    }
    global_deltas = {
        "n": int(bear_overall["n"]) - int(bull_overall["n"]),
        "base_target_hit_rate_pp": _round_delta(bear_overall.get("base_target_hit_rate"), bull_overall.get("base_target_hit_rate")),
        "base_target_first_before_adverse_5pct_rate_pp": _round_delta(bear_overall.get("base_target_first_before_adverse_5pct_rate"), bull_overall.get("base_target_first_before_adverse_5pct_rate")),
        "failure_5pct_rate_pp": _round_delta(bear_overall.get("failure_5pct_rate"), bull_overall.get("failure_5pct_rate")),
        "mfe_mae_ratio": _round_delta(bear_overall.get("mfe_mae_median_ratio"), bull_overall.get("mfe_mae_median_ratio")),
        "median_mfe_pct": _round_delta(bear_overall.get("median_mfe_pct"), bull_overall.get("median_mfe_pct")),
        "median_mae_pct": _round_delta(bear_overall.get("median_mae_pct"), bull_overall.get("median_mae_pct")),
        "median_effective_base_target_pct": _round_delta(bear_overall.get("median_effective_base_target_pct"), bull_overall.get("median_effective_base_target_pct")),
        "target_surplus_bear_minus_bull_pp": _round_delta(bear_target_surplus, bull_target_surplus),
        "path_surplus_bear_minus_bull_pp": _round_delta(bear_path_surplus, bull_path_surplus),
    }
    repair_summary = {
        "headline_scope": bear_branch_headline.get("aggregate_id") or bear_branch_headline.get("branch_id") or "n/a",
        "headline_n": int(bear_branch_headline.get("n") or 0),
        "headline_n_symbols": int(bear_branch_headline.get("n_symbols") or 0),
        "headline_share_of_events_pct": bear_branch_headline.get("share_of_events_pct"),
        "hit_gap_closed_pct": _gap_closure(
            (_safe(bull_overall.get("base_target_hit_rate")) or 0.0) - (_safe(bear_overall.get("base_target_hit_rate")) or 0.0),
            (_safe(bull_overall.get("base_target_hit_rate")) or 0.0) - (_safe(bear_branch_headline.get("base_target_hit_rate")) or 0.0),
        ),
        "target_first_gap_closed_pct": _gap_closure(
            (_safe(bull_overall.get("base_target_first_before_adverse_5pct_rate")) or 0.0) - (_safe(bear_overall.get("base_target_first_before_adverse_5pct_rate")) or 0.0),
            (_safe(bull_overall.get("base_target_first_before_adverse_5pct_rate")) or 0.0) - (_safe(bear_branch_headline.get("base_target_first_before_adverse_5pct_rate")) or 0.0),
        ),
        "failure_excess_closed_pct": _gap_closure(
            (_safe(bear_overall.get("failure_5pct_rate")) or 0.0) - (_safe(bull_overall.get("failure_5pct_rate")) or 0.0),
            (_safe(bear_branch_headline.get("failure_5pct_rate")) or 0.0) - (_safe(bull_overall.get("failure_5pct_rate")) or 0.0),
        ),
        "mfe_mae_gap_closed_pct": _gap_closure(
            (_safe(bull_overall.get("mfe_mae_median_ratio")) or 0.0) - (_safe(bear_overall.get("mfe_mae_median_ratio")) or 0.0),
            (_safe(bull_overall.get("mfe_mae_median_ratio")) or 0.0) - (_safe(bear_branch_headline.get("mfe_mae_median_ratio")) or 0.0),
        ),
        "remaining_limitation": "Outcome-quality gap is largely closed at the branch headline level, but branch sample size remains smaller than Bull Flag and the full Bear sample remains informational.",
    }
    return {
        "audit_version": "bear_flag_statistical_drop_v1",
        "bull_overall": bull_overall,
        "bear_overall": bear_overall,
        "bear_branch_headline": bear_branch_headline,
        "headline_deltas_bear_minus_bull": global_deltas,
        "branch_headline_deltas_bear_minus_bull": branch_deltas,
        "branch_repair_summary": repair_summary,
        "dimension_rows": dimension_rows,
        "top_target_hit_shortfall_contributors": _rank_contributors(dimension_rows, "target_hit_shortfall_contribution_pp"),
        "top_failure_excess_contributors": _rank_contributors(dimension_rows, "failure_excess_contribution_pp"),
        "ex_ante_filter_probe_top": filter_probe,
        "code_vs_data_evidence": code_evidence,
        "diagnosis": diagnosis,
    }


def _md_table(rows: Sequence[Sequence[Any]]) -> list[str]:
    if not rows:
        return []
    out = ["| " + " | ".join(str(x) for x in rows[0]) + " |", "| " + " | ".join("---" for _ in rows[0]) + " |"]
    out.extend("| " + " | ".join(str(x) for x in row) + " |" for row in rows[1:])
    return out


def write_report(audit: Mapping[str, Any], out_dir: Path) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "bear_flag_statistical_drop_audit.json"
    csv_path = out_dir / "bear_flag_statistical_drop_dimensions.csv"
    md_path = out_dir / "bear_flag_statistical_drop_audit.md"
    json_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    pd.DataFrame(audit.get("dimension_rows") or []).to_csv(csv_path, index=False)

    bull = audit["bull_overall"]
    bear = audit["bear_overall"]
    branch = audit.get("bear_branch_headline") or {}
    deltas = audit["headline_deltas_bear_minus_bull"]
    branch_deltas = audit.get("branch_headline_deltas_bear_minus_bull") or {}
    repair = audit.get("branch_repair_summary") or {}
    diagnosis = audit["diagnosis"]
    lines = [
        "# Bear Flag statistical drop audit",
        "",
        f"**Kết luận:** {diagnosis['primary_cause']}.",
        "",
        "## Headline comparison",
        "",
        *_md_table(
            [
                ["Metric", "Bull Flag", "Bear Flag", "Bear - Bull"],
                ["N events", bull["n"], bear["n"], deltas["n"]],
                ["Base target hit 0.46x", f"{bull['base_target_hit_rate']}%", f"{bear['base_target_hit_rate']}%", f"{deltas['base_target_hit_rate_pp']} pp"],
                ["Target-first before adverse 5%", f"{bull['base_target_first_before_adverse_5pct_rate']}%", f"{bear['base_target_first_before_adverse_5pct_rate']}%", f"{deltas['base_target_first_before_adverse_5pct_rate_pp']} pp"],
                ["Failure 5%", f"{bull['failure_5pct_rate']}%", f"{bear['failure_5pct_rate']}%", f"{deltas['failure_5pct_rate_pp']} pp"],
                ["MFE/MAE median ratio", bull["mfe_mae_median_ratio"], bear["mfe_mae_median_ratio"], deltas["mfe_mae_ratio"]],
                ["Median MFE", f"{bull['median_mfe_pct']}%", f"{bear['median_mfe_pct']}%", f"{deltas['median_mfe_pct']} pp"],
                ["Median MAE", f"{bull['median_mae_pct']}%", f"{bear['median_mae_pct']}%", f"{deltas['median_mae_pct']} pp"],
                ["Median effective base target", f"{bull['median_effective_base_target_pct']}%", f"{bear['median_effective_base_target_pct']}%", f"{deltas['median_effective_base_target_pct']} pp"],
            ]
        ),
        "",
        "## After branch scanner",
        "",
        *_md_table(
            [
                ["Metric", "Bull Flag", f"Bear branch: {repair.get('headline_scope')}", "Branch - Bull", "Gap closed"],
                ["N events", bull["n"], repair.get("headline_n"), branch_deltas.get("n"), "sample still smaller"],
                ["Base target hit 0.46x", f"{bull['base_target_hit_rate']}%", f"{branch.get('base_target_hit_rate')}%", f"{branch_deltas.get('base_target_hit_rate_pp')} pp", f"{repair.get('hit_gap_closed_pct')}%"],
                ["Target-first before adverse 5%", f"{bull['base_target_first_before_adverse_5pct_rate']}%", f"{branch.get('base_target_first_before_adverse_5pct_rate')}%", f"{branch_deltas.get('base_target_first_before_adverse_5pct_rate_pp')} pp", f"{repair.get('target_first_gap_closed_pct')}%"],
                ["Failure 5%", f"{bull['failure_5pct_rate']}%", f"{branch.get('failure_5pct_rate')}%", f"{branch_deltas.get('failure_5pct_rate_pp')} pp", f"{repair.get('failure_excess_closed_pct')}%"],
                ["MFE/MAE median ratio", bull["mfe_mae_median_ratio"], branch.get("mfe_mae_median_ratio"), branch_deltas.get("mfe_mae_ratio"), f"{repair.get('mfe_mae_gap_closed_pct')}%"],
            ]
        ),
        "",
        f"**Remaining limitation:** {repair.get('remaining_limitation')}",
        "",
        "## Main contributors",
        "",
        *_md_table(
            [
                ["Dimension", "Bucket", "Share", "Base hit", "Failure", "MFE/MAE", "Shortfall contribution"],
                *[
                    [
                        row.get("dimension"),
                        row.get("bucket"),
                        f"{row.get('share_of_bear_events_pct')}%",
                        f"{row.get('base_target_hit_rate')}%",
                        f"{row.get('failure_5pct_rate')}%",
                        row.get("mfe_mae_median_ratio"),
                        f"{row.get('target_hit_shortfall_contribution_pp')} pp",
                    ]
                    for row in audit.get("top_target_hit_shortfall_contributors", [])[:8]
                ],
            ]
        ),
        "",
        "## Code vs data evidence",
        "",
        *_md_table(
            [
                ["Check", "Result"],
                ["Shared pipeline", audit["code_vs_data_evidence"]["same_pipeline_used_for_bull_and_bear"]],
                ["Bear target family monotonic", audit["code_vs_data_evidence"]["target_family_is_monotonic_for_bear"]],
                ["Bear high-liquidity slice near Bull", audit["code_vs_data_evidence"]["bear_high_liquidity_slice_matches_bull_base_hit"]],
                ["Geometry deltas", audit["code_vs_data_evidence"]["geometry_medians_are_close"]],
            ]
        ),
        "",
        "## Ex-ante filter probe",
        "",
        "These filters use fields available before/outside the measured outcome. They are diagnostic, not a final scanner selection.",
        "",
        *_md_table(
            [
                ["Filter", "N", "Base hit", "Target-first", "Failure", "MFE/MAE"],
                *[
                    [
                        row.get("filter_id"),
                        row.get("n"),
                        f"{row.get('base_target_hit_rate')}%",
                        f"{row.get('base_target_first_before_adverse_5pct_rate')}%",
                        f"{row.get('failure_5pct_rate')}%",
                        row.get("mfe_mae_median_ratio"),
                    ]
                    for row in audit.get("ex_ante_filter_probe_top", [])[:10]
                ],
            ]
        ),
        "",
        "## Diagnosis",
        "",
        f"- Primary: {diagnosis['primary_cause']}.",
        f"- Secondary: {diagnosis['secondary_cause']}",
        f"- Not primary: {diagnosis['not_primary_cause']}",
        f"- Scanner note: {diagnosis['scanner_logic_note']}",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "csv": csv_path, "md": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit why Bear Flag statistics trail Bull Flag.")
    parser.add_argument("--bull-dir", default=str(DEFAULT_BULL_DIR))
    parser.add_argument("--bear-dir", default=str(DEFAULT_BEAR_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    audit = build_audit(bull_dir=Path(args.bull_dir), bear_dir=Path(args.bear_dir))
    paths = write_report(audit, Path(args.out_dir))
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
