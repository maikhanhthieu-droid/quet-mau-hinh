"""Localize Bull Flag scanner rules for Vietnam available-series data.

The localization pass uses the current Bull Flag event table as a baseline
candidate set, then searches conservative acceptance profiles over geometry,
liquidity, and path-quality fields. This is intentionally a scanner-rule
calibration artifact, not a trading-system optimizer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from ..research_support_analysis import PatternArtifacts, target_sensitivity, wilson_ci
from .bull_flags_monograph import DEFAULT_MARKET_STATS_JSON, PATTERN_KEY
from .bull_flags_monograph import DEFAULT_OUT_DIR as DEFAULT_BULL_FLAGS_DIR
from .bull_flags_monograph import (
    _apply_event_filter,
    _enrich_events,
    _event_passes_filter,
    _filter_bull_flags,
    _load_active_symbols,
    _restrict_scan_to_active_universe,
)
from .flags_experiment import DEFAULT_INDEX_DB, DEFAULT_INDEX_SYMBOL, _path_rows, scan_market_stats
from .flags_experiment import FlagDetectorConfig
from .source_data import load_market_stats_symbol as _load_market_stats_symbol
from .source_data import symbol_from_path as _symbol_from_path


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bull_flags_localization")
DEFAULT_DETECTOR_GRID_OUT_DIR = Path("artifacts/scanner_v2/bull_flags_detector_grid")
DEFAULT_ADAPTIVE_GRID_OUT_DIR = Path("artifacts/scanner_v2/bull_flags_adaptive_grid")
DEFAULT_BASE_TARGET_MULTIPLE = 0.46
LOCAL_STRETCH_TARGET_MULTIPLE = 0.75
LEGACY_TARGET_MULTIPLE = 1.0
BULL_FLAG_V2_STRICT_PROFILE_ID = "bull_flag_v2_strict"
BULL_FLAG_V2_BALANCED_PROFILE_ID = "bull_flag_v2_balanced"
BULL_FLAG_V2_RECALL_PROFILE_ID = "bull_flag_v2_recall"
BULL_FLAG_V2_STABILITY_PROFILE_ID = "bull_flag_v2_stability_recovery"
BULL_FLAG_V2_SPLIT_STABLE_PROFILE_ID = "bull_flag_v2_split_stable_recovery"
BULL_FLAG_V2_SETUP_QUALITY_PROFILE_ID = "bull_flag_v2_setup_quality_recovery"
BULL_FLAG_V2_BREAKOUT_QUALITY_PROFILE_ID = "bull_flag_v2_breakout_quality_recovery"
BULL_FLAG_V2_FOLLOWTHROUGH_DIAGNOSTIC_PROFILE_ID = "bull_flag_v2_followthrough_confirmed_diagnostic"
BULL_FLAG_V2_PROFILE_ID = BULL_FLAG_V2_BALANCED_PROFILE_ID
BULL_FLAG_V2_VARIANTS: Dict[str, Dict[str, Any]] = {
    BULL_FLAG_V2_STRICT_PROFILE_ID: {
        "variant_label": "strict",
        "min_setup_score": 70.0,
        "min_confirmation_score": 60.0,
    },
    BULL_FLAG_V2_BALANCED_PROFILE_ID: {
        "variant_label": "balanced",
        "min_setup_score": 68.0,
        "min_confirmation_score": 58.0,
    },
    BULL_FLAG_V2_RECALL_PROFILE_ID: {
        "variant_label": "recall",
        "min_setup_score": 65.0,
        "min_confirmation_score": 60.0,
    },
    BULL_FLAG_V2_STABILITY_PROFILE_ID: {
        "variant_label": "stability_recovery",
        "min_setup_score": 65.0,
        "min_confirmation_score": 60.0,
        "contextual_rules": [
            {
                "rule_id": "post_2024_setup_dominant_parallel_recovery",
                "allowed_adaptive_branch_ids": ["post_2024_balanced"],
                "min_breakout_year": 2025,
                "min_setup_score": 78.0,
                "min_confirmation_score": 20.0,
                "max_slope_gap_deg": 1.75,
                "max_flag_to_pole_pct": 42.0,
            }
        ],
    },
    BULL_FLAG_V2_SPLIT_STABLE_PROFILE_ID: {
        "variant_label": "split_stable_recovery",
        "min_setup_score": 65.0,
        "min_confirmation_score": 60.0,
        "contextual_rules": [
            {
                "rule_id": "post_2024_setup_dominant_parallel_recovery",
                "allowed_adaptive_branch_ids": ["post_2024_balanced"],
                "min_breakout_year": 2025,
                "min_setup_score": 78.0,
                "min_confirmation_score": 20.0,
                "max_slope_gap_deg": 1.75,
                "max_flag_to_pole_pct": 42.0,
            },
            {
                "rule_id": "setup_dominant_compact_recovery",
                "min_setup_score": 80.0,
                "min_confirmation_score": 20.0,
                "max_slope_gap_deg": 3.0,
                "max_flag_to_pole_pct": 35.0,
            },
            {
                "rule_id": "confirmation_volume_parallel_recovery",
                "min_setup_score": 60.0,
                "min_confirmation_score": 70.0,
                "require_volume_confirmed": True,
                "max_slope_gap_deg": 2.5,
                "max_flag_to_pole_pct": 40.0,
            },
        ],
    },
    BULL_FLAG_V2_BREAKOUT_QUALITY_PROFILE_ID: {
        "variant_label": "breakout_quality_recovery",
        "min_setup_score": 55.0,
        "min_confirmation_score": 65.0,
        "contextual_rules": [
            {
                "rule_id": "compact_breakout_quality",
                "min_setup_score": 60.0,
                "min_confirmation_score": 60.0,
                "min_breakout_close_location": 0.75,
                "min_breakout_body_to_range": 0.45,
                "max_flag_range_to_pole_ratio": 1.15,
            },
            {
                "rule_id": "post_2024_quality_recovery",
                "allowed_adaptive_branch_ids": ["post_2024_balanced"],
                "min_breakout_year": 2025,
                "min_setup_score": 60.0,
                "min_confirmation_score": 58.0,
                "min_breakout_close_location": 0.70,
                "max_slope_gap_deg": 2.5,
                "max_flag_to_pole_pct": 42.0,
            },
        ],
    },
    BULL_FLAG_V2_SETUP_QUALITY_PROFILE_ID: {
        "variant_label": "setup_quality_recovery",
        "min_setup_score": 70.0,
        "min_confirmation_score": 45.0,
        "contextual_rules": [
            {
                "rule_id": "compact_setup_low_confirmation_recovery",
                "min_setup_score": 78.0,
                "min_confirmation_score": 20.0,
                "max_slope_gap_deg": 2.5,
                "max_flag_to_pole_pct": 38.0,
                "max_flag_range_to_pole_ratio": 1.05,
            },
            {
                "rule_id": "volume_contracted_setup_recovery",
                "min_setup_score": 70.0,
                "min_confirmation_score": 45.0,
                "max_flag_to_pole_pct": 45.0,
                "max_flag_range_to_pole_ratio": 1.15,
                "max_flag_volume_to_pole_ratio": 1.00,
            },
            {
                "rule_id": "recent_setup_watch_recovery",
                "allowed_adaptive_branch_ids": ["post_2024_balanced"],
                "min_breakout_year": 2025,
                "min_setup_score": 72.0,
                "min_confirmation_score": 30.0,
                "max_slope_gap_deg": 2.5,
                "max_flag_to_pole_pct": 42.0,
            },
        ],
    },
}
BULL_FLAG_V2_SETUP_MIN = BULL_FLAG_V2_VARIANTS[BULL_FLAG_V2_PROFILE_ID]["min_setup_score"]
BULL_FLAG_V2_CONFIRMATION_MIN = BULL_FLAG_V2_VARIANTS[BULL_FLAG_V2_PROFILE_ID]["min_confirmation_score"]


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _boolify(series: pd.Series) -> pd.Series:
    return series.map(lambda value: value if isinstance(value, bool) else str(value).strip().lower() in {"true", "1", "yes"})


def load_baseline_events(artifact_dir: Path = DEFAULT_BULL_FLAGS_DIR) -> PatternArtifacts:
    events = _read_csv(artifact_dir / "events.csv")
    path = _read_csv(artifact_dir / "post_breakout_path.csv")
    if not events.empty and "event_id" not in events.columns and "detection_id" in events.columns:
        events["event_id"] = events["detection_id"]
    for col in (
        "mfe_pct",
        "mae_pct",
        "target_dist_pct",
        "pole_move_pct",
        "flag_to_pole_pct",
        "slope_gap_deg",
        "pattern_width_bars",
        "pattern_quality_score",
        "adtv20_value",
        "zero_volume_days_20",
        "post_breakout_zero_volume_days_60d",
        "post_breakout_unchanged_close_days_60d",
    ):
        if col in events.columns:
            events[col] = pd.to_numeric(events[col], errors="coerce")
    for col in ("target_hit", "failure_5pct", "target_first_before_adverse_5pct", "volume_confirmed", "is_primary_event_60d"):
        if col in events.columns:
            events[col] = _boolify(events[col])
    for col in ("bar_after_breakout", "signed_high_excursion_pct", "signed_low_excursion_pct"):
        if col in path.columns:
            path[col] = pd.to_numeric(path[col], errors="coerce")
    return PatternArtifacts("bull_flags", events, path)


def _target_row(events: pd.DataFrame, path: pd.DataFrame, *, label: str = "bull_flags") -> Dict[str, Any]:
    rows = target_sensitivity(PatternArtifacts(label, events.copy(), path), label)
    for row in rows:
        if float(row.get("target_multiple") or -1) == DEFAULT_BASE_TARGET_MULTIPLE:
            return dict(row)
    return {"n": int(len(events))}


def _target_row_for_multiple(events: pd.DataFrame, path: pd.DataFrame, *, multiple: float, label: str = "bull_flags") -> Dict[str, Any]:
    rows = target_sensitivity(PatternArtifacts(label, events.copy(), path), label)
    for row in rows:
        if abs(float(row.get("target_multiple") or -1) - float(multiple)) < 1e-9:
            return dict(row)
    return {"n": int(len(events)), "target_multiple": float(multiple)}


def _metric_contract(events: pd.DataFrame, path: pd.DataFrame, *, label: str = "bull_flags") -> Dict[str, Any]:
    """Expose explicit base/stretch/legacy metrics to avoid target-rule drift."""

    base = _target_row_for_multiple(events, path, multiple=DEFAULT_BASE_TARGET_MULTIPLE, label=label)
    stretch = _target_row_for_multiple(events, path, multiple=LOCAL_STRETCH_TARGET_MULTIPLE, label=label)
    legacy = _target_row_for_multiple(events, path, multiple=LEGACY_TARGET_MULTIPLE, label=label)
    return {
        "base_target_multiple": DEFAULT_BASE_TARGET_MULTIPLE,
        "stretch_target_multiple": LOCAL_STRETCH_TARGET_MULTIPLE,
        "legacy_target_multiple": LEGACY_TARGET_MULTIPLE,
        "target_hit_base_046x_rate": base.get("target_hit_rate"),
        "target_hit_base_046x_ci_low": base.get("target_hit_ci_low"),
        "target_hit_base_046x_ci_high": base.get("target_hit_ci_high"),
        "target_first_base_046x_rate": base.get("target_first_before_adverse_5pct_rate"),
        "effective_target_base_046x_median_pct": base.get("median_effective_target_pct"),
        "target_hit_stretch_075x_rate": stretch.get("target_hit_rate"),
        "target_first_stretch_075x_rate": stretch.get("target_first_before_adverse_5pct_rate"),
        "target_hit_legacy_1x_rate": legacy.get("target_hit_rate"),
        "target_hit_legacy_1x_ci_low": legacy.get("target_hit_ci_low"),
        "target_first_legacy_1x_rate": legacy.get("target_first_before_adverse_5pct_rate"),
        "failure_5pct_rate": base.get("failure_5pct_rate"),
        "mfe_mae_median_ratio": base.get("mfe_mae_median_ratio"),
        "target_family_monotonic": _monotonic_nonincreasing(
            [
                base.get("target_hit_rate"),
                stretch.get("target_hit_rate"),
                legacy.get("target_hit_rate"),
            ]
        ),
    }


def _monotonic_nonincreasing(values: Sequence[Any]) -> bool:
    numeric = [float(value) for value in values if value is not None and pd.notna(value)]
    if len(numeric) < 2:
        return True
    return all(left >= right for left, right in zip(numeric, numeric[1:]))


def _safe_number(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(out):
        return default
    return out


def _scale_score(value: Any, low: float, high: float) -> float:
    numeric = _safe_number(value, default=np.nan)
    if not np.isfinite(numeric):
        return 50.0
    if high == low:
        return 50.0
    return round(float(np.clip((numeric - low) / (high - low) * 100.0, 0.0, 100.0)), 2)


def _reverse_score(value: Any, good: float, bad: float) -> float:
    numeric = _safe_number(value, default=np.nan)
    if not np.isfinite(numeric):
        return 50.0
    if bad == good:
        return 50.0
    return round(float(np.clip((bad - numeric) / (bad - good) * 100.0, 0.0, 100.0)), 2)


def _band_score(value: Any, *, ideal_low: float, ideal_high: float, hard_low: float, hard_high: float) -> float:
    numeric = _safe_number(value, default=np.nan)
    if not np.isfinite(numeric):
        return 50.0
    if ideal_low <= numeric <= ideal_high:
        return 100.0
    if numeric < ideal_low:
        return _scale_score(numeric, hard_low, ideal_low)
    return _reverse_score(numeric, ideal_high, hard_high)


def _tier_from_score(score: float, *, premium: float = 75.0, watchlist: float = 65.0, descriptive: float = 55.0) -> str:
    if score >= premium:
        return "premium"
    if score >= watchlist:
        return "watchlist"
    if score >= descriptive:
        return "descriptive"
    return "weak"


def _event_ids(events: pd.DataFrame) -> pd.Series:
    if "event_id" in events.columns:
        return events["event_id"].astype(str)
    if "detection_id" in events.columns:
        return events["detection_id"].astype(str)
    return pd.Series([str(idx) for idx in events.index], index=events.index)


def _prebreakout_context_metrics(events: pd.DataFrame, *, source_dir: Optional[Path]) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(index=events.index)
    out = pd.DataFrame(index=events.index)
    out["flag_volume_to_pole_ratio"] = np.nan
    out["flag_range_to_pole_ratio"] = np.nan
    out["flag_end_to_breakout_pct"] = np.nan
    paths = _source_paths_by_symbol(source_dir)
    if not paths:
        return out
    cache: Dict[str, pd.DataFrame] = {}
    for idx, event in events.iterrows():
        symbol = str(event.get("symbol") or "").upper()
        source_path = paths.get(symbol)
        if source_path is None:
            continue
        if symbol not in cache:
            cache[symbol] = _load_market_stats_symbol(source_path).reset_index(drop=True)
        df = cache[symbol]
        if df.empty:
            continue
        try:
            pole_idx = int(event.get("pole_idx"))
            start_idx = int(event.get("formation_start_idx"))
            end_idx = int(event.get("formation_end_idx"))
        except (TypeError, ValueError):
            continue
        if pole_idx < 0 or start_idx < 0 or end_idx < 0 or pole_idx >= len(df) or end_idx >= len(df):
            continue
        pole_window = df.iloc[pole_idx : max(pole_idx + 1, start_idx + 1)].copy()
        flag_window = df.iloc[start_idx : end_idx + 1].copy()
        if pole_window.empty or flag_window.empty:
            continue
        pole_volume = pd.to_numeric(pole_window.get("volume"), errors="coerce")
        flag_volume = pd.to_numeric(flag_window.get("volume"), errors="coerce")
        if pole_volume.notna().any() and float(pole_volume.median()) > 0 and flag_volume.notna().any():
            out.at[idx, "flag_volume_to_pole_ratio"] = round(float(flag_volume.median()) / float(pole_volume.median()), 4)
        pole_range = (pd.to_numeric(pole_window.get("high"), errors="coerce") - pd.to_numeric(pole_window.get("low"), errors="coerce")) / pd.to_numeric(
            pole_window.get("close"), errors="coerce"
        ).replace(0, np.nan)
        flag_range = (pd.to_numeric(flag_window.get("high"), errors="coerce") - pd.to_numeric(flag_window.get("low"), errors="coerce")) / pd.to_numeric(
            flag_window.get("close"), errors="coerce"
        ).replace(0, np.nan)
        if pole_range.notna().any() and float(pole_range.median()) > 0 and flag_range.notna().any():
            out.at[idx, "flag_range_to_pole_ratio"] = round(float(flag_range.median()) / float(pole_range.median()), 4)
        flag_end_close = _safe_number(df.iloc[end_idx].get("close"), default=np.nan)
        breakout_price = _safe_number(event.get("breakout_price"), default=np.nan)
        direction = 1 if str(event.get("breakout_direction") or "up").lower() == "up" else -1
        if np.isfinite(flag_end_close) and flag_end_close > 0 and np.isfinite(breakout_price):
            out.at[idx, "flag_end_to_breakout_pct"] = round(float(direction * (breakout_price / flag_end_close - 1.0) * 100.0), 4)
    return out


def _followthrough_context_metrics(events: pd.DataFrame, path: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(index=events.index)
    out = pd.DataFrame(index=events.index)
    for col in (
        "mfe_5_pct",
        "mae_5_pct",
        "close_return_5_pct",
        "mfe_10_pct",
        "mae_10_pct",
        "close_return_10_pct",
        "mfe_20_pct",
        "mae_20_pct",
        "close_return_20_pct",
    ):
        out[col] = np.nan
    for col in (
        "target_first_5d",
        "early_adverse_3pct_5d",
        "target_first_10d",
        "early_adverse_3pct_10d",
        "target_first_20d",
        "early_adverse_3pct_20d",
        "retest_10d",
        "retest_recovered_20d",
    ):
        out[col] = pd.Series([pd.NA] * len(events), index=events.index, dtype="object")
    if path.empty or "event_id" not in path.columns:
        return out
    working_path = path.copy()
    for col in ("bar_after_breakout", "signed_high_excursion_pct", "signed_low_excursion_pct", "signed_close_return_pct"):
        if col in working_path.columns:
            working_path[col] = pd.to_numeric(working_path[col], errors="coerce")
    path_groups = {str(event_id): group.sort_values("bar_after_breakout") for event_id, group in working_path.groupby("event_id")}
    ids = _event_ids(events)
    for idx, event in events.iterrows():
        per_event = path_groups.get(str(ids.loc[idx]))
        if per_event is None or per_event.empty:
            continue
        target_pct = _safe_number(event.get("target_dist_pct"), default=0.0) * DEFAULT_BASE_TARGET_MULTIPLE
        for horizon in (5, 10, 20):
            frame = per_event[per_event["bar_after_breakout"] <= horizon]
            if frame.empty:
                continue
            high = pd.to_numeric(frame.get("signed_high_excursion_pct"), errors="coerce")
            low = pd.to_numeric(frame.get("signed_low_excursion_pct"), errors="coerce")
            close = pd.to_numeric(frame.get("signed_close_return_pct"), errors="coerce")
            mfe = float(high.max()) if high.notna().any() else 0.0
            mae = abs(float(low.min())) if low.notna().any() else 0.0
            out.at[idx, f"mfe_{horizon}_pct"] = round(mfe, 4)
            out.at[idx, f"mae_{horizon}_pct"] = round(mae, 4)
            if close.notna().any():
                out.at[idx, f"close_return_{horizon}_pct"] = round(float(close.iloc[-1]), 4)
            target_bar = _first_bar(frame, high >= target_pct)
            adverse_bar = _first_bar(frame, low <= -5.0)
            out.at[idx, f"target_first_{horizon}d"] = bool(False if target_bar is None else (True if adverse_bar is None else target_bar < adverse_bar))
            out.at[idx, f"early_adverse_3pct_{horizon}d"] = bool((low <= -3.0).any())
        first10 = per_event[per_event["bar_after_breakout"] <= 10]
        first20 = per_event[per_event["bar_after_breakout"] <= 20]
        if not first10.empty and "signed_low_excursion_pct" in first10:
            retest = bool((pd.to_numeric(first10["signed_low_excursion_pct"], errors="coerce") <= 0.0).any())
            out.at[idx, "retest_10d"] = retest
            if retest and not first20.empty:
                out.at[idx, "retest_recovered_20d"] = bool((pd.to_numeric(first20["signed_high_excursion_pct"], errors="coerce") >= target_pct).any())
    return out


def _score_setup_row(row: Mapping[str, Any]) -> float:
    pole_move = _scale_score(row.get("pole_move_pct"), 8.0, 18.0)
    pole_slope = _scale_score(row.get("pole_slope_deg"), 5.0, 16.0)
    compactness = _reverse_score(row.get("flag_to_pole_pct"), 30.0, 70.0)
    parallel = _reverse_score(row.get("slope_gap_deg"), 0.0, 6.0)
    height = _band_score(row.get("pattern_height_pct"), ideal_low=3.5, ideal_high=9.0, hard_low=1.5, hard_high=15.0)
    volume_contraction = _reverse_score(row.get("flag_volume_to_pole_ratio"), 0.45, 1.25)
    range_contraction = _reverse_score(row.get("flag_range_to_pole_ratio"), 0.45, 1.35)
    flag_end_near = _reverse_score(row.get("flag_end_to_breakout_pct"), 0.0, 8.0)
    score = (
        0.22 * pole_move
        + 0.12 * pole_slope
        + 0.18 * compactness
        + 0.12 * parallel
        + 0.10 * height
        + 0.10 * volume_contraction
        + 0.08 * range_contraction
        + 0.08 * flag_end_near
    )
    return round(float(score), 2)


def _score_confirmation_row(row: Mapping[str, Any]) -> float:
    breakout_impulse = _scale_score(row.get("breakout_return_from_flag_end_pct"), 0.5, 5.0)
    volume = _scale_score(row.get("breakout_volume_ratio_20"), 0.8, 2.0)
    close_location = _scale_score(row.get("breakout_close_location"), 0.45, 0.90)
    body = _scale_score(row.get("breakout_body_to_range"), 0.20, 0.80)
    no_false_start = 100.0 if not bool(row.get("early_adverse_3pct_5d") is True) else 30.0
    volume_confirmed = 100.0 if bool(row.get("volume_confirmed") is True) else 55.0
    score = 0.25 * breakout_impulse + 0.18 * volume + 0.18 * close_location + 0.14 * body + 0.15 * no_false_start + 0.10 * volume_confirmed
    return round(float(score), 2)


def _score_followthrough_row(row: Mapping[str, Any]) -> float:
    mfe10 = _scale_score(row.get("mfe_10_pct"), 3.0, 12.0)
    mfe20 = _scale_score(row.get("mfe_20_pct"), 5.0, 18.0)
    mae10_containment = _reverse_score(row.get("mae_10_pct"), 2.0, 12.0)
    close10 = _scale_score(row.get("close_return_10_pct"), -2.0, 8.0)
    close20 = _scale_score(row.get("close_return_20_pct"), -2.0, 12.0)
    race10 = 100.0 if bool(row.get("target_first_10d") is True) else 35.0
    race20 = 100.0 if bool(row.get("target_first_20d") is True) else 40.0
    retest_recovery = 70.0
    if bool(row.get("retest_10d") is True):
        retest_recovery = 100.0 if bool(row.get("retest_recovered_20d") is True) else 35.0
    score = 0.15 * mfe10 + 0.18 * mfe20 + 0.15 * mae10_containment + 0.12 * close10 + 0.12 * close20 + 0.13 * race10 + 0.10 * race20 + 0.05 * retest_recovery
    return round(float(score), 2)


def _breakout_confirmation_context(events: pd.DataFrame, *, source_dir: Optional[Path]) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(index=events.index)
    out = pd.DataFrame(index=events.index)
    for col in ("breakout_return_from_flag_end_pct", "breakout_volume_ratio_20", "breakout_close_location", "breakout_body_to_range"):
        out[col] = np.nan
    paths = _source_paths_by_symbol(source_dir)
    if not paths:
        return out
    cache: Dict[str, pd.DataFrame] = {}
    for idx, event in events.iterrows():
        symbol = str(event.get("symbol") or "").upper()
        source_path = paths.get(symbol)
        if source_path is None:
            continue
        if symbol not in cache:
            cache[symbol] = _load_market_stats_symbol(source_path).reset_index(drop=True)
        df = cache[symbol]
        try:
            breakout_idx = int(event.get("breakout_idx"))
            end_idx = int(event.get("formation_end_idx"))
        except (TypeError, ValueError):
            continue
        if breakout_idx < 0 or breakout_idx >= len(df) or end_idx < 0 or end_idx >= len(df):
            continue
        direction = 1 if str(event.get("breakout_direction") or "up").lower() == "up" else -1
        breakout = df.iloc[breakout_idx]
        flag_end_close = _safe_number(df.iloc[end_idx].get("close"), default=np.nan)
        breakout_close = _safe_number(breakout.get("close"), default=np.nan)
        if np.isfinite(flag_end_close) and flag_end_close > 0 and np.isfinite(breakout_close):
            out.at[idx, "breakout_return_from_flag_end_pct"] = round(float(direction * (breakout_close / flag_end_close - 1.0) * 100.0), 4)
        prior = df.iloc[max(0, breakout_idx - 20) : breakout_idx]
        prior_volume = pd.to_numeric(prior.get("volume"), errors="coerce")
        breakout_volume = _safe_number(breakout.get("volume"), default=np.nan)
        if prior_volume.notna().any() and float(prior_volume.median()) > 0 and np.isfinite(breakout_volume):
            out.at[idx, "breakout_volume_ratio_20"] = round(float(breakout_volume) / float(prior_volume.median()), 4)
        high = _safe_number(breakout.get("high"), default=np.nan)
        low = _safe_number(breakout.get("low"), default=np.nan)
        open_px = _safe_number(breakout.get("open"), default=np.nan)
        if np.isfinite(high) and np.isfinite(low) and high > low and np.isfinite(breakout_close) and np.isfinite(open_px):
            location = (breakout_close - low) / (high - low) if direction == 1 else (high - breakout_close) / (high - low)
            out.at[idx, "breakout_close_location"] = round(float(location), 4)
            out.at[idx, "breakout_body_to_range"] = round(float(abs(breakout_close - open_px) / (high - low)), 4)
    return out


def _assign_bull_flag_branch(row: Mapping[str, Any]) -> str:
    setup = _safe_number(row.get("setup_score"))
    confirmation = _safe_number(row.get("confirmation_score"))
    follow = _safe_number(row.get("followthrough_score"))
    if setup >= 70.0 and confirmation < 60.0:
        return "early_setup_watch"
    if follow >= 70.0:
        return "post_breakout_continuation"
    if setup >= 65.0 and confirmation >= 60.0:
        return "confirmed_breakout"
    return "low_quality_confirmed"


def _apply_three_layer_scores(events: pd.DataFrame, path: pd.DataFrame, *, source_dir: Optional[Path] = None) -> pd.DataFrame:
    if events.empty:
        return events.copy()
    scored = events.copy()
    if "event_id" not in scored.columns and "detection_id" in scored.columns:
        scored["event_id"] = scored["detection_id"]
    pre = _prebreakout_context_metrics(scored, source_dir=source_dir)
    confirm = _breakout_confirmation_context(scored, source_dir=source_dir)
    follow = _followthrough_context_metrics(scored, path)
    for frame in (pre, confirm, follow):
        for col in frame.columns:
            scored[col] = frame[col]
    scored["setup_score"] = scored.apply(lambda row: _score_setup_row(row.to_dict()), axis=1)
    scored["confirmation_score"] = scored.apply(lambda row: _score_confirmation_row(row.to_dict()), axis=1)
    scored["followthrough_score"] = scored.apply(lambda row: _score_followthrough_row(row.to_dict()), axis=1)
    scored["bull_flag_score_total"] = (
        0.40 * pd.to_numeric(scored["setup_score"], errors="coerce")
        + 0.30 * pd.to_numeric(scored["confirmation_score"], errors="coerce")
        + 0.30 * pd.to_numeric(scored["followthrough_score"], errors="coerce")
    ).round(2)
    scored["setup_tier"] = scored["setup_score"].map(lambda value: _tier_from_score(float(value)))
    scored["confirmation_tier"] = scored["confirmation_score"].map(lambda value: _tier_from_score(float(value), premium=72.0, watchlist=62.0, descriptive=52.0))
    scored["followthrough_tier"] = scored["followthrough_score"].map(lambda value: _tier_from_score(float(value), premium=72.0, watchlist=62.0, descriptive=52.0))
    scored["bull_flag_tier"] = scored["bull_flag_score_total"].map(lambda value: _tier_from_score(float(value), premium=72.0, watchlist=62.0, descriptive=52.0))
    scored["bull_flag_scanner_branch"] = scored.apply(lambda row: _assign_bull_flag_branch(row.to_dict()), axis=1)
    return scored


def _post_score_rule_mask(events: pd.DataFrame, config: Mapping[str, Any]) -> pd.Series:
    mask = pd.Series(True, index=events.index)
    if not config or events.empty:
        return mask
    if config.get("min_breakout_year") is not None:
        mask &= pd.to_numeric(events.get("breakout_year"), errors="coerce").fillna(0).astype(int) >= int(config["min_breakout_year"])
    if config.get("max_breakout_year") is not None:
        mask &= pd.to_numeric(events.get("breakout_year"), errors="coerce").fillna(9999).astype(int) <= int(config["max_breakout_year"])
    if config.get("allowed_liquidity_buckets"):
        allowed = {str(value) for value in config.get("allowed_liquidity_buckets") or []}
        mask &= events.get("liquidity_bucket", pd.Series("", index=events.index)).astype(str).isin(allowed)
    if config.get("allowed_regimes"):
        allowed = {str(value) for value in config.get("allowed_regimes") or []}
        mask &= events.get("market_regime", pd.Series("", index=events.index)).astype(str).isin(allowed)
    if config.get("allowed_adaptive_branch_ids"):
        allowed = {str(value) for value in config.get("allowed_adaptive_branch_ids") or []}
        mask &= events.get("adaptive_branch_id", pd.Series("", index=events.index)).astype(str).isin(allowed)
    if config.get("min_setup_score") is not None:
        mask &= pd.to_numeric(events.get("setup_score"), errors="coerce").fillna(0.0) >= float(config["min_setup_score"])
    if config.get("min_confirmation_score") is not None:
        mask &= pd.to_numeric(events.get("confirmation_score"), errors="coerce").fillna(0.0) >= float(config["min_confirmation_score"])
    if config.get("min_followthrough_score") is not None:
        mask &= pd.to_numeric(events.get("followthrough_score"), errors="coerce").fillna(0.0) >= float(config["min_followthrough_score"])
    if config.get("max_slope_gap_deg") is not None:
        mask &= pd.to_numeric(events.get("slope_gap_deg"), errors="coerce").fillna(999.0) <= float(config["max_slope_gap_deg"])
    if config.get("max_flag_to_pole_pct") is not None:
        mask &= pd.to_numeric(events.get("flag_to_pole_pct"), errors="coerce").fillna(999.0) <= float(config["max_flag_to_pole_pct"])
    if config.get("min_breakout_close_location") is not None:
        mask &= pd.to_numeric(events.get("breakout_close_location"), errors="coerce").fillna(-999.0) >= float(config["min_breakout_close_location"])
    if config.get("min_breakout_body_to_range") is not None:
        mask &= pd.to_numeric(events.get("breakout_body_to_range"), errors="coerce").fillna(-999.0) >= float(config["min_breakout_body_to_range"])
    if config.get("max_flag_range_to_pole_ratio") is not None:
        mask &= pd.to_numeric(events.get("flag_range_to_pole_ratio"), errors="coerce").fillna(999.0) <= float(config["max_flag_range_to_pole_ratio"])
    if config.get("max_flag_volume_to_pole_ratio") is not None:
        mask &= pd.to_numeric(events.get("flag_volume_to_pole_ratio"), errors="coerce").fillna(999.0) <= float(config["max_flag_volume_to_pole_ratio"])
    if config.get("require_volume_confirmed") is True:
        mask &= events.get("volume_confirmed", pd.Series(False, index=events.index)).map(
            lambda value: value if isinstance(value, bool) else str(value).strip().lower() in {"true", "1", "yes"}
        )
    if config.get("allowed_bull_flag_tiers"):
        allowed = {str(value) for value in config.get("allowed_bull_flag_tiers") or []}
        mask &= events.get("bull_flag_tier", pd.Series("", index=events.index)).astype(str).isin(allowed)
    if config.get("allowed_scanner_branches"):
        allowed = {str(value) for value in config.get("allowed_scanner_branches") or []}
        mask &= events.get("bull_flag_scanner_branch", pd.Series("", index=events.index)).astype(str).isin(allowed)
    return mask


def _apply_post_score_filter(events: pd.DataFrame, profile: Mapping[str, Any]) -> tuple[pd.DataFrame, Dict[str, Any]]:
    config = profile.get("post_score_filter_config") if isinstance(profile.get("post_score_filter_config"), Mapping) else None
    if not config or events.empty:
        return events.copy(), {
            "enabled": bool(config),
            "input_count": int(len(events)),
            "kept_count": int(len(events)),
            "removed_count": 0,
            "kept_share_pct": 100.0 if len(events) else None,
        }
    mask = _post_score_rule_mask(events, config)
    contextual_rules = [rule for rule in config.get("contextual_rules") or [] if isinstance(rule, Mapping)]
    for rule in contextual_rules:
        mask |= _post_score_rule_mask(events, rule)
    kept = events[mask].copy()
    removed = int(len(events) - len(kept))
    kept["post_score_filter_id"] = config.get("profile_id")
    kept["post_score_min_setup_score"] = config.get("min_setup_score")
    kept["post_score_min_confirmation_score"] = config.get("min_confirmation_score")
    kept["post_score_use_followthrough_for_entry"] = bool(config.get("use_followthrough_for_entry"))
    return kept, {
        "enabled": True,
        "config": dict(config),
        "contextual_rule_count": len(contextual_rules),
        "input_count": int(len(events)),
        "kept_count": int(len(kept)),
        "removed_count": removed,
        "kept_share_pct": round(len(kept) / max(1, len(events)) * 100.0, 2),
    }


def _filter_path_to_events(path: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    if path.empty or events.empty or "event_id" not in path.columns:
        return path.copy()
    ids = set(_event_ids(events).astype(str))
    return path[path["event_id"].astype(str).isin(ids)].copy()


def _score_from_row(
    row: Mapping[str, Any],
    *,
    sample_n: int,
    baseline_n: int,
    holdout_row: Optional[Mapping[str, Any]] = None,
    stretch_row: Optional[Mapping[str, Any]] = None,
) -> float:
    target_first = float(row.get("target_first_before_adverse_5pct_rate") or 0.0)
    hit_low = float(row.get("target_hit_ci_low") or 0.0)
    failure_component = max(0.0, 100.0 - float(row.get("failure_5pct_rate") or 100.0))
    ratio_component = min(float(row.get("mfe_mae_median_ratio") or 0.0), 2.5) / 2.5 * 100.0
    sample_component = min(sample_n / max(1, baseline_n), 1.0) * 100.0
    if holdout_row:
        holdout_hit = float(holdout_row.get("target_hit_rate") or 0.0)
        validation_hit = float(row.get("target_hit_rate") or 0.0)
        holdout_stability = max(0.0, 100.0 - abs(validation_hit - holdout_hit) * 2.0)
    else:
        holdout_stability = 0.0
    score = (
        0.30 * target_first
        + 0.20 * hit_low
        + 0.20 * failure_component
        + 0.15 * ratio_component
        + 0.10 * holdout_stability
        + 0.05 * sample_component
    )
    if stretch_row:
        stretch_target_first = float(stretch_row.get("target_first_before_adverse_5pct_rate") or 0.0)
        stretch_hit = float(stretch_row.get("target_hit_rate") or 0.0)
        if stretch_target_first < 20.0:
            score -= 5.0
        if stretch_hit < 35.0:
            score -= 3.0
    return round(float(score), 2)


def candidate_profiles() -> List[Dict[str, Any]]:
    profiles: List[Dict[str, Any]] = [
        {
            "profile_id": "baseline_all",
            "profile_role": "baseline_reference",
            "description": "No post-detection localization filter.",
        }
    ]
    path_modes = {
        "clean_only": ["clean"],
        "clean_or_stale": ["clean", "stale_close"],
        "exclude_zero_and_short": ["clean", "stale_close"],
    }
    profile_index = 0
    for path_mode, path_buckets in path_modes.items():
        for pole_min in (10.0, 12.0, 14.0):
            for flag_to_pole_max in (55.0, 45.0, 35.0):
                for slope_gap_max in (4.0, 3.0, 2.0):
                    for min_quality in (None, 75.0, 85.0):
                        for require_volume in (False, True):
                            profile_index += 1
                            profile: Dict[str, Any] = {
                                "profile_id": f"vn_local_{profile_index:04d}",
                                "profile_role": "localized_candidate",
                                "path_mode": path_mode,
                                "allowed_path_quality_buckets": path_buckets,
                                "min_pole_move_pct": pole_min,
                                "max_flag_to_pole_pct": flag_to_pole_max,
                                "max_slope_gap_deg": slope_gap_max,
                                "max_post_zero_volume_days_60d": 4,
                                "require_primary_event_60d": True,
                                "require_volume_confirmed": require_volume,
                            }
                            if min_quality is not None:
                                profile["min_pattern_quality_score"] = min_quality
                            profiles.append(profile)
    return profiles


def detector_config_profiles() -> List[Dict[str, Any]]:
    """Small full-rescan grid for Vietnam Bull Flag detector localization."""

    return [
        {
            "profile_id": "detector_baseline",
            "profile_role": "baseline_detector",
            "detector_config": FlagDetectorConfig().to_dict(),
            "event_filter_config": {},
        },
        {
            "profile_id": "vn_detector_loose_breakout",
            "profile_role": "detector_grid_candidate",
            "detector_config": FlagDetectorConfig(
                pole_min_change_pct=8.0,
                pole_min_slope_deg=6.0,
                parallel_tol_deg=5.0,
                flag_to_pole_max_pct=65.0,
                breakout_threshold=0.005,
                width_max_bars=30,
            ).to_dict(),
            "event_filter_config": {
                "profile_id": "vn_accept_clean_or_stale",
                "allowed_path_quality_buckets": ["clean", "stale_close"],
                "max_post_zero_volume_days_60d": 4,
                "require_primary_event_60d": True,
            },
        },
        {
            "profile_id": "vn_detector_medium_loose",
            "profile_role": "detector_grid_candidate",
            "detector_config": FlagDetectorConfig(
                pole_min_change_pct=10.0,
                pole_min_slope_deg=7.0,
                parallel_tol_deg=5.0,
                flag_to_pole_max_pct=65.0,
                breakout_threshold=0.005,
                width_max_bars=30,
            ).to_dict(),
            "event_filter_config": {
                "profile_id": "vn_accept_clean_or_stale",
                "allowed_path_quality_buckets": ["clean", "stale_close"],
                "max_post_zero_volume_days_60d": 4,
                "require_primary_event_60d": True,
            },
        },
        {
            "profile_id": "vn_detector_balanced_55",
            "profile_role": "detector_grid_candidate",
            "detector_config": FlagDetectorConfig(
                pole_min_change_pct=10.0,
                pole_min_slope_deg=8.0,
                parallel_tol_deg=4.0,
                flag_to_pole_max_pct=55.0,
                breakout_threshold=0.005,
            ).to_dict(),
            "event_filter_config": {
                "profile_id": "vn_accept_clean_or_stale",
                "allowed_path_quality_buckets": ["clean", "stale_close"],
                "max_post_zero_volume_days_60d": 4,
                "require_primary_event_60d": True,
            },
        },
        {
            "profile_id": "vn_detector_balanced_45",
            "profile_role": "detector_grid_candidate",
            "detector_config": FlagDetectorConfig(
                pole_min_change_pct=10.0,
                pole_min_slope_deg=8.0,
                parallel_tol_deg=4.0,
                flag_to_pole_max_pct=45.0,
                breakout_threshold=0.005,
            ).to_dict(),
            "event_filter_config": {
                "profile_id": "vn_accept_clean_or_stale",
                "allowed_path_quality_buckets": ["clean", "stale_close"],
                "max_post_zero_volume_days_60d": 4,
                "require_primary_event_60d": True,
            },
        },
        {
            "profile_id": "vn_detector_steep_45",
            "profile_role": "detector_grid_candidate",
            "detector_config": FlagDetectorConfig(
                pole_min_change_pct=12.0,
                pole_min_slope_deg=8.0,
                parallel_tol_deg=3.0,
                flag_to_pole_max_pct=45.0,
                breakout_threshold=0.0075,
            ).to_dict(),
            "event_filter_config": {
                "profile_id": "vn_accept_clean_or_stale",
                "allowed_path_quality_buckets": ["clean", "stale_close"],
                "max_post_zero_volume_days_60d": 4,
                "require_primary_event_60d": True,
            },
        },
        {
            "profile_id": "vn_detector_tight_35",
            "profile_role": "detector_grid_candidate",
            "detector_config": FlagDetectorConfig(
                pole_min_change_pct=12.0,
                pole_min_slope_deg=8.0,
                parallel_tol_deg=2.0,
                flag_to_pole_max_pct=35.0,
                breakout_threshold=0.0075,
            ).to_dict(),
            "event_filter_config": {
                "profile_id": "vn_accept_clean_or_stale",
                "allowed_path_quality_buckets": ["clean", "stale_close"],
                "max_post_zero_volume_days_60d": 4,
                "require_primary_event_60d": True,
            },
        },
        {
            "profile_id": "vn_detector_volume_confirmed",
            "profile_role": "detector_grid_candidate",
            "detector_config": FlagDetectorConfig(
                pole_min_change_pct=10.0,
                pole_min_slope_deg=8.0,
                parallel_tol_deg=4.0,
                flag_to_pole_max_pct=55.0,
                breakout_threshold=0.005,
                require_volume_confirmed=True,
            ).to_dict(),
            "event_filter_config": {
                "profile_id": "vn_accept_clean_or_stale",
                "allowed_path_quality_buckets": ["clean", "stale_close"],
                "max_post_zero_volume_days_60d": 4,
                "require_primary_event_60d": True,
            },
        },
        {
            "profile_id": "vn_detector_clean_path_only",
            "profile_role": "detector_grid_candidate",
            "detector_config": FlagDetectorConfig(
                pole_min_change_pct=10.0,
                pole_min_slope_deg=8.0,
                parallel_tol_deg=4.0,
                flag_to_pole_max_pct=55.0,
                breakout_threshold=0.005,
            ).to_dict(),
            "event_filter_config": {
                "profile_id": "vn_accept_clean_only",
                "allowed_path_quality_buckets": ["clean"],
                "max_post_zero_volume_days_60d": 4,
                "require_primary_event_60d": True,
            },
        },
    ]


def _base_accept_filter() -> Dict[str, Any]:
    return {
        "profile_id": "vn_accept_clean_or_stale",
        "allowed_path_quality_buckets": ["clean", "stale_close"],
        "max_post_zero_volume_days_60d": 4,
        "require_primary_event_60d": True,
    }


def _tight_accept_filter() -> Dict[str, Any]:
    return {
        "profile_id": "vn_accept_premium_path",
        "allowed_path_quality_buckets": ["clean", "stale_close"],
        "max_post_zero_volume_days_60d": 2,
        "max_post_unchanged_close_days_60d": 8,
        "require_primary_event_60d": True,
    }


def adaptive_detector_profiles() -> List[Dict[str, Any]]:
    """Context-branch detector profiles for Vietnam Bull Flags.

    Each branch runs a different detector configuration, then accepts only the
    events belonging to that branch context. Branches are merged with a
    symbol-level overlap policy so the output is still one event table.
    """

    baseline = FlagDetectorConfig()
    loose = FlagDetectorConfig(
        pole_min_change_pct=8.0,
        pole_min_slope_deg=6.0,
        parallel_tol_deg=5.0,
        flag_to_pole_max_pct=65.0,
        breakout_threshold=0.005,
        width_max_bars=30,
    )
    balanced = FlagDetectorConfig(
        pole_min_change_pct=10.0,
        pole_min_slope_deg=8.0,
        parallel_tol_deg=4.0,
        flag_to_pole_max_pct=55.0,
        breakout_threshold=0.005,
    )
    compact = FlagDetectorConfig(
        pole_min_change_pct=10.0,
        pole_min_slope_deg=8.0,
        parallel_tol_deg=4.0,
        flag_to_pole_max_pct=45.0,
        breakout_threshold=0.005,
    )
    tight = FlagDetectorConfig(
        pole_min_change_pct=12.0,
        pole_min_slope_deg=8.0,
        parallel_tol_deg=2.0,
        flag_to_pole_max_pct=35.0,
        breakout_threshold=0.0075,
    )
    volume_confirmed = FlagDetectorConfig(
        pole_min_change_pct=10.0,
        pole_min_slope_deg=8.0,
        parallel_tol_deg=4.0,
        flag_to_pole_max_pct=55.0,
        breakout_threshold=0.005,
        require_volume_confirmed=True,
    )

    def guard_branches(*, volume_guard: bool = False) -> List[Dict[str, Any]]:
        high_mid_config = volume_confirmed if volume_guard else tight
        high_mid_filter = _tight_accept_filter() | {
            "min_breakout_year": 2024,
            "max_breakout_year": 2024,
            "allowed_liquidity_buckets": ["high", "mid"],
            "max_flag_to_pole_pct": 55.0 if volume_guard else 35.0,
        }
        if volume_guard:
            high_mid_filter["require_volume_confirmed"] = True
        return [
            {
                "branch_id": "pre_2024_balanced",
                "branch_priority": 20,
                "detector_config": balanced.to_dict(),
                "event_filter_config": _base_accept_filter()
                | {
                    "max_breakout_year": 2023,
                },
            },
            {
                "branch_id": "problem_2024_high_mid_volume_confirmed" if volume_guard else "problem_2024_high_mid_tight",
                "branch_priority": 70 if volume_guard else 60,
                "detector_config": high_mid_config.to_dict(),
                "event_filter_config": high_mid_filter,
            },
            {
                "branch_id": "problem_2024_low_compact",
                "branch_priority": 50,
                "detector_config": compact.to_dict(),
                "event_filter_config": _tight_accept_filter()
                | {
                    "min_breakout_year": 2024,
                    "max_breakout_year": 2024,
                    "allowed_liquidity_buckets": ["low", "unknown"],
                    "max_flag_to_pole_pct": 45.0,
                },
            },
            {
                "branch_id": "post_2024_balanced",
                "branch_priority": 30,
                "detector_config": balanced.to_dict(),
                "event_filter_config": _base_accept_filter()
                | {
                    "min_breakout_year": 2025,
                },
            },
        ]

    def bull_flag_v2_profiles() -> List[Dict[str, Any]]:
        profiles: List[Dict[str, Any]] = []
        for profile_id, variant in BULL_FLAG_V2_VARIANTS.items():
            profiles.append(
                {
                    "profile_id": profile_id,
                    "profile_role": "canonical_bull_flag_v2",
                    "bull_flag_v2_variant": variant["variant_label"],
                    "overlap_cooldown_days": 30,
                    "post_score_filter_config": {
                        "profile_id": profile_id,
                        "entry_layer": "setup_confirmation",
                        "diagnostic_layer": "followthrough",
                        "min_setup_score": variant["min_setup_score"],
                        "min_confirmation_score": variant["min_confirmation_score"],
                        "use_followthrough_for_entry": False,
                        "contextual_rules": variant.get("contextual_rules") or [],
                    },
                    "branches": guard_branches(),
                }
            )
        profiles.append(
            {
                "profile_id": BULL_FLAG_V2_FOLLOWTHROUGH_DIAGNOSTIC_PROFILE_ID,
                "profile_role": "diagnostic_bull_flag_v2",
                "bull_flag_v2_variant": "followthrough_confirmed_diagnostic",
                "overlap_cooldown_days": 30,
                "post_score_filter_config": {
                    "profile_id": BULL_FLAG_V2_FOLLOWTHROUGH_DIAGNOSTIC_PROFILE_ID,
                    "entry_layer": "setup_confirmation",
                    "diagnostic_layer": "followthrough",
                    "min_setup_score": 70.0,
                    "min_confirmation_score": 60.0,
                    "min_followthrough_score": 65.0,
                    "use_followthrough_for_entry": True,
                    "diagnostic_only_reason": "uses post-breakout continuation-window information; do not use as an executable entry filter",
                },
                "branches": guard_branches(),
            }
        )
        return profiles

    return [
        {
            "profile_id": "detector_baseline",
            "profile_role": "baseline_detector",
            "overlap_cooldown_days": 0,
            "branches": [
                {
                    "branch_id": "baseline_all",
                    "branch_priority": 1,
                    "detector_config": baseline.to_dict(),
                    "event_filter_config": {},
                }
            ],
        },
        {
            "profile_id": "adaptive_liquidity_regime",
            "profile_role": "adaptive_detector_candidate",
            "overlap_cooldown_days": 30,
            "branches": [
                {
                    "branch_id": "high_mid_liquidity_bull_loose",
                    "branch_priority": 30,
                    "detector_config": loose.to_dict(),
                    "event_filter_config": _base_accept_filter()
                    | {
                        "allowed_regimes": ["bull"],
                        "allowed_liquidity_buckets": ["high", "mid"],
                        "max_flag_to_pole_pct": 65.0,
                    },
                },
                {
                    "branch_id": "low_liquidity_bull_compact",
                    "branch_priority": 40,
                    "detector_config": compact.to_dict(),
                    "event_filter_config": _tight_accept_filter()
                    | {
                        "allowed_regimes": ["bull"],
                        "allowed_liquidity_buckets": ["low", "unknown"],
                        "max_flag_to_pole_pct": 45.0,
                    },
                },
                {
                    "branch_id": "bear_market_tight",
                    "branch_priority": 50,
                    "detector_config": tight.to_dict(),
                    "event_filter_config": _tight_accept_filter()
                    | {
                        "allowed_regimes": ["bear"],
                        "max_flag_to_pole_pct": 35.0,
                    },
                },
            ],
        },
        {
            "profile_id": "adaptive_recover_validation",
            "profile_role": "adaptive_detector_candidate",
            "overlap_cooldown_days": 30,
            "branches": [
                {
                    "branch_id": "recent_high_mid_loose",
                    "branch_priority": 30,
                    "detector_config": loose.to_dict(),
                    "event_filter_config": _base_accept_filter()
                    | {
                        "min_breakout_year": 2023,
                        "allowed_liquidity_buckets": ["high", "mid"],
                    },
                },
                {
                    "branch_id": "recent_low_compact",
                    "branch_priority": 40,
                    "detector_config": compact.to_dict(),
                    "event_filter_config": _tight_accept_filter()
                    | {
                        "min_breakout_year": 2023,
                        "allowed_liquidity_buckets": ["low", "unknown"],
                    },
                },
                {
                    "branch_id": "early_sample_balanced",
                    "branch_priority": 20,
                    "detector_config": balanced.to_dict(),
                    "event_filter_config": _base_accept_filter()
                    | {
                        "max_breakout_year": 2022,
                    },
                },
            ],
        },
        {
            "profile_id": "adaptive_quality_volume",
            "profile_role": "adaptive_detector_candidate",
            "overlap_cooldown_days": 30,
            "branches": [
                {
                    "branch_id": "volume_confirmed_expansion",
                    "branch_priority": 40,
                    "detector_config": volume_confirmed.to_dict(),
                    "event_filter_config": _base_accept_filter()
                    | {
                        "allowed_liquidity_buckets": ["high", "mid"],
                    },
                },
                {
                    "branch_id": "premium_no_volume_fallback",
                    "branch_priority": 30,
                    "detector_config": tight.to_dict(),
                    "event_filter_config": _tight_accept_filter()
                    | {
                        "max_flag_to_pole_pct": 35.0,
                    },
                },
                {
                    "branch_id": "balanced_clean_recovery",
                    "branch_priority": 20,
                    "detector_config": balanced.to_dict(),
                    "event_filter_config": {
                        "profile_id": "vn_accept_clean_only",
                        "allowed_path_quality_buckets": ["clean"],
                        "max_post_zero_volume_days_60d": 4,
                        "require_primary_event_60d": True,
                    },
                },
            ],
        },
        {
            "profile_id": "adaptive_broad_recovery",
            "profile_role": "adaptive_detector_candidate",
            "overlap_cooldown_days": 30,
            "branches": [
                {
                    "branch_id": "broad_high_liquidity",
                    "branch_priority": 20,
                    "detector_config": loose.to_dict(),
                    "event_filter_config": _base_accept_filter()
                    | {
                        "allowed_liquidity_buckets": ["high"],
                    },
                },
                {
                    "branch_id": "balanced_mid_liquidity",
                    "branch_priority": 30,
                    "detector_config": balanced.to_dict(),
                    "event_filter_config": _base_accept_filter()
                    | {
                        "allowed_liquidity_buckets": ["mid"],
                    },
                },
                {
                    "branch_id": "tight_low_liquidity",
                    "branch_priority": 50,
                    "detector_config": tight.to_dict(),
                    "event_filter_config": _tight_accept_filter()
                    | {
                        "allowed_liquidity_buckets": ["low", "unknown"],
                    },
                },
            ],
        },
        {
            "profile_id": "adaptive_2024_guard",
            "profile_role": "adaptive_detector_candidate",
            "overlap_cooldown_days": 30,
            "branches": guard_branches(),
        },
        {
            "profile_id": "adaptive_2024_volume_guard",
            "profile_role": "adaptive_detector_candidate",
            "overlap_cooldown_days": 30,
            "branches": guard_branches(volume_guard=True),
        },
        *bull_flag_v2_profiles(),
    ]


def _apply_profile(events: pd.DataFrame, profile: Mapping[str, Any]) -> pd.DataFrame:
    if profile.get("profile_id") == "baseline_all":
        return events.copy()
    mask = events.apply(lambda row: _event_passes_filter(row.to_dict(), profile), axis=1)
    return events[mask].copy()


def _split(events: pd.DataFrame, split_name: str) -> pd.DataFrame:
    if "time_split" not in events.columns:
        return pd.DataFrame(columns=events.columns)
    return events[events["time_split"].astype(str) == split_name].copy()


def _regime(events: pd.DataFrame, regime: str) -> pd.DataFrame:
    if "market_regime" not in events.columns:
        return pd.DataFrame(columns=events.columns)
    return events[events["market_regime"].astype(str) == regime].copy()


def _clean_share(events: pd.DataFrame) -> Optional[float]:
    if events.empty or "path_quality_bucket" not in events.columns:
        return None
    return round(float((events["path_quality_bucket"].astype(str) == "clean").mean()) * 100.0, 2)


def _overfit_flags(row: Mapping[str, Any]) -> List[str]:
    flags: List[str] = []
    if int(row.get("n") or 0) < int(row.get("min_n_required") or 0):
        flags.append("sample_too_small")
    if int(row.get("validation_n") or 0) < 15:
        flags.append("validation_too_small")
    if int(row.get("holdout_n") or 0) < 15:
        flags.append("holdout_too_small")
    if float(row.get("clean_share_pct") or 0.0) < 60.0:
        flags.append("clean_path_share_low")
    if float(row.get("validation_target_first_rate") or 0.0) < 35.0:
        flags.append("validation_target_first_weak")
    if float(row.get("validation_failure_rate") or 100.0) > 30.0:
        flags.append("validation_failure_high")
    if float(row.get("holdout_target_first_rate") or 0.0) < 30.0:
        flags.append("holdout_target_first_weak")
    if float(row.get("holdout_failure_rate") or 100.0) > 40.0:
        flags.append("holdout_failure_high")
    if abs(float(row.get("train_hit_rate") or 0.0) - float(row.get("validation_hit_rate") or 0.0)) > 25.0:
        flags.append("train_validation_gap_large")
    if abs(float(row.get("validation_hit_rate") or 0.0) - float(row.get("holdout_hit_rate") or 0.0)) > 25.0:
        flags.append("validation_holdout_gap_large")
    if row.get("target_family_monotonic") is False:
        flags.append("target_family_non_monotonic")
    return flags


def evaluate_profile(profile: Mapping[str, Any], artifacts: PatternArtifacts, *, baseline_n: int) -> Dict[str, Any]:
    events = _apply_profile(artifacts.events, profile)
    all_row = _target_row(events, artifacts.path)
    contract = _metric_contract(events, artifacts.path)
    train_row = _target_row(_split(events, "train_60"), artifacts.path)
    validation_row = _target_row(_split(events, "validation_20"), artifacts.path)
    validation_stretch_row = _target_row_for_multiple(_split(events, "validation_20"), artifacts.path, multiple=LOCAL_STRETCH_TARGET_MULTIPLE)
    holdout_row = _target_row(_split(events, "holdout_20"), artifacts.path)
    bull_row = _target_row(_regime(events, "bull"), artifacts.path)
    bear_row = _target_row(_regime(events, "bear"), artifacts.path)
    min_n_required = max(40, int(round(baseline_n * 0.35)))
    score = _score_from_row(
        validation_row,
        sample_n=int(len(events)),
        baseline_n=baseline_n,
        holdout_row=holdout_row,
        stretch_row=validation_stretch_row,
    )
    row = {
        "profile_id": profile.get("profile_id"),
        "profile_role": profile.get("profile_role"),
        "path_mode": profile.get("path_mode"),
        "min_pole_move_pct": profile.get("min_pole_move_pct"),
        "max_flag_to_pole_pct": profile.get("max_flag_to_pole_pct"),
        "max_slope_gap_deg": profile.get("max_slope_gap_deg"),
        "min_pattern_quality_score": profile.get("min_pattern_quality_score"),
        "require_volume_confirmed": profile.get("require_volume_confirmed"),
        "n": int(len(events)),
        "baseline_n": int(baseline_n),
        "min_n_required": int(min_n_required),
        "sample_retention_pct": round(int(len(events)) / max(1, baseline_n) * 100.0, 2),
        "clean_share_pct": _clean_share(events),
        "target_hit_rate": all_row.get("target_hit_rate"),
        "target_hit_ci_low": all_row.get("target_hit_ci_low"),
        "target_first_rate": all_row.get("target_first_before_adverse_5pct_rate"),
        "failure_rate": all_row.get("failure_5pct_rate"),
        "mfe_mae_ratio": all_row.get("mfe_mae_median_ratio"),
        **contract,
        "train_n": train_row.get("n"),
        "train_hit_rate": train_row.get("target_hit_rate"),
        "train_target_first_rate": train_row.get("target_first_before_adverse_5pct_rate"),
        "train_failure_rate": train_row.get("failure_5pct_rate"),
        "validation_n": validation_row.get("n"),
        "validation_hit_rate": validation_row.get("target_hit_rate"),
        "validation_hit_ci_low": validation_row.get("target_hit_ci_low"),
        "validation_target_first_rate": validation_row.get("target_first_before_adverse_5pct_rate"),
        "validation_failure_rate": validation_row.get("failure_5pct_rate"),
        "validation_mfe_mae_ratio": validation_row.get("mfe_mae_median_ratio"),
        "holdout_n": holdout_row.get("n"),
        "holdout_hit_rate": holdout_row.get("target_hit_rate"),
        "holdout_hit_ci_low": holdout_row.get("target_hit_ci_low"),
        "holdout_target_first_rate": holdout_row.get("target_first_before_adverse_5pct_rate"),
        "holdout_failure_rate": holdout_row.get("failure_5pct_rate"),
        "holdout_mfe_mae_ratio": holdout_row.get("mfe_mae_median_ratio"),
        "bull_n": bull_row.get("n"),
        "bull_hit_rate": bull_row.get("target_hit_rate"),
        "bull_target_first_rate": bull_row.get("target_first_before_adverse_5pct_rate"),
        "bull_failure_rate": bull_row.get("failure_5pct_rate"),
        "bear_n": bear_row.get("n"),
        "bear_hit_rate": bear_row.get("target_hit_rate"),
        "bear_target_first_rate": bear_row.get("target_first_before_adverse_5pct_rate"),
        "bear_failure_rate": bear_row.get("failure_5pct_rate"),
        "localization_score": score,
    }
    flags = _overfit_flags(row)
    row["overfit_flags"] = ",".join(flags)
    row["gates_pass"] = not flags
    return row


def _evaluate_events(events: pd.DataFrame, path: pd.DataFrame, *, profile: Mapping[str, Any], baseline_n: int, raw_n: int) -> Dict[str, Any]:
    all_row = _target_row(events, path)
    contract = _metric_contract(events, path)
    train_row = _target_row(_split(events, "train_60"), path)
    validation_row = _target_row(_split(events, "validation_20"), path)
    validation_stretch_row = _target_row_for_multiple(_split(events, "validation_20"), path, multiple=LOCAL_STRETCH_TARGET_MULTIPLE)
    holdout_row = _target_row(_split(events, "holdout_20"), path)
    bull_row = _target_row(_regime(events, "bull"), path)
    bear_row = _target_row(_regime(events, "bear"), path)
    min_n_required = max(40, int(round(baseline_n * 0.35)))
    score = _score_from_row(
        validation_row,
        sample_n=int(len(events)),
        baseline_n=baseline_n,
        holdout_row=holdout_row,
        stretch_row=validation_stretch_row,
    )
    detector_config = profile.get("detector_config") if isinstance(profile.get("detector_config"), Mapping) else {}
    event_filter = profile.get("event_filter_config") if isinstance(profile.get("event_filter_config"), Mapping) else {}
    row = {
        "profile_id": profile.get("profile_id"),
        "profile_role": profile.get("profile_role"),
        "raw_detection_count": int(raw_n),
        "n": int(len(events)),
        "baseline_n": int(baseline_n),
        "min_n_required": int(min_n_required),
        "sample_retention_pct": round(int(len(events)) / max(1, baseline_n) * 100.0, 2),
        "raw_to_kept_pct": round(int(len(events)) / max(1, raw_n) * 100.0, 2),
        "clean_share_pct": _clean_share(events),
        "target_hit_rate": all_row.get("target_hit_rate"),
        "target_hit_ci_low": all_row.get("target_hit_ci_low"),
        "target_first_rate": all_row.get("target_first_before_adverse_5pct_rate"),
        "failure_rate": all_row.get("failure_5pct_rate"),
        "mfe_mae_ratio": all_row.get("mfe_mae_median_ratio"),
        **contract,
        "train_n": train_row.get("n"),
        "train_hit_rate": train_row.get("target_hit_rate"),
        "train_target_first_rate": train_row.get("target_first_before_adverse_5pct_rate"),
        "train_failure_rate": train_row.get("failure_5pct_rate"),
        "validation_n": validation_row.get("n"),
        "validation_hit_rate": validation_row.get("target_hit_rate"),
        "validation_hit_ci_low": validation_row.get("target_hit_ci_low"),
        "validation_target_first_rate": validation_row.get("target_first_before_adverse_5pct_rate"),
        "validation_failure_rate": validation_row.get("failure_5pct_rate"),
        "validation_mfe_mae_ratio": validation_row.get("mfe_mae_median_ratio"),
        "holdout_n": holdout_row.get("n"),
        "holdout_hit_rate": holdout_row.get("target_hit_rate"),
        "holdout_hit_ci_low": holdout_row.get("target_hit_ci_low"),
        "holdout_target_first_rate": holdout_row.get("target_first_before_adverse_5pct_rate"),
        "holdout_failure_rate": holdout_row.get("failure_5pct_rate"),
        "holdout_mfe_mae_ratio": holdout_row.get("mfe_mae_median_ratio"),
        "bull_n": bull_row.get("n"),
        "bull_hit_rate": bull_row.get("target_hit_rate"),
        "bull_target_first_rate": bull_row.get("target_first_before_adverse_5pct_rate"),
        "bull_failure_rate": bull_row.get("failure_5pct_rate"),
        "bear_n": bear_row.get("n"),
        "bear_hit_rate": bear_row.get("target_hit_rate"),
        "bear_target_first_rate": bear_row.get("target_first_before_adverse_5pct_rate"),
        "bear_failure_rate": bear_row.get("failure_5pct_rate"),
        "localization_score": score,
        "detector_pole_min_change_pct": detector_config.get("pole_min_change_pct"),
        "detector_pole_min_slope_deg": detector_config.get("pole_min_slope_deg"),
        "detector_parallel_tol_deg": detector_config.get("parallel_tol_deg"),
        "detector_flag_to_pole_max_pct": detector_config.get("flag_to_pole_max_pct"),
        "detector_breakout_threshold": detector_config.get("breakout_threshold"),
        "detector_require_volume_confirmed": detector_config.get("require_volume_confirmed"),
        "event_filter_profile_id": event_filter.get("profile_id"),
    }
    flags = _overfit_flags(row)
    row["overfit_flags"] = ",".join(flags)
    row["gates_pass"] = not flags
    return row


def _scan_detector_profile(
    profile: Mapping[str, Any],
    *,
    source_dir: Path,
    market_stats_json: Optional[Path],
    index_db: Path,
    index_symbol: str,
    limit_symbols: Optional[int] = None,
) -> tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    active_meta = _load_active_symbols(market_stats_json)
    allowed_symbols = active_meta.get("active_symbols") if active_meta.get("enabled") else None
    raw_scan = scan_market_stats(
        source_dir,
        limit_symbols=limit_symbols,
        index_db=index_db,
        index_symbol=index_symbol,
        allowed_symbols=allowed_symbols,
        detector_config=profile.get("detector_config"),
    )
    raw_scan = _restrict_scan_to_active_universe(raw_scan, market_stats_json)
    scan = _filter_bull_flags(raw_scan)
    raw_count = len(scan.get("detections") or [])
    _enrich_events(scan, source_dir=source_dir)
    event_filter = profile.get("event_filter_config") if isinstance(profile.get("event_filter_config"), Mapping) else None
    _apply_event_filter(scan, event_filter)
    path_rows = _path_rows(scan, source_dir=source_dir)
    return scan | {"raw_bull_flag_detection_count": raw_count}, list(scan.get("detections") or []), path_rows


def _detector_cache_key(config: Mapping[str, Any]) -> str:
    clean = FlagDetectorConfig.from_mapping(config).to_dict()
    return json.dumps(clean, sort_keys=True, ensure_ascii=True)


def _scan_detector_config_base(
    detector_config: Mapping[str, Any],
    *,
    source_dir: Path,
    market_stats_json: Optional[Path],
    index_db: Path,
    index_symbol: str,
    limit_symbols: Optional[int],
    cache: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    key = _detector_cache_key(detector_config)
    if key in cache:
        return cache[key]
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
    scan = _filter_bull_flags(raw_scan)
    raw_count = len(scan.get("detections") or [])
    _enrich_events(scan, source_dir=source_dir)
    scan["raw_bull_flag_detection_count"] = raw_count
    scan["detector_cache_key"] = key
    cache[key] = scan
    return scan


def _copy_scan_with_rows(scan: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    return {**dict(scan), "detections": [dict(row) for row in rows]}


def _dedupe_adaptive_events(rows: Sequence[Mapping[str, Any]], *, cooldown_days: int) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for row in rows:
        breakout = pd.to_datetime(row.get("breakout_date"), errors="coerce")
        if pd.isna(breakout):
            continue
        enriched = dict(row)
        enriched["_breakout_ts"] = breakout
        candidates.append(enriched)
    if not candidates:
        return [], {"input_count": len(rows), "kept_count": 0, "removed_count": len(rows), "cooldown_days": cooldown_days}

    def quality_key(row: Mapping[str, Any]) -> tuple[float, float, float, float, float]:
        priority = float(row.get("adaptive_branch_priority") or 0.0)
        quality = float(row.get("pattern_quality_score") or 0.0)
        pole = float(row.get("pole_move_pct") or 0.0)
        compactness = -float(row.get("flag_to_pole_pct") or 999.0)
        slope = -float(row.get("slope_gap_deg") or 999.0)
        return priority, quality, pole, compactness, slope

    kept: List[Dict[str, Any]] = []
    kept_dates_by_symbol: Dict[str, List[pd.Timestamp]] = {}
    for row in sorted(candidates, key=quality_key, reverse=True):
        symbol = str(row.get("symbol") or "").upper()
        breakout = row["_breakout_ts"]
        dates = kept_dates_by_symbol.setdefault(symbol, [])
        if cooldown_days > 0 and any(abs((breakout - prior).days) <= cooldown_days for prior in dates):
            continue
        clean = {key: value for key, value in row.items() if key != "_breakout_ts"}
        kept.append(clean)
        dates.append(breakout)

    kept.sort(key=lambda row: (str(row.get("breakout_date") or ""), str(row.get("symbol") or ""), str(row.get("adaptive_branch_id") or "")))
    for idx, row in enumerate(kept, start=1):
        row["detection_id"] = f"{PATTERN_KEY}:adaptive:{idx:06d}"
        row["pattern_key"] = PATTERN_KEY
    return kept, {
        "input_count": len(rows),
        "kept_count": len(kept),
        "removed_count": len(rows) - len(kept),
        "cooldown_days": cooldown_days,
        "kept_share_pct": round(len(kept) / len(rows) * 100.0, 2) if rows else None,
    }


def _scan_adaptive_profile(
    profile: Mapping[str, Any],
    *,
    source_dir: Path,
    market_stats_json: Optional[Path],
    index_db: Path,
    index_symbol: str,
    limit_symbols: Optional[int],
    cache: Dict[str, Dict[str, Any]],
) -> tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    branches = list(profile.get("branches") or [])
    candidate_rows: List[Dict[str, Any]] = []
    branch_summaries: List[Dict[str, Any]] = []
    unique_raw_counts: Dict[str, int] = {}
    for branch in branches:
        if not isinstance(branch, Mapping):
            continue
        detector_config = branch.get("detector_config") if isinstance(branch.get("detector_config"), Mapping) else {}
        base_scan = _scan_detector_config_base(
            detector_config,
            source_dir=source_dir,
            market_stats_json=market_stats_json,
            index_db=index_db,
            index_symbol=index_symbol,
            limit_symbols=limit_symbols,
            cache=cache,
        )
        cache_key = str(base_scan.get("detector_cache_key") or _detector_cache_key(detector_config))
        unique_raw_counts[cache_key] = int(base_scan.get("raw_bull_flag_detection_count") or 0)
        branch_scan = _copy_scan_with_rows(base_scan, base_scan.get("detections") or [])
        event_filter = branch.get("event_filter_config") if isinstance(branch.get("event_filter_config"), Mapping) else {}
        _apply_event_filter(branch_scan, event_filter)
        branch_rows = [dict(row) for row in branch_scan.get("detections") or []]
        for row in branch_rows:
            row["adaptive_profile_id"] = profile.get("profile_id")
            row["adaptive_branch_id"] = branch.get("branch_id")
            row["adaptive_branch_priority"] = branch.get("branch_priority", 0)
        candidate_rows.extend(branch_rows)
        branch_summaries.append(
            {
                "branch_id": branch.get("branch_id"),
                "branch_priority": branch.get("branch_priority", 0),
                "detector_cache_key": cache_key,
                "raw_bull_flag_detection_count": int(base_scan.get("raw_bull_flag_detection_count") or 0),
                "kept_before_merge": len(branch_rows),
                "event_filter_config": dict(event_filter),
            }
        )

    deduped, overlap_report = _dedupe_adaptive_events(candidate_rows, cooldown_days=int(profile.get("overlap_cooldown_days") or 0))
    scan: Dict[str, Any] = {
        "generated_at": None,
        "pattern_key": PATTERN_KEY,
        "detections": deduped,
        "adaptive_profile_id": profile.get("profile_id"),
        "adaptive_profile_role": profile.get("profile_role"),
        "adaptive_branches": branch_summaries,
        "adaptive_overlap_report": overlap_report,
        "raw_bull_flag_detection_count": sum(unique_raw_counts.values()),
        "branch_candidate_count": len(candidate_rows),
    }
    _enrich_events(scan, source_dir=source_dir)
    path_rows = _path_rows(scan, source_dir=source_dir)
    return scan, list(scan.get("detections") or []), path_rows


def _branch_attribution_rows(events: pd.DataFrame, path: pd.DataFrame, *, profile_id: str) -> List[Dict[str, Any]]:
    if events.empty or "adaptive_branch_id" not in events.columns:
        return []
    rows: List[Dict[str, Any]] = []
    for branch_id, group in events.groupby("adaptive_branch_id", dropna=False):
        contract = _metric_contract(group.copy(), path)
        rows.append(
            {
                "profile_id": profile_id,
                "branch_id": str(branch_id),
                "n": int(len(group)),
                "clean_share_pct": _clean_share(group),
                "train_n": int((_split(group, "train_60")).shape[0]),
                "validation_n": int((_split(group, "validation_20")).shape[0]),
                "holdout_n": int((_split(group, "holdout_20")).shape[0]),
                **contract,
            }
        )
    return sorted(rows, key=lambda row: str(row.get("branch_id") or ""))


def _context_stability_rows(events: pd.DataFrame, path: pd.DataFrame, *, profile_id: str) -> List[Dict[str, Any]]:
    if events.empty:
        return []
    contexts = [
        ("time_split", ["time_split"]),
        ("breakout_year", ["breakout_year"]),
        ("market_regime", ["market_regime"]),
        ("liquidity_bucket", ["liquidity_bucket"]),
        ("adaptive_branch", ["adaptive_branch_id"]),
        ("time_split_x_branch", ["time_split", "adaptive_branch_id"]),
        ("time_split_x_liquidity", ["time_split", "liquidity_bucket"]),
        ("time_split_x_regime", ["time_split", "market_regime"]),
    ]
    rows: List[Dict[str, Any]] = []
    for context_id, cols in contexts:
        if any(col not in events.columns for col in cols):
            continue
        for key, group in events.groupby(cols, dropna=False):
            key_values = key if isinstance(key, tuple) else (key,)
            contract = _metric_contract(group.copy(), path)
            n = int(len(group))
            rows.append(
                {
                    "profile_id": profile_id,
                    "context_id": context_id,
                    "context_key": " | ".join(str(value) for value in key_values),
                    "n": n,
                    "underpowered_lt_10": n < 10,
                    "diagnostic_pass": bool(
                        n >= 10
                        and float(contract.get("target_first_base_046x_rate") or 0.0) >= 30.0
                        and float(contract.get("failure_5pct_rate") or 100.0) <= 40.0
                    ),
                    "clean_share_pct": _clean_share(group),
                    **contract,
                }
            )
    return rows


def _context_stability_summary(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    time_rows = [row for row in rows if row.get("context_id") == "time_split"]
    diagnostic_rows = [row for row in rows if not bool(row.get("underpowered_lt_10"))]
    failed_rows = [row for row in diagnostic_rows if row.get("diagnostic_pass") is not True]
    underpowered_rows = [row for row in rows if bool(row.get("underpowered_lt_10"))]
    holdout = next((row for row in time_rows if row.get("context_key") == "holdout_20"), {})
    validation = next((row for row in time_rows if row.get("context_key") == "validation_20"), {})
    return {
        "context_diagnostic_check_count": len(diagnostic_rows),
        "context_diagnostic_fail_count": len(failed_rows),
        "context_underpowered_count": len(underpowered_rows),
        "context_holdout_n": holdout.get("n"),
        "context_holdout_target_first": holdout.get("target_first_base_046x_rate"),
        "context_holdout_failure": holdout.get("failure_5pct_rate"),
        "context_validation_n": validation.get("n"),
        "context_validation_target_first": validation.get("target_first_base_046x_rate"),
        "context_validation_failure": validation.get("failure_5pct_rate"),
    }


def _chronological_split(events: pd.DataFrame, *, train_frac: float, validation_frac: float) -> Dict[str, pd.DataFrame]:
    if events.empty or "breakout_date" not in events.columns:
        empty = pd.DataFrame(columns=events.columns)
        return {"train": empty, "validation": empty, "holdout": empty}
    ordered = events.copy()
    ordered["_breakout_ts"] = pd.to_datetime(ordered["breakout_date"], errors="coerce")
    ordered = ordered.dropna(subset=["_breakout_ts"]).sort_values(["_breakout_ts", "symbol"]).drop(columns=["_breakout_ts"])
    n = len(ordered)
    train_end = int(np.floor(n * train_frac))
    validation_end = int(np.floor(n * (train_frac + validation_frac)))
    train_end = min(max(1, train_end), n)
    validation_end = min(max(train_end + 1, validation_end), n) if n >= 3 else n
    return {
        "train": ordered.iloc[:train_end].copy(),
        "validation": ordered.iloc[train_end:validation_end].copy(),
        "holdout": ordered.iloc[validation_end:].copy(),
    }


def _alternate_split_rows(events: pd.DataFrame, path: pd.DataFrame, *, profile_id: str) -> List[Dict[str, Any]]:
    schemes = [
        ("chronological_50_25_25", 0.50, 0.25),
        ("chronological_60_20_20", 0.60, 0.20),
        ("chronological_70_15_15", 0.70, 0.15),
    ]
    rows: List[Dict[str, Any]] = []
    for scheme_id, train_frac, validation_frac in schemes:
        splits = _chronological_split(events, train_frac=train_frac, validation_frac=validation_frac)
        for split_name, subset in splits.items():
            contract = _metric_contract(subset, path)
            n = int(len(subset))
            underpowered = False
            metric_pass = True
            gate_pass = True
            if split_name in {"validation", "holdout"}:
                underpowered = n < 10
                metric_pass = (
                    float(contract.get("target_first_base_046x_rate") or 0.0) >= 30.0
                    and float(contract.get("failure_5pct_rate") or 100.0) <= 40.0
                )
                gate_pass = (not underpowered) and metric_pass
            rows.append(
                {
                    "profile_id": profile_id,
                    "scheme_id": scheme_id,
                    "split": split_name,
                    "n": n,
                    "underpowered_lt_10": bool(underpowered),
                    "metric_pass": bool(metric_pass),
                    "gate_pass": bool(gate_pass),
                    **contract,
                }
            )
    return rows


def _alternate_split_summary(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    check_rows = [row for row in rows if row.get("split") in {"validation", "holdout"}]
    fail_rows = [row for row in check_rows if row.get("gate_pass") is not True]
    underpowered_rows = [row for row in check_rows if bool(row.get("underpowered_lt_10"))]
    metric_fail_rows = [row for row in check_rows if not bool(row.get("underpowered_lt_10")) and row.get("metric_pass") is not True]
    validation_rows = [row for row in rows if row.get("split") == "validation"]
    holdout_rows = [row for row in rows if row.get("split") == "holdout"]
    return {
        "alternate_split_check_count": len(check_rows),
        "alternate_split_fail_count": len(fail_rows),
        "alternate_split_metric_fail_count": len(metric_fail_rows),
        "alternate_split_underpowered_count": len(underpowered_rows),
        "alternate_split_pass_rate_pct": round((len(check_rows) - len(fail_rows)) / len(check_rows) * 100.0, 2) if check_rows else None,
        "alternate_validation_min_target_first": min((float(row.get("target_first_base_046x_rate") or 0.0) for row in validation_rows), default=None),
        "alternate_validation_max_failure": max((float(row.get("failure_5pct_rate") or 100.0) for row in validation_rows), default=None),
        "alternate_holdout_min_target_first": min((float(row.get("target_first_base_046x_rate") or 0.0) for row in holdout_rows), default=None),
        "alternate_holdout_max_failure": max((float(row.get("failure_5pct_rate") or 100.0) for row in holdout_rows), default=None),
    }


def _first_bar(per_event: pd.DataFrame, condition: pd.Series) -> Optional[int]:
    rows = per_event[condition]
    if rows.empty:
        return None
    return int(rows.iloc[0]["bar_after_breakout"])


def _negative_control_rows(events: pd.DataFrame, path: pd.DataFrame, *, profile_id: str) -> List[Dict[str, Any]]:
    if events.empty or path.empty or "event_id" not in path.columns:
        return []
    working_events = events.copy()
    if "event_id" not in working_events.columns and "detection_id" in working_events.columns:
        working_events["event_id"] = working_events["detection_id"]
    working_path = path.copy()
    working_path["bar_after_breakout"] = pd.to_numeric(working_path.get("bar_after_breakout"), errors="coerce")
    working_path["signed_high_excursion_pct"] = pd.to_numeric(working_path.get("signed_high_excursion_pct"), errors="coerce")
    working_path["signed_low_excursion_pct"] = pd.to_numeric(working_path.get("signed_low_excursion_pct"), errors="coerce")
    working_path = working_path[working_path["bar_after_breakout"] <= 60].copy()
    path_groups = {
        str(event_id): group.sort_values("bar_after_breakout")
        for event_id, group in working_path.dropna(subset=["event_id"]).groupby("event_id")
    }
    thresholds = pd.to_numeric(working_events.get("target_dist_pct"), errors="coerce").fillna(0.0) * DEFAULT_BASE_TARGET_MULTIPLE
    rotated_thresholds = thresholds.shift(1)
    if not rotated_thresholds.empty:
        rotated_thresholds.iloc[0] = thresholds.iloc[-1]

    controls = {
        "actual_base_046x": {"hit": [], "race": [], "failure": [], "mfe": [], "mae": []},
        "opposite_direction_base_046x": {"hit": [], "race": [], "failure": [], "mfe": [], "mae": []},
        "delayed_10_bar_entry_base_046x": {"hit": [], "race": [], "failure": [], "mfe": [], "mae": []},
        "permuted_target_distance_base_046x": {"hit": [], "race": [], "failure": [], "mfe": [], "mae": []},
    }

    for idx, (_, event) in enumerate(working_events.iterrows()):
        event_id = str(event.get("event_id"))
        per_event = path_groups.get(event_id)
        threshold = float(thresholds.iloc[idx]) if idx < len(thresholds) else 0.0
        permuted_threshold = float(rotated_thresholds.iloc[idx]) if idx < len(rotated_thresholds) else threshold
        if per_event is None or per_event.empty:
            for control in controls.values():
                control["hit"].append(False)
                control["race"].append(False)
                control["failure"].append(True)
                control["mfe"].append(0.0)
                control["mae"].append(0.0)
            continue

        def add_actual(control_id: str, frame: pd.DataFrame, target_pct: float) -> None:
            mfe = float(frame["signed_high_excursion_pct"].max()) if frame["signed_high_excursion_pct"].notna().any() else 0.0
            mae = abs(float(frame["signed_low_excursion_pct"].min())) if frame["signed_low_excursion_pct"].notna().any() else 0.0
            target_bar = _first_bar(frame, frame["signed_high_excursion_pct"] >= target_pct)
            adverse_bar = _first_bar(frame, frame["signed_low_excursion_pct"] <= -5.0)
            controls[control_id]["hit"].append(bool(mfe >= target_pct))
            controls[control_id]["race"].append(False if target_bar is None else (True if adverse_bar is None else target_bar < adverse_bar))
            controls[control_id]["failure"].append(bool(mfe < 5.0))
            controls[control_id]["mfe"].append(mfe)
            controls[control_id]["mae"].append(mae)

        add_actual("actual_base_046x", per_event, threshold)
        add_actual("permuted_target_distance_base_046x", per_event, permuted_threshold)
        delayed = per_event[per_event["bar_after_breakout"] > 10]
        add_actual("delayed_10_bar_entry_base_046x", delayed if not delayed.empty else per_event.iloc[0:0], threshold)

        opposite_mfe = abs(float(per_event["signed_low_excursion_pct"].min())) if per_event["signed_low_excursion_pct"].notna().any() else 0.0
        opposite_mae = float(per_event["signed_high_excursion_pct"].max()) if per_event["signed_high_excursion_pct"].notna().any() else 0.0
        opposite_target_bar = _first_bar(per_event, per_event["signed_low_excursion_pct"] <= -threshold)
        opposite_adverse_bar = _first_bar(per_event, per_event["signed_high_excursion_pct"] >= 5.0)
        controls["opposite_direction_base_046x"]["hit"].append(bool(opposite_mfe >= threshold))
        controls["opposite_direction_base_046x"]["race"].append(
            False if opposite_target_bar is None else (True if opposite_adverse_bar is None else opposite_target_bar < opposite_adverse_bar)
        )
        controls["opposite_direction_base_046x"]["failure"].append(bool(opposite_mfe < 5.0))
        controls["opposite_direction_base_046x"]["mfe"].append(opposite_mfe)
        controls["opposite_direction_base_046x"]["mae"].append(opposite_mae)

    rows: List[Dict[str, Any]] = []
    for control_id, values in controls.items():
        hit_ci = wilson_ci(sum(1 for value in values["hit"] if value), len(values["hit"]))
        race_ci = wilson_ci(sum(1 for value in values["race"] if value), len(values["race"]))
        fail_ci = wilson_ci(sum(1 for value in values["failure"] if value), len(values["failure"]))
        mfe = pd.Series(values["mfe"], dtype=float)
        mae = pd.Series(values["mae"], dtype=float)
        rows.append(
            {
                "profile_id": profile_id,
                "control_id": control_id,
                "n": len(values["hit"]),
                "target_hit_rate": hit_ci.get("rate"),
                "target_hit_ci_low": hit_ci.get("low"),
                "target_first_rate": race_ci.get("rate"),
                "target_first_ci_low": race_ci.get("low"),
                "failure_rate": fail_ci.get("rate"),
                "failure_ci_high": fail_ci.get("high"),
                "mfe_median_pct": round(float(mfe.median()), 2) if not mfe.empty else None,
                "mae_median_pct": round(float(mae.median()), 2) if not mae.empty else None,
                "mfe_mae_ratio": round(float(mfe.median()) / float(mae.median()), 2) if not mfe.empty and float(mae.median()) != 0 else None,
            }
        )
    actual = next((row for row in rows if row["control_id"] == "actual_base_046x"), None)
    if actual:
        actual_tf = float(actual.get("target_first_rate") or 0.0)
        actual_fail = float(actual.get("failure_rate") or 100.0)
        for row in rows:
            if row["control_id"] == "actual_base_046x":
                row["edge_vs_actual_target_first"] = 0.0
                row["edge_vs_actual_failure"] = 0.0
            else:
                row["edge_vs_actual_target_first"] = round(actual_tf - float(row.get("target_first_rate") or 0.0), 2)
                row["edge_vs_actual_failure"] = round(float(row.get("failure_rate") or 100.0) - actual_fail, 2)
    return rows


def _evaluate_price_frame(
    frame: pd.DataFrame,
    *,
    anchor_price: float,
    direction: str,
    target_pct: float,
    target_abs: Optional[float] = None,
    adverse_pct: float = 5.0,
) -> Optional[Dict[str, Any]]:
    if frame.empty or anchor_price <= 0 or target_pct <= 0:
        return None
    working = frame.copy().reset_index(drop=True)
    for col in ("high", "low", "close"):
        working[col] = pd.to_numeric(working.get(col), errors="coerce")
    working = working.dropna(subset=["high", "low"])
    if working.empty:
        return None
    sign = 1 if str(direction).lower() == "up" else -1
    if target_abs is None:
        target_abs = anchor_price * (1.0 + sign * target_pct / 100.0)
    if sign == 1:
        favorable = (working["high"] - anchor_price) / anchor_price * 100.0
        adverse = (working["low"] - anchor_price) / anchor_price * 100.0
        target_mask = working["high"] >= target_abs
        adverse_mask = working["low"] <= anchor_price * (1.0 - adverse_pct / 100.0)
    else:
        favorable = (anchor_price - working["low"]) / anchor_price * 100.0
        adverse = (anchor_price - working["high"]) / anchor_price * 100.0
        target_mask = working["low"] <= target_abs
        adverse_mask = working["high"] >= anchor_price * (1.0 + adverse_pct / 100.0)
    target_positions = np.flatnonzero(target_mask.to_numpy())
    adverse_positions = np.flatnonzero(adverse_mask.to_numpy())
    target_pos = int(target_positions[0]) if len(target_positions) else None
    adverse_pos = int(adverse_positions[0]) if len(adverse_positions) else None
    mfe = float(favorable.max()) if favorable.notna().any() else 0.0
    mae = abs(float(adverse.min())) if adverse.notna().any() else 0.0
    return {
        "target_hit": target_pos is not None,
        "target_first": False if target_pos is None else (True if adverse_pos is None else target_pos < adverse_pos),
        "failure_5pct": bool(mfe < adverse_pct),
        "mfe_pct": mfe,
        "mae_pct": mae,
        "days_to_target": None if target_pos is None else target_pos + 1,
    }


def _add_timing_result(
    bucket: Dict[str, List[Any]],
    result: Optional[Mapping[str, Any]],
    *,
    entry_offset_bars: Optional[int],
    entry_vs_breakout_pct: Optional[float],
) -> None:
    if not result:
        return
    bucket["target_hit"].append(bool(result.get("target_hit")))
    bucket["target_first"].append(bool(result.get("target_first")))
    bucket["failure_5pct"].append(bool(result.get("failure_5pct")))
    bucket["mfe"].append(float(result.get("mfe_pct") or 0.0))
    bucket["mae"].append(float(result.get("mae_pct") or 0.0))
    bucket["entry_offset_bars"].append(entry_offset_bars)
    bucket["entry_vs_breakout_pct"].append(entry_vs_breakout_pct)


def _timing_bucket(policy: str, target_policy: str) -> Dict[str, Any]:
    return {
        "entry_policy": policy,
        "target_policy": target_policy,
        "target_hit": [],
        "target_first": [],
        "failure_5pct": [],
        "mfe": [],
        "mae": [],
        "entry_offset_bars": [],
        "entry_vs_breakout_pct": [],
    }


def _summarize_timing_buckets(profile_id: str, buckets: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for timing_id, bucket in buckets.items():
        hits = list(bucket.get("target_hit") or [])
        races = list(bucket.get("target_first") or [])
        failures = list(bucket.get("failure_5pct") or [])
        hit_ci = wilson_ci(sum(1 for value in hits if value), len(hits))
        race_ci = wilson_ci(sum(1 for value in races if value), len(races))
        fail_ci = wilson_ci(sum(1 for value in failures if value), len(failures))
        mfe = pd.Series(bucket.get("mfe") or [], dtype=float)
        mae = pd.Series(bucket.get("mae") or [], dtype=float)
        offsets = pd.Series([v for v in bucket.get("entry_offset_bars") or [] if v is not None], dtype=float)
        slippage = pd.Series([v for v in bucket.get("entry_vs_breakout_pct") or [] if v is not None], dtype=float)
        rows.append(
            {
                "profile_id": profile_id,
                "timing_id": timing_id,
                "entry_policy": bucket.get("entry_policy"),
                "target_policy": bucket.get("target_policy"),
                "n": len(hits),
                "target_hit_rate": hit_ci.get("rate"),
                "target_hit_ci_low": hit_ci.get("low"),
                "target_first_rate": race_ci.get("rate"),
                "target_first_ci_low": race_ci.get("low"),
                "failure_rate": fail_ci.get("rate"),
                "failure_ci_high": fail_ci.get("high"),
                "mfe_median_pct": round(float(mfe.median()), 2) if not mfe.empty else None,
                "mae_median_pct": round(float(mae.median()), 2) if not mae.empty else None,
                "mfe_mae_ratio": round(float(mfe.median()) / float(mae.median()), 2) if not mfe.empty and not mae.empty and float(mae.median()) != 0 else None,
                "median_entry_offset_bars": round(float(offsets.median()), 2) if not offsets.empty else None,
                "median_entry_vs_breakout_pct": round(float(slippage.median()), 2) if not slippage.empty else None,
            }
        )
    actual = next((row for row in rows if row["timing_id"] == "actual_breakout_base_046x"), None)
    if actual:
        actual_tf = float(actual.get("target_first_rate") or 0.0)
        actual_failure = float(actual.get("failure_rate") or 100.0)
        for row in rows:
            if row["timing_id"] == "actual_breakout_base_046x":
                row["edge_vs_actual_target_first"] = 0.0
                row["edge_vs_actual_failure"] = 0.0
            else:
                row["edge_vs_actual_target_first"] = round(actual_tf - float(row.get("target_first_rate") or 0.0), 2)
                row["edge_vs_actual_failure"] = round(float(row.get("failure_rate") or 100.0) - actual_failure, 2)
    return rows


def _source_paths_by_symbol(source_dir: Optional[Path]) -> Dict[str, Path]:
    if source_dir is None or not source_dir.exists():
        return {}
    paths: Dict[str, Path] = {}
    for path in sorted(source_dir.glob("*.json")):
        symbol = _symbol_from_path(path)
        current = paths.get(symbol)
        rank = (0 if path.name.upper() == f"{symbol}.JSON" else 1, len(path.name), path.name)
        current_rank = (2, 9999, "") if current is None else (0 if current.name.upper() == f"{symbol}.JSON" else 1, len(current.name), current.name)
        if current is None or rank < current_rank:
            paths[symbol] = path
    return paths


def _breakout_timing_rows(
    events: pd.DataFrame,
    path: pd.DataFrame,
    *,
    profile_id: str,
    source_dir: Optional[Path] = None,
    horizon_bars: int = 60,
) -> List[Dict[str, Any]]:
    """Compare exact breakout timing with delayed and pre-breakout trend controls."""

    if events.empty:
        return []
    working_events = events.copy()
    if "event_id" not in working_events.columns and "detection_id" in working_events.columns:
        working_events["event_id"] = working_events["detection_id"]
    for col in ("breakout_price", "target_dist_pct", "breakout_idx", "formation_start_idx", "formation_end_idx"):
        if col in working_events.columns:
            working_events[col] = pd.to_numeric(working_events[col], errors="coerce")

    working_path = path.copy()
    if not working_path.empty:
        for col in ("bar_after_breakout", "open", "high", "low", "close"):
            if col in working_path.columns:
                working_path[col] = pd.to_numeric(working_path[col], errors="coerce")
    path_groups = {
        str(event_id): group.sort_values("bar_after_breakout")
        for event_id, group in working_path.dropna(subset=["event_id"]).groupby("event_id")
    } if not working_path.empty and "event_id" in working_path.columns else {}

    buckets: Dict[str, Dict[str, Any]] = {
        "actual_breakout_base_046x": _timing_bucket("breakout_price_at_confirmation", "same_absolute_base_target"),
        "next_open_same_abs_base_046x": _timing_bucket("next_session_open", "same_absolute_base_target"),
        "next_open_reanchored_base_046x": _timing_bucket("next_session_open", "reanchored_same_pct_target"),
    }
    for delay in (5, 10, 20):
        buckets[f"delayed_{delay}_close_same_abs_base_046x"] = _timing_bucket(f"close_after_{delay}_bars", "same_absolute_base_target")
        buckets[f"delayed_{delay}_close_reanchored_base_046x"] = _timing_bucket(f"close_after_{delay}_bars", "reanchored_same_pct_target")
    source_paths = _source_paths_by_symbol(source_dir)
    source_cache: Dict[str, pd.DataFrame] = {}
    if source_paths:
        for control_id, entry_policy in (
            ("flag_start_close_same_abs_base_046x", "flag_start_close_before_breakout"),
            ("flag_end_close_same_abs_base_046x", "flag_end_close_before_breakout"),
            ("pre_breakout_minus_3_close_same_abs_base_046x", "close_3_bars_before_breakout"),
            ("pre_breakout_minus_5_close_same_abs_base_046x", "close_5_bars_before_breakout"),
        ):
            buckets[control_id] = _timing_bucket(entry_policy, "same_absolute_base_target")

    for _, event in working_events.iterrows():
        event_id = str(event.get("event_id"))
        direction = str(event.get("breakout_direction") or "up").lower()
        sign = 1 if direction == "up" else -1
        breakout_price = float(event.get("breakout_price") or 0.0)
        target_dist_pct = float(event.get("target_dist_pct") or 0.0)
        if breakout_price <= 0 or target_dist_pct <= 0:
            continue
        target_pct = target_dist_pct * DEFAULT_BASE_TARGET_MULTIPLE
        target_abs = breakout_price * (1.0 + sign * target_pct / 100.0)
        per_event = path_groups.get(event_id)
        if per_event is not None and not per_event.empty:
            actual_frame = per_event[per_event["bar_after_breakout"] <= horizon_bars].copy()
            _add_timing_result(
                buckets["actual_breakout_base_046x"],
                _evaluate_price_frame(actual_frame, anchor_price=breakout_price, direction=direction, target_pct=target_pct, target_abs=target_abs),
                entry_offset_bars=0,
                entry_vs_breakout_pct=0.0,
            )
            first = per_event[per_event["bar_after_breakout"] == 1]
            if not first.empty:
                anchor = float(first.iloc[0]["open"])
                frame = per_event[(per_event["bar_after_breakout"] >= 1) & (per_event["bar_after_breakout"] <= horizon_bars)].copy()
                entry_vs_breakout = sign * (anchor / breakout_price - 1.0) * 100.0 if breakout_price > 0 else None
                _add_timing_result(
                    buckets["next_open_same_abs_base_046x"],
                    _evaluate_price_frame(frame, anchor_price=anchor, direction=direction, target_pct=target_pct, target_abs=target_abs),
                    entry_offset_bars=1,
                    entry_vs_breakout_pct=entry_vs_breakout,
                )
                _add_timing_result(
                    buckets["next_open_reanchored_base_046x"],
                    _evaluate_price_frame(frame, anchor_price=anchor, direction=direction, target_pct=target_pct),
                    entry_offset_bars=1,
                    entry_vs_breakout_pct=entry_vs_breakout,
                )
            for delay in (5, 10, 20):
                row = per_event[per_event["bar_after_breakout"] == delay]
                if row.empty:
                    continue
                anchor = float(row.iloc[0]["close"])
                frame = per_event[
                    (per_event["bar_after_breakout"] > delay)
                    & (per_event["bar_after_breakout"] <= delay + horizon_bars)
                ].copy()
                entry_vs_breakout = sign * (anchor / breakout_price - 1.0) * 100.0 if breakout_price > 0 else None
                _add_timing_result(
                    buckets[f"delayed_{delay}_close_same_abs_base_046x"],
                    _evaluate_price_frame(frame, anchor_price=anchor, direction=direction, target_pct=target_pct, target_abs=target_abs),
                    entry_offset_bars=delay,
                    entry_vs_breakout_pct=entry_vs_breakout,
                )
                _add_timing_result(
                    buckets[f"delayed_{delay}_close_reanchored_base_046x"],
                    _evaluate_price_frame(frame, anchor_price=anchor, direction=direction, target_pct=target_pct),
                    entry_offset_bars=delay,
                    entry_vs_breakout_pct=entry_vs_breakout,
                )

        if source_paths:
            symbol = str(event.get("symbol") or "").upper()
            source_path = source_paths.get(symbol)
            breakout_idx = event.get("breakout_idx")
            if source_path is None or pd.isna(breakout_idx):
                continue
            if symbol not in source_cache:
                source_cache[symbol] = _load_market_stats_symbol(source_path).reset_index(drop=True)
            df = source_cache[symbol]
            if df.empty:
                continue
            idx_map = {
                "flag_start_close_same_abs_base_046x": event.get("formation_start_idx"),
                "flag_end_close_same_abs_base_046x": event.get("formation_end_idx"),
                "pre_breakout_minus_3_close_same_abs_base_046x": int(breakout_idx) - 3,
                "pre_breakout_minus_5_close_same_abs_base_046x": int(breakout_idx) - 5,
            }
            for control_id, anchor_idx_value in idx_map.items():
                if control_id not in buckets or pd.isna(anchor_idx_value):
                    continue
                anchor_idx = int(anchor_idx_value)
                if anchor_idx < 0 or anchor_idx >= len(df):
                    continue
                anchor = float(df.iloc[anchor_idx]["close"])
                frame = df.iloc[anchor_idx + 1 : min(len(df), anchor_idx + 1 + horizon_bars)].copy()
                entry_offset = anchor_idx - int(breakout_idx)
                entry_vs_breakout = sign * (anchor / breakout_price - 1.0) * 100.0 if breakout_price > 0 else None
                _add_timing_result(
                    buckets[control_id],
                    _evaluate_price_frame(frame, anchor_price=anchor, direction=direction, target_pct=target_pct, target_abs=target_abs),
                    entry_offset_bars=entry_offset,
                    entry_vs_breakout_pct=entry_vs_breakout,
                )

    return _summarize_timing_buckets(profile_id, buckets)


def _timing_study_summary(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    by_id = {str(row.get("timing_id")): row for row in rows}
    actual = by_id.get("actual_breakout_base_046x", {})
    delayed_10 = by_id.get("delayed_10_close_reanchored_base_046x", {})
    pre_minus_3 = by_id.get("pre_breakout_minus_3_close_same_abs_base_046x", {})
    flag_end = by_id.get("flag_end_close_same_abs_base_046x", {})
    actual_tf = float(actual.get("target_first_rate") or 0.0)
    delayed_tf = float(delayed_10.get("target_first_rate") or 0.0)
    pre_tf = float(pre_minus_3.get("target_first_rate") or 0.0)
    flag_end_tf = float(flag_end.get("target_first_rate") or 0.0)
    return {
        "timing_actual_target_first_rate": actual.get("target_first_rate"),
        "timing_actual_failure_rate": actual.get("failure_rate"),
        "timing_delayed10_reanchored_target_first_rate": delayed_10.get("target_first_rate"),
        "timing_delayed10_reanchored_edge_vs_actual": delayed_10.get("edge_vs_actual_target_first"),
        "timing_prebreakout_minus3_target_first_rate": pre_minus_3.get("target_first_rate"),
        "timing_prebreakout_minus3_edge_vs_actual": pre_minus_3.get("edge_vs_actual_target_first"),
        "timing_flag_end_target_first_rate": flag_end.get("target_first_rate"),
        "timing_flag_end_edge_vs_actual": flag_end.get("edge_vs_actual_target_first"),
        "timing_breakout_specificity": (
            "breakout_timing_distinct"
            if actual_tf >= delayed_tf + 7.5 and actual_tf >= max(pre_tf, flag_end_tf) + 7.5
            else "trend_continuation_component_material"
        ),
    }


def _median_col(events: pd.DataFrame, col: str) -> Optional[float]:
    if events.empty or col not in events.columns:
        return None
    values = pd.to_numeric(events[col], errors="coerce").dropna()
    if values.empty:
        return None
    return round(float(values.median()), 2)


def _share(events: pd.DataFrame, mask: pd.Series) -> Optional[float]:
    if events.empty:
        return None
    return round(float(mask.mean()) * 100.0, 2)


def _three_layer_comparison_rows(events: pd.DataFrame, path: pd.DataFrame, *, profile_id: str) -> List[Dict[str, Any]]:
    if events.empty or "setup_score" not in events.columns:
        return []
    working = events.copy()
    setup = pd.to_numeric(working.get("setup_score"), errors="coerce").fillna(0.0)
    confirmation = pd.to_numeric(working.get("confirmation_score"), errors="coerce").fillna(0.0)
    follow = pd.to_numeric(working.get("followthrough_score"), errors="coerce").fillna(0.0)
    total = pd.to_numeric(working.get("bull_flag_score_total"), errors="coerce").fillna(0.0)
    branches = working.get("bull_flag_scanner_branch", pd.Series("", index=working.index)).astype(str)
    tiers = working.get("bull_flag_tier", pd.Series("", index=working.index)).astype(str)
    masks: List[tuple[str, str, pd.Series]] = [
        ("current_adaptive", "current selected adaptive scanner output", pd.Series(True, index=working.index)),
        ("setup_only_70", "setup_score >= 70", setup >= 70.0),
        ("confirmation_only_65", "confirmation_score >= 65", confirmation >= 65.0),
        ("followthrough_only_65", "followthrough_score >= 65; diagnostic post-breakout filter", follow >= 65.0),
        ("setup_confirmation", "setup_score >= 70 and confirmation_score >= 60", (setup >= 70.0) & (confirmation >= 60.0)),
        (
            "setup_confirmation_followthrough",
            "setup_score >= 70, confirmation_score >= 60, followthrough_score >= 65; diagnostic post-breakout filter",
            (setup >= 70.0) & (confirmation >= 60.0) & (follow >= 65.0),
        ),
        ("premium_tier", "bull_flag_tier == premium", tiers == "premium"),
        ("post_breakout_continuation_branch", "branch == post_breakout_continuation", branches == "post_breakout_continuation"),
        ("confirmed_breakout_branch", "branch == confirmed_breakout", branches == "confirmed_breakout"),
        ("early_setup_watch_branch", "branch == early_setup_watch; confirmed historical proxy for pre-breakout setup watch", branches == "early_setup_watch"),
    ]
    rows: List[Dict[str, Any]] = []
    for layer_id, description, mask in masks:
        subset = working[mask].copy()
        contract = _metric_contract(subset, path)
        rows.append(
            {
                "profile_id": profile_id,
                "layer_filter_id": layer_id,
                "description": description,
                "n": int(len(subset)),
                "retention_pct": round(len(subset) / max(1, len(working)) * 100.0, 2),
                "setup_score_median": _median_col(subset, "setup_score"),
                "confirmation_score_median": _median_col(subset, "confirmation_score"),
                "followthrough_score_median": _median_col(subset, "followthrough_score"),
                "bull_flag_score_median": _median_col(subset, "bull_flag_score_total"),
                "premium_share_pct": _share(subset, subset.get("bull_flag_tier", pd.Series("", index=subset.index)).astype(str) == "premium") if not subset.empty else None,
                **contract,
            }
        )
    return rows


def _three_layer_summary(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    by_id = {str(row.get("layer_filter_id")): row for row in rows}
    current = by_id.get("current_adaptive", {})
    confirmation_only = by_id.get("confirmation_only_65", {})
    setup_confirmation = by_id.get("setup_confirmation", {})
    combined = by_id.get("setup_confirmation_followthrough", {})
    post_branch = by_id.get("post_breakout_continuation_branch", {})
    current_tf = float(current.get("target_first_base_046x_rate") or 0.0)
    current_failure = float(current.get("failure_5pct_rate") or 100.0)
    confirmation_tf = float(confirmation_only.get("target_first_base_046x_rate") or 0.0)
    sc_tf = float(setup_confirmation.get("target_first_base_046x_rate") or 0.0)
    sc_failure = float(setup_confirmation.get("failure_5pct_rate") or 100.0)
    combined_tf = float(combined.get("target_first_base_046x_rate") or 0.0)
    post_tf = float(post_branch.get("target_first_base_046x_rate") or 0.0)
    sc_retention = float(setup_confirmation.get("retention_pct") or 0.0)
    return {
        "three_layer_confirmation_only_n": confirmation_only.get("n"),
        "three_layer_confirmation_only_retention_pct": confirmation_only.get("retention_pct"),
        "three_layer_confirmation_only_target_first": confirmation_only.get("target_first_base_046x_rate"),
        "three_layer_confirmation_only_failure": confirmation_only.get("failure_5pct_rate"),
        "three_layer_setup_confirmation_n": setup_confirmation.get("n"),
        "three_layer_setup_confirmation_retention_pct": setup_confirmation.get("retention_pct"),
        "three_layer_setup_confirmation_target_first": setup_confirmation.get("target_first_base_046x_rate"),
        "three_layer_setup_confirmation_failure": setup_confirmation.get("failure_5pct_rate"),
        "three_layer_setup_confirmation_gate_pass": bool(sc_retention >= 35.0 and sc_tf >= current_tf and sc_failure <= current_failure - 5.0),
        "three_layer_combined_n": combined.get("n"),
        "three_layer_combined_retention_pct": combined.get("retention_pct"),
        "three_layer_combined_target_first": combined.get("target_first_base_046x_rate"),
        "three_layer_combined_failure": combined.get("failure_5pct_rate"),
        "three_layer_combined_diagnostic_only": True,
        "three_layer_post_branch_n": post_branch.get("n"),
        "three_layer_post_branch_target_first": post_branch.get("target_first_base_046x_rate"),
        "three_layer_post_branch_diagnostic_only": True,
        "three_layer_uplift_confirmation_only_tf": round(confirmation_tf - current_tf, 2) if confirmation_only else None,
        "three_layer_uplift_setup_confirmation_tf": round(sc_tf - current_tf, 2) if setup_confirmation else None,
        "three_layer_uplift_combined_tf": round(combined_tf - current_tf, 2) if combined else None,
        "three_layer_uplift_post_branch_tf": round(post_tf - current_tf, 2) if post_branch else None,
    }


def _bull_flag_v2_release_gate(row: Mapping[str, Any], reference: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    failures: List[str] = []
    warnings: List[str] = []
    n = int(row.get("n") or 0)
    validation_n = int(row.get("validation_n") or 0)
    holdout_n = int(row.get("holdout_n") or 0)
    min_validation_holdout_n = min(validation_n, holdout_n)
    target_first = float(row.get("target_first_base_046x_rate") or 0.0)
    failure = float(row.get("failure_5pct_rate") or 100.0)
    mfe_mae_ratio = float(row.get("mfe_mae_median_ratio") or 0.0)
    alternate_fail_source = row.get("alternate_split_metric_fail_count")
    if alternate_fail_source is None or pd.isna(alternate_fail_source):
        alternate_fail_source = row.get("alternate_split_fail_count")
    alternate_fail = int(alternate_fail_source or 0)
    alternate_underpowered = int(row.get("alternate_split_underpowered_count") or 0)
    timing_specificity = str(row.get("timing_breakout_specificity") or "")
    reference_target_first = float((reference or {}).get("target_first_base_046x_rate") or target_first)
    reference_failure = float((reference or {}).get("failure_5pct_rate") or failure)
    setup_min = float(row.get("post_score_min_setup_score") or BULL_FLAG_V2_SETUP_MIN)
    confirmation_min = float(row.get("post_score_min_confirmation_score") or BULL_FLAG_V2_CONFIRMATION_MIN)
    if n < 50:
        failures.append("n_below_50")
    if min_validation_holdout_n < 10:
        failures.append("validation_holdout_n_below_10")
    if target_first < reference_target_first:
        failures.append("target_first_below_reference")
    if failure > 12.0:
        failures.append("failure_gt_12pct")
    if mfe_mae_ratio < 3.0:
        failures.append("mfe_mae_below_3")
    if alternate_fail > 1:
        failures.append("alternate_split_fail_count_gt_1")
    if alternate_underpowered:
        warnings.append("alternate_split_underpowered_cells")
    if timing_specificity == "breakout_timing_distinct":
        timing_note = "breakout timing appears distinct; still disclose continuation controls"
    else:
        timing_note = "continuation component is material; do not claim pure breakout timing edge"
    return {
        "bull_flag_v2_release_gate_pass": not failures,
        "bull_flag_v2_release_gate_failures": ",".join(failures),
        "bull_flag_v2_release_gate_warnings": ",".join(warnings),
        "bull_flag_v2_reference_profile_id": (reference or {}).get("profile_id"),
        "bull_flag_v2_reference_n": (reference or {}).get("n"),
        "bull_flag_v2_reference_hit": (reference or {}).get("target_hit_base_046x_rate"),
        "bull_flag_v2_reference_target_first": reference_target_first,
        "bull_flag_v2_reference_failure": reference_failure,
        "bull_flag_v2_reference_failure_reduction_pp": round(reference_failure - failure, 2),
        "bull_flag_v2_min_validation_holdout_n": min_validation_holdout_n,
        "bull_flag_v2_timing_note": timing_note,
        "scanner_entry_rule": f"setup_score >= {setup_min:g} and confirmation_score >= {confirmation_min:g}",
        "diagnostic_followthrough_rule": "followthrough_score is diagnostic-only and is not used for entry filtering",
        "classification": (
            "Bull Flag V2 investment-reference candidate"
            if not failures and not warnings
            else ("Bull Flag V2 watchlist-reference candidate" if not failures else "Bull Flag V2 provisional")
        ),
    }


def _is_bull_flag_v2_profile_id(profile_id: Any) -> bool:
    return str(profile_id) in BULL_FLAG_V2_VARIANTS


def select_bull_flag_v2_variant(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    variants = [dict(row) for row in rows if _is_bull_flag_v2_profile_id(row.get("profile_id"))]
    if not variants:
        return {
            "selected_v2_profile_id": None,
            "status": "no_bull_flag_v2_variant",
            "selection_basis": "no_v2_variants_available",
        }
    variant_priority = {
        BULL_FLAG_V2_BREAKOUT_QUALITY_PROFILE_ID: 4,
        BULL_FLAG_V2_SPLIT_STABLE_PROFILE_ID: 3,
        BULL_FLAG_V2_SETUP_QUALITY_PROFILE_ID: 2,
        BULL_FLAG_V2_BALANCED_PROFILE_ID: 2,
        BULL_FLAG_V2_RECALL_PROFILE_ID: 1,
        BULL_FLAG_V2_STRICT_PROFILE_ID: 0,
    }

    def key(row: Mapping[str, Any]) -> tuple:
        return (
            bool(row.get("bull_flag_v2_release_gate_pass")),
            not bool(str(row.get("bull_flag_v2_release_gate_warnings") or "").strip()),
            float(row.get("target_first_base_046x_rate") or 0.0),
            -float(row.get("failure_5pct_rate") or 100.0),
            float(row.get("mfe_mae_median_ratio") or 0.0),
            int(row.get("n") or 0),
            variant_priority.get(str(row.get("profile_id")), -1),
        )

    selected = max(variants, key=key)
    passing_count = sum(1 for row in variants if bool(row.get("bull_flag_v2_release_gate_pass")))
    return {
        "selected_v2_profile_id": selected.get("profile_id"),
        "selected_v2_classification": selected.get("classification"),
        "selected_v2_gate_pass": bool(selected.get("bull_flag_v2_release_gate_pass")),
        "passing_variant_count": passing_count,
        "variant_count": len(variants),
        "selection_basis": "release_gate_then_target_first_failure_mfe_mae_sample",
    }


def select_detector_profile(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    candidates = [dict(row) for row in rows if row.get("profile_id") != "detector_baseline"]
    passing = [row for row in candidates if bool(row.get("gates_pass"))]
    pool = passing if passing else candidates
    if not pool:
        return {}
    best = max(pool, key=lambda row: (float(row.get("localization_score") or 0.0), int(row.get("n") or 0)))
    return {
        "status": "selected_detector_profile" if passing else "no_detector_profile_passed_all_gates",
        "selection_basis": "full_rescan_detector_grid_with_validation_holdout_gates",
        "selected_profile_id": best.get("profile_id"),
        "selected_score": best.get("localization_score"),
        "selected_gates_pass": best.get("gates_pass"),
        "selected_overfit_flags": best.get("overfit_flags"),
        "selected_metrics": best,
    }


def select_profile(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    candidates = [dict(row) for row in rows if row.get("profile_id") != "baseline_all"]
    passing = [row for row in candidates if bool(row.get("gates_pass"))]
    pool = passing if passing else candidates
    if not pool:
        return {}
    best = max(pool, key=lambda row: (float(row.get("localization_score") or 0.0), int(row.get("n") or 0)))
    return {
        "status": "selected_localized_profile" if passing else "no_profile_passed_all_gates",
        "selection_basis": "validation_score_with_holdout_stability_and_overfit_gates",
        "selected_profile_id": best.get("profile_id"),
        "selected_score": best.get("localization_score"),
        "selected_gates_pass": best.get("gates_pass"),
        "selected_overfit_flags": best.get("overfit_flags"),
        "selected_metrics": best,
    }


def _profile_by_id(profiles: Sequence[Mapping[str, Any]], profile_id: str) -> Dict[str, Any]:
    for profile in profiles:
        if profile.get("profile_id") == profile_id:
            return dict(profile)
    return {}


def render_markdown(selection: Mapping[str, Any], baseline: Mapping[str, Any], selected_profile: Mapping[str, Any]) -> str:
    selected = selection.get("selected_metrics") if isinstance(selection.get("selected_metrics"), Mapping) else {}
    lines = [
        "# Bull Flag Localization Report",
        "",
        "Scope: available active Market Stats V1 series. This localizes scanner acceptance rules; it does not validate a trading system.",
        "",
        "## Selection",
        "",
        f"- Status: `{selection.get('status')}`",
        f"- Selected profile: `{selection.get('selected_profile_id')}`",
        f"- Score: `{selection.get('selected_score')}`",
        f"- Overfit flags: `{selection.get('selected_overfit_flags') or 'none'}`",
        "",
        "## Baseline vs Selected",
        "",
        "| Metric | Baseline | Selected |",
        "|---|---:|---:|",
    ]
    for key in (
        "n",
        "target_hit_rate",
        "target_hit_ci_low",
        "target_first_rate",
        "failure_rate",
        "mfe_mae_ratio",
        "validation_hit_rate",
        "validation_target_first_rate",
        "validation_failure_rate",
        "holdout_hit_rate",
        "holdout_target_first_rate",
        "holdout_failure_rate",
        "clean_share_pct",
    ):
        lines.append(f"| {key} | {baseline.get(key)} | {selected.get(key)} |")
    lines.extend(
        [
            "",
            "## Selected Event Filter",
            "",
            "```json",
            json.dumps(selected_profile, indent=2, ensure_ascii=False),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def render_detector_grid_markdown(selection: Mapping[str, Any], baseline: Mapping[str, Any], selected_profile: Mapping[str, Any]) -> str:
    selected = selection.get("selected_metrics") if isinstance(selection.get("selected_metrics"), Mapping) else {}
    lines = [
        "# Bull Flag Detector Grid Report",
        "",
        "Scope: full active-universe rescans across a small detector-config grid. This is scanner localization, not a trading-system test.",
        "",
        "## Selection",
        "",
        f"- Status: `{selection.get('status')}`",
        f"- Selected profile: `{selection.get('selected_profile_id')}`",
        f"- Score: `{selection.get('selected_score')}`",
        f"- Overfit flags: `{selection.get('selected_overfit_flags') or 'none'}`",
        "",
        "## Baseline vs Selected Detector",
        "",
        "| Metric | Baseline detector | Selected detector |",
        "|---|---:|---:|",
    ]
    for key in (
        "raw_detection_count",
        "n",
        "target_hit_rate",
        "target_hit_ci_low",
        "target_first_rate",
        "failure_rate",
        "mfe_mae_ratio",
        "validation_n",
        "validation_hit_rate",
        "validation_target_first_rate",
        "validation_failure_rate",
        "holdout_n",
        "holdout_hit_rate",
        "holdout_target_first_rate",
        "holdout_failure_rate",
        "clean_share_pct",
    ):
        lines.append(f"| {key} | {baseline.get(key)} | {selected.get(key)} |")
    lines.extend(
        [
            "",
            "## Selected Detector Profile",
            "",
            "```json",
            json.dumps(selected_profile, indent=2, ensure_ascii=False),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def select_adaptive_detector_profile(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    candidates = [dict(row) for row in rows if row.get("profile_id") != "detector_baseline"]
    passing = [row for row in candidates if bool(row.get("gates_pass"))]
    pool = passing if passing else candidates
    if not pool:
        return {}
    best = max(pool, key=lambda row: (float(row.get("localization_score") or 0.0), int(row.get("n") or 0)))
    return {
        "status": "selected_adaptive_detector_profile" if passing else "no_adaptive_profile_passed_all_gates",
        "selection_basis": "branched_detector_grid_with_context_filters_validation_holdout_gates",
        "selected_profile_id": best.get("profile_id"),
        "selected_score": best.get("localization_score"),
        "selected_gates_pass": best.get("gates_pass"),
        "selected_overfit_flags": best.get("overfit_flags"),
        "selected_metrics": best,
    }


def render_adaptive_grid_markdown(
    selection: Mapping[str, Any],
    baseline: Mapping[str, Any],
    selected_profile: Mapping[str, Any],
    *,
    branch_rows: Sequence[Mapping[str, Any]] = (),
    alternate_rows: Sequence[Mapping[str, Any]] = (),
    negative_control_rows: Sequence[Mapping[str, Any]] = (),
    timing_rows: Sequence[Mapping[str, Any]] = (),
    three_layer_rows: Sequence[Mapping[str, Any]] = (),
    v2_row: Mapping[str, Any] | None = None,
    v2_profile: Mapping[str, Any] | None = None,
    v2_variant_rows: Sequence[Mapping[str, Any]] = (),
    v2_selection: Mapping[str, Any] | None = None,
    v2_three_layer_rows: Sequence[Mapping[str, Any]] = (),
) -> str:
    selected = selection.get("selected_metrics") if isinstance(selection.get("selected_metrics"), Mapping) else {}
    lines = [
        "# Bull Flag Adaptive Detector Grid Report",
        "",
        "Scope: full active-universe rescans with context branches by regime, time, and liquidity. This is scanner localization, not a trading-system test.",
        "",
        "## Selection",
        "",
        f"- Status: `{selection.get('status')}`",
        f"- Selected profile: `{selection.get('selected_profile_id')}`",
        f"- Score: `{selection.get('selected_score')}`",
        f"- Overfit flags: `{selection.get('selected_overfit_flags') or 'none'}`",
        "",
        "## Baseline vs Selected Adaptive Scanner",
        "",
        "| Metric | Baseline detector | Selected adaptive |",
        "|---|---:|---:|",
    ]
    for key in (
        "raw_detection_count",
        "branch_candidate_count",
        "n",
        "target_hit_base_046x_rate",
        "target_hit_base_046x_ci_low",
        "target_first_base_046x_rate",
        "target_hit_legacy_1x_rate",
        "target_first_legacy_1x_rate",
        "failure_5pct_rate",
        "mfe_mae_median_ratio",
        "validation_n",
        "validation_hit_rate",
        "validation_target_first_rate",
        "validation_failure_rate",
        "holdout_n",
        "holdout_hit_rate",
        "holdout_target_first_rate",
        "holdout_failure_rate",
        "clean_share_pct",
        "adaptive_overlap_removed",
    ):
        lines.append(f"| {key} | {baseline.get(key)} | {selected.get(key)} |")
    lines.extend(
        [
            "",
            "## Metric Contract",
            "",
            "- `target_hit_base_046x_rate`: hit rate using the Bulkowski-adjusted 0.46x pole target.",
            "- `target_hit_legacy_1x_rate`: hit rate using the full pole-height benchmark; kept only as a stretch/legacy reference.",
            "- `target_first_base_046x_rate`: target 0.46x reached before adverse -5%; this is the main path-quality metric.",
            "",
            "## Selected Branch Attribution",
            "",
            "| Branch | N | Clean % | Hit 0.46x | Target-first 0.46x | Fail 5% | MFE/MAE |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in branch_rows:
        lines.append(
            "| {branch} | {n} | {clean} | {hit} | {race} | {fail} | {ratio} |".format(
                branch=row.get("branch_id"),
                n=row.get("n"),
                clean=row.get("clean_share_pct"),
                hit=row.get("target_hit_base_046x_rate"),
                race=row.get("target_first_base_046x_rate"),
                fail=row.get("failure_5pct_rate"),
                ratio=row.get("mfe_mae_median_ratio"),
            )
        )
    lines.extend(
        [
            "",
            "## Alternate Chronological Splits",
            "",
            "| Scheme | Split | N | Pass | Hit 0.46x | Target-first 0.46x | Fail 5% |",
            "|---|---|---:|---|---:|---:|---:|",
        ]
    )
    for row in alternate_rows:
        lines.append(
            "| {scheme} | {split} | {n} | {gate} | {hit} | {race} | {fail} |".format(
                scheme=row.get("scheme_id"),
                split=row.get("split"),
                n=row.get("n"),
                gate=row.get("gate_pass"),
                hit=row.get("target_hit_base_046x_rate"),
                race=row.get("target_first_base_046x_rate"),
                fail=row.get("failure_5pct_rate"),
            )
        )
    lines.extend(
        [
            "",
            "## Negative Controls",
            "",
            "| Control | N | Hit | Target-first | Fail 5% | MFE/MAE | TF edge vs actual |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in negative_control_rows:
        lines.append(
            "| {control} | {n} | {hit} | {race} | {fail} | {ratio} | {edge} |".format(
                control=row.get("control_id"),
                n=row.get("n"),
                hit=row.get("target_hit_rate"),
                race=row.get("target_first_rate"),
                fail=row.get("failure_rate"),
                ratio=row.get("mfe_mae_ratio"),
                edge=row.get("edge_vs_actual_target_first"),
            )
        )
    lines.extend(
        [
            "",
            "## Breakout Timing vs Trend Continuation",
            "",
            "This section compares the confirmed breakout entry against delayed entries and pre-breakout trend/setup controls. If delayed or pre-breakout controls remain close to actual, the Bull Flag edge is partly continuation-driven rather than purely breakout-timing-specific.",
            "",
            "| Timing test | Target policy | N | Entry offset | Entry vs breakout % | Hit | Target-first | Fail 5% | MFE/MAE | TF edge vs actual |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in timing_rows:
        lines.append(
            "| {timing} | {target_policy} | {n} | {offset} | {slip} | {hit} | {race} | {fail} | {ratio} | {edge} |".format(
                timing=row.get("timing_id"),
                target_policy=row.get("target_policy"),
                n=row.get("n"),
                offset=row.get("median_entry_offset_bars"),
                slip=row.get("median_entry_vs_breakout_pct"),
                hit=row.get("target_hit_rate"),
                race=row.get("target_first_rate"),
                fail=row.get("failure_rate"),
                ratio=row.get("mfe_mae_ratio"),
                edge=row.get("edge_vs_actual_target_first"),
            )
        )
    lines.extend(
        [
            "",
            "## Three-Layer Scanner Logic",
            "",
            "Scores separate the Bull Flag lifecycle into setup quality before breakout, confirmation quality at breakout, and follow-through quality after breakout. Follow-through filters are diagnostic because they use post-breakout information.",
            "",
            "| Layer filter | N | Retention % | Setup med | Confirm med | Follow med | Total med | Hit 0.46x | Target-first 0.46x | Fail 5% |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in three_layer_rows:
        lines.append(
            "| {layer} | {n} | {retention} | {setup} | {confirm} | {follow} | {total} | {hit} | {race} | {fail} |".format(
                layer=row.get("layer_filter_id"),
                n=row.get("n"),
                retention=row.get("retention_pct"),
                setup=row.get("setup_score_median"),
                confirm=row.get("confirmation_score_median"),
                follow=row.get("followthrough_score_median"),
                total=row.get("bull_flag_score_median"),
                hit=row.get("target_hit_base_046x_rate"),
                race=row.get("target_first_base_046x_rate"),
                fail=row.get("failure_5pct_rate"),
            )
        )
    v2 = dict(v2_row or {})
    if v2:
        v2_selection = dict(v2_selection or {})
        lines.extend(
            [
                "",
                "## Bull Flag V2 Canonical Rule Decision",
                "",
                f"- Selected V2 profile: `{v2_selection.get('selected_v2_profile_id') or v2.get('profile_id')}`",
                f"- Profile: `{v2.get('profile_id')}`",
                f"- Entry rule: `{v2.get('scanner_entry_rule')}`",
                f"- Diagnostic rule: `{v2.get('diagnostic_followthrough_rule')}`",
                f"- Release gate: `{v2.get('bull_flag_v2_release_gate_pass')}`",
                f"- Gate failures: `{v2.get('bull_flag_v2_release_gate_failures') or 'none'}`",
                f"- Gate warnings: `{v2.get('bull_flag_v2_release_gate_warnings') or 'none'}`",
                f"- Classification: `{v2.get('classification')}`",
                f"- Timing note: {v2.get('bull_flag_v2_timing_note')}",
                "",
                "### Bull Flag V2 Variant Grid",
                "",
                "| Variant | N | Validation/Holdout min N | Hit 0.46x | Target-first 0.46x | Fail 5% | MFE/MAE | Gate | Failures | Warnings |",
                "|---|---:|---:|---:|---:|---:|---:|---|---|---|",
            ]
        )
        for row in v2_variant_rows:
            lines.append(
                "| {profile} | {n} | {vh} | {hit} | {race} | {fail} | {ratio} | {gate} | {failures} | {warnings} |".format(
                    profile=row.get("profile_id"),
                    n=row.get("n"),
                    vh=row.get("bull_flag_v2_min_validation_holdout_n"),
                    hit=row.get("target_hit_base_046x_rate"),
                    race=row.get("target_first_base_046x_rate"),
                    fail=row.get("failure_5pct_rate"),
                    ratio=row.get("mfe_mae_median_ratio"),
                    gate=row.get("bull_flag_v2_release_gate_pass"),
                    failures=row.get("bull_flag_v2_release_gate_failures") or "none",
                    warnings=row.get("bull_flag_v2_release_gate_warnings") or "none",
                )
            )
        lines.extend(
            [
                "",
                "| Metric | Adaptive reference | Bull Flag V2 |",
                "|---|---:|---:|",
                f"| N | {v2.get('bull_flag_v2_reference_n')} | {v2.get('n')} |",
                f"| Retention vs baseline | 100.0 | {v2.get('sample_retention_pct')} |",
                f"| Hit 0.46x | {v2.get('bull_flag_v2_reference_hit')} | {v2.get('target_hit_base_046x_rate')} |",
                f"| Target-first 0.46x | {v2.get('bull_flag_v2_reference_target_first')} | {v2.get('target_first_base_046x_rate')} |",
                f"| Fail 5% | {v2.get('bull_flag_v2_reference_failure')} | {v2.get('failure_5pct_rate')} |",
                "",
                "### Bull Flag V2 Layer Filters",
                "",
                "| Layer filter | N | Retention % | Hit 0.46x | Target-first 0.46x | Fail 5% |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for row in v2_three_layer_rows:
            lines.append(
                "| {layer} | {n} | {retention} | {hit} | {race} | {fail} |".format(
                    layer=row.get("layer_filter_id"),
                    n=row.get("n"),
                    retention=row.get("retention_pct"),
                    hit=row.get("target_hit_base_046x_rate"),
                    race=row.get("target_first_base_046x_rate"),
                    fail=row.get("failure_5pct_rate"),
                )
            )
    lines.extend(
        [
            "",
            "## Selected Adaptive Profile",
            "",
            "```json",
            json.dumps(selected_profile, indent=2, ensure_ascii=False),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def render_bull_flag_v2_monograph_draft(
    v2_row: Mapping[str, Any],
    reference_row: Mapping[str, Any],
    v2_profile: Mapping[str, Any],
    *,
    variant_rows: Sequence[Mapping[str, Any]] = (),
    v2_selection: Mapping[str, Any] | None = None,
    alternate_rows: Sequence[Mapping[str, Any]] = (),
    timing_rows: Sequence[Mapping[str, Any]] = (),
    three_layer_rows: Sequence[Mapping[str, Any]] = (),
) -> str:
    v2_selection = dict(v2_selection or {})
    lines = [
        "# Bull Flag V2 Monograph Draft",
        "",
        "Status: provisional canonical scanner rule for the Bull Flag pilot. This is an investment-reference research artifact, not a trading system.",
        "",
        "## Scanner Rule Decision",
        "",
        f"- Selected profile: `{v2_selection.get('selected_v2_profile_id') or v2_row.get('profile_id')}`",
        f"- Profile: `{v2_row.get('profile_id')}`",
        f"- Entry rule: `{v2_row.get('scanner_entry_rule')}`",
        f"- Follow-through: `{v2_row.get('diagnostic_followthrough_rule')}`",
        f"- Release gate pass: `{v2_row.get('bull_flag_v2_release_gate_pass')}`",
        f"- Gate failures: `{v2_row.get('bull_flag_v2_release_gate_failures') or 'none'}`",
        f"- Gate warnings: `{v2_row.get('bull_flag_v2_release_gate_warnings') or 'none'}`",
        f"- Classification: `{v2_row.get('classification')}`",
        "",
        "## Reference Comparison",
        "",
        "| Metric | Adaptive reference | Bull Flag V2 |",
        "|---|---:|---:|",
        f"| N | {reference_row.get('n')} | {v2_row.get('n')} |",
        f"| Target hit 0.46x | {reference_row.get('target_hit_base_046x_rate')} | {v2_row.get('target_hit_base_046x_rate')} |",
        f"| Target-first 0.46x | {reference_row.get('target_first_base_046x_rate')} | {v2_row.get('target_first_base_046x_rate')} |",
        f"| Failure 5% | {reference_row.get('failure_5pct_rate')} | {v2_row.get('failure_5pct_rate')} |",
        f"| MFE/MAE median ratio | {reference_row.get('mfe_mae_median_ratio')} | {v2_row.get('mfe_mae_median_ratio')} |",
        "",
        "## Variant Grid",
        "",
        "| Variant | Entry rule | N | Validation/Holdout min N | Hit 0.46x | Target-first 0.46x | Fail 5% | MFE/MAE | Gate | Failures | Warnings |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---|---|",
    ]
    for row in variant_rows:
        lines.append(
            "| {profile} | `{rule}` | {n} | {vh} | {hit} | {race} | {fail} | {ratio} | {gate} | {failures} | {warnings} |".format(
                profile=row.get("profile_id"),
                rule=row.get("scanner_entry_rule"),
                n=row.get("n"),
                vh=row.get("bull_flag_v2_min_validation_holdout_n"),
                hit=row.get("target_hit_base_046x_rate"),
                race=row.get("target_first_base_046x_rate"),
                fail=row.get("failure_5pct_rate"),
                ratio=row.get("mfe_mae_median_ratio"),
                gate=row.get("bull_flag_v2_release_gate_pass"),
                failures=row.get("bull_flag_v2_release_gate_failures") or "none",
                warnings=row.get("bull_flag_v2_release_gate_warnings") or "none",
            )
        )
    lines.extend(
        [
        "",
        "## Three-Layer Interpretation",
        "",
        "Setup and confirmation are allowed to define the scanner entry rule. Follow-through is only a post-breakout diagnostic layer because it uses future bars after the confirmation event.",
        "",
        "| Layer filter | N | Retention % | Target-first 0.46x | Fail 5% |",
        "|---|---:|---:|---:|---:|",
    ]
    )
    for row in three_layer_rows:
        lines.append(
            "| {layer} | {n} | {retention} | {race} | {fail} |".format(
                layer=row.get("layer_filter_id"),
                n=row.get("n"),
                retention=row.get("retention_pct"),
                race=row.get("target_first_base_046x_rate"),
                fail=row.get("failure_5pct_rate"),
            )
        )
    lines.extend(
        [
            "",
            "## Chronological Robustness",
            "",
            "| Scheme | Split | N | Pass | Target-first 0.46x | Fail 5% |",
            "|---|---|---:|---|---:|---:|",
        ]
    )
    for row in alternate_rows:
        lines.append(
            "| {scheme} | {split} | {n} | {gate} | {race} | {fail} |".format(
                scheme=row.get("scheme_id"),
                split=row.get("split"),
                n=row.get("n"),
                gate=row.get("gate_pass"),
                race=row.get("target_first_base_046x_rate"),
                fail=row.get("failure_5pct_rate"),
            )
        )
    lines.extend(
        [
            "",
            "## Timing Caveat",
            "",
            f"- Timing classification: `{v2_row.get('timing_breakout_specificity')}`",
            f"- Timing note: {v2_row.get('bull_flag_v2_timing_note')}",
            "",
            "| Timing test | N | Target-first | Fail 5% | Edge vs actual TF |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in timing_rows:
        lines.append(
            "| {timing} | {n} | {race} | {fail} | {edge} |".format(
                timing=row.get("timing_id"),
                n=row.get("n"),
                race=row.get("target_first_rate"),
                fail=row.get("failure_rate"),
                edge=row.get("edge_vs_actual_target_first"),
            )
        )
    lines.extend(
        [
            "",
            "## Profile Config",
            "",
            "```json",
            json.dumps(v2_profile, indent=2, ensure_ascii=False, default=str),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def run_localization(
    *,
    artifact_dir: Path = DEFAULT_BULL_FLAGS_DIR,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts = load_baseline_events(artifact_dir)
    if artifacts.events.empty:
        raise RuntimeError(f"missing baseline Bull Flag events at {artifact_dir / 'events.csv'}")
    baseline_n = int(len(artifacts.events))
    profiles = candidate_profiles()
    rows = [evaluate_profile(profile, artifacts, baseline_n=baseline_n) for profile in profiles]
    selection = select_profile(rows)
    baseline_row = next((row for row in rows if row.get("profile_id") == "baseline_all"), {})
    selected_profile = _profile_by_id(profiles, str(selection.get("selected_profile_id") or ""))
    selected_profile["localized_from_artifact_dir"] = str(artifact_dir)
    selected_profile["detector_config_basis"] = "baseline_flag_detector_with_local_event_acceptance_profile"
    paths = {
        "baseline_stats": out_dir / "baseline_stats.json",
        "detector_config": out_dir / "bull_flag_detector_config.json",
        "parameter_sweep": out_dir / "parameter_sweep.csv",
        "selection": out_dir / "localized_rule_selection.json",
        "selected_filter": out_dir / "selected_event_filter_config.json",
        "markdown": out_dir / "localization_report.md",
    }
    paths["baseline_stats"].write_text(json.dumps(baseline_row, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    paths["detector_config"].write_text(json.dumps(FlagDetectorConfig().to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    pd.DataFrame(rows).sort_values(["gates_pass", "localization_score", "n"], ascending=[False, False, False]).to_csv(paths["parameter_sweep"], index=False)
    paths["selection"].write_text(json.dumps(selection, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    paths["selected_filter"].write_text(json.dumps(selected_profile, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    paths["markdown"].write_text(render_markdown(selection, baseline_row, selected_profile), encoding="utf-8")
    return paths


def run_detector_grid(
    *,
    source_dir: Path,
    out_dir: Path = DEFAULT_DETECTOR_GRID_OUT_DIR,
    market_stats_json: Optional[Path] = DEFAULT_MARKET_STATS_JSON,
    index_db: Path = DEFAULT_INDEX_DB,
    index_symbol: str = DEFAULT_INDEX_SYMBOL,
    limit_symbols: Optional[int] = None,
    limit_profiles: Optional[int] = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    baseline_artifacts = load_baseline_events(DEFAULT_BULL_FLAGS_DIR)
    baseline_n = int(len(baseline_artifacts.events)) if not baseline_artifacts.events.empty else 1
    profiles = detector_config_profiles()
    if limit_profiles is not None:
        profiles = profiles[: int(limit_profiles)]
    rows: List[Dict[str, Any]] = []
    scans_dir = out_dir / "scans"
    scans_dir.mkdir(parents=True, exist_ok=True)
    for idx, profile in enumerate(profiles, start=1):
        print(f"[{idx}/{len(profiles)}] scanning {profile['profile_id']}", flush=True)
        scan, events_rows, path_rows = _scan_detector_profile(
            profile,
            source_dir=source_dir,
            market_stats_json=market_stats_json,
            index_db=index_db,
            index_symbol=index_symbol,
            limit_symbols=limit_symbols,
        )
        events = pd.DataFrame(events_rows)
        path = pd.DataFrame(path_rows)
        if not events.empty and "event_id" not in events.columns and "detection_id" in events.columns:
            events["event_id"] = events["detection_id"]
        row = _evaluate_events(
            events,
            path,
            profile=profile,
            baseline_n=baseline_n,
            raw_n=int(scan.get("raw_bull_flag_detection_count") or 0),
        )
        rows.append(row)
        profile_dir = scans_dir / str(profile["profile_id"])
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "profile.json").write_text(json.dumps(profile, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        events.to_csv(profile_dir / "events.csv", index=False)
        path.to_csv(profile_dir / "post_breakout_path.csv", index=False)
        (profile_dir / "scan_summary.json").write_text(
            json.dumps(
                {
                    "profile_id": profile.get("profile_id"),
                    "raw_bull_flag_detection_count": scan.get("raw_bull_flag_detection_count"),
                    "kept_detection_count": len(events_rows),
                    "event_filter_report": scan.get("event_filter_report"),
                    "metrics": row,
                },
                indent=2,
                ensure_ascii=False,
                default=str,
            )
            + "\n",
            encoding="utf-8",
        )
    selection = select_detector_profile(rows)
    baseline_row = next((row for row in rows if row.get("profile_id") == "detector_baseline"), {})
    selected_profile = _profile_by_id(profiles, str(selection.get("selected_profile_id") or ""))
    paths = {
        "grid_csv": out_dir / "detector_grid.csv",
        "selection": out_dir / "detector_grid_selection.json",
        "selected_detector_config": out_dir / "selected_detector_config.json",
        "selected_event_filter": out_dir / "selected_event_filter_config.json",
        "markdown": out_dir / "detector_grid_report.md",
    }
    pd.DataFrame(rows).sort_values(["gates_pass", "localization_score", "n"], ascending=[False, False, False]).to_csv(paths["grid_csv"], index=False)
    paths["selection"].write_text(json.dumps(selection, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    paths["selected_detector_config"].write_text(
        json.dumps((selected_profile.get("detector_config") if selected_profile else {}) or {}, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    paths["selected_event_filter"].write_text(
        json.dumps((selected_profile.get("event_filter_config") if selected_profile else {}) or {}, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    paths["markdown"].write_text(render_detector_grid_markdown(selection, baseline_row, selected_profile), encoding="utf-8")
    return paths


def run_adaptive_detector_grid(
    *,
    source_dir: Path,
    out_dir: Path = DEFAULT_ADAPTIVE_GRID_OUT_DIR,
    market_stats_json: Optional[Path] = DEFAULT_MARKET_STATS_JSON,
    index_db: Path = DEFAULT_INDEX_DB,
    index_symbol: str = DEFAULT_INDEX_SYMBOL,
    limit_symbols: Optional[int] = None,
    limit_profiles: Optional[int] = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    baseline_artifacts = load_baseline_events(DEFAULT_BULL_FLAGS_DIR)
    baseline_n = int(len(baseline_artifacts.events)) if not baseline_artifacts.events.empty else 1
    profiles = adaptive_detector_profiles()
    if limit_profiles is not None:
        profiles = profiles[: int(limit_profiles)]
    rows: List[Dict[str, Any]] = []
    branch_rows_all: List[Dict[str, Any]] = []
    alternate_rows_all: List[Dict[str, Any]] = []
    negative_control_rows_all: List[Dict[str, Any]] = []
    timing_rows_all: List[Dict[str, Any]] = []
    three_layer_rows_all: List[Dict[str, Any]] = []
    context_rows_all: List[Dict[str, Any]] = []
    scans_dir = out_dir / "scans"
    scans_dir.mkdir(parents=True, exist_ok=True)
    detector_cache: Dict[str, Dict[str, Any]] = {}
    for idx, profile in enumerate(profiles, start=1):
        print(f"[{idx}/{len(profiles)}] scanning adaptive {profile['profile_id']}", flush=True)
        scan, events_rows, path_rows = _scan_adaptive_profile(
            profile,
            source_dir=source_dir,
            market_stats_json=market_stats_json,
            index_db=index_db,
            index_symbol=index_symbol,
            limit_symbols=limit_symbols,
            cache=detector_cache,
        )
        events = pd.DataFrame(events_rows)
        path = pd.DataFrame(path_rows)
        if not events.empty and "event_id" not in events.columns and "detection_id" in events.columns:
            events["event_id"] = events["detection_id"]
        events = _apply_three_layer_scores(events, path, source_dir=source_dir)
        events, post_score_report = _apply_post_score_filter(events, profile)
        path = _filter_path_to_events(path, events)
        row = _evaluate_events(
            events,
            path,
            profile=profile,
            baseline_n=baseline_n,
            raw_n=int(scan.get("raw_bull_flag_detection_count") or 0),
        )
        overlap_report = scan.get("adaptive_overlap_report") if isinstance(scan.get("adaptive_overlap_report"), Mapping) else {}
        row.update(
            {
                "branch_count": len(profile.get("branches") or []),
                "branch_candidate_count": int(scan.get("branch_candidate_count") or 0),
                "adaptive_overlap_removed": overlap_report.get("removed_count"),
                "adaptive_overlap_kept_share_pct": overlap_report.get("kept_share_pct"),
                "post_score_filter_enabled": post_score_report.get("enabled"),
                "post_score_filter_removed": post_score_report.get("removed_count"),
                "post_score_filter_kept_share_pct": post_score_report.get("kept_share_pct"),
                "post_score_filter_id": (post_score_report.get("config") or {}).get("profile_id") if isinstance(post_score_report.get("config"), Mapping) else None,
                "post_score_min_setup_score": (post_score_report.get("config") or {}).get("min_setup_score") if isinstance(post_score_report.get("config"), Mapping) else None,
                "post_score_min_confirmation_score": (post_score_report.get("config") or {}).get("min_confirmation_score") if isinstance(post_score_report.get("config"), Mapping) else None,
                "post_score_use_followthrough_for_entry": (post_score_report.get("config") or {}).get("use_followthrough_for_entry") if isinstance(post_score_report.get("config"), Mapping) else None,
                "post_score_contextual_rule_count": post_score_report.get("contextual_rule_count"),
            }
        )
        branch_rows = _branch_attribution_rows(events, path, profile_id=str(profile.get("profile_id")))
        alternate_rows = _alternate_split_rows(events, path, profile_id=str(profile.get("profile_id")))
        negative_control_rows = _negative_control_rows(events, path, profile_id=str(profile.get("profile_id")))
        timing_rows = _breakout_timing_rows(events, path, profile_id=str(profile.get("profile_id")), source_dir=source_dir)
        three_layer_rows = _three_layer_comparison_rows(events, path, profile_id=str(profile.get("profile_id")))
        context_rows = _context_stability_rows(events, path, profile_id=str(profile.get("profile_id")))
        row.update(_alternate_split_summary(alternate_rows))
        row.update(_timing_study_summary(timing_rows))
        row.update(_three_layer_summary(three_layer_rows))
        row.update(_context_stability_summary(context_rows))
        flags = _overfit_flags(row)
        row["overfit_flags"] = ",".join(flags)
        row["gates_pass"] = not flags
        rows.append(row)
        branch_rows_all.extend(branch_rows)
        alternate_rows_all.extend(alternate_rows)
        negative_control_rows_all.extend(negative_control_rows)
        timing_rows_all.extend(timing_rows)
        three_layer_rows_all.extend(three_layer_rows)
        context_rows_all.extend(context_rows)
        profile_dir = scans_dir / str(profile["profile_id"])
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "profile.json").write_text(json.dumps(profile, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        events.to_csv(profile_dir / "events.csv", index=False)
        path.to_csv(profile_dir / "post_breakout_path.csv", index=False)
        pd.DataFrame(branch_rows).to_csv(profile_dir / "branch_attribution.csv", index=False)
        pd.DataFrame(alternate_rows).to_csv(profile_dir / "alternate_splits.csv", index=False)
        pd.DataFrame(negative_control_rows).to_csv(profile_dir / "negative_controls.csv", index=False)
        pd.DataFrame(timing_rows).to_csv(profile_dir / "breakout_timing_study.csv", index=False)
        pd.DataFrame(three_layer_rows).to_csv(profile_dir / "three_layer_comparison.csv", index=False)
        pd.DataFrame(context_rows).to_csv(profile_dir / "context_stability.csv", index=False)
        (profile_dir / "scan_summary.json").write_text(
            json.dumps(
                {
                    "profile_id": profile.get("profile_id"),
                    "raw_bull_flag_detection_count": scan.get("raw_bull_flag_detection_count"),
                    "branch_candidate_count": scan.get("branch_candidate_count"),
                    "adaptive_branches": scan.get("adaptive_branches"),
                    "adaptive_overlap_report": scan.get("adaptive_overlap_report"),
                    "post_score_filter_report": post_score_report,
                    "branch_attribution": branch_rows,
                    "alternate_splits": alternate_rows,
                    "negative_controls": negative_control_rows,
                    "breakout_timing_study": timing_rows,
                    "three_layer_comparison": three_layer_rows,
                    "context_stability": context_rows,
                    "metrics": row,
                },
                indent=2,
                ensure_ascii=False,
                default=str,
            )
            + "\n",
            encoding="utf-8",
        )
    reference_row = next((row for row in rows if row.get("profile_id") == "adaptive_2024_guard"), {})
    for row in rows:
        if _is_bull_flag_v2_profile_id(row.get("profile_id")):
            row.update(_bull_flag_v2_release_gate(row, reference_row))
    v2_selection = select_bull_flag_v2_variant(rows)
    selected_v2_profile_id = str(v2_selection.get("selected_v2_profile_id") or BULL_FLAG_V2_PROFILE_ID)
    selection = select_adaptive_detector_profile(rows)
    baseline_row = next((row for row in rows if row.get("profile_id") == "detector_baseline"), {})
    selected_profile = _profile_by_id(profiles, str(selection.get("selected_profile_id") or ""))
    selected_profile_id = str(selection.get("selected_profile_id") or "")
    v2_row = next((row for row in rows if row.get("profile_id") == selected_v2_profile_id), {})
    v2_profile = _profile_by_id(profiles, selected_v2_profile_id)
    v2_variant_rows = [row for row in rows if _is_bull_flag_v2_profile_id(row.get("profile_id"))]
    selected_branch_rows = [row for row in branch_rows_all if row.get("profile_id") == selected_profile_id]
    selected_alternate_rows = [row for row in alternate_rows_all if row.get("profile_id") == selected_profile_id]
    selected_negative_control_rows = [row for row in negative_control_rows_all if row.get("profile_id") == selected_profile_id]
    selected_timing_rows = [row for row in timing_rows_all if row.get("profile_id") == selected_profile_id]
    selected_three_layer_rows = [row for row in three_layer_rows_all if row.get("profile_id") == selected_profile_id]
    v2_alternate_rows = [row for row in alternate_rows_all if row.get("profile_id") == selected_v2_profile_id]
    v2_timing_rows = [row for row in timing_rows_all if row.get("profile_id") == selected_v2_profile_id]
    v2_three_layer_rows = [row for row in three_layer_rows_all if row.get("profile_id") == selected_v2_profile_id]
    paths = {
        "grid_csv": out_dir / "adaptive_detector_grid.csv",
        "selection": out_dir / "adaptive_detector_grid_selection.json",
        "selected_profile": out_dir / "selected_adaptive_profile.json",
        "v2_variants_csv": out_dir / "bull_flag_v2_variants.csv",
        "v2_release": out_dir / "bull_flag_v2_release_gate.json",
        "v2_monograph_draft": out_dir / "bull_flag_v2_monograph_draft.md",
        "branch_attribution_csv": out_dir / "adaptive_branch_attribution.csv",
        "alternate_splits_csv": out_dir / "adaptive_alternate_splits.csv",
        "negative_controls_csv": out_dir / "adaptive_negative_controls.csv",
        "breakout_timing_csv": out_dir / "adaptive_breakout_timing_study.csv",
        "three_layer_comparison_csv": out_dir / "adaptive_three_layer_comparison.csv",
        "context_stability_csv": out_dir / "adaptive_context_stability.csv",
        "markdown": out_dir / "adaptive_detector_grid_report.md",
    }
    pd.DataFrame(rows).sort_values(["gates_pass", "localization_score", "n"], ascending=[False, False, False]).to_csv(paths["grid_csv"], index=False)
    pd.DataFrame(branch_rows_all).to_csv(paths["branch_attribution_csv"], index=False)
    pd.DataFrame(alternate_rows_all).to_csv(paths["alternate_splits_csv"], index=False)
    pd.DataFrame(negative_control_rows_all).to_csv(paths["negative_controls_csv"], index=False)
    pd.DataFrame(timing_rows_all).to_csv(paths["breakout_timing_csv"], index=False)
    pd.DataFrame(three_layer_rows_all).to_csv(paths["three_layer_comparison_csv"], index=False)
    pd.DataFrame(context_rows_all).to_csv(paths["context_stability_csv"], index=False)
    pd.DataFrame(v2_variant_rows).sort_values(
        ["bull_flag_v2_release_gate_pass", "target_first_base_046x_rate", "failure_5pct_rate", "n"],
        ascending=[False, False, True, False],
    ).to_csv(paths["v2_variants_csv"], index=False)
    paths["selection"].write_text(json.dumps(selection, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    paths["selected_profile"].write_text(json.dumps(selected_profile, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    paths["v2_release"].write_text(
        json.dumps(
            {
                "selection": v2_selection,
                "selected_profile": v2_profile,
                "selected_metrics": v2_row,
                "reference_profile_id": reference_row.get("profile_id"),
                "reference_metrics": reference_row,
                "variants": v2_variant_rows,
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    paths["v2_monograph_draft"].write_text(
        render_bull_flag_v2_monograph_draft(
            v2_row,
            reference_row,
            v2_profile,
            variant_rows=v2_variant_rows,
            v2_selection=v2_selection,
            alternate_rows=v2_alternate_rows,
            timing_rows=v2_timing_rows,
            three_layer_rows=v2_three_layer_rows,
        ),
        encoding="utf-8",
    )
    paths["markdown"].write_text(
        render_adaptive_grid_markdown(
            selection,
            baseline_row,
            selected_profile,
            branch_rows=selected_branch_rows,
            alternate_rows=selected_alternate_rows,
            negative_control_rows=selected_negative_control_rows,
            timing_rows=selected_timing_rows,
            three_layer_rows=selected_three_layer_rows,
            v2_row=v2_row,
            v2_profile=v2_profile,
            v2_variant_rows=v2_variant_rows,
            v2_selection=v2_selection,
            v2_three_layer_rows=v2_three_layer_rows,
        ),
        encoding="utf-8",
    )
    return paths


__all__ = [
    "BULL_FLAG_V2_BALANCED_PROFILE_ID",
    "BULL_FLAG_V2_BREAKOUT_QUALITY_PROFILE_ID",
    "BULL_FLAG_V2_FOLLOWTHROUGH_DIAGNOSTIC_PROFILE_ID",
    "BULL_FLAG_V2_PROFILE_ID",
    "BULL_FLAG_V2_RECALL_PROFILE_ID",
    "BULL_FLAG_V2_SETUP_QUALITY_PROFILE_ID",
    "BULL_FLAG_V2_SPLIT_STABLE_PROFILE_ID",
    "BULL_FLAG_V2_STABILITY_PROFILE_ID",
    "BULL_FLAG_V2_STRICT_PROFILE_ID",
    "BULL_FLAG_V2_VARIANTS",
    "DEFAULT_ADAPTIVE_GRID_OUT_DIR",
    "DEFAULT_OUT_DIR",
    "adaptive_detector_profiles",
    "candidate_profiles",
    "detector_config_profiles",
    "evaluate_profile",
    "load_baseline_events",
    "run_adaptive_detector_grid",
    "run_detector_grid",
    "run_localization",
    "select_adaptive_detector_profile",
    "select_bull_flag_v2_variant",
    "select_detector_profile",
    "select_profile",
]
