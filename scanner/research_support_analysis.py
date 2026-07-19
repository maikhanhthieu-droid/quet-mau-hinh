"""Build technical research-support artifacts for Scanner V2 experiments.

This script does not promote any pattern to official status. It reads completed
event/path artifacts and produces the statistical packet needed before deeper
academic interpretation: uncertainty intervals, target sensitivity, and a
pattern comparison brief.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

_cache_root = Path(".tmp/research_support_cache").resolve()
(_cache_root / "matplotlib").mkdir(parents=True, exist_ok=True)
(_cache_root / "xdg").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_cache_root / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(_cache_root / "xdg"))

import numpy as np
import pandas as pd


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/research_support")
DEFAULT_FLAGS_DIR = Path("artifacts/scanner_v2/flags_experiment")
DEFAULT_BULL_FLAGS_DIR = Path("artifacts/scanner_v2/bull_flags")
FALLBACK_TARGET_MULTIPLES = (0.5, 0.75, 1.0, 1.25)
TARGET_FAMILIES: Dict[str, Sequence[Dict[str, Any]]] = {
    "flags_experiment": (
        {
            "multiple": 0.46,
            "role": "bulkowski_adjusted_base",
            "note": "Flags adjusted benchmark based on fractional pole-height target.",
        },
        {"multiple": 0.5, "role": "rounded_local_base", "note": "Rounded local base target for Vietnam calibration."},
        {"multiple": 0.75, "role": "local_stretch", "note": "Stretch target below full pole-height."},
        {"multiple": 1.0, "role": "legacy_full_pole", "note": "Full pole-height target kept as legacy benchmark."},
    ),
    "bull_flags": (
        {
            "multiple": 0.46,
            "role": "bulkowski_adjusted_base",
            "note": "Bull Flag adjusted benchmark based on fractional pole-height target.",
        },
        {"multiple": 0.5, "role": "rounded_local_base", "note": "Rounded local base target for Vietnam calibration."},
        {"multiple": 0.75, "role": "local_stretch", "note": "Stretch target below full pole-height."},
        {"multiple": 1.0, "role": "legacy_full_pole", "note": "Full pole-height target kept as legacy benchmark."},
    ),
    "bear_flags": (
        {
            "multiple": 0.46,
            "role": "bulkowski_adjusted_base",
            "note": "Bear Flag adjusted benchmark based on fractional pole-height target.",
        },
        {"multiple": 0.5, "role": "rounded_local_base", "note": "Rounded local base target for Vietnam defensive calibration."},
        {"multiple": 0.75, "role": "local_stretch", "note": "Stretch target below full pole-height."},
        {"multiple": 1.0, "role": "legacy_full_pole", "note": "Full pole-height target kept as legacy benchmark."},
    ),
    "triangles_ascending": (
        {"multiple": 0.5, "role": "local_base", "note": "Local base target at half triangle height for Vietnam calibration."},
        {"multiple": 0.75, "role": "local_stretch", "note": "Stretch target below full triangle height."},
        {"multiple": 1.0, "role": "legacy_full_height", "note": "Full triangle-height target kept as legacy benchmark."},
    ),
}
DEFAULT_ANALYSIS_HORIZON_DAYS = 60
BASE_TARGET_RULE = {
    "min_n": 100,
    "min_target_hit_ci_low": 55.0,
    "min_target_first_before_adverse_5pct_rate": 35.0,
    "max_failure_5pct_rate": 30.0,
}
ROBUSTNESS_BASE_MULTIPLE = 0.46


@dataclass(frozen=True)
class PatternArtifacts:
    pattern_key: str
    events: pd.DataFrame
    path: pd.DataFrame


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _coerce_bool(series: pd.Series) -> pd.Series:
    if series.empty:
        return series
    return series.map(
        lambda value: value
        if isinstance(value, bool)
        else str(value).strip().lower() in {"true", "1", "yes", "y"}
        if pd.notna(value)
        else np.nan
    )


def load_pattern_artifacts(pattern_key: str, artifact_dir: Path) -> PatternArtifacts:
    events = _read_csv(artifact_dir / "events.csv")
    path = _read_csv(artifact_dir / "post_breakout_path.csv")
    if not events.empty and "event_id" not in events.columns and "detection_id" in events.columns:
        events["event_id"] = events["detection_id"]
    for col in ("mfe_pct", "mae_pct", "target_dist_pct", "pattern_quality_score"):
        if col in events.columns:
            events[col] = pd.to_numeric(events[col], errors="coerce")
    for col in ("target_hit", "failure_5pct", "target_first_before_adverse_5pct"):
        if col in events.columns:
            events[col] = _coerce_bool(events[col])
    for col in ("bar_after_breakout", "signed_high_excursion_pct", "signed_low_excursion_pct"):
        if col in path.columns:
            path[col] = pd.to_numeric(path[col], errors="coerce")
    return PatternArtifacts(pattern_key=pattern_key, events=events, path=path)


def wilson_ci(successes: int, total: int, z: float = 1.959963984540054) -> Dict[str, Optional[float]]:
    if total <= 0:
        return {"rate": None, "low": None, "high": None, "n": 0}
    phat = successes / total
    denom = 1 + z * z / total
    center = (phat + z * z / (2 * total)) / denom
    half = z * math.sqrt((phat * (1 - phat) + z * z / (4 * total)) / total) / denom
    return {
        "rate": round(phat * 100.0, 2),
        "low": round((center - half) * 100.0, 2),
        "high": round((center + half) * 100.0, 2),
        "n": int(total),
    }


def _median(values: Iterable[Any]) -> Optional[float]:
    vals = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna()
    if vals.empty:
        return None
    return round(float(vals.median()), 2)


def _rate(series: pd.Series) -> Optional[float]:
    vals = series.dropna()
    if vals.empty:
        return None
    return round(float(vals.mean()) * 100.0, 2)


def _ci_rate(series: pd.Series) -> Dict[str, Optional[float]]:
    vals = series.dropna()
    if vals.empty:
        return wilson_ci(0, 0)
    return wilson_ci(int(vals.sum()), int(len(vals)))


def target_family_for_label(label: str) -> Sequence[Dict[str, Any]]:
    for key, family in TARGET_FAMILIES.items():
        if label == key or label.startswith(f"{key}:"):
            return family
    return tuple({"multiple": multiple, "role": "generic", "note": "Generic fallback band."} for multiple in FALLBACK_TARGET_MULTIPLES)


def _cluster_bootstrap_ci(
    df: pd.DataFrame,
    *,
    column: str,
    reducer: str,
    cluster_col: str = "symbol",
    iterations: int = 400,
    seed: int = 20260516,
) -> Dict[str, Optional[float]]:
    if df.empty or column not in df.columns or cluster_col not in df.columns:
        return {"low": None, "high": None, "iterations": 0}
    usable = df[[cluster_col, column]].dropna()
    if usable.empty:
        return {"low": None, "high": None, "iterations": 0}
    clusters = usable[cluster_col].dropna().unique()
    if len(clusters) == 0:
        return {"low": None, "high": None, "iterations": 0}
    grouped = {cluster: usable[usable[cluster_col] == cluster][column].to_numpy(dtype=float) for cluster in clusters}
    rng = np.random.default_rng(seed)
    values: List[float] = []
    for _ in range(iterations):
        sampled = rng.choice(clusters, size=len(clusters), replace=True)
        arr = np.concatenate([grouped[item] for item in sampled])
        if arr.size == 0:
            continue
        if reducer == "median":
            values.append(float(np.median(arr)))
        elif reducer == "mean":
            values.append(float(np.mean(arr)))
        elif reducer == "rate":
            values.append(float(np.mean(arr)) * 100.0)
        else:
            raise ValueError(f"unsupported reducer {reducer}")
    if not values:
        return {"low": None, "high": None, "iterations": 0}
    return {
        "low": round(float(np.percentile(values, 2.5)), 2),
        "high": round(float(np.percentile(values, 97.5)), 2),
        "iterations": len(values),
    }


def summarize_events(label: str, events: pd.DataFrame) -> Dict[str, Any]:
    if events.empty:
        return {
            "label": label,
            "n": 0,
            "n_symbols": 0,
        }
    target_hit = events["target_hit"] if "target_hit" in events.columns else pd.Series(dtype=float)
    failure = events["failure_5pct"] if "failure_5pct" in events.columns else pd.Series(dtype=float)
    target_first = (
        events["target_first_before_adverse_5pct"] if "target_first_before_adverse_5pct" in events.columns else pd.Series(dtype=float)
    )
    return {
        "label": label,
        "n": int(len(events)),
        "n_symbols": int(events["symbol"].nunique()) if "symbol" in events.columns else 0,
        "median_mfe_pct": _median(events.get("mfe_pct", [])),
        "median_mfe_cluster_bootstrap_ci": _cluster_bootstrap_ci(events, column="mfe_pct", reducer="median"),
        "median_mae_pct": _median(events.get("mae_pct", [])),
        "median_mae_cluster_bootstrap_ci": _cluster_bootstrap_ci(events, column="mae_pct", reducer="median"),
        "median_target_dist_pct": _median(events.get("target_dist_pct", [])),
        "target_hit_ci": _ci_rate(target_hit),
        "failure_5pct_ci": _ci_rate(failure),
        "target_first_before_adverse_5pct_ci": _ci_rate(target_first),
    }


def _race_target_before_adverse(path: pd.DataFrame, target_pct: float, adverse_pct: float = 5.0) -> Dict[str, bool]:
    if path.empty:
        return {}
    required = {"event_id", "bar_after_breakout", "signed_high_excursion_pct", "signed_low_excursion_pct"}
    if not required.issubset(path.columns):
        return {}
    out: Dict[str, bool] = {}
    for event_id, group in path.dropna(subset=["event_id"]).groupby("event_id"):
        ordered = group.sort_values("bar_after_breakout")
        target_rows = ordered[ordered["signed_high_excursion_pct"] >= target_pct]
        adverse_rows = ordered[ordered["signed_low_excursion_pct"] <= -adverse_pct]
        target_bar = None if target_rows.empty else int(target_rows.iloc[0]["bar_after_breakout"])
        adverse_bar = None if adverse_rows.empty else int(adverse_rows.iloc[0]["bar_after_breakout"])
        if target_bar is None:
            out[str(event_id)] = False
        elif adverse_bar is None:
            out[str(event_id)] = True
        else:
            out[str(event_id)] = target_bar < adverse_bar
    return out


def target_sensitivity(pattern: PatternArtifacts, label: str, *, horizon_days: int = DEFAULT_ANALYSIS_HORIZON_DAYS) -> List[Dict[str, Any]]:
    events = pattern.events.copy()
    if events.empty or "target_dist_pct" not in events.columns or "mfe_pct" not in events.columns:
        return []
    failure = events["failure_5pct"] if "failure_5pct" in events.columns else pd.Series(dtype=float)
    failure_ci = _ci_rate(failure)
    mfe_median = _median(events.get("mfe_pct", []))
    mae_median = _median(events.get("mae_pct", []))
    mfe_mae_ratio = None
    if mfe_median is not None and mae_median not in (None, 0):
        mfe_mae_ratio = round(float(mfe_median) / float(mae_median), 2)
    path = pattern.path
    if not path.empty and "bar_after_breakout" in path.columns:
        path = path[path["bar_after_breakout"] <= int(horizon_days)].copy()
    path_groups = {
        str(event_id): group.sort_values("bar_after_breakout")
        for event_id, group in path.dropna(subset=["event_id"]).groupby("event_id")
    } if not path.empty and "event_id" in path.columns else {}
    rows: List[Dict[str, Any]] = []
    for target_def in target_family_for_label(label):
        multiple = float(target_def["multiple"])
        threshold = events["target_dist_pct"] * multiple
        hit = events["mfe_pct"] >= threshold
        has_path_schema = not pattern.path.empty and "event_id" in pattern.path.columns
        if has_path_schema:
            race_values = []
            for _, row in events.iterrows():
                event_id = str(row.get("event_id"))
                target_pct = float(row.get("target_dist_pct") or 0.0) * multiple
                per_event = path_groups.get(event_id)
                if per_event is None:
                    race_values.append(False)
                    continue
                target_rows = per_event[per_event["signed_high_excursion_pct"] >= target_pct]
                adverse_rows = per_event[per_event["signed_low_excursion_pct"] <= -5.0]
                target_bar = None if target_rows.empty else int(target_rows.iloc[0]["bar_after_breakout"])
                adverse_bar = None if adverse_rows.empty else int(adverse_rows.iloc[0]["bar_after_breakout"])
                race_values.append(False if target_bar is None else (True if adverse_bar is None else target_bar < adverse_bar))
            race_series = pd.Series(race_values)
        else:
            race_series = pd.Series(dtype=float)
        rows.append(
            {
                "label": label,
                "target_multiple": multiple,
                "target_role": target_def.get("role"),
                "target_note": target_def.get("note"),
                "median_effective_target_pct": round(float(threshold.median()), 2) if threshold.notna().any() else None,
                "target_hit_rate": _rate(hit),
                "target_hit_ci_low": _ci_rate(hit)["low"],
                "target_hit_ci_high": _ci_rate(hit)["high"],
                "target_first_before_adverse_5pct_rate": _rate(race_series),
                "failure_5pct_rate": failure_ci.get("rate"),
                "failure_5pct_ci_low": failure_ci.get("low"),
                "failure_5pct_ci_high": failure_ci.get("high"),
                "mfe_mae_median_ratio": mfe_mae_ratio,
                "horizon_days": int(horizon_days),
                "n": int(hit.dropna().shape[0]),
            }
        )
    return rows


def _bool_mask(series: pd.Series) -> pd.Series:
    return series.map(lambda value: str(value).strip().lower() in {"true", "1", "yes"})


def _bull_flag_subgroups(events: pd.DataFrame) -> List[tuple[str, pd.DataFrame]]:
    return _flag_subgroups(events, "bull_flags")


def _flag_subgroups(events: pd.DataFrame, pattern_key: str) -> List[tuple[str, pd.DataFrame]]:
    if events.empty:
        return []
    groups: List[tuple[str, pd.DataFrame]] = [(pattern_key, events.copy())]
    if "liquidity_bucket" in events.columns:
        for bucket in ("high", "mid", "low"):
            subset = events[events["liquidity_bucket"].astype(str) == bucket].copy()
            if not subset.empty:
                groups.append((f"{pattern_key}:liquidity={bucket}", subset))
    if "is_primary_event_60d" in events.columns:
        primary = _bool_mask(events["is_primary_event_60d"])
        groups.append((f"{pattern_key}:primary_60d=true", events[primary].copy()))
        groups.append((f"{pattern_key}:primary_60d=false", events[~primary].copy()))
    if "halted_delisted_proxy_flag" in events.columns:
        flagged = _bool_mask(events["halted_delisted_proxy_flag"])
        groups.append((f"{pattern_key}:path_proxy_clean", events[~flagged].copy()))
        groups.append((f"{pattern_key}:path_proxy_flagged", events[flagged].copy()))
    if "path_quality_bucket" in events.columns:
        for bucket in ("clean", "stale_close", "zero_and_stale", "zero_volume", "short_path", "mixed_flag"):
            subset = events[events["path_quality_bucket"].astype(str) == bucket].copy()
            if not subset.empty:
                groups.append((f"{pattern_key}:path_quality={bucket}", subset))
    if "market_regime" in events.columns:
        for regime in ("bull", "bear", "unknown"):
            subset = events[events["market_regime"].astype(str) == regime].copy()
            if not subset.empty:
                groups.append((f"{pattern_key}:regime={regime}", subset))
    if "time_split" in events.columns:
        for split in ("train_60", "validation_20", "holdout_20", "unknown"):
            subset = events[events["time_split"].astype(str) == split].copy()
            if not subset.empty:
                groups.append((f"{pattern_key}:time={split}", subset))
    if "corp_action_proxy_flag" in events.columns:
        flagged = _bool_mask(events["corp_action_proxy_flag"])
        groups.append((f"{pattern_key}:corp_proxy_clean", events[~flagged].copy()))
        groups.append((f"{pattern_key}:corp_proxy_flagged", events[flagged].copy()))
    return [(label, group) for label, group in groups if not group.empty]


def _target_row_passes_base_rule(row: Mapping[str, Any], *, min_n: int) -> bool:
    if int(row.get("n") or 0) < int(min_n):
        return False
    hit_low = row.get("target_hit_ci_low")
    target_first = row.get("target_first_before_adverse_5pct_rate")
    failure = row.get("failure_5pct_rate")
    if hit_low is None or target_first is None or failure is None:
        return False
    return (
        float(hit_low) >= float(BASE_TARGET_RULE["min_target_hit_ci_low"])
        and float(target_first) >= float(BASE_TARGET_RULE["min_target_first_before_adverse_5pct_rate"])
        and float(failure) <= float(BASE_TARGET_RULE["max_failure_5pct_rate"])
    )


def _target_score(row: Mapping[str, Any]) -> float:
    hit_low = float(row.get("target_hit_ci_low") or 0.0)
    target_first = float(row.get("target_first_before_adverse_5pct_rate") or 0.0)
    failure = float(row.get("failure_5pct_rate") or 100.0)
    ratio = float(row.get("mfe_mae_median_ratio") or 0.0)
    n = min(int(row.get("n") or 0), 200) / 200.0
    raw = (0.35 * hit_low) + (0.30 * target_first) + (0.20 * max(0.0, 100.0 - failure)) + (0.10 * min(ratio, 2.0) * 50.0) + (0.05 * n * 100.0)
    return round(raw, 2)


def build_target_calibration_decisions(
    sensitivity_rows: Sequence[Mapping[str, Any]],
    *,
    family_labels: Sequence[str] = ("bull_flags",),
) -> List[Dict[str, Any]]:
    decisions: List[Dict[str, Any]] = []
    for label in family_labels:
        rows = [dict(row) for row in sensitivity_rows if row.get("label") == label]
        if not rows:
            continue
        min_n = int(BASE_TARGET_RULE["min_n"]) if label == "bull_flags" else 30
        for row in rows:
            row["base_rule_pass"] = _target_row_passes_base_rule(row, min_n=min_n)
            row["calibration_score"] = _target_score(row)
        passing = [row for row in rows if row["base_rule_pass"]]
        if passing:
            selected = passing[0]
            status = "selected_base_target"
            reason = "First target band passing the preregistered base-target rule, preserving Bulkowski-adjusted family order."
        else:
            selected = max(rows, key=lambda item: item["calibration_score"])
            status = "no_base_target_pass"
            reason = "No target band passed all base-target gates; best score is reported for diagnostics only."
        decisions.append(
            {
                "label": label,
                "selected_target_multiple": selected.get("target_multiple"),
                "selected_target_role": selected.get("target_role"),
                "status": status,
                "reason": reason,
                "rule": dict(BASE_TARGET_RULE) | {"min_n_applied": min_n},
                "selected_metrics": {
                    "n": selected.get("n"),
                    "target_hit_rate": selected.get("target_hit_rate"),
                    "target_hit_ci_low": selected.get("target_hit_ci_low"),
                    "target_hit_ci_high": selected.get("target_hit_ci_high"),
                    "target_first_before_adverse_5pct_rate": selected.get("target_first_before_adverse_5pct_rate"),
                    "failure_5pct_rate": selected.get("failure_5pct_rate"),
                    "mfe_mae_median_ratio": selected.get("mfe_mae_median_ratio"),
                    "calibration_score": selected.get("calibration_score"),
                },
                "candidates": rows,
            }
        )
    return decisions


def _row_for_target(
    sensitivity_rows: Sequence[Mapping[str, Any]],
    *,
    label: str,
    target_multiple: float = ROBUSTNESS_BASE_MULTIPLE,
) -> Optional[Dict[str, Any]]:
    for row in sensitivity_rows:
        if row.get("label") == label and float(row.get("target_multiple") or -1) == float(target_multiple):
            return dict(row)
    return None


def _target_row_passes_metrics(row: Optional[Mapping[str, Any]], *, min_n: int = 30) -> bool:
    if not row:
        return False
    if int(row.get("n") or 0) < int(min_n):
        return False
    if row.get("target_hit_rate") is None or row.get("target_first_before_adverse_5pct_rate") is None:
        return False
    if row.get("failure_5pct_rate") is None:
        return False
    return (
        float(row.get("target_hit_rate") or 0.0) >= 65.0
        and float(row.get("target_first_before_adverse_5pct_rate") or 0.0) >= 35.0
        and float(row.get("failure_5pct_rate") or 100.0) <= 30.0
    )


def _target_row_has_precision(row: Optional[Mapping[str, Any]]) -> bool:
    return bool(row and row.get("target_hit_ci_low") is not None and float(row.get("target_hit_ci_low") or 0.0) >= 55.0)


def build_bull_flag_robustness_checks(report: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Convert Bull Flag sensitivity rows into publication-facing robustness gates.

    These checks are intentionally conservative. They do not decide whether a
    pattern is tradable; they decide whether the current available-series chapter
    can be read as a watchlist/reference chapter without overstating the data.
    """

    sensitivity = list(report.get("target_sensitivity") or [])
    decisions = list(report.get("target_calibration_decisions") or [])
    decision = next((row for row in decisions if row.get("label") == "bull_flags"), {})
    base = _row_for_target(sensitivity, label="bull_flags")
    legacy = _row_for_target(sensitivity, label="bull_flags", target_multiple=1.0)
    checks: List[Dict[str, Any]] = []

    base_selected = (
        decision.get("status") == "selected_base_target"
        and float(decision.get("selected_target_multiple") or -1) == ROBUSTNESS_BASE_MULTIPLE
        and _target_row_passes_base_rule(base or {}, min_n=int(BASE_TARGET_RULE["min_n"]))
    )
    checks.append(
        {
            "check_id": "base_target_selection",
            "status": "pass" if base_selected else "fail",
            "evidence": {
                "selected_target_multiple": decision.get("selected_target_multiple"),
                "selected_target_role": decision.get("selected_target_role"),
                "n": base.get("n") if base else None,
                "target_hit_rate": base.get("target_hit_rate") if base else None,
                "target_hit_ci_low": base.get("target_hit_ci_low") if base else None,
                "target_first_before_adverse_5pct_rate": base.get("target_first_before_adverse_5pct_rate") if base else None,
                "failure_5pct_rate": base.get("failure_5pct_rate") if base else None,
            },
            "interpretation": "0.46x pole is accepted as the Bull Flag base target only if it passes the preregistered base-target rule.",
        }
    )

    legacy_fails_base = not _target_row_passes_base_rule(legacy or {}, min_n=int(BASE_TARGET_RULE["min_n"]))
    checks.append(
        {
            "check_id": "legacy_1x_stretch_target",
            "status": "pass" if legacy_fails_base else "partial",
            "evidence": {
                "target_hit_rate": legacy.get("target_hit_rate") if legacy else None,
                "target_hit_ci_low": legacy.get("target_hit_ci_low") if legacy else None,
                "target_first_before_adverse_5pct_rate": legacy.get("target_first_before_adverse_5pct_rate") if legacy else None,
                "failure_5pct_rate": legacy.get("failure_5pct_rate") if legacy else None,
            },
            "interpretation": "The full 1.0x pole target remains a stretch/legacy benchmark, not the headline base target.",
        }
    )

    liquidity_labels = [f"bull_flags:liquidity={bucket}" for bucket in ("high", "mid", "low")]
    liquidity_rows = [_row_for_target(sensitivity, label=label) for label in liquidity_labels]
    liquidity_metric_pass = all(_target_row_passes_metrics(row, min_n=30) for row in liquidity_rows)
    liquidity_precision_pass = all(_target_row_has_precision(row) for row in liquidity_rows)
    checks.append(
        {
            "check_id": "liquidity_bucket_consistency",
            "status": "pass" if liquidity_metric_pass and liquidity_precision_pass else "partial" if liquidity_metric_pass else "fail",
            "evidence": {
                (row or {}).get("label", label): {
                    "n": (row or {}).get("n"),
                    "target_hit_rate": (row or {}).get("target_hit_rate"),
                    "target_hit_ci_low": (row or {}).get("target_hit_ci_low"),
                    "target_first_before_adverse_5pct_rate": (row or {}).get("target_first_before_adverse_5pct_rate"),
                    "failure_5pct_rate": (row or {}).get("failure_5pct_rate"),
                }
                for row, label in zip(liquidity_rows, liquidity_labels)
            },
            "interpretation": "Base-target behavior should keep the same direction across high/mid/low liquidity buckets; small bucket N can still limit precision.",
        }
    )

    primary = _row_for_target(sensitivity, label="bull_flags:primary_60d=true")
    repeat = _row_for_target(sensitivity, label="bull_flags:primary_60d=false")
    primary_pass = _target_row_passes_base_rule(primary or {}, min_n=70)
    checks.append(
        {
            "check_id": "primary_event_60d_sensitivity",
            "status": "pass" if primary_pass else "partial",
            "evidence": {
                "primary_event_60d": {
                    "n": primary.get("n") if primary else None,
                    "target_hit_rate": primary.get("target_hit_rate") if primary else None,
                    "target_first_before_adverse_5pct_rate": primary.get("target_first_before_adverse_5pct_rate") if primary else None,
                    "failure_5pct_rate": primary.get("failure_5pct_rate") if primary else None,
                },
                "repeat_events_within_60d": {
                    "n": repeat.get("n") if repeat else None,
                    "target_hit_rate": repeat.get("target_hit_rate") if repeat else None,
                },
            },
            "interpretation": "The result should remain visible after keeping one primary event per symbol within 60 days.",
        }
    )

    path_clean = _row_for_target(sensitivity, label="bull_flags:path_proxy_clean")
    path_flagged = _row_for_target(sensitivity, label="bull_flags:path_proxy_flagged")
    clean_pass = _target_row_passes_metrics(path_clean, min_n=30)
    flagged_pass = _target_row_passes_metrics(path_flagged, min_n=30)
    checks.append(
        {
            "check_id": "path_proxy_quality_sensitivity",
            "status": "pass" if clean_pass and flagged_pass else "partial" if clean_pass else "fail",
            "evidence": {
                "path_proxy_clean": {
                    "n": path_clean.get("n") if path_clean else None,
                    "target_hit_rate": path_clean.get("target_hit_rate") if path_clean else None,
                    "target_hit_ci_low": path_clean.get("target_hit_ci_low") if path_clean else None,
                    "target_first_before_adverse_5pct_rate": path_clean.get("target_first_before_adverse_5pct_rate") if path_clean else None,
                    "failure_5pct_rate": path_clean.get("failure_5pct_rate") if path_clean else None,
                    "mfe_mae_median_ratio": path_clean.get("mfe_mae_median_ratio") if path_clean else None,
                },
                "path_proxy_flagged": {
                    "n": path_flagged.get("n") if path_flagged else None,
                    "target_hit_rate": path_flagged.get("target_hit_rate") if path_flagged else None,
                    "target_hit_ci_low": path_flagged.get("target_hit_ci_low") if path_flagged else None,
                    "target_first_before_adverse_5pct_rate": path_flagged.get("target_first_before_adverse_5pct_rate") if path_flagged else None,
                    "failure_5pct_rate": path_flagged.get("failure_5pct_rate") if path_flagged else None,
                    "mfe_mae_median_ratio": path_flagged.get("mfe_mae_median_ratio") if path_flagged else None,
                },
            },
            "interpretation": "Clean path-proxy events are stronger than flagged events, so path-quality flags remain a real caveat.",
        }
    )

    clean_bucket = _row_for_target(sensitivity, label="bull_flags:path_quality=clean")
    stale_bucket = _row_for_target(sensitivity, label="bull_flags:path_quality=stale_close")
    zero_stale_bucket = _row_for_target(sensitivity, label="bull_flags:path_quality=zero_and_stale")
    short_bucket = _row_for_target(sensitivity, label="bull_flags:path_quality=short_path")
    bucket_rows = [row for row in (clean_bucket, stale_bucket, zero_stale_bucket, short_bucket) if row]
    clean_bucket_pass = _target_row_passes_metrics(clean_bucket, min_n=30)
    non_clean_large = [row for row in (stale_bucket, zero_stale_bucket, short_bucket) if row and int(row.get("n") or 0) >= 20]
    non_clean_all_pass = all(_target_row_passes_metrics(row, min_n=20) for row in non_clean_large)
    checks.append(
        {
            "check_id": "path_quality_bucket_audit",
            "status": "pass" if clean_bucket_pass and non_clean_all_pass else "partial" if clean_bucket_pass else "fail",
            "evidence": {
                (row or {}).get("label", "missing"): {
                    "n": row.get("n"),
                    "target_hit_rate": row.get("target_hit_rate"),
                    "target_hit_ci_low": row.get("target_hit_ci_low"),
                    "target_first_before_adverse_5pct_rate": row.get("target_first_before_adverse_5pct_rate"),
                    "failure_5pct_rate": row.get("failure_5pct_rate"),
                    "mfe_mae_median_ratio": row.get("mfe_mae_median_ratio"),
                }
                for row in bucket_rows
            },
            "interpretation": "Detailed path buckets separate clean paths from stale/zero-volume/short-path cases; weak non-clean buckets prevent promotion beyond watchlist-reference.",
        }
    )

    regime_labels = [f"bull_flags:regime={regime}" for regime in ("bull", "bear")]
    regime_rows = [_row_for_target(sensitivity, label=label) for label in regime_labels]
    regime_metric_pass = all(_target_row_passes_metrics(row, min_n=30) for row in regime_rows)
    regime_precision_pass = all(_target_row_has_precision(row) for row in regime_rows)
    checks.append(
        {
            "check_id": "regime_split_consistency",
            "status": "pass" if regime_metric_pass and regime_precision_pass else "partial" if regime_metric_pass else "fail",
            "evidence": {
                (row or {}).get("label", label): {
                    "n": (row or {}).get("n"),
                    "target_hit_rate": (row or {}).get("target_hit_rate"),
                    "target_hit_ci_low": (row or {}).get("target_hit_ci_low"),
                    "target_first_before_adverse_5pct_rate": (row or {}).get("target_first_before_adverse_5pct_rate"),
                    "failure_5pct_rate": (row or {}).get("failure_5pct_rate"),
                }
                for row, label in zip(regime_rows, regime_labels)
            },
            "interpretation": "Bull Flag should not be promoted if the base target only survives in one VNINDEX regime.",
        }
    )

    time_labels = [f"bull_flags:time={split}" for split in ("train_60", "validation_20", "holdout_20")]
    time_rows = [_row_for_target(sensitivity, label=label) for label in time_labels]
    holdout = _row_for_target(sensitivity, label="bull_flags:time=holdout_20")
    train_validation_pass = all(_target_row_passes_metrics(row, min_n=20) for row in time_rows[:2])
    holdout_metric_pass = _target_row_passes_metrics(holdout, min_n=20)
    holdout_precision_pass = _target_row_has_precision(holdout)
    checks.append(
        {
            "check_id": "time_holdout_consistency",
            "status": "pass" if train_validation_pass and holdout_metric_pass and holdout_precision_pass else "partial" if holdout_metric_pass else "fail",
            "evidence": {
                (row or {}).get("label", label): {
                    "n": (row or {}).get("n"),
                    "target_hit_rate": (row or {}).get("target_hit_rate"),
                    "target_hit_ci_low": (row or {}).get("target_hit_ci_low"),
                    "target_first_before_adverse_5pct_rate": (row or {}).get("target_first_before_adverse_5pct_rate"),
                    "failure_5pct_rate": (row or {}).get("failure_5pct_rate"),
                }
                for row, label in zip(time_rows, time_labels)
            },
            "interpretation": "Chronological train/validation/holdout checks reduce the risk that the 0.46x target is only an in-sample calibration artifact.",
        }
    )

    corp_flagged = _row_for_target(sensitivity, label="bull_flags:corp_proxy_flagged")
    checks.append(
        {
            "check_id": "corporate_action_proxy_scope",
            "status": "pass" if corp_flagged is None or int(corp_flagged.get("n") or 0) == 0 else "partial",
            "evidence": {
                "corp_proxy_flagged_n": corp_flagged.get("n") if corp_flagged else 0,
            },
            "interpretation": "No local corporate-action proxy hits means this run has no obvious large adjustment artifact near Bull Flag breakouts.",
        }
    )

    gate = (report.get("data_gate_audits") or {}).get("bull_flags") if isinstance(report.get("data_gate_audits"), Mapping) else {}
    blocked_by = gate.get("blocked_by") if isinstance(gate, Mapping) else []
    checks.append(
        {
            "check_id": "available_series_data_gates",
            "status": "pass" if not blocked_by else "fail",
            "evidence": {
                "blocked_by": blocked_by or [],
                "gate_pass": gate.get("investment_reference_data_gates_pass") if isinstance(gate, Mapping) else None,
            },
            "interpretation": "This is scoped to available active-series data gates, not a claim of full historical point-in-time universe coverage.",
        }
    )

    hard_fail = any(row["status"] == "fail" for row in checks if row["check_id"] in {"base_target_selection", "available_series_data_gates"})
    partials = [row["check_id"] for row in checks if row["status"] == "partial"]
    noncritical_fails = [
        row["check_id"]
        for row in checks
        if row["status"] == "fail" and row["check_id"] not in {"base_target_selection", "available_series_data_gates"}
    ]
    checks.append(
        {
            "check_id": "classification_after_robustness",
            "status": "fail" if hard_fail else "partial" if partials or noncritical_fails else "pass",
            "evidence": {
                "classification": "not-usable" if hard_fail else "watchlist-reference" if partials or noncritical_fails else "investment-reference-candidate",
                "partial_checks": partials,
                "noncritical_fail_checks": noncritical_fails,
            },
            "interpretation": "Bull Flag currently qualifies as watchlist-reference in available-series scope; investment-reference still needs stronger path/data confirmation.",
        }
    )
    return checks


