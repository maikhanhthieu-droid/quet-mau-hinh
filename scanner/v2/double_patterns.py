"""Double Bottom / Double Top scanner for the Double Pattern Family lane.

This module is deliberately separate from Flag and Triangle scanners. Double
patterns are reversal structures around a neckline, not continuation channels or
trendline-compression patterns. The output shape is kept compatible with the
shared publication core.
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

from scanner.double_pattern_utils import resolve_double_bottom_variant, resolve_double_top_variant  # noqa: E402
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


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/double_pattern_family")


@dataclass(frozen=True)
class DoublePatternConfig:
    width_min_bars: int = 18
    width_max_bars: int = 125
    extreme_similarity_tol_pct: float = 4.5
    min_neckline_height_pct: float = 5.0
    max_neckline_height_pct: float = 45.0
    min_prior_trend_pct: float = 4.0
    prior_trend_lookback_bars: int = 45
    breakout_search_bars: int = 35
    breakout_threshold: float = 0.0075
    breakout_cooldown_bars: int = 45
    max_events_per_symbol: int = 10

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]] = None) -> "DoublePatternConfig":
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
    return None if not vals else _pct(sum(1 for val in vals if val is True), len(vals))


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


def _find_breakout(
    df: pd.DataFrame,
    *,
    start_idx: int,
    neckline: float,
    direction: str,
    search_bars: int,
    threshold: float,
) -> Tuple[Optional[int], Optional[float], Optional[float]]:
    for idx in range(start_idx, min(len(df), start_idx + search_bars)):
        close = _safe_float(df.iloc[idx].get("close"))
        if close is None:
            continue
        if direction == "up" and close > neckline * (1.0 + threshold):
            return idx, close, _safe_float(df.iloc[idx].get("volume_ratio"))
        if direction == "down" and close < neckline * (1.0 - threshold):
            return idx, close, _safe_float(df.iloc[idx].get("volume_ratio"))
    return None, None, None


def _prior_trend_pct(df: pd.DataFrame, *, pivot_idx: int, pivot_price: float, direction: str, lookback: int) -> Optional[float]:
    if pivot_idx <= 0 or pivot_price <= 0:
        return None
    ref_idx = max(0, pivot_idx - lookback)
    ref = _safe_float(df.iloc[ref_idx].get("close"))
    if ref is None or ref <= 0:
        return None
    if direction == "up":
        return round((ref - pivot_price) / ref * 100.0, 2)
    return round((pivot_price - ref) / ref * 100.0, 2)


def _evaluate_detection(df: pd.DataFrame, detection: Mapping[str, Any], *, lookahead: int = 120) -> Dict[str, Any]:
    breakout_idx = int(detection["breakout_idx"])
    breakout_price = float(detection["breakout_price"])
    target = float(detection["target_price"])
    direction = str(detection["breakout_direction"])
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
        }
    if direction == "up":
        mfe = (float(future["high"].max()) - breakout_price) / breakout_price * 100.0
        mae = (breakout_price - float(future["low"].min())) / breakout_price * 100.0
        target_hit = bool(float(future["high"].max()) >= target)
    else:
        mfe = (breakout_price - float(future["low"].min())) / breakout_price * 100.0
        mae = (float(future["high"].max()) - breakout_price) / breakout_price * 100.0
        target_hit = bool(float(future["low"].min()) <= target)
    target_dist_pct = abs(target - breakout_price) / breakout_price * 100.0
    days_to_target: Optional[int] = None
    days_to_adverse_5: Optional[int] = None
    for offset, (_, row) in enumerate(future.iterrows(), start=1):
        high = float(row["high"])
        low = float(row["low"])
        if direction == "up":
            if days_to_target is None and high >= target:
                days_to_target = offset
            if days_to_adverse_5 is None and low <= breakout_price * 0.95:
                days_to_adverse_5 = offset
        else:
            if days_to_target is None and low <= target:
                days_to_target = offset
            if days_to_adverse_5 is None and high >= breakout_price * 1.05:
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
    }


class DoublePatternDetector:
    def __init__(self, config: Optional[DoublePatternConfig | Mapping[str, Any]] = None) -> None:
        self.config = config if isinstance(config, DoublePatternConfig) else DoublePatternConfig.from_mapping(config)

    def scan_triplet(self, df: pd.DataFrame, triplet: Sequence[Pivot], *, family: str) -> Optional[Dict[str, Any]]:
        if len(triplet) != 3:
            return None
        p1, mid, p2 = triplet
        if family == "double_bottoms":
            if not (p1.type == PivotType.LOW and mid.type == PivotType.HIGH and p2.type == PivotType.LOW):
                return None
            return self._scan_bottom(df, p1, mid, p2)
        if family == "double_tops":
            if not (p1.type == PivotType.HIGH and mid.type == PivotType.LOW and p2.type == PivotType.HIGH):
                return None
            return self._scan_top(df, p1, mid, p2)
        raise ValueError(f"Unsupported double pattern family: {family}")

    def _scan_bottom(self, df: pd.DataFrame, low1: Pivot, peak: Pivot, low2: Pivot) -> Optional[Dict[str, Any]]:
        l1_idx, p_idx, l2_idx = int(low1.idx), int(peak.idx), int(low2.idx)
        if not (l1_idx < p_idx < l2_idx):
            return None
        l1, l2 = float(df.iloc[l1_idx]["low"]), float(df.iloc[l2_idx]["low"])
        neckline = float(df.iloc[p_idx]["high"])
        return self._scan_common(
            df,
            family="double_bottoms",
            first_idx=l1_idx,
            middle_idx=p_idx,
            second_idx=l2_idx,
            first_price=l1,
            second_price=l2,
            neckline=neckline,
            direction="up",
        )

    def _scan_top(self, df: pd.DataFrame, high1: Pivot, trough: Pivot, high2: Pivot) -> Optional[Dict[str, Any]]:
        h1_idx, t_idx, h2_idx = int(high1.idx), int(trough.idx), int(high2.idx)
        if not (h1_idx < t_idx < h2_idx):
            return None
        h1, h2 = float(df.iloc[h1_idx]["high"]), float(df.iloc[h2_idx]["high"])
        neckline = float(df.iloc[t_idx]["low"])
        return self._scan_common(
            df,
            family="double_tops",
            first_idx=h1_idx,
            middle_idx=t_idx,
            second_idx=h2_idx,
            first_price=h1,
            second_price=h2,
            neckline=neckline,
            direction="down",
        )

    def _scan_common(
        self,
        df: pd.DataFrame,
        *,
        family: str,
        first_idx: int,
        middle_idx: int,
        second_idx: int,
        first_price: float,
        second_price: float,
        neckline: float,
        direction: str,
    ) -> Optional[Dict[str, Any]]:
        cfg = self.config
        if first_price <= 0 or second_price <= 0 or neckline <= 0:
            return None
        width = second_idx - first_idx + 1
        if width < cfg.width_min_bars or width > cfg.width_max_bars:
            return None
        spacing_left = middle_idx - first_idx
        spacing_right = second_idx - middle_idx
        if spacing_left < 4 or spacing_right < 4:
            return None
        avg_extreme = (first_price + second_price) / 2.0
        extreme_spread_pct = abs(second_price - first_price) / max(avg_extreme, 1e-9) * 100.0
        if extreme_spread_pct > cfg.extreme_similarity_tol_pct:
            return None
        if direction == "up":
            base = min(first_price, second_price)
            if neckline <= base:
                return None
            height_abs = neckline - base
        else:
            base = max(first_price, second_price)
            if neckline >= base:
                return None
            height_abs = base - neckline
        height_pct = height_abs / max(neckline, 1e-9) * 100.0
        if height_pct < cfg.min_neckline_height_pct or height_pct > cfg.max_neckline_height_pct:
            return None
        prior_trend = _prior_trend_pct(
            df,
            pivot_idx=first_idx,
            pivot_price=first_price,
            direction=direction,
            lookback=cfg.prior_trend_lookback_bars,
        )
        if prior_trend is not None and prior_trend < cfg.min_prior_trend_pct:
            return None
        breakout_idx, breakout_price, volume_ratio = _find_breakout(
            df,
            start_idx=second_idx + 1,
            neckline=neckline,
            direction=direction,
            search_bars=cfg.breakout_search_bars,
            threshold=cfg.breakout_threshold,
        )
        if breakout_idx is None or breakout_price is None:
            return None
        target_price = float(breakout_price) + height_abs if direction == "up" else float(breakout_price) - height_abs
        breakout_clearance_pct = (
            (float(breakout_price) - neckline) / neckline * 100.0
            if direction == "up"
            else (neckline - float(breakout_price)) / neckline * 100.0
        )
        variant = (
            resolve_double_bottom_variant(df, first_idx=first_idx, second_idx=second_idx)
            if direction == "up"
            else resolve_double_top_variant(df, first_idx=first_idx, second_idx=second_idx)
        )
        variant_code = str(variant.get("variant_code") or "unclassified")
        variant_confidence = int(variant.get("variant_confidence") or 0)
        balance_ratio = min(spacing_left, spacing_right) / max(spacing_left, spacing_right)
        score = 60.0
        score += _score_band(extreme_spread_pct, good=1.0, weak=cfg.extreme_similarity_tol_pct, reverse=True, weight=0.14)
        score += _score_band(height_pct, good=12.0, weak=cfg.min_neckline_height_pct, reverse=False, weight=0.10)
        score += _score_band(balance_ratio, good=0.65, weak=0.25, reverse=False, weight=0.10)
        score += _score_band(breakout_clearance_pct, good=2.0, weak=0.75, reverse=False, weight=0.12)
        if volume_ratio is not None and volume_ratio >= 1.1:
            score += 5.0
        if variant_confidence >= 70:
            score += 4.0
        score = int(max(0, min(100, round(score))))
        return {
            "formation_start_idx": int(first_idx),
            "formation_end_idx": int(second_idx),
            "formation_start_date": str(pd.Timestamp(df.iloc[first_idx]["date"]).date()),
            "formation_end_date": str(pd.Timestamp(df.iloc[second_idx]["date"]).date()),
            "breakout_idx": int(breakout_idx),
            "breakout_date": str(pd.Timestamp(df.iloc[int(breakout_idx)]["date"]).date()),
            "breakout_direction": direction,
            "breakout_price": round(float(breakout_price), 4),
            "target_price": round(float(target_price), 4),
            "pattern_width_bars": int(width),
            "pattern_height_pct": round(float(height_pct), 2),
            "pivot_indices": [int(first_idx), int(middle_idx), int(second_idx)],
            "variant": variant_code,
            "variant_confidence": variant_confidence,
            "variant_evidence": json.dumps(variant.get("evidence") or {}, ensure_ascii=False),
            "volume_confirmed": bool(volume_ratio is not None and volume_ratio >= 1.1),
            "breakout_volume_ratio": round(float(volume_ratio), 4) if volume_ratio is not None else None,
            "pattern_quality_score": score,
            "pattern_quality_tier": "clean" if score >= 84 else ("usable" if score >= 72 else "loose"),
            "neckline_price": round(float(neckline), 4),
            "neckline_height_abs": round(float(height_abs), 4),
            "extreme_spread_pct": round(float(extreme_spread_pct), 2),
            "prior_trend_pct": prior_trend,
            "breakout_clearance_pct": round(float(breakout_clearance_pct), 2),
            "left_spacing_bars": int(spacing_left),
            "right_spacing_bars": int(spacing_right),
            "balance_ratio": round(float(balance_ratio), 3),
            "first_extreme_idx": int(first_idx),
            "middle_extreme_idx": int(middle_idx),
            "second_extreme_idx": int(second_idx),
            "first_extreme_price": round(float(first_price), 4),
            "middle_extreme_price": round(float(neckline), 4),
            "second_extreme_price": round(float(second_price), 4),
            # Compatibility fields for the shared chapter factory.
            "pole_move_pct": round(float(height_pct), 2),
            "flag_to_pole_pct": round(float(extreme_spread_pct), 2),
        }


def scan_symbol(
    df_raw: pd.DataFrame,
    *,
    family: str,
    max_events_per_symbol: Optional[int] = None,
    detector_config: Optional[DoublePatternConfig | Mapping[str, Any]] = None,
) -> Tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(df_raw) < 160:
        return [], {"rows": int(len(df_raw)), "skipped": "too_few_rows"}
    config = detector_config if isinstance(detector_config, DoublePatternConfig) else DoublePatternConfig.from_mapping(detector_config)
    max_events = int(max_events_per_symbol if max_events_per_symbol is not None else config.max_events_per_symbol)
    df, norm_stats = OHLCVNormalizer().normalize(df_raw)
    pivots = PivotDetector().detect_pivots(df, pivot_type="minor")
    detector = DoublePatternDetector(config)
    out: list[dict[str, Any]] = []
    used_breakouts: list[int] = []
    symbol = str(df.iloc[0]["symbol"])
    for i in range(len(pivots) - 2):
        candidate = detector.scan_triplet(df, pivots[i : i + 3], family=family)
        if not candidate:
            continue
        breakout_idx = int(candidate["breakout_idx"])
        if any(abs(breakout_idx - prev) <= config.breakout_cooldown_bars for prev in used_breakouts):
            continue
        record = {"symbol": symbol, "pattern_key": family, **candidate}
        record.update(_evaluate_detection(df, record))
        out.append(record)
        used_breakouts.append(breakout_idx)
        if len(out) >= max_events:
            return out, {"rows": int(len(df)), "pivots": int(len(pivots)), "normalizer": norm_stats, "detector_config": config.to_dict()}
    return out, {"rows": int(len(df)), "pivots": int(len(pivots)), "normalizer": norm_stats, "detector_config": config.to_dict()}


def _assign_publication_quality_tiers(rows: list[dict[str, Any]], *, defensive: bool = False) -> None:
    data_limited_path = {"short_path", "zero_and_stale", "zero_volume", "mixed_flag"}
    for row in rows:
        path_bucket = str(row.get("path_quality_bucket") or "unknown")
        tradability_bucket = str(row.get("tradability_quality_bucket") or "unknown")
        extreme_spread = _safe_float(row.get("extreme_spread_pct"))
        height_pct = _safe_float(row.get("pattern_height_pct"))
        balance = _safe_float(row.get("balance_ratio"))
        breakout_clearance = _safe_float(row.get("breakout_clearance_pct"))
        variant_confidence = _safe_float(row.get("variant_confidence"))
        mfe_pct = _safe_float(row.get("mfe_pct"))
        mae_pct = _safe_float(row.get("mae_pct"))
        mfe_mae_ratio = None if mfe_pct is None or mae_pct is None else float(mfe_pct) / max(float(mae_pct), 1.0)
        target_hit = _truthy(row.get("target_hit"))
        failure_5pct = _truthy(row.get("failure_5pct"))
        target_first = _truthy(row.get("target_first_before_adverse_5pct"))
        reasons: list[str] = []
        if path_bucket in data_limited_path or tradability_bucket == "impaired":
            row["publication_quality_score"] = 0.0
            row["publication_quality_tier"] = "data_limited"
            row["publication_quality_reasons"] = ",".join(filter(None, [f"path:{path_bucket}", f"tradability:{tradability_bucket}"]))
            continue
        score = 0.0
        score += _score_band(extreme_spread, good=1.0, weak=4.5, reverse=True, weight=0.18)
        score += _score_band(height_pct, good=12.0, weak=5.0, reverse=False, weight=0.15)
        score += _score_band(balance, good=0.65, weak=0.25, reverse=False, weight=0.13)
        score += _score_band(breakout_clearance, good=2.0, weak=0.75, reverse=False, weight=0.14)
        score += _score_band(variant_confidence, good=75.0, weak=50.0, reverse=False, weight=0.10)
        if path_bucket == "clean":
            score += 8.0
        else:
            reasons.append(f"path:{path_bucket}")
        if tradability_bucket == "clean":
            score += 5.0
        elif tradability_bucket == "usable":
            score += 2.0
            reasons.append("tradability:usable")
        else:
            reasons.append(f"tradability:{tradability_bucket}")
        if target_hit:
            score += 6.0
        else:
            reasons.append("no_target_hit")
        if target_first:
            score += 5.0
        else:
            reasons.append("not_target_first")
        if failure_5pct:
            reasons.append("failure_5pct")
        if mfe_mae_ratio is not None and mfe_mae_ratio < (1.15 if defensive else 1.30):
            reasons.append("weak_mfe_mae_ratio")
        if extreme_spread is not None and extreme_spread > 3.0:
            reasons.append("extremes_not_similar_enough")
        if balance is not None and balance < 0.45:
            reasons.append("unbalanced_legs")
        score = round(float(max(0.0, min(100.0, score))), 2)
        premium_path_ok = (
            target_hit
            and target_first
            and not failure_5pct
            and (mfe_mae_ratio is not None and mfe_mae_ratio >= (1.20 if defensive else 1.40))
            and (mae_pct is not None and mae_pct <= 22.0)
        )
        premium_geometry_ok = (
            extreme_spread is not None
            and extreme_spread <= 2.4
            and height_pct is not None
            and 7.0 <= height_pct <= 32.0
            and balance is not None
            and balance >= 0.45
            and breakout_clearance is not None
            and breakout_clearance >= 1.0
            and tradability_bucket in {"clean", "usable"}
        )
        if score >= 78.0 and path_bucket == "clean" and premium_geometry_ok and premium_path_ok:
            tier = "premium"
        elif score >= 61.0:
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
        "median_target_dist_pct": _median([row.get("target_dist_pct") for row in evals]),
        "median_quality_score": _median([row.get("pattern_quality_score") for row in rows]),
    }


def _group_table(rows: Sequence[Mapping[str, Any]], column: str, labels: Sequence[str]) -> Dict[str, Any]:
    return {label: _group_stats([row for row in rows if str(row.get(column) or "unknown") == label]) for label in labels}


def _path_quality_audit(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    buckets: Dict[str, int] = {}
    for row in rows:
        bucket = str(row.get("path_quality_bucket") or "unknown")
        buckets[bucket] = buckets.get(bucket, 0) + 1
    return {
        "bucket_counts": dict(sorted(buckets.items())),
        "median_coverage_60d": _median([row.get("evaluated_bars") for row in rows]),
        "median_missing_bar_rate_60d": _median([row.get("missing_bar_rate_60d") for row in rows]),
        "median_zero_volume_rate_60d": _median([row.get("zero_volume_rate_60d") for row in rows]),
        "median_price_limit_proxy_rate_60d": _median([row.get("price_limit_proxy_rate_60d") for row in rows]),
    }


def summarize(scan: Mapping[str, Any]) -> Dict[str, Any]:
    rows = list(scan.get("detections") or [])
    evals = [row for row in rows if row.get("mfe_pct") is not None]
    family = str(scan.get("pattern_key") or "double_patterns")
    direction = "up" if family == "double_bottoms" else "down"
    return {
        "generated_at": _utc_now(),
        "pattern_key": family,
        "symbols_scanned": int(scan.get("symbols_scanned") or 0),
        "detection_count": len(rows),
        "evaluated_count": len(evals),
        "up_breakouts": len(rows) if direction == "up" else 0,
        "down_breakouts": len(rows) if direction == "down" else 0,
        **_group_stats(rows),
        "breakout_groups": {"all": _group_stats(rows), "up": _group_stats(rows if direction == "up" else []), "down": _group_stats(rows if direction == "down" else [])},
        "variant_table": {label: _group_stats([row for row in rows if str(row.get("variant") or "unclassified") == label]) for label in ("AA", "AE", "EA", "EE", "unclassified")},
        "quality_table": {tier: _group_stats([row for row in rows if row.get("pattern_quality_tier") == tier]) for tier in ("clean", "usable", "loose")},
        "publication_quality_table": {tier: _group_stats([row for row in rows if row.get("publication_quality_tier") == tier]) for tier in ("premium", "standard", "loose", "data_limited")},
        "regime_groups": {regime: _group_stats([row for row in rows if str(row.get("market_regime") or "unknown") == regime]) for regime in ("bull", "bear", "unknown")},
        "market_group_table": {group: _group_stats([row for row in rows if str(row.get("market_group") or "Outside VN100") == group]) for group in ("VN30", "VN100 ex VN30", "Outside VN100")},
        "liquidity_proxy_table": _group_table(rows, "liquidity_bucket", ("high", "mid", "low", "unknown")),
        "regime_proxy_table": _group_table(rows, "market_regime", ("bull", "bear", "unknown")),
        "path_quality_audit": _path_quality_audit(rows),
        "symbol_concentration": {
            "symbols_with_events": len({str(row.get("symbol")) for row in rows if row.get("symbol")}),
            "top10_symbol_share_pct": round(float(pd.Series([str(row.get("symbol")) for row in rows if row.get("symbol")]).value_counts().head(10).sum()) / max(len(rows), 1) * 100.0, 2),
        },
        "quantile_metrics": {
            "fav_exc_pct": _quantiles([row.get("mfe_pct") for row in evals]),
            "adv_exc_pct": _quantiles([row.get("mae_pct") for row in evals]),
            "target_dist_pct": _quantiles([row.get("target_dist_pct") for row in evals]),
        },
        "experiment_note": "Double Pattern scanner uses first extreme, neckline, second extreme, close-confirmed breakout, and Adam/Eve width classification.",
    }


EVENT_FIELDS = [
    "detection_id",
    "symbol",
    "variant",
    "variant_confidence",
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
    "pattern_width_bars",
    "pattern_height_pct",
    "pole_move_pct",
    "flag_to_pole_pct",
    "neckline_price",
    "neckline_height_abs",
    "extreme_spread_pct",
    "prior_trend_pct",
    "breakout_clearance_pct",
    "left_spacing_bars",
    "right_spacing_bars",
    "balance_ratio",
    "breakout_volume_ratio",
    "first_extreme_price",
    "middle_extreme_price",
    "second_extreme_price",
    "evaluated_bars",
    "is_primary_event_60d",
    "liquidity_bucket",
    "path_quality_bucket",
    "tradability_quality_bucket",
    "tradability_quality_score",
    "missing_bar_rate_60d",
    "zero_volume_rate_60d",
    "price_limit_proxy_rate_60d",
    "publication_quality_score",
    "publication_quality_tier",
    "publication_quality_reasons",
]


def _add_target_calibration(stats: Dict[str, Any], scan: Mapping[str, Any], path_rows: Sequence[Mapping[str, Any]]) -> None:
    from scanner.research_support_analysis import PatternArtifacts, build_target_calibration_decisions, target_sensitivity

    events = pd.DataFrame(list(scan.get("detections") or []))
    path = pd.DataFrame(list(path_rows))
    family = str(scan.get("pattern_key") or "double_patterns")
    if events.empty:
        stats["target_family_sensitivity"] = []
        stats["target_calibration_decision"] = None
        return
    if "event_id" not in events.columns and "detection_id" in events.columns:
        events["event_id"] = events["detection_id"]
    sensitivity = target_sensitivity(PatternArtifacts(family, events, path), family, horizon_days=120)
    stats["target_family_sensitivity"] = sensitivity
    stats["target_calibration_decision"] = (build_target_calibration_decisions(sensitivity, family_labels=(family,)) or [None])[0]
    stats["target_family"] = {"local_base": 0.5, "local_stretch": 0.75, "legacy_full_height": 1.0}


def scan_double_patterns_db(
    *,
    family: str,
    db_path: Path,
    out_dir: Path,
    allowed_symbols: Optional[Sequence[str]] = None,
    detector_config: Optional[Mapping[str, Any]] = None,
    limit_symbols: Optional[int] = None,
    index_db: Path = DEFAULT_INDEX_DB,
    index_symbol: str = DEFAULT_INDEX_SYMBOL,
) -> dict[str, Path]:
    if family not in {"double_bottoms", "double_tops"}:
        raise ValueError("family must be double_bottoms or double_tops")
    out_dir.mkdir(parents=True, exist_ok=True)
    config = DoublePatternConfig.from_mapping(detector_config)
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
                rows, stats = scan_symbol(frame, family=family, detector_config=config)
                if rows:
                    series_by_symbol[symbol] = frame
                detections.extend(rows)
                symbol_stats.append({"symbol": symbol, "detections": len(rows), **stats})
            except Exception as exc:
                symbol_stats.append({"symbol": symbol, "detections": 0, "error": str(exc)})
    finally:
        conn.close()
    for i, row in enumerate(detections):
        row["detection_id"] = f"{family}:{i + 1:06d}"
    detections, regime_meta = classify_market_regimes(detections, index_db=index_db, index_symbol=index_symbol, anchor_field="breakout_date")
    market_group_meta = attach_current_market_groups(detections)
    scan: dict[str, Any] = {
        "generated_at": _utc_now(),
        "source": "Market Cache latest.sqlite stock_price_history",
        "db_path": str(db_path),
        "pattern_key": family,
        "symbols_scanned": len(symbols),
        "detections": detections,
        "symbol_stats": symbol_stats,
        "regime": regime_meta,
        "market_group": market_group_meta,
        "detector_config": config.to_dict(),
    }
    _enrich_events_from_series(scan, series_by_symbol, corporate_db=index_db)
    _assign_publication_quality_tiers(scan["detections"], defensive=(family == "double_tops"))
    stats = summarize(scan)
    stats["source"] = scan["source"]
    stats["db_source_meta"] = _db_meta(db_path)
    stats["detector_config"] = config.to_dict()
    path_rows = _path_rows_from_series(scan, series_by_symbol, horizon_bars=120)
    _add_target_calibration(stats, scan, path_rows)
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
    parser = argparse.ArgumentParser(description="Run Double Pattern scanner against Market Cache latest.sqlite.")
    parser.add_argument("--family", choices=["double_bottoms", "double_tops"], required=True)
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--market-stats-json", default=str(DEFAULT_MARKET_STATS_JSON))
    parser.add_argument("--limit-symbols", type=int, default=None)
    args = parser.parse_args()
    active_meta = _load_active_symbols(Path(args.market_stats_json) if args.market_stats_json else None)
    active_symbols = active_meta.get("active_symbols") if active_meta.get("enabled") else None
    paths = scan_double_patterns_db(
        family=args.family,
        db_path=Path(args.db),
        out_dir=Path(args.out_dir) / args.family / "db_active",
        allowed_symbols=active_symbols,
        limit_symbols=args.limit_symbols,
    )
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
