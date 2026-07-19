"""Measured Move Family scanner.

Measured Moves are not flag/triangle-style breakout boxes.  The source
chapters define a three-stage swing: first leg, corrective phase, and second
leg.  This scanner therefore confirms the event at the start of the second
leg, then measures whether price reaches a projected target based on the first
leg.
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


MEASURED_MOVE_UP = "measured_move_up"
MEASURED_MOVE_DOWN = "measured_move_down"
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/measured_move_family")


@dataclass(frozen=True)
class MeasuredMoveConfig:
    prior_trend_lookback_bars: int = 70
    prior_trend_min_pct: float = 6.0
    first_leg_min_bars: int = 12
    first_leg_max_bars: int = 95
    first_leg_min_pct: float = 10.0
    first_leg_max_pct: float = 95.0
    correction_min_bars: int = 5
    correction_max_bars: int = 70
    retrace_min_pct: float = 30.0
    retrace_ideal_min_pct: float = 38.0
    retrace_ideal_max_pct: float = 62.0
    retrace_max_pct: float = 80.0
    leg_linearity_min_r2: float = 0.62
    correction_sawtooth_max_turns: int = 6
    confirmation_search_bars: int = 18
    confirmation_threshold: float = 0.006
    breakout_cooldown_bars: int = 45
    max_events_per_symbol: int = 12

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]] = None) -> "MeasuredMoveConfig":
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


def _linearity_r2(values: Sequence[float]) -> Optional[float]:
    if len(values) < 4:
        return None
    y = np.asarray(values, dtype=float)
    if not np.isfinite(y).all() or float(np.var(y)) <= 1e-12:
        return None
    x = np.arange(len(y), dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    pred = slope * x + intercept
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - float(np.mean(y))) ** 2))
    return max(0.0, min(1.0, 1.0 - ss_res / max(ss_tot, 1e-12)))


def _turn_count(series: Sequence[float]) -> int:
    values = np.asarray(series, dtype=float)
    if len(values) < 4:
        return 0
    diffs = np.diff(values)
    signs = np.sign(diffs[np.abs(diffs) > 1e-9])
    if len(signs) < 2:
        return 0
    return int(np.sum(signs[1:] != signs[:-1]))


class MeasuredMoveDetector:
    def __init__(self, pattern_key: str, config: Optional[MeasuredMoveConfig | Mapping[str, Any]] = None) -> None:
        if pattern_key not in {MEASURED_MOVE_UP, MEASURED_MOVE_DOWN}:
            raise ValueError(f"unsupported measured move pattern {pattern_key}")
        self.pattern_key = pattern_key
        self.config = config if isinstance(config, MeasuredMoveConfig) else MeasuredMoveConfig.from_mapping(config)

    @property
    def direction(self) -> int:
        return 1 if self.pattern_key == MEASURED_MOVE_UP else -1

    def _prior_trend_pct(self, df: pd.DataFrame, start_idx: int) -> Optional[float]:
        left = max(0, int(start_idx) - self.config.prior_trend_lookback_bars)
        if start_idx <= left:
            return None
        anchor = _safe_float(df.iloc[left].get("close"))
        start = _safe_float(df.iloc[int(start_idx)].get("close"))
        if anchor is None or start is None or anchor <= 0:
            return None
        return (start - anchor) / anchor * 100.0

    def _confirm_second_leg(self, df: pd.DataFrame, *, pivot_idx: int, pivot_price: float) -> Tuple[Optional[int], Optional[float], Optional[float]]:
        direction = self.direction
        for idx in range(pivot_idx + 1, min(len(df), pivot_idx + 1 + self.config.confirmation_search_bars)):
            close = _safe_float(df.iloc[idx].get("close"))
            if close is None:
                continue
            volume_ratio = _safe_float(df.iloc[idx].get("volume_ratio"))
            if direction == 1 and close > pivot_price * (1.0 + self.config.confirmation_threshold):
                return idx, close, volume_ratio
            if direction == -1 and close < pivot_price * (1.0 - self.config.confirmation_threshold):
                return idx, close, volume_ratio
        return None, None, None

    def scan_window(self, df: pd.DataFrame, pivots: Sequence[Pivot]) -> Optional[Dict[str, Any]]:
        if len(pivots) < 3:
            return None
        p0, p1, p2 = pivots[0], pivots[1], pivots[2]
        if self.direction == 1:
            expected = (PivotType.LOW, PivotType.HIGH, PivotType.LOW)
        else:
            expected = (PivotType.HIGH, PivotType.LOW, PivotType.HIGH)
        if (p0.type, p1.type, p2.type) != expected:
            return None
        if not (int(p0.idx) < int(p1.idx) < int(p2.idx)):
            return None

        start_idx, mid_idx, correction_end_idx = int(p0.idx), int(p1.idx), int(p2.idx)
        first_leg_bars = mid_idx - start_idx
        correction_bars = correction_end_idx - mid_idx
        if first_leg_bars < self.config.first_leg_min_bars or first_leg_bars > self.config.first_leg_max_bars:
            return None
        if correction_bars < self.config.correction_min_bars or correction_bars > self.config.correction_max_bars:
            return None

        start_price = float(p0.price)
        mid_price = float(p1.price)
        correction_price = float(p2.price)
        if min(start_price, mid_price, correction_price) <= 0:
            return None
        first_leg_abs = abs(mid_price - start_price)
        if first_leg_abs <= 0:
            return None
        first_leg_pct = first_leg_abs / start_price * 100.0
        if first_leg_pct < self.config.first_leg_min_pct or first_leg_pct > self.config.first_leg_max_pct:
            return None
        retrace_pct = abs(mid_price - correction_price) / first_leg_abs * 100.0
        if retrace_pct < self.config.retrace_min_pct or retrace_pct > self.config.retrace_max_pct:
            return None

        prior_trend = self._prior_trend_pct(df, start_idx)
        if prior_trend is None:
            return None
        if self.direction == 1 and prior_trend > -self.config.prior_trend_min_pct:
            return None
        if self.direction == -1 and prior_trend < self.config.prior_trend_min_pct:
            return None

        leg_prices = df.iloc[start_idx : mid_idx + 1]["close"].astype(float).to_list()
        correction_prices = df.iloc[mid_idx : correction_end_idx + 1]["close"].astype(float).to_list()
        leg_r2 = _linearity_r2(leg_prices)
        if leg_r2 is None or leg_r2 < self.config.leg_linearity_min_r2:
            return None
        correction_turns = _turn_count(correction_prices)
        if correction_turns > self.config.correction_sawtooth_max_turns:
            return None

        confirmation_idx, confirmation_price, volume_ratio = self._confirm_second_leg(
            df,
            pivot_idx=correction_end_idx,
            pivot_price=correction_price,
        )
        if confirmation_idx is None or confirmation_price is None:
            return None

        target_price = correction_price + first_leg_abs if self.direction == 1 else correction_price - first_leg_abs
        if target_price <= 0:
            return None
        target_dist_pct = abs(target_price - confirmation_price) / confirmation_price * 100.0
        if target_dist_pct <= 0 or target_dist_pct > 90:
            return None

        source_retrace_good = self.config.retrace_ideal_min_pct <= retrace_pct <= self.config.retrace_ideal_max_pct
        score = 52.0
        score += _score_band(first_leg_pct, good=24.0, weak=self.config.first_leg_min_pct, weight=0.12)
        score += _score_band(leg_r2, good=0.82, weak=self.config.leg_linearity_min_r2, weight=0.14)
        score += _score_band(abs(retrace_pct - 50.0), good=8.0, weak=28.0, reverse=True, weight=0.18)
        score += _score_band(correction_turns, good=2.0, weak=float(self.config.correction_sawtooth_max_turns), reverse=True, weight=0.10)
        score += _score_band(abs(float(prior_trend)), good=14.0, weak=self.config.prior_trend_min_pct, weight=0.08)
        if volume_ratio is not None and volume_ratio >= 1.05:
            score += 4.0
        score = int(max(0, min(100, round(score))))

        return {
            "formation_start_idx": start_idx,
            "formation_end_idx": correction_end_idx,
            "formation_start_date": str(pd.Timestamp(df.iloc[start_idx]["date"]).date()),
            "formation_end_date": str(pd.Timestamp(df.iloc[correction_end_idx]["date"]).date()),
            "first_leg_start_date": str(pd.Timestamp(df.iloc[start_idx]["date"]).date()),
            "first_leg_end_date": str(pd.Timestamp(df.iloc[mid_idx]["date"]).date()),
            "correction_end_date": str(pd.Timestamp(df.iloc[correction_end_idx]["date"]).date()),
            "breakout_idx": int(confirmation_idx),
            "breakout_date": str(pd.Timestamp(df.iloc[int(confirmation_idx)]["date"]).date()),
            "breakout_direction": "up" if self.direction == 1 else "down",
            "breakout_price": round(float(confirmation_price), 4),
            "target_price": round(float(target_price), 4),
            "pattern_width_bars": int(correction_end_idx - start_idx + 1),
            "pattern_height_pct": round(float(first_leg_pct), 2),
            "variant": self.pattern_key,
            "prior_trend_pct": round(float(prior_trend), 2),
            "first_leg_start_idx": start_idx,
            "first_leg_end_idx": mid_idx,
            "correction_end_idx": correction_end_idx,
            "first_leg_start_price": round(float(start_price), 4),
            "first_leg_end_price": round(float(mid_price), 4),
            "correction_end_price": round(float(correction_price), 4),
            "first_leg_abs": round(float(first_leg_abs), 4),
            "first_leg_pct": round(float(first_leg_pct), 2),
            "first_leg_bars": int(first_leg_bars),
            "correction_bars": int(correction_bars),
            "corrective_retrace_pct": round(float(retrace_pct), 2),
            "source_retrace_band": "ideal_38_62" if source_retrace_good else "usable_outside_ideal",
            "first_leg_linearity_r2": round(float(leg_r2), 3),
            "correction_turn_count": int(correction_turns),
            "confirmation_clearance_pct": round(abs(float(confirmation_price - correction_price)) / correction_price * 100.0, 2),
            "volume_confirmed": bool(volume_ratio is not None and volume_ratio >= 1.05),
            "breakout_volume_ratio": round(float(volume_ratio), 4) if volume_ratio is not None else None,
            "pattern_quality_score": score,
            "pattern_quality_tier": "clean" if score >= 84 and source_retrace_good else ("usable" if score >= 70 else "loose"),
            "pole_move_pct": round(float(first_leg_pct), 2),
            "flag_to_pole_pct": round(float(retrace_pct), 2),
        }


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
            "target_dist_pct": None,
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
    target_dist_pct = abs(target - breakout_price) / breakout_price * 100.0
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
        "target_dist_pct": round(float(target_dist_pct), 2),
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
    detector_config: Optional[MeasuredMoveConfig | Mapping[str, Any]] = None,
) -> Tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(df_raw) < 170:
        return [], {"rows": int(len(df_raw)), "skipped": "too_few_rows"}
    config = detector_config if isinstance(detector_config, MeasuredMoveConfig) else MeasuredMoveConfig.from_mapping(detector_config)
    max_events = int(max_events_per_symbol if max_events_per_symbol is not None else config.max_events_per_symbol)
    df, norm_stats = OHLCVNormalizer().normalize(df_raw)
    pivots = PivotDetector().detect_pivots(df, pivot_type="intermediate")
    detector = MeasuredMoveDetector(pattern_key, config)
    out: list[dict[str, Any]] = []
    used_confirmations: list[int] = []
    symbol = str(df.iloc[0]["symbol"])
    for i in range(len(pivots) - 2):
        candidate = detector.scan_window(df, pivots[i : i + 3])
        if not candidate:
            continue
        confirmation_idx = int(candidate["breakout_idx"])
        if any(abs(confirmation_idx - prev) <= config.breakout_cooldown_bars for prev in used_confirmations):
            continue
        record = {"symbol": symbol, "pattern_key": pattern_key, **candidate}
        record.update(_evaluate_detection(df, record))
        out.append(record)
        used_confirmations.append(confirmation_idx)
        if len(out) >= max_events:
            return out, {"rows": int(len(df)), "pivots": int(len(pivots)), "normalizer": norm_stats, "detector_config": config.to_dict()}
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
        retrace = _safe_float(row.get("corrective_retrace_pct"))
        linearity = _safe_float(row.get("first_leg_linearity_r2"))
        turns = _safe_float(row.get("correction_turn_count"))
        first_leg = _safe_float(row.get("first_leg_pct"))
        mfe = _safe_float(row.get("mfe_pct"))
        mae = _safe_float(row.get("mae_pct"))
        target_dist = _safe_float(row.get("target_dist_pct"))
        ratio = None if mfe is None or mae is None else mfe / max(mae, 1.0)
        score = 0.0
        score += _score_band(abs((retrace or 0) - 50.0), good=8.0, weak=28.0, reverse=True, weight=0.22)
        score += _score_band(linearity, good=0.86, weak=0.62, weight=0.18)
        score += _score_band(turns, good=2.0, weak=6.0, reverse=True, weight=0.12)
        score += _score_band(first_leg, good=22.0, weak=10.0, weight=0.10)
        score += _score_band(target_dist, good=12.0, weak=45.0, reverse=True, weight=0.10)
        score += 8.0 if path_bucket == "clean" else 3.0
        score += 5.0 if tradability_bucket == "clean" else (2.0 if tradability_bucket == "usable" else 0.0)
        reasons: list[str] = []
        if str(row.get("source_retrace_band")) != "ideal_38_62":
            reasons.append("retrace_outside_source_ideal")
        if linearity is not None and linearity < 0.76:
            reasons.append("leg_not_straight_enough")
        if turns is not None and turns > 4:
            reasons.append("choppy_correction")
        if ratio is not None and ratio < 1.15:
            reasons.append("weak_mfe_mae_ratio")
        if not _truthy(row.get("target_hit")):
            reasons.append("no_target_hit")
        score = round(float(max(0.0, min(100.0, score))), 2)
        morphology_clean = (
            str(row.get("source_retrace_band")) == "ideal_38_62"
            and linearity is not None
            and linearity >= 0.78
            and turns is not None
            and turns <= 4
        )
        if score >= 72 and morphology_clean and path_bucket == "clean":
            tier = "premium"
        elif score >= 56:
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
        "median_first_leg_pct": _median([row.get("first_leg_pct") for row in rows]),
        "median_corrective_retrace_pct": _median([row.get("corrective_retrace_pct") for row in rows]),
        "median_first_leg_linearity_r2": _median([row.get("first_leg_linearity_r2") for row in rows]),
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
            "first_leg_pct": _quantiles([row.get("first_leg_pct") for row in rows]),
            "corrective_retrace_pct": _quantiles([row.get("corrective_retrace_pct") for row in rows]),
            "first_leg_linearity_r2": _quantiles([row.get("first_leg_linearity_r2") for row in rows]),
        },
        "experiment_note": "Measured Move scanner uses first-leg, corrective-phase, and second-leg confirmation; the event anchor is the start of the projected second leg.",
    }


def _add_target_calibration(stats: Dict[str, Any], scan: Mapping[str, Any], path_rows: Sequence[Mapping[str, Any]], *, pattern_key: str) -> None:
    from scanner.research_support_analysis import PatternArtifacts, build_target_calibration_decisions, target_sensitivity

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
    stats["target_family"] = {"conservative_half_leg": 0.5, "source_full_leg": 1.0}


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
    "first_leg_pct",
    "first_leg_bars",
    "correction_bars",
    "corrective_retrace_pct",
    "source_retrace_band",
    "first_leg_linearity_r2",
    "correction_turn_count",
    "first_leg_start_price",
    "first_leg_end_price",
    "correction_end_price",
    "first_leg_start_date",
    "first_leg_end_date",
    "correction_end_date",
    "confirmation_clearance_pct",
    "volume_confirmed",
    "breakout_volume_ratio",
    "pole_move_pct",
    "flag_to_pole_pct",
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


def scan_measured_moves_db(
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
    config = MeasuredMoveConfig.from_mapping(detector_config)
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
    parser = argparse.ArgumentParser(description="Run Measured Move Family scanners against Market Cache latest.sqlite.")
    parser.add_argument("--pattern", choices=[MEASURED_MOVE_UP, MEASURED_MOVE_DOWN, "all"], default="all")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--market-stats-json", default=str(DEFAULT_MARKET_STATS_JSON))
    parser.add_argument("--limit-symbols", type=int, default=None)
    args = parser.parse_args()
    active_meta = _load_active_symbols(Path(args.market_stats_json) if args.market_stats_json else None)
    active_symbols = active_meta.get("active_symbols") if active_meta.get("enabled") else None
    patterns = [MEASURED_MOVE_UP, MEASURED_MOVE_DOWN] if args.pattern == "all" else [args.pattern]
    outputs: dict[str, str] = {}
    for pattern_key in patterns:
        paths = scan_measured_moves_db(
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
