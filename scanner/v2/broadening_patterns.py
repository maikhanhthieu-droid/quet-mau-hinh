"""Broadening Family scanner.

The Broadening lane is deliberately separate from Triangle/Wedge/Flag logic.
Bulkowski's first six chart-pattern chapters share the idea of a widening
formation, but each variant has different boundary geometry and target rules.
This module owns only detection, path outcomes, quality tiers, and portable
artifacts; publication wording is handled by the family chapter factory.
"""

from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from dataclasses import asdict, dataclass, fields
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
from scanner.research_support_analysis import PatternArtifacts, build_target_calibration_decisions, target_sensitivity  # noqa: E402
from scanner.v2.bull_flags_monograph import DEFAULT_MARKET_STATS_JSON, _load_active_symbols  # noqa: E402
from scanner.v2.flags_experiment import DEFAULT_INDEX_DB, DEFAULT_INDEX_SYMBOL, _write_csv, _write_json  # noqa: E402
from scanner.v2.source_data import attach_current_market_groups, classify_market_regimes  # noqa: E402
from scanner.v2.symmetrical_triangles import (  # noqa: E402
    Trendline,
    _evaluate_detection,
    _group_stats,
    _group_table,
    _path_quality_audit,
    _quantiles,
    _safe_float,
    _score_band,
    _slope_degrees,
    _truthy,
    _utc_now,
)


BROADENING_PATTERNS = (
    "broadening_bottoms",
    "broadening_formations_right_angled_ascending",
    "broadening_formations_right_angled_descending",
    "broadening_tops",
    "broadening_wedges_ascending",
    "broadening_wedges_descending",
)

DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/broadening_family")


@dataclass(frozen=True)
class BroadeningConfig:
    width_min_bars: int = 24
    width_max_bars: int = 150
    prior_trend_bars: int = 55
    prior_trend_min_pct: float = 6.0
    high_rise_min_pct: float = 3.5
    low_fall_min_pct: float = 3.5
    wedge_slope_min_abs_deg: float = 0.35
    right_angle_tolerance_pct: float = 2.4
    expansion_min_ratio: float = 1.12
    height_min_pct: float = 5.0
    height_max_pct: float = 72.0
    breakout_search_bars: int = 42
    breakout_threshold: float = 0.0075
    breakout_cooldown_bars: int = 38
    pivot_window_stride: int = 3
    max_events_per_symbol: int = 10

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]] = None) -> "BroadeningConfig":
        if value is None:
            return cls()
        allowed = {field.name for field in fields(cls)}
        return cls(**{key: item for key, item in value.items() if key in allowed})

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


PATTERN_META: dict[str, dict[str, Any]] = {
    "broadening_bottoms": {
        "variant": "broadening_bottom",
        "geometry": "megaphone",
        "prior": "down",
        "min_touches": 2,
        "preferred_direction": "mixed",
    },
    "broadening_tops": {
        "variant": "broadening_top",
        "geometry": "megaphone",
        "prior": "up",
        "min_touches": 2,
        "preferred_direction": "mixed",
    },
    "broadening_formations_right_angled_ascending": {
        "variant": "right_angled_ascending",
        "geometry": "right_angled_ascending",
        "prior": "any",
        "min_touches": 2,
        "preferred_direction": "down",
    },
    "broadening_formations_right_angled_descending": {
        "variant": "right_angled_descending",
        "geometry": "right_angled_descending",
        "prior": "any",
        "min_touches": 2,
        "preferred_direction": "up",
    },
    "broadening_wedges_ascending": {
        "variant": "ascending_broadening_wedge",
        "geometry": "ascending_wedge",
        "prior": "any",
        "min_touches": 3,
        "preferred_direction": "down",
    },
    "broadening_wedges_descending": {
        "variant": "descending_broadening_wedge",
        "geometry": "descending_wedge",
        "prior": "any",
        "min_touches": 3,
        "preferred_direction": "up",
    },
}