def build_comparison(patterns: Sequence[PatternArtifacts], *, horizon_days: int = DEFAULT_ANALYSIS_HORIZON_DAYS) -> Dict[str, Any]:
    summaries: List[Dict[str, Any]] = []
    sensitivity_rows: List[Dict[str, Any]] = []
    for pattern in patterns:
        events = pattern.events
        summaries.append(summarize_events(pattern.pattern_key, events))
        sensitivity_rows.extend(target_sensitivity(pattern, pattern.pattern_key, horizon_days=horizon_days))
        if pattern.pattern_key == "bull_flags":
            for label, subgroup in _bull_flag_subgroups(events):
                if label == "bull_flags":
                    continue
                summaries.append(summarize_events(label, subgroup))
                sensitivity_rows.extend(target_sensitivity(PatternArtifacts(label, subgroup.copy(), pattern.path), label, horizon_days=horizon_days))
            continue
        if pattern.pattern_key != "bull_flags" and "variant" in events.columns:
            for variant, group in events.groupby("variant"):
                label = f"{pattern.pattern_key}:{variant}"
                summaries.append(summarize_events(label, group))
                sensitivity_rows.extend(target_sensitivity(PatternArtifacts(label, group.copy(), pattern.path), label, horizon_days=horizon_days))
        if "pattern_quality_tier" in events.columns:
            for tier, group in events.groupby("pattern_quality_tier"):
                label = f"{pattern.pattern_key}:quality={tier}"
                summaries.append(summarize_events(label, group))
        if "liquidity_bucket" in events.columns:
            for bucket, group in events.groupby("liquidity_bucket"):
                label = f"{pattern.pattern_key}:liquidity={bucket}"
                summaries.append(summarize_events(label, group))
        if "is_primary_event_60d" in events.columns:
            bools = events["is_primary_event_60d"].map(lambda value: str(value).strip().lower() in {"true", "1", "yes"})
            summaries.append(summarize_events(f"{pattern.pattern_key}:primary_60d=true", events[bools].copy()))
            summaries.append(summarize_events(f"{pattern.pattern_key}:primary_60d=false", events[~bools].copy()))
        if "corp_action_proxy_flag" in events.columns:
            bools = events["corp_action_proxy_flag"].map(lambda value: str(value).strip().lower() in {"true", "1", "yes"})
            summaries.append(summarize_events(f"{pattern.pattern_key}:corp_proxy_clean", events[~bools].copy()))
            summaries.append(summarize_events(f"{pattern.pattern_key}:corp_proxy_flagged", events[bools].copy()))
        if "halted_delisted_proxy_flag" in events.columns:
            bools = events["halted_delisted_proxy_flag"].map(lambda value: str(value).strip().lower() in {"true", "1", "yes"})
            summaries.append(summarize_events(f"{pattern.pattern_key}:halt_proxy_clean", events[~bools].copy()))
            summaries.append(summarize_events(f"{pattern.pattern_key}:halt_proxy_flagged", events[bools].copy()))
    bull_gate_path = DEFAULT_BULL_FLAGS_DIR / "data_gate_audit.json"
    bull_gate_report: Dict[str, Any] = {}
    if bull_gate_path.exists():
        bull_gate_report = json.loads(bull_gate_path.read_text(encoding="utf-8"))
    report = {
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "analysis_horizon_days": int(horizon_days),
        "summaries": summaries,
        "target_sensitivity": sensitivity_rows,
        "target_calibration_decisions": build_target_calibration_decisions(sensitivity_rows),
        "data_gate_audits": {"bull_flags": bull_gate_report} if bull_gate_report else {},
        "interpretive_notes": [
            "Wilson CI is used for binary rates.",
            "Median MFE/MAE intervals use symbol-cluster bootstrap to reduce single-symbol dominance.",
            f"Target sensitivity recalculates target hit over {int(horizon_days)} trading sessions using pattern-specific target families.",
            "Pattern-specific target families are used where research has a Bulkowski-adjusted benchmark: Flags use 0.46x/0.5x/0.75x/1.0x.",
            "Base-target selection is rule-based: preserve target-family order and pass minimum N, hit-rate Wilson lower bound, target-first-before-adverse, and failure containment.",
            "This packet is descriptive research support, not a trading-system validation.",
        ],
    }
    report["bull_flag_robustness_checks"] = build_bull_flag_robustness_checks(report)
    return report


