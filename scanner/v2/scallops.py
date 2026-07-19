"""Scallop Family scanner.

Scallops are a rounded-turn family, not a flag/triangle box.  The source
chapters split the family by two ideas:

* normal scallops use two lips with a rounded recession between them (H-L-H);
* inverted scallops use a rounded cap between two lows (L-H-L).

This module keeps that family logic separate from earlier digitized scanners so
publication chapters and tradable tests can be grounded in the family-specific
shape rather than inherited from another pattern.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.ohlcv_normalizer import OHLCVNormalizer  # noqa: E402
from scanner.pivot_detector import Pivot, PivotDetector, PivotType  # noqa: E402
from scanner.research_support_analysis import (  # noqa: E402
    PatternArtifacts,
    build_target_calibration_decisions,
    target_sensitivity,
)
from scanner.run_bear_flag_db_source_parity_audit import (  # noqa: E402
    DEFAULT_DB,
    _db_meta,
    _enrich_events_from_series,
    _load_symbol_from_db,
    _path_rows_from_series,
    _symbols_in_db,
)
from scanner.v2.bull_flags_monograph import DEFAULT_MARKET_STATS_JSON, _load_active_symbols  # noqa: E402
from scanner.v2.flags_experiment import DEFAULT_INDEX_DB, DEFAULT_INDEX_SYMBOL, _write_csv, _write_json  # noqa: E402
from scanner.v2.source_data import attach_current_market_groups, classify_market_regimes  # noqa: E402


SCALLOPS_ASCENDING = "scallops_ascending"
SCALLOPS_ASCENDING_INVERTED = "scallops_ascending_inverted"
SCALLOPS_DESCENDING = "scallops_descending"
SCALLOPS_DESCENDING_INVERTED = "scallops_descending_inverted"
SCALLOP_PATTERNS = (
    SCALLOPS_ASCENDING,
    SCALLOPS_ASCENDING_INVERTED,
    SCALLOPS_DESCENDING,
    SCALLOPS_DESCENDING_INVERTED,
)
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/scallop_family")


@dataclass(frozen=True)
class ScallopConfig:
    width_min_bars: int = 14
    width_max_bars: int = 84
    height_min_pct: float = 5.0
    height_max_pct: float = 55.0
    lip_shift_min_pct: float = 2.5
    lip_shift_near_equal_pct: float = 1.5
    left_share_min_pct: float = 25.0
    left_share_max_pct: float = 78.0
    arc_excursion_min_pct: float = 35.0
    min_directional_ratio: float = 0.46
    smooth_turn_max_turns: int = 9
    prior_trend_lookback_bars: int = 80
    confirmation_search_bars: int = 45
    confirmation_threshold: float = 0.004
    breakout_cooldown_bars: int = 45
    max_events_per_symbol: int = 14

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]] = None) -> "ScallopConfig":
        if value is None:
            return cls()
        allowed = {field.name for field in fields(cls)}
        return cls(**{key: item for key, item in value.items() if key in allowed})

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_float(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _median(values: Sequence[Any]) -> Optional[float]:
    series = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna()
    return None if series.empty else round(float(series.median()), 2)


def _mean(values: Sequence[Any]) -> Optional[float]:
    series = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna()
    return None if series.empty else round(float(series.mean()), 2)


def _pct(numerator: int, denominator: int) -> Optional[float]:
    return None if denominator <= 0 else round(numerator / denominator * 100.0, 2)


def _rate(rows: Sequence[Mapping[str, Any]], key: str) -> Optional[float]:
    vals = [row.get(key) for row in rows if row.get(key) is not None]
    return None if not vals else _pct(sum(1 for val in vals if _truthy(val)), len(vals))


def _quantiles(values: Sequence[Any]) -> Dict[str, Optional[float]]:
    series = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna()
    points = [1, 5, 10, 25, 50, 75, 90, 95, 99]
    if series.empty:
        return {f"P{point}": None for point in points}
    return {f"P{point}": round(float(np.percentile(series, point)), 2) for point in points}


def _score_band(value: Optional[float], *, good: float, weak: float, reverse: bool = False, weight: float = 1.0) -> float:
    if value is None:
        return 0.0
    if reverse:
        if value <= good:
            return 100.0 * weight
        if value >= weak:
            return 0.0
        return (weak - value) / max(weak - good, 1e-9) * 100.0 * weight
    if value >= good:
        return 100.0 * weight
    if value <= weak:
        return 0.0
    return (value - weak) / max(good - weak, 1e-9) * 100.0 * weight


def _turn_count(series: Sequence[float]) -> int:
    values = np.asarray(series, dtype=float)
    if len(values) < 4:
        return 0
    diffs = np.diff(values)
    signs = np.sign(diffs[np.abs(diffs) > 1e-9])
    if len(signs) < 2:
        return 0
    return int(np.sum(signs[1:] != signs[:-1]))


def _directional_ratio(series: Sequence[float], *, positive: bool) -> Optional[float]:
    values = np.asarray(series, dtype=float)
    if len(values) < 2 or not np.isfinite(values).all():
        return None
    diffs = np.diff(values)
    diffs = diffs[np.abs(diffs) > 1e-9]
    if len(diffs) == 0:
        return None
    return float(np.mean(diffs > 0 if positive else diffs < 0))


def _prior_trend_pct(df: pd.DataFrame, start_idx: int, lookback: int) -> Optional[float]:
    left = max(0, int(start_idx) - int(lookback))
    if start_idx <= left:
        return None
    anchor = _safe_float(df.iloc[left].get("close"))
    start = _safe_float(df.iloc[int(start_idx)].get("close"))
    if anchor is None or start is None or anchor <= 0:
        return None
    return (start - anchor) / anchor * 100.0


class ScallopDetector:
    def __init__(self, pattern_key: str, config: Optional[ScallopConfig | Mapping[str, Any]] = None) -> None:
        if pattern_key not in SCALLOP_PATTERNS:
            raise ValueError(f"unsupported scallop pattern {pattern_key}")
        self.pattern_key = pattern_key
        self.config = config if isinstance(config, ScallopConfig) else ScallopConfig.from_mapping(config)

    def _base_sequence(self) -> tuple[PivotType, PivotType, PivotType]:
        if self.pattern_key in {SCALLOPS_ASCENDING, SCALLOPS_DESCENDING}:
            return (PivotType.HIGH, PivotType.LOW, PivotType.HIGH)
        return (PivotType.LOW, PivotType.HIGH, PivotType.LOW)

    def _shape_metrics(self, df: pd.DataFrame, p0: Pivot, p1: Pivot, p2: Pivot) -> Optional[dict[str, Any]]:
        i0, i1, i2 = int(p0.idx), int(p1.idx), int(p2.idx)
        if not (i0 < i1 < i2):
            return None
        width = i2 - i0 + 1
        if width < self.config.width_min_bars or width > self.config.width_max_bars:
            return None
        sequence = "HLH" if p0.type == PivotType.HIGH else "LHL"
        start_price = float(p0.price)
        mid_price = float(p1.price)
        end_price = float(p2.price)
        if min(start_price, mid_price, end_price) <= 0:
            return None
        high_boundary = max(start_price, mid_price, end_price)
        low_boundary = min(start_price, mid_price, end_price)
        height_pct = (high_boundary - low_boundary) / max((high_boundary + low_boundary) / 2.0, 1e-9) * 100.0
        if height_pct < self.config.height_min_pct or height_pct > self.config.height_max_pct:
            return None
        left_span = i1 - i0
        right_span = i2 - i1
        left_share = left_span / max(i2 - i0, 1) * 100.0
        if left_share < self.config.left_share_min_pct or left_share > self.config.left_share_max_pct:
            return None
        line_mid = start_price + (end_price - start_price) * (left_span / max(i2 - i0, 1))
        arc_excursion = abs(mid_price - line_mid) / max(high_boundary - low_boundary, 1e-9) * 100.0
        if arc_excursion < self.config.arc_excursion_min_pct:
            return None
        closes_left = df.iloc[i0 : i1 + 1]["close"].astype(float).to_list()
        closes_right = df.iloc[i1 : i2 + 1]["close"].astype(float).to_list()
        if sequence == "HLH":
            left_ratio = _directional_ratio(closes_left, positive=False)
            right_ratio = _directional_ratio(closes_right, positive=True)
        else:
            left_ratio = _directional_ratio(closes_left, positive=True)
            right_ratio = _directional_ratio(closes_right, positive=False)
        if left_ratio is not None and left_ratio < self.config.min_directional_ratio:
            return None
        if right_ratio is not None and right_ratio < self.config.min_directional_ratio:
            return None
        turn_count = _turn_count(df.iloc[i0 : i2 + 1]["close"].astype(float).to_list())
        if turn_count > self.config.smooth_turn_max_turns:
            return None
        lip_shift_pct = (end_price - start_price) / start_price * 100.0
        prior = _prior_trend_pct(df, i0, self.config.prior_trend_lookback_bars)
        return {
            "sequence_tag": sequence,
            "formation_start_idx": i0,
            "middle_idx": i1,
            "formation_end_idx": i2,
            "formation_start_date": str(pd.Timestamp(df.iloc[i0]["date"]).date()),
            "formation_end_date": str(pd.Timestamp(df.iloc[i2]["date"]).date()),
            "start_anchor_price": round(start_price, 4),
            "middle_anchor_price": round(mid_price, 4),
            "end_anchor_price": round(end_price, 4),
            "left_lip_price": round(start_price, 4),
            "right_lip_price": round(end_price, 4),
            "high_boundary_price": round(high_boundary, 4),
            "low_boundary_price": round(low_boundary, 4),
            "pattern_width_bars": int(width),
            "pattern_height_pct": round(float(height_pct), 2),
            "lip_shift_pct": round(float(lip_shift_pct), 2),
            "left_share_pct": round(float(left_share), 2),
            "arc_excursion_pct": round(float(arc_excursion), 2),
            "left_directional_ratio": round(float(left_ratio), 3) if left_ratio is not None else None,
            "right_directional_ratio": round(float(right_ratio), 3) if right_ratio is not None else None,
            "smooth_turn_count": int(turn_count),
            "prior_trend_pct": round(float(prior), 2) if prior is not None else None,
        }

    def _variant_matches(self, metrics: Mapping[str, Any]) -> bool:
        shift = float(metrics.get("lip_shift_pct") or 0.0)
        if self.pattern_key in {SCALLOPS_ASCENDING, SCALLOPS_ASCENDING_INVERTED}:
            return shift >= self.config.lip_shift_min_pct
        return shift <= -self.config.lip_shift_min_pct

    def _breakout_candidates(self, df: pd.DataFrame, metrics: Mapping[str, Any]) -> list[tuple[int, str, float]]:
        end_idx = int(metrics["formation_end_idx"])
        high_boundary = float(metrics["high_boundary_price"])
        low_boundary = float(metrics["low_boundary_price"])
        up_level = high_boundary * (1.0 + self.config.confirmation_threshold)
        down_level = low_boundary * (1.0 - self.config.confirmation_threshold)
        rows: list[tuple[int, str, float]] = []
        for idx in range(end_idx + 1, min(len(df), end_idx + 1 + self.config.confirmation_search_bars)):
            close = _safe_float(df.iloc[idx].get("close"))
            if close is None:
                continue
            if close > up_level:
                rows.append((idx, "up", float(close)))
            if close < down_level:
                rows.append((idx, "down", float(close)))
            if rows:
                break
        return rows

    def scan_window(self, df: pd.DataFrame, pivots: Sequence[Pivot]) -> Optional[dict[str, Any]]:
        if len(pivots) < 3:
            return None
        p0, p1, p2 = pivots[0], pivots[1], pivots[2]
        if (p0.type, p1.type, p2.type) != self._base_sequence():
            return None
        metrics = self._shape_metrics(df, p0, p1, p2)
        if not metrics or not self._variant_matches(metrics):
            return None
        candidates = self._breakout_candidates(df, metrics)
        if not candidates:
            return None
        breakout_idx, breakout_direction, breakout_price = candidates[0]
        if self.pattern_key == SCALLOPS_ASCENDING_INVERTED and breakout_direction != "up":
            return None
        if self.pattern_key == SCALLOPS_DESCENDING_INVERTED and breakout_direction != "down":
            return None
        high_boundary = float(metrics["high_boundary_price"])
        low_boundary = float(metrics["low_boundary_price"])
        height = high_boundary - low_boundary
        target_price = high_boundary + height if breakout_direction == "up" else low_boundary - height
        if target_price <= 0:
            return None
        target_dist_pct = abs(target_price - breakout_price) / breakout_price * 100.0
        if target_dist_pct <= 0 or target_dist_pct > 90:
            return None
        source_lip_band = "source_separated_lips"
        if abs(float(metrics["lip_shift_pct"])) <= self.config.lip_shift_near_equal_pct:
            source_lip_band = "near_equal_lips"
        score = 50.0
        score += _score_band(abs(float(metrics["lip_shift_pct"])), good=9.0, weak=self.config.lip_shift_min_pct, weight=0.16)
        score += _score_band(float(metrics["arc_excursion_pct"]), good=72.0, weak=self.config.arc_excursion_min_pct, weight=0.18)
        score += _score_band(abs(float(metrics["left_share_pct"]) - 52.0), good=8.0, weak=28.0, reverse=True, weight=0.12)
        score += _score_band(float(metrics["smooth_turn_count"]), good=4.0, weak=float(self.config.smooth_turn_max_turns), reverse=True, weight=0.10)
        prior = _safe_float(metrics.get("prior_trend_pct"))
        if prior is not None:
            expected_positive = self.pattern_key in {SCALLOPS_ASCENDING, SCALLOPS_ASCENDING_INVERTED}
            if (expected_positive and prior > 0) or ((not expected_positive) and prior < 0):
                score += 5.0
        if (breakout_direction == "up" and self.pattern_key in {SCALLOPS_ASCENDING, SCALLOPS_ASCENDING_INVERTED}) or (
            breakout_direction == "down" and self.pattern_key in {SCALLOPS_DESCENDING, SCALLOPS_DESCENDING_INVERTED}
        ):
            score += 5.0
        score = int(max(0, min(100, round(score))))
        out = {
            **metrics,
            "breakout_idx": int(breakout_idx),
            "breakout_date": str(pd.Timestamp(df.iloc[int(breakout_idx)]["date"]).date()),
            "breakout_direction": breakout_direction,
            "breakout_price": round(float(breakout_price), 4),
            "target_price": round(float(target_price), 4),
            "target_dist_pct": round(float(target_dist_pct), 2),
            "variant": self.pattern_key,
            "source_lip_band": source_lip_band,
            "scallop_shape": "rounded_recession" if self.pattern_key in {SCALLOPS_ASCENDING, SCALLOPS_DESCENDING} else "rounded_cap",
            "confirmation_clearance_pct": round(
                abs(float(breakout_price - (high_boundary if breakout_direction == "up" else low_boundary)))
                / max((high_boundary if breakout_direction == "up" else low_boundary), 1e-9)
                * 100.0,
                2,
            ),
            "pattern_quality_score": score,
            "pattern_quality_tier": "clean" if score >= 82 else ("usable" if score >= 66 else "loose"),
        }
        return out


def _evaluate_detection(df: pd.DataFrame, detection: Mapping[str, Any], *, lookahead: int = 120) -> Dict[str, Any]:
    breakout_idx = int(detection["breakout_idx"])
    breakout_price = float(detection["breakout_price"])
    target = float(detection["target_price"])
    direction = 1 if detection.get("breakout_direction") == "up" else -1
    future = df.iloc[breakout_idx + 1 : min(len(df), breakout_idx + 1 + lookahead)]
    b_exec = float(future.iloc[0]["open"]) if not future.empty else None
    if future.empty or breakout_price <= 0:
        return {
            "evaluated_bars": 0,
            "b_exec_price": round(b_exec, 4) if b_exec is not None else None,
            "mfe_pct": None,
            "mae_pct": None,
            "target_hit": None,
            "failure_5pct": None,
            "target_first_before_adverse_5pct": None,
            "days_to_target": None,
            "throwback_pullback_30d": None,
            "days_to_throwback_pullback": None,
        }
    if direction == 1:
        mfe = (float(future["high"].max()) - breakout_price) / breakout_price * 100.0
        mae = (breakout_price - float(future["low"].min())) / breakout_price * 100.0
        target_hit = bool(float(future["high"].max()) >= target)
        retest_rows = future.iloc[:30][future.iloc[:30]["low"] <= breakout_price * 1.005]
    else:
        mfe = (breakout_price - float(future["low"].min())) / breakout_price * 100.0
        mae = (float(future["high"].max()) - breakout_price) / breakout_price * 100.0
        target_hit = bool(float(future["low"].min()) <= target)
        retest_rows = future.iloc[:30][future.iloc[:30]["high"] >= breakout_price * 0.995]
    days_to_target: Optional[int] = None
    days_to_adverse_5: Optional[int] = None
    for offset, (_, row) in enumerate(future.iterrows(), start=1):
        high = float(row["high"])
        low = float(row["low"])
        if direction == 1:
            target_now = high >= target
            adverse_now = low <= breakout_price * 0.95
        else:
            target_now = low <= target
            adverse_now = high >= breakout_price * 1.05
        if days_to_target is None and target_now:
            days_to_target = offset
        if days_to_adverse_5 is None and adverse_now:
            days_to_adverse_5 = offset
    target_first = False if days_to_target is None else (True if days_to_adverse_5 is None else days_to_target < days_to_adverse_5)
    return {
        "evaluated_bars": int(len(future)),
        "b_exec_price": round(b_exec, 4) if b_exec is not None else None,
        "mfe_pct": round(float(mfe), 2),
        "mae_pct": round(float(mae), 2),
        "target_hit": target_hit,
        "failure_5pct": bool(float(mfe) < 5.0),
        "target_first_before_adverse_5pct": bool(target_first),
        "days_to_target": int(days_to_target) if days_to_target is not None else None,
        "throwback_pullback_30d": bool(not retest_rows.empty),
        "days_to_throwback_pullback": int(retest_rows.index[0] - breakout_idx) if not retest_rows.empty else None,
    }


def scan_symbol(
    df_raw: pd.DataFrame,
    *,
    pattern_key: str,
    max_events_per_symbol: Optional[int] = None,
    detector_config: Optional[ScallopConfig | Mapping[str, Any]] = None,
) -> Tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(df_raw) < 150:
        return [], {"rows": int(len(df_raw)), "skipped": "too_few_rows"}
    config = detector_config if isinstance(detector_config, ScallopConfig) else ScallopConfig.from_mapping(detector_config)
    max_events = int(max_events_per_symbol if max_events_per_symbol is not None else config.max_events_per_symbol)
    df, norm_stats = OHLCVNormalizer().normalize(df_raw)
    pivots = PivotDetector().detect_pivots(df, pivot_type="intermediate")
    detector = ScallopDetector(pattern_key, config)
    out: list[dict[str, Any]] = []
    used_breakouts: list[int] = []
    symbol = str(df.iloc[0]["symbol"])
    for i in range(len(pivots) - 2):
        candidate = detector.scan_window(df, pivots[i : i + 3])
        if not candidate:
            continue
        breakout_idx = int(candidate["breakout_idx"])
        if any(abs(breakout_idx - prev) <= config.breakout_cooldown_bars for prev in used_breakouts):
            continue
        record = {"symbol": symbol, "pattern_key": pattern_key, **candidate}
        record.update(_evaluate_detection(df, record))
        out.append(record)
        used_breakouts.append(breakout_idx)
        if len(out) >= max_events:
            break
    return out, {"rows": int(len(df)), "pivots": int(len(pivots)), "normalizer": norm_stats, "detector_config": config.to_dict()}


def _assign_publication_quality_tiers(rows: list[dict[str, Any]]) -> None:
    data_limited = {"short_path", "zero_and_stale", "zero_volume", "mixed_flag"}
    for row in rows:
        path_bucket = str(row.get("path_quality_bucket") or "unknown")
        tradability_bucket = str(row.get("tradability_quality_bucket") or "unknown")
        if path_bucket in data_limited or tradability_bucket == "impaired":
            row["publication_quality_score"] = 0.0
            row["publication_quality_tier"] = "data_limited"
            row["publication_quality_reasons"] = f"path:{path_bucket},tradability:{tradability_bucket}"
            continue
        score = 0.0
        score += _score_band(abs(float(row.get("lip_shift_pct") or 0.0)), good=9.0, weak=2.5, weight=0.20)
        score += _score_band(float(row.get("arc_excursion_pct") or 0.0), good=72.0, weak=35.0, weight=0.22)
        score += _score_band(abs(float(row.get("left_share_pct") or 0.0) - 52.0), good=8.0, weak=28.0, reverse=True, weight=0.12)
        score += _score_band(float(row.get("smooth_turn_count") or 99.0), good=4.0, weak=9.0, reverse=True, weight=0.12)
        score += 8.0 if path_bucket == "clean" else 3.0
        score += 5.0 if tradability_bucket == "clean" else (2.0 if tradability_bucket == "usable" else 0.0)
        if _truthy(row.get("target_first_before_adverse_5pct")):
            score += 5.0
        reasons: list[str] = []
        if str(row.get("source_lip_band")) != "source_separated_lips":
            reasons.append("lips_not_separated")
        if float(row.get("smooth_turn_count") or 0.0) > 7:
            reasons.append("rough_turn")
        if float(row.get("arc_excursion_pct") or 0.0) < 50.0:
            reasons.append("weak_rounded_shape")
        score = round(float(max(0.0, min(100.0, score))), 2)
        if score >= 70 and path_bucket == "clean" and str(row.get("source_lip_band")) == "source_separated_lips":
            tier = "premium"
        elif score >= 52:
            tier = "standard"
        else:
            tier = "loose"
        row["publication_quality_score"] = score
        row["publication_quality_tier"] = tier
        row["publication_quality_reasons"] = ",".join(sorted(set(reasons)))


def _group_stats(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    evals = [row for row in rows if row.get("mfe_pct") is not None]
    median_mfe = _median([row.get("mfe_pct") for row in evals])
    median_mae = _median([row.get("mae_pct") for row in evals])
    return {
        "detection_count": len(rows),
        "evaluated_count": len(evals),
        "n": len(rows),
        "median_mfe_pct": median_mfe,
        "median_mae_pct": median_mae,
        "mfe_mae_median_ratio": round(float(median_mfe) / max(float(median_mae), 1.0), 2) if median_mfe is not None and median_mae is not None else None,
        "average_mfe_pct": _mean([row.get("mfe_pct") for row in evals]),
        "average_mae_pct": _mean([row.get("mae_pct") for row in evals]),
        "target_hit_rate": _rate(evals, "target_hit"),
        "failure_5pct_rate": _rate(evals, "failure_5pct"),
        "target_first_before_adverse_5pct_rate": _rate(evals, "target_first_before_adverse_5pct"),
        "throwback_pullback_30d_rate": _rate(evals, "throwback_pullback_30d"),
        "median_target_dist_pct": _median([row.get("target_dist_pct") for row in evals]),
        "median_quality_score": _median([row.get("pattern_quality_score") for row in rows]),
        "median_lip_shift_pct": _median([row.get("lip_shift_pct") for row in rows]),
        "median_arc_excursion_pct": _median([row.get("arc_excursion_pct") for row in rows]),
        "median_smooth_turn_count": _median([row.get("smooth_turn_count") for row in rows]),
    }


def _group_table(rows: Sequence[Mapping[str, Any]], column: str, labels: Sequence[str]) -> Dict[str, Any]:
    return {label: _group_stats([row for row in rows if str(row.get(column) or "unknown") == label]) for label in labels}


def summarize(scan: Mapping[str, Any], *, pattern_key: str) -> Dict[str, Any]:
    rows = list(scan.get("detections") or [])
    evals = [row for row in rows if row.get("mfe_pct") is not None]
    return {
        "generated_at": _utc_now(),
        "pattern_key": pattern_key,
        "symbols_scanned": int(scan.get("symbols_scanned") or 0),
        "detection_count": len(rows),
        "evaluated_count": len(evals),
        "up_breakouts": sum(1 for row in rows if row.get("breakout_direction") == "up"),
        "down_breakouts": sum(1 for row in rows if row.get("breakout_direction") == "down"),
        **_group_stats(rows),
        "breakout_groups": {
            "all": _group_stats(rows),
            "up": _group_stats([row for row in rows if row.get("breakout_direction") == "up"]),
            "down": _group_stats([row for row in rows if row.get("breakout_direction") == "down"]),
        },
        "variant_table": {pattern_key: _group_stats(rows)},
        "quality_table": {tier: _group_stats([row for row in rows if row.get("pattern_quality_tier") == tier]) for tier in ("clean", "usable", "loose")},
        "publication_quality_table": {tier: _group_stats([row for row in rows if row.get("publication_quality_tier") == tier]) for tier in ("premium", "standard", "loose", "data_limited")},
        "regime_groups": _group_table(rows, "market_regime", ("bull", "bear", "unknown")),
        "market_group_table": _group_table(rows, "market_group", ("VN30", "VN100 ex VN30", "Outside VN100")),
        "liquidity_proxy_table": _group_table(rows, "liquidity_bucket", ("high", "mid", "low", "unknown")),
        "path_quality_audit": {
            "bucket_counts": dict(pd.Series([str(row.get("path_quality_bucket") or "unknown") for row in rows]).value_counts().sort_index()),
            "median_coverage_60d": _median([row.get("evaluated_bars") for row in rows]),
        },
        "symbol_concentration": {
            "symbols_with_events": len({str(row.get("symbol")) for row in rows if row.get("symbol")}),
            "top10_symbol_share_pct": round(float(pd.Series([str(row.get("symbol")) for row in rows if row.get("symbol")]).value_counts().head(10).sum()) / max(len(rows), 1) * 100.0, 2),
        },
        "quantile_metrics": {
            "fav_exc_pct": _quantiles([row.get("mfe_pct") for row in evals]),
            "adv_exc_pct": _quantiles([row.get("mae_pct") for row in evals]),
            "target_dist_pct": _quantiles([row.get("target_dist_pct") for row in evals]),
            "pattern_height_pct": _quantiles([row.get("pattern_height_pct") for row in rows]),
            "lip_shift_pct": _quantiles([row.get("lip_shift_pct") for row in rows]),
            "arc_excursion_pct": _quantiles([row.get("arc_excursion_pct") for row in rows]),
        },
        "experiment_note": "Scallop scanner uses source-grounded H-L-H or L-H-L rounded-turn geometry; final publication still requires example visual audit.",
    }


def _add_target_calibration(stats: Dict[str, Any], scan: Mapping[str, Any], path_rows: Sequence[Mapping[str, Any]], *, pattern_key: str) -> None:
    events = pd.DataFrame(list(scan.get("detections") or []))
    path = pd.DataFrame(list(path_rows))
    if events.empty:
        stats["target_family_sensitivity"] = []
        stats["target_calibration_decision"] = None
        return
    if "event_id" not in events.columns and "detection_id" in events.columns:
        events["event_id"] = events["detection_id"]
    sensitivity = target_sensitivity(PatternArtifacts(pattern_key, events, path), pattern_key, horizon_days=120)
    stats["target_family_sensitivity"] = sensitivity
    stats["target_calibration_decision"] = (build_target_calibration_decisions(sensitivity, family_labels=(pattern_key,)) or [None])[0]
    stats["target_family"] = {"half_height": 0.5, "three_quarter_height": 0.75, "source_full_height": 1.0}


EVENT_FIELDS = [
    "detection_id",
    "symbol",
    "variant",
    "market_group",
    "market_regime",
    "formation_start_date",
    "formation_end_date",
    "breakout_date",
    "breakout_direction",
    "breakout_price",
    "b_exec_price",
    "target_price",
    "target_dist_pct",
    "mfe_pct",
    "mae_pct",
    "target_hit",
    "failure_5pct",
    "target_first_before_adverse_5pct",
    "days_to_target",
    "pattern_quality_score",
    "pattern_quality_tier",
    "publication_quality_score",
    "publication_quality_tier",
    "publication_quality_reasons",
    "pattern_width_bars",
    "pattern_height_pct",
    "prior_trend_pct",
    "sequence_tag",
    "scallop_shape",
    "lip_shift_pct",
    "source_lip_band",
    "arc_excursion_pct",
    "left_share_pct",
    "left_directional_ratio",
    "right_directional_ratio",
    "smooth_turn_count",
    "left_lip_price",
    "right_lip_price",
    "high_boundary_price",
    "low_boundary_price",
    "confirmation_clearance_pct",
    "evaluated_bars",
    "is_primary_event_60d",
    "liquidity_bucket",
    "path_quality_bucket",
    "tradability_quality_bucket",
    "tradability_quality_score",
    "missing_bar_rate_60d",
    "zero_volume_rate_60d",
    "price_limit_proxy_rate_60d",
]


def scan_scallops_db(
    *,
    pattern_key: str,
    db_path: Path,
    out_dir: Path,
    allowed_symbols: Optional[Sequence[str]] = None,
    detector_config: Optional[Mapping[str, Any]] = None,
    limit_symbols: Optional[int] = None,
    index_db: Path = DEFAULT_INDEX_DB,
    index_symbol: str = DEFAULT_INDEX_SYMBOL,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    config = ScallopConfig.from_mapping(detector_config)
    symbols = _symbols_in_db(db_path, allowed_symbols)
    if limit_symbols is not None:
        symbols = symbols[: int(limit_symbols)]
    detections: list[dict[str, Any]] = []
    symbol_stats: list[dict[str, Any]] = []
    series_by_symbol: dict[str, pd.DataFrame] = {}
    conn = sqlite3.connect(str(db_path))
    try:
        for symbol in symbols:
            try:
                frame = _load_symbol_from_db(conn, symbol)
                rows, stats = scan_symbol(frame, pattern_key=pattern_key, detector_config=config)
                if rows:
                    series_by_symbol[symbol] = frame
                detections.extend(rows)
                symbol_stats.append({"symbol": symbol, "detections": len(rows), **stats})
            except Exception as exc:
                symbol_stats.append({"symbol": symbol, "detections": 0, "error": str(exc)})
    finally:
        conn.close()
    for i, row in enumerate(detections):
        row["detection_id"] = f"{pattern_key}:{i + 1:06d}"
    detections, regime_meta = classify_market_regimes(detections, index_db=index_db, index_symbol=index_symbol)
    market_group_meta = attach_current_market_groups(detections)
    scan: dict[str, Any] = {
        "generated_at": _utc_now(),
        "source": "Market Cache latest.sqlite stock_price_history",
        "db_path": str(db_path),
        "pattern_key": pattern_key,
        "symbols_scanned": len(symbols),
        "detections": detections,
        "symbol_stats": symbol_stats,
        "regime": regime_meta,
        "market_group": market_group_meta,
        "detector_config": config.to_dict(),
    }
    _enrich_events_from_series(scan, series_by_symbol, corporate_db=index_db)
    _assign_publication_quality_tiers(scan["detections"])
    path_rows = _path_rows_from_series(scan, series_by_symbol, horizon_bars=120)
    stats = summarize(scan, pattern_key=pattern_key)
    stats["source"] = scan["source"]
    stats["db_source_meta"] = _db_meta(db_path)
    stats["detector_config"] = config.to_dict()
    _add_target_calibration(stats, scan, path_rows, pattern_key=pattern_key)
    paths = {
        "detections": out_dir / "detections.json",
        "statistics": out_dir / "statistics.json",
        "events_csv": out_dir / "events.csv",
        "post_breakout_path_csv": out_dir / "post_breakout_path.csv",
    }
    _write_json(paths["detections"], scan)
    _write_json(paths["statistics"], stats)
    _write_csv(paths["events_csv"], scan.get("detections") or [], EVENT_FIELDS)
    _write_csv(
        paths["post_breakout_path_csv"],
        path_rows,
        ["event_id", "symbol", "trade_date", "bar_after_breakout", "open", "high", "low", "close", "volume", "signed_close_return_pct", "signed_high_excursion_pct", "signed_low_excursion_pct"],
    )
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Scallop Family scanners against Market Cache latest.sqlite.")
    parser.add_argument("--pattern", choices=[*SCALLOP_PATTERNS, "all"], default="all")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--market-stats-json", default=str(DEFAULT_MARKET_STATS_JSON))
    parser.add_argument("--limit-symbols", type=int, default=None)
    args = parser.parse_args()
    active_meta = _load_active_symbols(Path(args.market_stats_json) if args.market_stats_json else None)
    active_symbols = active_meta.get("active_symbols") if active_meta.get("enabled") else None
    patterns = list(SCALLOP_PATTERNS) if args.pattern == "all" else [args.pattern]
    outputs: dict[str, str] = {}
    for pattern_key in patterns:
        paths = scan_scallops_db(
            pattern_key=pattern_key,
            db_path=Path(args.db),
            out_dir=Path(args.out_dir) / pattern_key / "db_active",
            allowed_symbols=active_symbols,
            limit_symbols=args.limit_symbols,
        )
        outputs[pattern_key] = str(paths["events_csv"])
    print(json.dumps({"status": "PASS", "outputs": outputs}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