def _line_from_pivots(df: pd.DataFrame, pivots: Sequence[Pivot], *, price_col: str) -> Trendline:
    first, last = pivots[0], pivots[-1]
    p0 = float(df.iloc[int(first.idx)][price_col])
    p1 = float(df.iloc[int(last.idx)][price_col])
    slope = (p1 - p0) / max(1, int(last.idx) - int(first.idx))
    return Trendline(int(first.idx), p0, slope)


def _pretrend_pct(df: pd.DataFrame, formation_start: int, bars: int) -> Optional[float]:
    left = max(0, int(formation_start) - int(bars))
    right = int(formation_start) - 1
    if right <= left:
        return None
    start = _safe_float(df.iloc[left].get("close"))
    end = _safe_float(df.iloc[right].get("close"))
    if start is None or end is None or start <= 0:
        return None
    return (end - start) / start * 100.0


def _horizontal_diff_pct(values: Sequence[float]) -> float:
    vals = [float(v) for v in values if math.isfinite(float(v)) and float(v) > 0]
    if len(vals) < 2:
        return 999.0
    return (max(vals) - min(vals)) / max(np.median(vals), 1e-9) * 100.0


def _breakout(
    df: pd.DataFrame,
    *,
    start_idx: int,
    pattern_key: str,
    upper: Trendline,
    lower: Trendline,
    pattern_high: float,
    pattern_low: float,
    horizontal_high: Optional[float],
    horizontal_low: Optional[float],
    threshold: float,
    search_bars: int,
) -> Tuple[Optional[int], Optional[float], Optional[float], Optional[str], Optional[float]]:
    meta = PATTERN_META[pattern_key]
    geometry = meta["geometry"]
    for idx in range(start_idx, min(len(df), start_idx + search_bars)):
        close = _safe_float(df.iloc[idx].get("close"))
        if close is None:
            continue
        if geometry == "megaphone":
            up_level = pattern_high
            down_level = pattern_low
        elif geometry == "right_angled_ascending":
            up_level = upper.value_at(idx)
            down_level = float(horizontal_low if horizontal_low is not None else pattern_low)
        elif geometry == "right_angled_descending":
            up_level = float(horizontal_high if horizontal_high is not None else pattern_high)
            down_level = lower.value_at(idx)
        else:
            up_level = upper.value_at(idx)
            down_level = lower.value_at(idx)
        if up_level > 0 and close > up_level * (1.0 + threshold):
            volume_ratio = _safe_float(df.iloc[idx].get("volume_ratio"))
            return idx, close, volume_ratio, "up", (close - up_level) / up_level * 100.0
        if down_level > 0 and close < down_level * (1.0 - threshold):
            volume_ratio = _safe_float(df.iloc[idx].get("volume_ratio"))
            return idx, close, volume_ratio, "down", (down_level - close) / down_level * 100.0
    return None, None, None, None, None


def _target_price(
    *,
    pattern_key: str,
    direction: str,
    breakout_price: float,
    pattern_high: float,
    pattern_low: float,
    height_abs: float,
    horizontal_high: Optional[float],
    horizontal_low: Optional[float],
) -> float:
    geometry = PATTERN_META[pattern_key]["geometry"]
    if geometry == "right_angled_ascending":
        if direction == "up":
            return float(pattern_high + height_abs)
        base = float(horizontal_low if horizontal_low is not None else pattern_low)
        return float(base - height_abs)
    if geometry == "right_angled_descending":
        top = float(horizontal_high if horizontal_high is not None else pattern_high)
        if direction == "up":
            return float(top + height_abs)
        return float(pattern_low - height_abs)
    if pattern_key == "broadening_wedges_ascending" and direction == "down":
        target = float(pattern_low)
        if target < breakout_price:
            return target
        return float(breakout_price - max(height_abs * 0.50, breakout_price * 0.03))
    if pattern_key == "broadening_wedges_descending" and direction == "up":
        target = float(pattern_high)
        if target > breakout_price:
            return target
        return float(breakout_price + max(height_abs * 0.50, breakout_price * 0.03))
    if direction == "up":
        return float(pattern_high + height_abs)
    return float(pattern_low - height_abs)


