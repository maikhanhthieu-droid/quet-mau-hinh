"""Rectangle Family scanner.

Rectangle Bottoms and Rectangle Tops share the same horizontal-range geometry,
but the source chapters distinguish them by the trend leading into the range:
downtrend into the range is a Rectangle Bottom, uptrend into the range is a
Rectangle Top. Breakout direction is measured separately.
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


RECTANGLE_BOTTOMS = "rectangle_bottoms"
RECTANGLE_TOPS = "rectangle_tops"
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/rectangle_family")


@dataclass(frozen=True)
class RectangleConfig:
    width_min_bars: int = 18
    width_max_bars: int = 130
    prior_trend_lookback_bars: int = 55
    prior_trend_min_pct: float = 5.0
    high_flat_tol_pct: float = 3.2
    low_flat_tol_pct: float = 3.2
    height_min_pct: float = 5.0
    height_max_pct: float = 36.0
    min_high_touches: int = 2
    min_low_touches: int = 2
    containment_min_pct: float = 70.0
    breakout_search_bars: int = 25
    breakout_threshold: float = 0.006
    breakout_cooldown_bars: int = 35
    max_events_per_symbol: int = 10

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]] = None) -> "RectangleConfig":
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
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _pct(numerator: int, denominator: int) -> Optional[float]:
    return None if denominator <= 0 else round(numerator / denominator * 100.0, 2)


def _median(values: Sequence[Any]) -> Optional[float]:
    series = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna()
    return None if series.empty else round(float(series.median()), 2)


def _mean(values: Sequence[Any]) -> Optional[float]:
    series = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna()
    return None if series.empty else round(float(series.mean()), 2)


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


class RectangleDetector:
    def __init__(self, pattern_key: str, config: Optional[RectangleConfig | Mapping[str, Any]] = None) -> None:
        if pattern_key not in {RECTANGLE_BOTTOMS, RECTANGLE_TOPS}:
            raise ValueError(f"unsupported rectangle pattern {pattern_key}")
        self.pattern_key = pattern_key
        self.config = config if isinstance(config, RectangleConfig) else RectangleConfig.from_mapping(config)

    def _prior_trend_pct(self, df: pd.DataFrame, formation_start: int) -> Optional[float]:
        start = max(0, int(formation_start) - self.config.prior_trend_lookback_bars)
        if formation_start <= start:
            return None
        anchor = _safe_float(df.iloc[start].get("close"))
        current = _safe_float(df.iloc[int(formation_start)].get("close"))
        if anchor is None or current is None or anchor <= 0:
            return None
        return (current - anchor) / anchor * 100.0

    def _breakout(self, df: pd.DataFrame, *, start_idx: int, resistance: float, support: float) -> Tuple[Optional[int], Optional[str], Optional[float], Optional[float]]:
        for idx in range(start_idx, min(len(df), start_idx + self.config.breakout_search_bars)):
            close = _safe_float(df.iloc[idx].get("close"))
            if close is None:
                continue
            volume_ratio = _safe_float(df.iloc[idx].get("volume_ratio"))
            if close > resistance * (1.0 + self.config.breakout_threshold):
                return idx, "up", close, volume_ratio
            if close < support * (1.0 - self.config.breakout_threshold):
                return idx, "down", close, volume_ratio
        return None, None, None, None

    def scan_window(self, df: pd.DataFrame, pivots: Sequence[Pivot]) -> Optional[Dict[str, Any]]:
        highs = [pivot for pivot in pivots if pivot.type == PivotType.HIGH]
        lows = [pivot for pivot in pivots if pivot.type == PivotType.LOW]
        if len(highs) < self.config.min_high_touches or len(lows) < self.config.min_low_touches:
            return None
        idxs = [int(p.idx) for p in highs + lows]
        formation_start = min(idxs)
        formation_end = max(idxs)
        width = formation_end - formation_start + 1
        if width < self.config.width_min_bars or width > self.config.width_max_bars:
            return None
        prior_trend = self._prior_trend_pct(df, formation_start)
        if prior_trend is None:
            return None
        if self.pattern_key == RECTANGLE_BOTTOMS and prior_trend > -self.config.prior_trend_min_pct:
            return None
        if self.pattern_key == RECTANGLE_TOPS and prior_trend < self.config.prior_trend_min_pct:
            return None
        high_prices = [float(df.iloc[int(p.idx)]["high"]) for p in highs]
        low_prices = [float(df.iloc[int(p.idx)]["low"]) for p in lows]
        resistance = float(np.median(high_prices))
        support = float(np.median(low_prices))
        if resistance <= support or support <= 0:
            return None
        high_spread_pct = (max(high_prices) - min(high_prices)) / resistance * 100.0
        low_spread_pct = (max(low_prices) - min(low_prices)) / support * 100.0
        if high_spread_pct > self.config.high_flat_tol_pct or low_spread_pct > self.config.low_flat_tol_pct:
            return None
        height_abs = resistance - support
        height_pct = height_abs / resistance * 100.0
        if height_pct < self.config.height_min_pct or height_pct > self.config.height_max_pct:
            return None
        segment = df.iloc[formation_start : formation_end + 1]
        contained = segment[(segment["high"] <= resistance * 1.015) & (segment["low"] >= support * 0.985)]
        containment_pct = len(contained) / max(len(segment), 1) * 100.0
        if containment_pct < self.config.containment_min_pct:
            return None
        breakout_idx, breakout_direction, breakout_price, volume_ratio = self._breakout(df, start_idx=formation_end + 1, resistance=resistance, support=support)
        if breakout_idx is None or breakout_direction is None or breakout_price is None:
            return None
        target_price = resistance + height_abs if breakout_direction == "up" else support - height_abs
        breakout_clearance_pct = (
            (float(breakout_price) - resistance) / resistance * 100.0
            if breakout_direction == "up"
            else (support - float(breakout_price)) / support * 100.0
        )
        quality_score = 58.0
        quality_score += _score_band(high_spread_pct, good=0.7, weak=self.config.high_flat_tol_pct, reverse=True, weight=0.13)
        quality_score += _score_band(low_spread_pct, good=0.7, weak=self.config.low_flat_tol_pct, reverse=True, weight=0.13)
        quality_score += _score_band(containment_pct, good=88.0, weak=self.config.containment_min_pct, weight=0.12)
        quality_score += _score_band(abs(prior_trend), good=12.0, weak=self.config.prior_trend_min_pct, weight=0.10)
        quality_score += _score_band(breakout_clearance_pct, good=2.0, weak=0.6, weight=0.08)
        if volume_ratio is not None and volume_ratio >= 1.15:
            quality_score += 5.0
        quality_score = int(max(0, min(100, round(quality_score))))
        return {
            "formation_start_idx": int(formation_start),
            "formation_end_idx": int(formation_end),
            "formation_start_date": str(pd.Timestamp(df.iloc[formation_start]["date"]).date()),
            "formation_end_date": str(pd.Timestamp(df.iloc[formation_end]["date"]).date()),
            "breakout_idx": int(breakout_idx),
            "breakout_date": str(pd.Timestamp(df.iloc[int(breakout_idx)]["date"]).date()),
            "breakout_direction": breakout_direction,
            "breakout_price": round(float(breakout_price), 4),
            "target_price": round(float(target_price), 4),
            "pattern_width_bars": int(width),
            "pattern_height_pct": round(float(height_pct), 2),
            "variant": self.pattern_key,
            "prior_trend_pct": round(float(prior_trend), 2),
            "upper_touch_count": int(len(highs)),
            "lower_touch_count": int(len(lows)),
            "high_spread_pct": round(float(high_spread_pct), 2),
            "low_spread_pct": round(float(low_spread_pct), 2),
            "rectangle_resistance": round(float(resistance), 4),
            "rectangle_support": round(float(support), 4),
            "rectangle_height_abs": round(float(height_abs), 4),
            "rectangle_containment_pct": round(float(containment_pct), 2),
            "breakout_clearance_pct": round(float(breakout_clearance_pct), 2),
            "volume_confirmed": bool(volume_ratio is not None and volume_ratio >= 1.15),
            "breakout_volume_ratio": round(float(volume_ratio), 4) if volume_ratio is not None else None,
            "pattern_quality_score": quality_score,
            "pattern_quality_tier": "clean" if quality_score >= 84 else ("usable" if quality_score >= 72 else "loose"),
            "pole_move_pct": round(float(height_pct), 2),
            "flag_to_pole_pct": round(float(width), 2),
        }


def scan_symbol(
    df_raw: pd.DataFrame,
    *,
    pattern_key: str,
    max_events_per_symbol: Optional[int] = None,
    detector_config: Optional[RectangleConfig | Mapping[str, Any]] = None,
) -> Tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(df_raw) < 150:
        return [], {"rows": int(len(df_raw)), "skipped": "too_few_rows"}
    config = detector_config if isinstance(detector_config, RectangleConfig) else RectangleConfig.from_mapping(detector_config)
    max_events = int(max_events_per_symbol if max_events_per_symbol is not None else config.max_events_per_symbol)
    df, norm_stats = OHLCVNormalizer().normalize(df_raw)
    pivots = PivotDetector().detect_pivots(df, pivot_type="minor")
    detector = RectangleDetector(pattern_key, config)
    out: list[dict[str, Any]] = []
    used_breakouts: list[int] = []
    symbol = str(df.iloc[0]["symbol"])
    for window_size in (4, 5, 6, 7, 8):
        for i in range(len(pivots) - window_size + 1):
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
    data_limited = {"short_path", "zero_and_stale", "zero_volume", "mixed_flag"}
    for row in rows:
        path_bucket = str(row.get("path_quality_bucket") or "unknown")
        tradability_bucket = str(row.get("tradability_quality_bucket") or "unknown")
        if path_bucket in data_limited or tradability_bucket == "impaired":
            row["publication_quality_score"] = 0.0
            row["publication_quality_tier"] = "data_limited"
            row["publication_quality_reasons"] = f"path:{path_bucket},tradability:{tradability_bucket}"
            continue
        high_spread = _safe_float(row.get("high_spread_pct"))
        low_spread = _safe_float(row.get("low_spread_pct"))
        containment = _safe_float(row.get("rectangle_containment_pct"))
        clearance = _safe_float(row.get("breakout_clearance_pct"))
        height = _safe_float(row.get("pattern_height_pct"))
        touches = float(row.get("upper_touch_count") or 0) + float(row.get("lower_touch_count") or 0)
        mfe = _safe_float(row.get("mfe_pct"))
        mae = _safe_float(row.get("mae_pct"))
        ratio = None if mfe is None or mae is None else mfe / max(mae, 1.0)
        score = 0.0
        score += _score_band(high_spread, good=0.7, weak=3.2, reverse=True, weight=0.18)
        score += _score_band(low_spread, good=0.7, weak=3.2, reverse=True, weight=0.18)
        score += _score_band(containment, good=88.0, weak=70.0, weight=0.18)
        score += _score_band(clearance, good=2.0, weak=0.6, weight=0.12)
        score += 10.0 if height is not None and 6.0 <= height <= 24.0 else 4.0
        score += min(10.0, max(0.0, (touches - 4.0) * 3.0))
        score += 7.0 if path_bucket == "clean" else 3.0
        score += 5.0 if tradability_bucket == "clean" else (2.0 if tradability_bucket == "usable" else 0.0)
        reasons: list[str] = []
        if high_spread is not None and high_spread > 2.2:
            reasons.append("weak_top_flatness")
        if low_spread is not None and low_spread > 2.2:
            reasons.append("weak_bottom_flatness")
        if containment is not None and containment < 82:
            reasons.append("weak_containment")
        if not _truthy(row.get("target_hit")):
            reasons.append("no_target_hit")
        if _truthy(row.get("failure_5pct")):
            reasons.append("failure_5pct")
        if ratio is not None and ratio < 1.25:
            reasons.append("weak_mfe_mae_ratio")
        score = round(float(max(0.0, min(100.0, score))), 2)
        premium_path = _truthy(row.get("target_hit")) and _truthy(row.get("target_first_before_adverse_5pct")) and not _truthy(row.get("failure_5pct")) and ratio is not None and ratio >= 1.35
        if score >= 78 and premium_path and path_bucket == "clean":
            tier = "premium"
        elif score >= 63:
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
        "median_prior_trend_pct": _median([row.get("prior_trend_pct") for row in rows]),
        "median_containment_pct": _median([row.get("rectangle_containment_pct") for row in rows]),
        "median_high_spread_pct": _median([row.get("high_spread_pct") for row in rows]),
        "median_low_spread_pct": _median([row.get("low_spread_pct") for row in rows]),
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
        },
        "experiment_note": "Rectangle scanner uses horizontal resistance/support, prior-trend family classification, close-confirmed breakout, and full-height target.",
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
    stats["target_family"] = {"local_caution": 0.5, "local_stretch": 0.75, "legacy_full_height": 1.0}


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
    "upper_touch_count",
    "lower_touch_count",
    "high_spread_pct",
    "low_spread_pct",
    "rectangle_resistance",
    "rectangle_support",
    "rectangle_height_abs",
    "rectangle_containment_pct",
    "breakout_clearance_pct",
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


def scan_rectangles_db(
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
    config = RectangleConfig.from_mapping(detector_config)
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
    parser = argparse.ArgumentParser(description="Run Rectangle Family scanners against Market Cache latest.sqlite.")
    parser.add_argument("--pattern", choices=[RECTANGLE_BOTTOMS, RECTANGLE_TOPS, "all"], default="all")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--market-stats-json", default=str(DEFAULT_MARKET_STATS_JSON))
    parser.add_argument("--limit-symbols", type=int, default=None)
    args = parser.parse_args()
    active_meta = _load_active_symbols(Path(args.market_stats_json) if args.market_stats_json else None)
    active_symbols = active_meta.get("active_symbols") if active_meta.get("enabled") else None
    patterns = [RECTANGLE_BOTTOMS, RECTANGLE_TOPS] if args.pattern == "all" else [args.pattern]
    outputs: dict[str, str] = {}
    for pattern_key in patterns:
        paths = scan_rectangles_db(
            pattern_key=pattern_key,
            db_path=Path(args.db),
            out_dir=Path(args.out_dir) / pattern_key / "db_active",
            allowed_symbols=active_symbols,
            limit_symbols=args.limit_symbols,
        )
        outputs[pattern_key] = {key: str(value) for key, value in paths.items()}  # type: ignore[assignment]
    print(json.dumps(outputs, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