def _fmt_ci(ci: Mapping[str, Any]) -> str:
    if ci.get("rate") is None:
        return "n/a"
    return f"{ci.get('rate')}% [{ci.get('low')}, {ci.get('high')}]"


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Research Support Packet",
        "",
        "Mục tiêu: hỗ trợ đánh giá kỹ thuật trước khi đưa câu hỏi học thuật sang GPT 5.5 Pro.",
        "",
        "## Summary With Uncertainty",
        "",
        "| Nhóm | N | MFE median | MAE median | Legacy target hit Wilson | Fail 5% Wilson | Legacy target-first Wilson |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report.get("summaries", []):
        lines.append(
            "| {label} | {n} | {mfe} | {mae} | {hit} | {fail} | {race} |".format(
                label=row.get("label"),
                n=row.get("n"),
                mfe=row.get("median_mfe_pct"),
                mae=row.get("median_mae_pct"),
                hit=_fmt_ci(row.get("target_hit_ci") or {}),
                fail=_fmt_ci(row.get("failure_5pct_ci") or {}),
                race=_fmt_ci(row.get("target_first_before_adverse_5pct_ci") or {}),
            )
        )
    lines.extend(
        [
            "",
            "Ghi chú: các cột target trong bảng Summary dùng `target_hit` có sẵn trong event table, tức legacy/full target cho Bull Flag. Base target đã hiệu chuẩn 0.46x được báo riêng trong Target Sensitivity và adaptive-grid metric contract.",
            "",
            "## Base Target Decision",
            "",
            "| Pattern | Selected multiple | Vai trò | Trạng thái | Hit CI low | Target-first | Fail 5% | Score |",
            "|---|---:|---|---|---:|---:|---:|---:|",
        ]
    )
    for row in report.get("target_calibration_decisions", []):
        metrics = row.get("selected_metrics") or {}
        lines.append(
            "| {label} | {multiple} | {role} | {status} | {hit_low} | {race} | {fail} | {score} |".format(
                label=row.get("label"),
                multiple=row.get("selected_target_multiple"),
                role=row.get("selected_target_role"),
                status=row.get("status"),
                hit_low=metrics.get("target_hit_ci_low"),
                race=metrics.get("target_first_before_adverse_5pct_rate"),
                fail=metrics.get("failure_5pct_rate"),
                score=metrics.get("calibration_score"),
            )
        )
    lines.extend(
        [
            "",
            "## Bull Flag Robustness Check",
            "",
            "| Check | Status | Diễn giải |",
            "|---|---|---|",
        ]
    )
    for row in report.get("bull_flag_robustness_checks", []):
        lines.append(
            "| {check_id} | {status} | {interpretation} |".format(
                check_id=row.get("check_id"),
                status=row.get("status"),
                interpretation=str(row.get("interpretation") or "").replace("|", "\\|"),
            )
        )
    lines.extend(
        [
            "",
            "## Target Sensitivity",
            "",
        f"Horizon: `{report.get('analysis_horizon_days', DEFAULT_ANALYSIS_HORIZON_DAYS)}` phiên sau phá vỡ, để khớp với MFE/MAE trong event table.",
        "",
        "| Nhóm | Multiple | Vai trò target | Target hiệu dụng median | Target hit | Target-first trước -5% | Fail 5% | MFE/MAE | N |",
            "|---|---:|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in report.get("target_sensitivity", []):
        lines.append(
            "| {label} | {m} | {role} | {target} | {hit}% [{lo}, {hi}] | {race}% | {fail}% | {ratio} | {n} |".format(
                label=row.get("label"),
                m=row.get("target_multiple"),
                role=row.get("target_role"),
                target=row.get("median_effective_target_pct"),
                hit=row.get("target_hit_rate"),
                lo=row.get("target_hit_ci_low"),
                hi=row.get("target_hit_ci_high"),
                race=row.get("target_first_before_adverse_5pct_rate"),
                fail=row.get("failure_5pct_rate"),
                ratio=row.get("mfe_mae_median_ratio"),
                n=row.get("n"),
            )
        )
    lines.extend(
        [
            "",
            "## Data Gate Status",
            "",
        ]
    )
    gate = (report.get("data_gate_audits") or {}).get("bull_flags") if isinstance(report.get("data_gate_audits"), Mapping) else None
    if isinstance(gate, Mapping) and gate:
        lines.extend(
            [
                f"- Bull Flag available-series data gates pass: `{gate.get('investment_reference_data_gates_pass')}`",
                f"- Blocking gates: `{', '.join(gate.get('blocked_by') or []) or 'none'}`",
                "",
            ]
        )
    else:
        lines.extend(["- Bull Flag data-gate audit chưa có artifact.", ""])
    lines.extend(
        [
            "## Notes For GPT 5.5 Pro Research",
            "",
            "- Flags were run on Market Stats V1 stock series; Bull Flags are now filtered to the active/current Market Stats universe.",
            "- Bull Flags have Scanner V2 provenance, golden fixtures, and active-universe data gates; remaining work is calibration/regime/liquidity robustness, not legacy PTI membership.",
            "- The combined Flags experiment remains diagnostic-only for bear/downside comparison.",
            "- The current target calibration view is: full 1.0x remains a legacy benchmark, while Bulkowski-adjusted fractional targets are the candidate base targets.",
            "- Another key question is whether bearish/short-side continuation patterns should be treated as informational-only in Vietnam cash equities.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_pdf(path: Path, report: Mapping[str, Any]) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    path.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(path) as pdf:
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.patch.set_facecolor("#fffdf8")
        fig.text(0.5, 0.94, "Research Support Packet", ha="center", va="top", fontsize=18, weight="bold")
        fig.text(0.5, 0.91, "CI, bootstrap và target sensitivity", ha="center", va="top", fontsize=10)
        y = 0.86
        headers = ["Nhóm", "N", "MFE", "MAE", "Legacy hit", "Fail 5%"]
        xs = [0.08, 0.34, 0.43, 0.52, 0.62, 0.76]
        for x, header in zip(xs, headers):
            fig.text(x, y, header, fontsize=8.4, weight="bold", ha="left", va="top")
        y -= 0.025
        for row in list(report.get("summaries", []))[:18]:
            fig.text(xs[0], y, str(row.get("label")), fontsize=7.2, ha="left", va="top")
            fig.text(xs[1], y, str(row.get("n")), fontsize=7.2, ha="left", va="top")
            fig.text(xs[2], y, str(row.get("median_mfe_pct")), fontsize=7.2, ha="left", va="top")
            fig.text(xs[3], y, str(row.get("median_mae_pct")), fontsize=7.2, ha="left", va="top")
            fig.text(xs[4], y, _fmt_ci(row.get("target_hit_ci") or {}), fontsize=7.2, ha="left", va="top")
            fig.text(xs[5], y, _fmt_ci(row.get("failure_5pct_ci") or {}), fontsize=7.2, ha="left", va="top")
            y -= 0.026
        fig.text(
            0.08,
            0.11,
            "Summary dùng legacy/full target trong event table. Base target 0.46x được báo ở Target Sensitivity. Các khoảng Wilson/Bootstrap là lớp kiểm định kỹ thuật sơ bộ, chưa thay thế audit dữ liệu hoặc OOS validation.",
            fontsize=8,
            ha="left",
            va="top",
            wrap=True,
        )
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)


def write_report(report: Mapping[str, Any], out_dir: Path, *, render_pdf_artifact: bool = False) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": out_dir / "pattern_comparison_with_uncertainty.json",
        "target_sensitivity_csv": out_dir / "target_sensitivity.csv",
        "target_calibration_json": out_dir / "target_calibration_decisions.json",
        "target_calibration_csv": out_dir / "target_calibration_decisions.csv",
        "bull_flag_robustness_json": out_dir / "bull_flag_robustness_checks.json",
        "bull_flag_robustness_csv": out_dir / "bull_flag_robustness_checks.csv",
        "markdown": out_dir / "research_support_packet.md",
        "pdf": out_dir / "research_support_packet.pdf",
        "pdf_status": out_dir / "research_support_packet_pdf_status.txt",
    }
    paths["json"].write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    pd.DataFrame(report.get("target_sensitivity", [])).to_csv(paths["target_sensitivity_csv"], index=False)
    paths["target_calibration_json"].write_text(
        json.dumps(report.get("target_calibration_decisions", []), indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    calibration_rows = []
    for decision in report.get("target_calibration_decisions", []):
        metrics = decision.get("selected_metrics") or {}
        calibration_rows.append(
            {
                "label": decision.get("label"),
                "selected_target_multiple": decision.get("selected_target_multiple"),
                "selected_target_role": decision.get("selected_target_role"),
                "status": decision.get("status"),
                "reason": decision.get("reason"),
                **{f"selected_{key}": value for key, value in metrics.items()},
            }
        )
    pd.DataFrame(calibration_rows).to_csv(paths["target_calibration_csv"], index=False)
    robustness_rows = []
    for row in report.get("bull_flag_robustness_checks", []):
        robustness_rows.append(
            {
                "check_id": row.get("check_id"),
                "status": row.get("status"),
                "interpretation": row.get("interpretation"),
                "evidence": json.dumps(row.get("evidence") or {}, ensure_ascii=False, default=str),
            }
        )
    paths["bull_flag_robustness_json"].write_text(
        json.dumps(report.get("bull_flag_robustness_checks", []), indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    pd.DataFrame(robustness_rows).to_csv(paths["bull_flag_robustness_csv"], index=False)
    paths["markdown"].write_text(render_markdown(report), encoding="utf-8")
    if render_pdf_artifact:
        render_pdf(paths["pdf"], report)
        paths["pdf_status"].write_text("rendered\n", encoding="utf-8")
    else:
        paths["pdf_status"].write_text("skipped_by_default_to_avoid_font_cache_side_effects\n", encoding="utf-8")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--flags-dir", default=str(DEFAULT_FLAGS_DIR))
    parser.add_argument("--bull-flags-dir", default=str(DEFAULT_BULL_FLAGS_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--horizon-days", type=int, default=DEFAULT_ANALYSIS_HORIZON_DAYS)
    parser.add_argument("--render-pdf", action="store_true")
    args = parser.parse_args()

    patterns = [
        load_pattern_artifacts("bull_flags", Path(args.bull_flags_dir)),
        load_pattern_artifacts("flags_experiment", Path(args.flags_dir)),
    ]
    report = build_comparison(patterns, horizon_days=int(args.horizon_days))
    paths = write_report(report, Path(args.out_dir), render_pdf_artifact=bool(args.render_pdf))
    print(paths["markdown"])


if __name__ == "__main__":
    main()