class BroadeningDetector:
    def __init__(self, pattern_key: str, config: Optional[BroadeningConfig | Mapping[str, Any]] = None) -> None:
        if pattern_key not in PATTERN_META:
            raise ValueError(f"unsupported Broadening pattern {pattern_key}")
        self.pattern_key = pattern_key
        self.config = config if isinstance(config, BroadeningConfig) else BroadeningConfig.from_mapping(config)

    def _shape_ok(self, df: pd.DataFrame, highs: Sequence[Pivot], lows: Sequence[Pivot]) -> tuple[bool, dict[str, Any]]:
        cfg = self.config
        meta = PATTERN_META[self.pattern_key]
        geometry = str(meta["geometry"])
        high_prices = [float(df.iloc[int(p.idx)]["high"]) for p in highs]
        low_prices = [float(df.iloc[int(p.idx)]["low"]) for p in lows]
        upper = _line_from_pivots(df, highs, price_col="high")
        lower = _line_from_pivots(df, lows, price_col="low")
        upper_deg = _slope_degrees(int(highs[0].idx), high_prices[0], int(highs[-1].idx), high_prices[-1])
        lower_deg = _slope_degrees(int(lows[0].idx), low_prices[0], int(lows[-1].idx), low_prices[-1])
        high_rise_pct = (high_prices[-1] - high_prices[0]) / max(high_prices[0], 1e-9) * 100.0
        low_fall_pct = (low_prices[0] - low_prices[-1]) / max(low_prices[0], 1e-9) * 100.0
        high_flat_pct = _horizontal_diff_pct(high_prices)
        low_flat_pct = _horizontal_diff_pct(low_prices)

        ok = True
        if geometry == "megaphone":
            ok = high_rise_pct >= cfg.high_rise_min_pct and low_fall_pct >= cfg.low_fall_min_pct and upper_deg > 0 and lower_deg < 0
        elif geometry == "right_angled_ascending":
            ok = low_flat_pct <= cfg.right_angle_tolerance_pct and high_rise_pct >= cfg.high_rise_min_pct and upper_deg > 0
        elif geometry == "right_angled_descending":
            ok = high_flat_pct <= cfg.right_angle_tolerance_pct and low_fall_pct >= cfg.low_fall_min_pct and lower_deg < 0
        elif geometry == "ascending_wedge":
            ok = (
                upper_deg >= cfg.wedge_slope_min_abs_deg
                and lower_deg >= cfg.wedge_slope_min_abs_deg
                and upper_deg > lower_deg + 0.25
            )
        elif geometry == "descending_wedge":
            ok = (
                upper_deg <= -cfg.wedge_slope_min_abs_deg
                and lower_deg <= -cfg.wedge_slope_min_abs_deg
                and lower_deg < upper_deg - 0.25
            )
        return ok, {
            "upper": upper,
            "lower": lower,
            "upper_slope_deg": upper_deg,
            "lower_slope_deg": lower_deg,
            "high_rise_pct": high_rise_pct,
            "low_fall_pct": low_fall_pct,
            "high_flatness_pct": high_flat_pct,
            "low_flatness_pct": low_flat_pct,
        }

    def scan_window(self, df: pd.DataFrame, pivots: Sequence[Pivot]) -> Optional[Dict[str, Any]]:
        meta = PATTERN_META[self.pattern_key]
        cfg = self.config
        highs = [pivot for pivot in pivots if pivot.type == PivotType.HIGH]
        lows = [pivot for pivot in pivots if pivot.type == PivotType.LOW]
        min_touches = int(meta["min_touches"])
        if len(highs) < min_touches or len(lows) < min_touches:
            return None
        idxs = [int(p.idx) for p in list(highs) + list(lows)]
        if len(set(idxs)) != len(idxs):
            return None
        formation_start = min(idxs)
        formation_end = max(idxs)
        width = formation_end - formation_start + 1
        if width < cfg.width_min_bars or width > cfg.width_max_bars:
            return None

        pretrend = _pretrend_pct(df, formation_start, cfg.prior_trend_bars)
        prior = str(meta["prior"])
        if prior == "up" and (pretrend is None or pretrend < cfg.prior_trend_min_pct):
            return None
        if prior == "down" and (pretrend is None or pretrend > -cfg.prior_trend_min_pct):
            return None

        shape_ok, shape = self._shape_ok(df, highs, lows)
        if not shape_ok:
            return None
        upper: Trendline = shape["upper"]
        lower: Trendline = shape["lower"]
        upper_start = upper.value_at(formation_start)
        lower_start = lower.value_at(formation_start)
        upper_end = upper.value_at(formation_end)
        lower_end = lower.value_at(formation_end)
        if upper_start <= lower_start or upper_end <= lower_end:
            return None
        first_gap = upper_start - lower_start
        last_gap = upper_end - lower_end
        if first_gap <= 0 or last_gap <= 0:
            return None
        expansion_ratio = last_gap / first_gap
        if expansion_ratio < cfg.expansion_min_ratio:
            return None
        pattern_high = float(df.iloc[formation_start : formation_end + 1]["high"].max())
        pattern_low = float(df.iloc[formation_start : formation_end + 1]["low"].min())
        height_abs = pattern_high - pattern_low
        height_pct = height_abs / max(pattern_high, 1e-9) * 100.0
        if height_pct < cfg.height_min_pct or height_pct > cfg.height_max_pct:
            return None

        high_prices = [float(df.iloc[int(p.idx)]["high"]) for p in highs]
        low_prices = [float(df.iloc[int(p.idx)]["low"]) for p in lows]
        horizontal_high = float(np.median(high_prices)) if shape["high_flatness_pct"] <= cfg.right_angle_tolerance_pct else None
        horizontal_low = float(np.median(low_prices)) if shape["low_flatness_pct"] <= cfg.right_angle_tolerance_pct else None
        breakout_idx, breakout_price, volume_ratio, direction, clearance_pct = _breakout(
            df,
            start_idx=formation_end + 1,
            pattern_key=self.pattern_key,
            upper=upper,
            lower=lower,
            pattern_high=pattern_high,
            pattern_low=pattern_low,
            horizontal_high=horizontal_high,
            horizontal_low=horizontal_low,
            threshold=cfg.breakout_threshold,
            search_bars=cfg.breakout_search_bars,
        )
        if breakout_idx is None or breakout_price is None or direction is None:
            return None
        target = _target_price(
            pattern_key=self.pattern_key,
            direction=direction,
            breakout_price=float(breakout_price),
            pattern_high=pattern_high,
            pattern_low=pattern_low,
            height_abs=height_abs,
            horizontal_high=horizontal_high,
            horizontal_low=horizontal_low,
        )
        if direction == "up" and target <= float(breakout_price):
            target = float(breakout_price) + max(height_abs * 0.5, float(breakout_price) * 0.03)
        if direction == "down" and target >= float(breakout_price):
            target = float(breakout_price) - max(height_abs * 0.5, float(breakout_price) * 0.03)

        trend_alignment = 1.0 if str(meta["preferred_direction"]) in {"mixed", direction} else 0.0
        score = 55.0
        score += _score_band(expansion_ratio, good=1.45, weak=cfg.expansion_min_ratio, weight=0.14)
        score += _score_band(abs(float(shape["upper_slope_deg"])), good=2.0, weak=0.30, weight=0.08)
        score += _score_band(abs(float(shape["lower_slope_deg"])), good=2.0, weak=0.30, weight=0.08)
        score += _score_band(height_pct, good=14.0, weak=5.0, weight=0.10)
        score += _score_band(float(clearance_pct or 0.0), good=2.0, weak=0.75, weight=0.09)
        score += trend_alignment * 5.0
        if volume_ratio is not None and volume_ratio >= 1.15:
            score += 5.0
        score = round(float(max(0.0, min(100.0, score))), 2)

        return {
            "formation_start_idx": int(formation_start),
            "formation_end_idx": int(formation_end),
            "formation_start_date": str(pd.Timestamp(df.iloc[formation_start]["date"]).date()),
            "formation_end_date": str(pd.Timestamp(df.iloc[formation_end]["date"]).date()),
            "breakout_idx": int(breakout_idx),
            "breakout_date": str(pd.Timestamp(df.iloc[int(breakout_idx)]["date"]).date()),
            "breakout_direction": str(direction),
            "breakout_price": round(float(breakout_price), 4),
            "target_price": round(float(target), 4),
            "pattern_width_bars": int(width),
            "pattern_height_pct": round(float(height_pct), 2),
            "pivot_indices": [int(x) for x in idxs],
            "variant": str(meta["variant"]),
            "volume_confirmed": bool(volume_ratio is not None and volume_ratio >= 1.15),
            "breakout_volume_ratio": round(float(volume_ratio), 4) if volume_ratio is not None else None,
            "pattern_quality_score": score,
            "pattern_quality_tier": "clean" if score >= 82 else ("usable" if score >= 66 else "loose"),
            "upper_slope_deg": round(float(shape["upper_slope_deg"]), 2),
            "lower_slope_deg": round(float(shape["lower_slope_deg"]), 2),
            "high_rise_pct": round(float(shape["high_rise_pct"]), 2),
            "low_fall_pct": round(float(shape["low_fall_pct"]), 2),
            "high_flatness_pct": round(float(shape["high_flatness_pct"]), 2),
            "low_flatness_pct": round(float(shape["low_flatness_pct"]), 2),
            "expansion_ratio": round(float(expansion_ratio), 3),
            "breakout_clearance_pct": round(float(clearance_pct or 0.0), 2),
            "prior_trend_pct": round(float(pretrend), 2) if pretrend is not None else None,
            "touch_count_high": int(len(highs)),
            "touch_count_low": int(len(lows)),
            "pattern_high": round(float(pattern_high), 4),
            "pattern_low": round(float(pattern_low), 4),
            "broadening_resistance": round(float(upper_start), 4),
            "broadening_support": round(float(lower_start), 4),
            "broadening_height_abs": round(float(height_abs), 4),
            "broadening_upper_idx0": int(upper.idx0),
            "broadening_upper_price0": round(float(upper.price0), 4),
            "broadening_upper_slope_per_bar": round(float(upper.slope_per_bar), 8),
            "broadening_lower_idx0": int(lower.idx0),
            "broadening_lower_price0": round(float(lower.price0), 4),
            "broadening_lower_slope_per_bar": round(float(lower.slope_per_bar), 8),
            "horizontal_high": round(float(horizontal_high), 4) if horizontal_high is not None else None,
            "horizontal_low": round(float(horizontal_low), 4) if horizontal_low is not None else None,
            "pole_move_pct": round(float(height_pct), 2),
            "flag_to_pole_pct": round(float(expansion_ratio * 100.0), 2),
        }


def scan_symbol(
    df_raw: pd.DataFrame,
    *,
    pattern_key: str,
    max_events_per_symbol: Optional[int] = None,
    detector_config: Optional[BroadeningConfig | Mapping[str, Any]] = None,
) -> Tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(df_raw) < 180:
        return [], {"rows": int(len(df_raw)), "skipped": "too_few_rows"}
    config = detector_config if isinstance(detector_config, BroadeningConfig) else BroadeningConfig.from_mapping(detector_config)
    max_events = int(max_events_per_symbol if max_events_per_symbol is not None else config.max_events_per_symbol)
    df, norm_stats = OHLCVNormalizer().normalize(df_raw)
    pivots = PivotDetector().detect_pivots(df, pivot_type="minor")
    detector = BroadeningDetector(pattern_key, config)
    out: list[dict[str, Any]] = []
    used_breakouts: list[int] = []
    symbol = str(df.iloc[0]["symbol"])
    window_sizes = (6, 7, 8) if PATTERN_META[pattern_key]["min_touches"] >= 3 else (4, 5, 6)
    stride = max(1, int(config.pivot_window_stride))
    for window_size in window_sizes:
        for i in range(0, len(pivots) - window_size + 1, stride):
            candidate = detector.scan_window(df, pivots[i : i + window_size])
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
                return out, {"rows": int(len(df)), "pivots": int(len(pivots)), "normalizer": norm_stats, "detector_config": config.to_dict()}
    return out, {"rows": int(len(df)), "pivots": int(len(pivots)), "normalizer": norm_stats, "detector_config": config.to_dict()}


def _assign_publication_quality_tiers(rows: list[dict[str, Any]]) -> None:
    data_limited_path = {"short_path", "zero_and_stale", "zero_volume", "mixed_flag"}
    for row in rows:
        path_bucket = str(row.get("path_quality_bucket") or "unknown")
        tradability_bucket = str(row.get("tradability_quality_bucket") or "unknown")
        expansion = _safe_float(row.get("expansion_ratio"))
        height_pct = _safe_float(row.get("pattern_height_pct"))
        clearance = _safe_float(row.get("breakout_clearance_pct"))
        volume_ratio = _safe_float(row.get("breakout_volume_ratio"))
        touch_high = _safe_float(row.get("touch_count_high"))
        touch_low = _safe_float(row.get("touch_count_low"))
        mfe_pct = _safe_float(row.get("mfe_pct"))
        mae_pct = _safe_float(row.get("mae_pct"))
        reasons: list[str] = []
        outcome_reasons: list[str] = []
        if path_bucket in data_limited_path or tradability_bucket == "impaired":
            row["publication_quality_score"] = 0.0
            row["publication_quality_tier"] = "data_limited"
            row["publication_quality_reasons"] = ",".join(filter(None, [f"path:{path_bucket}", f"tradability:{tradability_bucket}"]))
            row["post_breakout_quality_label"] = "data_limited"
            row["post_breakout_quality_reasons"] = "not_evaluated_due_to_data_quality"
            continue
        score = 0.0
        score += _score_band(expansion, good=1.55, weak=1.12, weight=0.20)
        score += _score_band(height_pct, good=16.0, weak=5.0, weight=0.15)
        score += _score_band(clearance, good=2.0, weak=0.75, weight=0.12)
        score += _score_band(touch_high, good=3.0, weak=2.0, weight=0.10)
        score += _score_band(touch_low, good=3.0, weak=2.0, weight=0.10)
        if volume_ratio is not None:
            score += _score_band(volume_ratio, good=1.15, weak=0.75, weight=0.06)
        else:
            reasons.append("missing_breakout_volume")
        if path_bucket == "clean":
            score += 9.0
        else:
            reasons.append(f"path:{path_bucket}")
        if tradability_bucket == "clean":
            score += 8.0
        elif tradability_bucket == "usable":
            score += 4.0
            reasons.append("tradability:usable")
        else:
            reasons.append(f"tradability:{tradability_bucket}")
        if height_pct is not None and not (6.0 <= height_pct <= 45.0):
            reasons.append("extreme_height")
        if expansion is not None and expansion < 1.28:
            reasons.append("weak_broadening_expansion")
        if clearance is not None and clearance < 1.15:
            reasons.append("thin_breakout_clearance")
        target_hit = _truthy(row.get("target_hit"))
        failure_5pct = _truthy(row.get("failure_5pct"))
        target_first = _truthy(row.get("target_first_before_adverse_5pct"))
        ratio = None if mfe_pct is None or mae_pct is None else mfe_pct / max(mae_pct, 1.0)
        if not target_hit:
            outcome_reasons.append("no_target_hit")
        if not target_first:
            outcome_reasons.append("not_target_first")
        if failure_5pct:
            outcome_reasons.append("failure_5pct")
        if ratio is not None and ratio < 1.20:
            outcome_reasons.append("weak_mfe_mae_ratio")
        if mae_pct is not None and mae_pct > 24.0:
            outcome_reasons.append("large_adverse_excursion")
        strong = target_hit and target_first and not failure_5pct and ratio is not None and ratio >= 1.30 and (mae_pct is not None and mae_pct <= 24.0)
        partial = target_hit and not failure_5pct and ratio is not None and ratio >= 1.0
        if strong:
            outcome = "strong_follow_through"
        elif partial:
            outcome = "partial_follow_through"
        elif failure_5pct:
            outcome = "failed_follow_through"
        else:
            outcome = "weak_or_unresolved_follow_through"
        score = round(float(max(0.0, min(100.0, score))), 2)
        premium_geometry_ok = (
            expansion is not None
            and expansion >= 1.35
            and height_pct is not None
            and 6.0 <= height_pct <= 45.0
            and clearance is not None
            and clearance >= 1.15
            and tradability_bucket == "clean"
        )
        if score >= 78.0 and path_bucket == "clean" and premium_geometry_ok:
            tier = "premium"
        elif score >= 62.0:
            tier = "standard"
        else:
            tier = "loose"
        row["publication_quality_score"] = score
        row["publication_quality_tier"] = tier
        row["publication_quality_reasons"] = ",".join(sorted(set(reasons)))
        row["post_breakout_quality_label"] = outcome
        row["post_breakout_quality_reasons"] = ",".join(sorted(set(outcome_reasons)))


def summarize(pattern_key: str, scan: Mapping[str, Any]) -> Dict[str, Any]:
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
        "variant_table": {PATTERN_META[pattern_key]["variant"]: _group_stats(rows)},
        "quality_table": {tier: _group_stats([row for row in rows if row.get("pattern_quality_tier") == tier]) for tier in ("clean", "usable", "loose")},
        "publication_quality_table": {tier: _group_stats([row for row in rows if row.get("publication_quality_tier") == tier]) for tier in ("premium", "standard", "loose", "data_limited")},
        "regime_groups": {regime: _group_stats([row for row in rows if str(row.get("market_regime") or "unknown") == regime]) for regime in ("bull", "bear", "unknown")},
        "market_group_table": {group: _group_stats([row for row in rows if str(row.get("market_group") or "Outside VN100") == group]) for group in ("VN30", "VN100 ex VN30", "Outside VN100")},
        "liquidity_proxy_table": _group_table(rows, "liquidity_bucket", ("high", "mid", "low", "unknown")),
        "regime_proxy_table": _group_table(rows, "market_regime", ("bull", "bear", "unknown")),
        "path_quality_audit": _path_quality_audit(rows),
        "quantile_metrics": {
            "fav_exc_pct": _quantiles([row.get("mfe_pct") for row in evals]),
            "adv_exc_pct": _quantiles([row.get("mae_pct") for row in evals]),
            "target_dist_pct": _quantiles([row.get("target_dist_pct") for row in evals]),
        },
        "experiment_note": f"{pattern_key} uses Broadening-family source geometry, not Triangle/Wedge/Flag scanner inheritance.",
    }


EVENT_FIELDS = [
    "detection_id", "symbol", "variant", "market_group", "market_regime",
    "formation_start_idx", "formation_end_idx", "formation_start_date", "formation_end_date",
    "breakout_idx", "breakout_date", "breakout_direction", "breakout_price", "b_exec_price",
    "target_price", "target_dist_pct", "mfe_pct", "mae_pct", "target_hit", "failure_5pct",
    "target_first_before_adverse_5pct", "days_to_target", "throwback_pullback_30d",
    "days_to_throwback_pullback", "pattern_quality_score", "pattern_quality_tier",
    "pattern_width_bars", "pattern_height_pct", "high_rise_pct", "low_fall_pct",
    "high_flatness_pct", "low_flatness_pct", "upper_slope_deg", "lower_slope_deg",
    "expansion_ratio", "breakout_clearance_pct", "volume_confirmed",
    "breakout_volume_ratio", "prior_trend_pct", "touch_count_high", "touch_count_low",
    "pattern_high", "pattern_low", "horizontal_high", "horizontal_low",
    "broadening_resistance", "broadening_support", "broadening_height_abs",
    "broadening_upper_idx0", "broadening_upper_price0", "broadening_upper_slope_per_bar",
    "broadening_lower_idx0", "broadening_lower_price0", "broadening_lower_slope_per_bar",
    "evaluated_bars", "is_primary_event_60d", "liquidity_bucket",
    "path_quality_bucket", "tradability_quality_bucket", "tradability_quality_score",
    "missing_bar_rate_60d", "zero_volume_rate_60d", "price_limit_proxy_rate_60d",
    "publication_quality_score", "publication_quality_tier",
    "publication_quality_reasons", "post_breakout_quality_label",
    "post_breakout_quality_reasons",
]


def _add_target_calibration(pattern_key: str, stats: Dict[str, Any], scan: Mapping[str, Any], path_rows: Sequence[Mapping[str, Any]]) -> None:
    events = pd.DataFrame(list(scan.get("detections") or []))
    path = pd.DataFrame(list(path_rows))
    if events.empty:
        stats["target_family_sensitivity"] = []
        stats["target_calibration_decision"] = None
        stats["target_family"] = {"local_base": 0.5, "local_stretch": 0.75, "source_measure": 1.0}
        return
    if "event_id" not in events.columns and "detection_id" in events.columns:
        events["event_id"] = events["detection_id"]
    sensitivity = target_sensitivity(PatternArtifacts(pattern_key, events, path), pattern_key, horizon_days=120)
    stats["target_family_sensitivity"] = sensitivity
    stats["target_calibration_decision"] = (build_target_calibration_decisions(sensitivity, family_labels=(pattern_key,)) or [None])[0]
    stats["target_family"] = {"local_base": 0.5, "local_stretch": 0.75, "source_measure": 1.0}


def scan_broadening_pattern_db(
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
    if pattern_key not in BROADENING_PATTERNS:
        raise ValueError(f"unsupported Broadening pattern {pattern_key}")
    out_dir.mkdir(parents=True, exist_ok=True)
    config = BroadeningConfig.from_mapping(detector_config)
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
    stats = summarize(pattern_key, scan)
    stats["source"] = scan["source"]
    stats["db_source_meta"] = _db_meta(db_path)
    stats["detector_config"] = config.to_dict()
    path_rows = _path_rows_from_series(scan, series_by_symbol, horizon_bars=120)
    _add_target_calibration(pattern_key, stats, scan, path_rows)
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


def scan_broadening_family_db(
    *,
    db_path: Path,
    out_dir: Path,
    allowed_symbols: Optional[Sequence[str]] = None,
    detector_config: Optional[Mapping[str, Any]] = None,
    limit_symbols: Optional[int] = None,
) -> dict[str, dict[str, Path]]:
    outputs: dict[str, dict[str, Path]] = {}
    for pattern_key in BROADENING_PATTERNS:
        outputs[pattern_key] = scan_broadening_pattern_db(
            pattern_key=pattern_key,
            db_path=db_path,
            out_dir=out_dir / pattern_key / "db_active",
            allowed_symbols=allowed_symbols,
            detector_config=detector_config,
            limit_symbols=limit_symbols,
        )
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Broadening Family scanners against Market Cache latest.sqlite.")
    parser.add_argument("--pattern", choices=[*BROADENING_PATTERNS, "all"], default="all")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--market-stats-json", default=str(DEFAULT_MARKET_STATS_JSON))
    parser.add_argument("--limit-symbols", type=int, default=None)
    args = parser.parse_args()
    active_meta = _load_active_symbols(Path(args.market_stats_json) if args.market_stats_json else None)
    active_symbols = active_meta.get("active_symbols") if active_meta.get("enabled") else None
    if args.pattern == "all":
        outputs = scan_broadening_family_db(
            db_path=Path(args.db),
            out_dir=Path(args.out_dir),
            allowed_symbols=active_symbols,
            limit_symbols=args.limit_symbols,
        )
        print({key: {name: str(path) for name, path in value.items()} for key, value in outputs.items()})
        return
    paths = scan_broadening_pattern_db(
        pattern_key=args.pattern,
        db_path=Path(args.db),
        out_dir=Path(args.out_dir) / args.pattern / "db_active",
        allowed_symbols=active_symbols,
        limit_symbols=args.limit_symbols,
    )
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
