"""Diamond Bottoms / Diamond Tops scanner.

Diamonds are not triangles or wedges with a different label.  Bulkowski's
identification rule is two-stage: prices widen first with higher highs and
lower lows, then narrow with lower highs and higher lows.  The top/bottom
classification comes from the trend entering the pattern, while the breakout
itself can occur in either direction.
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
from scanner.v2.pipes import (  # noqa: E402
    _evaluate_detection,
    _mean,
    _median,
    _prior_trend_pct,
    _quantiles,
    _rate,
    _rolling_volume_ratio,
    _safe_float,
    _score_band,
    _truthy,
)
from scanner.v2.source_data import attach_current_market_groups, classify_market_regimes  # noqa: E402


DIAMOND_BOTTOMS = "diamond_bottoms"
DIAMOND_TOPS = "diamond_tops"
DIAMOND_PATTERNS = (DIAMOND_BOTTOMS, DIAMOND_TOPS)
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/diamond_family")


@dataclass(frozen=True)
class DiamondConfig:
    min_width_bars: int = 14
    max_width_bars: int = 75
    min_height_pct: float = 7.0
    max_height_pct: float = 70.0
    min_prior_trend_abs_pct: float = 5.0
    prior_trend_lookback_bars: int = 45
    min_expansion_ratio: float = 1.10
    max_contraction_ratio: float = 0.88
    min_left_high_rise_pct: float = 2.0
    min_left_low_drop_pct: float = 2.0
    min_right_high_drop_pct: float = 1.4
    min_right_low_rise_pct: float = 1.4
    breakout_search_bars: int = 30
    breakout_threshold: float = 0.003
    breakout_cooldown_bars: int = 45
    max_events_per_symbol: int = 18

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]] = None) -> "DiamondConfig":
        if value is None:
            return cls()
        allowed = {field.name for field in fields(cls)}
        return cls(**{key: item for key, item in value.items() if key in allowed})

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _lin_slope(xs: Sequence[float], ys: Sequence[float]) -> float:
    if len(xs) < 2 or len(ys) < 2:
        return 0.0
    try:
        return float(np.polyfit(np.asarray(xs, dtype=float), np.asarray(ys, dtype=float), 1)[0])
    except Exception:
        return 0.0


def _pct_change(a: float, b: float) -> float:
    if a <= 0:
        return 0.0
    return (b - a) / a * 100.0


def _volume_slope_pct(df: pd.DataFrame, start: int, end: int) -> Optional[float]:
    window = pd.to_numeric(df.iloc[start : end + 1]["volume"], errors="coerce").dropna()
    if len(window) < 6 or float(window.mean()) <= 0:
        return None
    slope = _lin_slope(range(len(window)), window.tolist())
    return round(float(slope / max(float(window.mean()), 1e-9) * 100.0), 4)


class DiamondDetector:
    def __init__(self, pattern_key: str, config: Optional[DiamondConfig | Mapping[str, Any]] = None) -> None:
        if pattern_key not in DIAMOND_PATTERNS:
            raise ValueError(f"unsupported diamond pattern {pattern_key}")
        self.pattern_key = pattern_key
        self.config = config if isinstance(config, DiamondConfig) else DiamondConfig.from_mapping(config)

    def _typed_pivots(self, pivots: Sequence[Pivot], pivot_type: PivotType) -> list[Pivot]:
        return [pivot for pivot in pivots if pivot.type == pivot_type]

    def _shape_metrics(self, df: pd.DataFrame, pivots: Sequence[Pivot]) -> Optional[dict[str, Any]]:
        if len(pivots) < 6:
            return None
        idxs = [int(pivot.idx) for pivot in pivots]
        if idxs != sorted(idxs) or len(set(idxs)) != len(idxs):
            return None
        start_idx, end_idx = min(idxs), max(idxs)
        width = end_idx - start_idx + 1
        if width < self.config.min_width_bars or width > self.config.max_width_bars:
            return None

        mid_idx = int(pivots[len(pivots) // 2].idx)
        left = [pivot for pivot in pivots if int(pivot.idx) <= mid_idx]
        right = [pivot for pivot in pivots if int(pivot.idx) >= mid_idx]
        left_highs = self._typed_pivots(left, PivotType.HIGH)
        left_lows = self._typed_pivots(left, PivotType.LOW)
        right_highs = self._typed_pivots(right, PivotType.HIGH)
        right_lows = self._typed_pivots(right, PivotType.LOW)
        if min(len(left_highs), len(left_lows), len(right_highs), len(right_lows)) < 2:
            return None

        left_high_rise = _pct_change(float(left_highs[0].price), float(left_highs[-1].price))
        left_low_drop = _pct_change(float(left_lows[0].price), float(left_lows[-1].price)) * -1.0
        right_high_drop = _pct_change(float(right_highs[0].price), float(right_highs[-1].price)) * -1.0
        right_low_rise = _pct_change(float(right_lows[0].price), float(right_lows[-1].price))
        if left_high_rise < self.config.min_left_high_rise_pct:
            return None
        if left_low_drop < self.config.min_left_low_drop_pct:
            return None
        if right_high_drop < self.config.min_right_high_drop_pct:
            return None
        if right_low_rise < self.config.min_right_low_rise_pct:
            return None

        first_range = float(df.iloc[start_idx : max(start_idx + 3, mid_idx)]["high"].max() - df.iloc[start_idx : max(start_idx + 3, mid_idx)]["low"].min())
        mid_window = df.iloc[max(start_idx, mid_idx - 4) : min(len(df), mid_idx + 5)]
        last_range = float(df.iloc[min(mid_idx + 1, end_idx) : end_idx + 1]["high"].max() - df.iloc[min(mid_idx + 1, end_idx) : end_idx + 1]["low"].min())
        mid_range = float(mid_window["high"].max() - mid_window["low"].min()) if not mid_window.empty else 0.0
        if first_range <= 0 or mid_range <= 0 or last_range <= 0:
            return None
        expansion_ratio = mid_range / first_range
        contraction_ratio = last_range / mid_range
        if expansion_ratio < self.config.min_expansion_ratio or contraction_ratio > self.config.max_contraction_ratio:
            return None

        high_boundary = float(df.iloc[start_idx : end_idx + 1]["high"].max())
        low_boundary = float(df.iloc[start_idx : end_idx + 1]["low"].min())
        height_abs = high_boundary - low_boundary
        if height_abs <= 0:
            return None
        right_upper = float(max(p.price for p in right_highs[-2:]))
        right_lower = float(min(p.price for p in right_lows[-2:]))
        height_pct = height_abs / max(right_upper if self.pattern_key == DIAMOND_BOTTOMS else right_lower, 1e-9) * 100.0
        if height_pct < self.config.min_height_pct or height_pct > self.config.max_height_pct:
            return None

        prior = _prior_trend_pct(df, start_idx, self.config.prior_trend_lookback_bars)
        if prior is None:
            return None
        if self.pattern_key == DIAMOND_BOTTOMS and prior > -self.config.min_prior_trend_abs_pct:
            return None
        if self.pattern_key == DIAMOND_TOPS and prior < self.config.min_prior_trend_abs_pct:
            return None

        upper_left_slope = _lin_slope([p.idx for p in left_highs], [p.price for p in left_highs])
        lower_left_slope = _lin_slope([p.idx for p in left_lows], [p.price for p in left_lows])
        upper_right_slope = _lin_slope([p.idx for p in right_highs], [p.price for p in right_highs])
        lower_right_slope = _lin_slope([p.idx for p in right_lows], [p.price for p in right_lows])

        return {
            "formation_start_idx": int(start_idx),
            "formation_end_idx": int(end_idx),
            "formation_start_date": str(pd.Timestamp(df.iloc[start_idx]["date"]).date()),
            "formation_end_date": str(pd.Timestamp(df.iloc[end_idx]["date"]).date()),
            "pattern_width_bars": int(width),
            "pattern_height_pct": round(float(height_pct), 2),
            "diamond_shape": "widening_then_narrowing",
            "expansion_ratio": round(float(expansion_ratio), 3),
            "contraction_ratio": round(float(contraction_ratio), 3),
            "left_high_rise_pct": round(float(left_high_rise), 2),
            "left_low_drop_pct": round(float(left_low_drop), 2),
            "right_high_drop_pct": round(float(right_high_drop), 2),
            "right_low_rise_pct": round(float(right_low_rise), 2),
            "upper_left_slope_per_bar": round(float(upper_left_slope), 6),
            "lower_left_slope_per_bar": round(float(lower_left_slope), 6),
            "upper_right_slope_per_bar": round(float(upper_right_slope), 6),
            "lower_right_slope_per_bar": round(float(lower_right_slope), 6),
            "high_boundary_price": round(float(high_boundary), 4),
            "low_boundary_price": round(float(low_boundary), 4),
            "right_upper_breakout_level": round(float(right_upper), 4),
            "right_lower_breakout_level": round(float(right_lower), 4),
            "prior_trend_pct": round(float(prior), 2),
            "volume_trend_slope_pct": _volume_slope_pct(df, start_idx, end_idx),
            "pivot_indices": [int(x) for x in idxs],
            "pivot_prices": [round(float(p.price), 4) for p in pivots],
        }

    def _breakout_candidate(self, df: pd.DataFrame, metrics: Mapping[str, Any]) -> Optional[tuple[int, str, float, float]]:
        end_idx = int(metrics["formation_end_idx"])
        up_level = float(metrics["right_upper_breakout_level"])
        down_level = float(metrics["right_lower_breakout_level"])
        up_threshold = up_level * (1.0 + self.config.breakout_threshold)
        down_threshold = down_level * (1.0 - self.config.breakout_threshold)
        for idx in range(end_idx + 1, min(len(df), end_idx + 1 + self.config.breakout_search_bars)):
            close = _safe_float(df.iloc[idx].get("close"))
            if close is None:
                continue
            if close > up_threshold:
                return idx, "up", float(close), (close - up_level) / max(up_level, 1e-9) * 100.0
            if close < down_threshold:
                return idx, "down", float(close), (down_level - close) / max(down_level, 1e-9) * 100.0
        return None

    def scan_window(self, df: pd.DataFrame, pivots: Sequence[Pivot]) -> Optional[Dict[str, Any]]:
        metrics = self._shape_metrics(df, pivots)
        if not metrics:
            return None
        candidate = self._breakout_candidate(df, metrics)
        if candidate is None:
            return None
        breakout_idx, direction, breakout_price, clearance_pct = candidate
        height_abs = float(metrics["high_boundary_price"]) - float(metrics["low_boundary_price"])
        target_price = breakout_price + height_abs if direction == "up" else breakout_price - height_abs
        if target_price <= 0:
            return None
        target_dist_pct = abs(target_price - breakout_price) / breakout_price * 100.0
        if target_dist_pct <= 0 or target_dist_pct > 90:
            return None
        lag = breakout_idx - int(metrics["formation_end_idx"])

        score = 42.0
        score += _score_band(float(metrics["expansion_ratio"]), good=1.45, weak=self.config.min_expansion_ratio, weight=0.15)
        score += _score_band(float(metrics["contraction_ratio"]), good=0.50, weak=self.config.max_contraction_ratio, reverse=True, weight=0.16)
        score += _score_band(float(metrics["left_high_rise_pct"]), good=6.0, weak=self.config.min_left_high_rise_pct, weight=0.08)
        score += _score_band(float(metrics["left_low_drop_pct"]), good=6.0, weak=self.config.min_left_low_drop_pct, weight=0.08)
        score += _score_band(float(metrics["right_high_drop_pct"]), good=5.0, weak=self.config.min_right_high_drop_pct, weight=0.08)
        score += _score_band(float(metrics["right_low_rise_pct"]), good=5.0, weak=self.config.min_right_low_rise_pct, weight=0.08)
        score += _score_band(float(lag), good=3.0, weak=float(self.config.breakout_search_bars), reverse=True, weight=0.10)
        if metrics.get("volume_trend_slope_pct") is not None and float(metrics["volume_trend_slope_pct"]) <= 0:
            score += 4.0
        score += min(5.0, abs(float(metrics["prior_trend_pct"])) / 3.0)
        score = int(max(0, min(100, round(score))))
        return {
            **metrics,
            "breakout_idx": int(breakout_idx),
            "breakout_date": str(pd.Timestamp(df.iloc[int(breakout_idx)]["date"]).date()),
            "breakout_direction": direction,
            "breakout_price": round(float(breakout_price), 4),
            "target_price": round(float(target_price), 4),
            "target_dist_pct": round(float(target_dist_pct), 2),
            "breakout_lag_bars": int(lag),
            "breakout_clearance_pct": round(float(clearance_pct), 2),
            "variant": self.pattern_key,
            "pattern_quality_score": score,
            "pattern_quality_tier": "clean" if score >= 78 else ("usable" if score >= 62 else "loose"),
        }


def scan_symbol(
    df_raw: pd.DataFrame,
    *,
    pattern_key: str,
    max_events_per_symbol: Optional[int] = None,
    detector_config: Optional[DiamondConfig | Mapping[str, Any]] = None,
) -> Tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(df_raw) < 180:
        return [], {"rows": int(len(df_raw)), "skipped": "too_few_rows"}
    config = detector_config if isinstance(detector_config, DiamondConfig) else DiamondConfig.from_mapping(detector_config)
    max_events = int(max_events_per_symbol if max_events_per_symbol is not None else config.max_events_per_symbol)
    df, norm_stats = OHLCVNormalizer().normalize(df_raw)
    pivots = PivotDetector().detect_pivots(df, pivot_type="minor")
    detector = DiamondDetector(pattern_key, config)
    out: list[dict[str, Any]] = []
    used_breakouts: list[int] = []
    symbol = str(df.iloc[0]["symbol"])
    for window_size in (6, 7, 8):
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
        score = 0.0
        score += _score_band(_safe_float(row.get("expansion_ratio")), good=1.45, weak=1.10, weight=0.14)
        score += _score_band(_safe_float(row.get("contraction_ratio")), good=0.50, weak=0.88, reverse=True, weight=0.18)
        score += _score_band(_safe_float(row.get("breakout_lag_bars")), good=3.0, weak=30.0, reverse=True, weight=0.12)
        score += _score_band(_safe_float(row.get("breakout_clearance_pct")), good=2.0, weak=0.3, weight=0.10)
        score += _score_band(abs(float(row.get("prior_trend_pct") or 0.0)), good=16.0, weak=5.0, weight=0.10)
        if row.get("volume_trend_slope_pct") is not None and float(row.get("volume_trend_slope_pct") or 0.0) <= 0:
            score += 4.0
        if 10.0 <= float(row.get("pattern_height_pct") or 0.0) <= 35.0:
            score += 7.0
        if path_bucket == "clean":
            score += 8.0
        else:
            score += 3.0
        if tradability_bucket == "clean":
            score += 5.0
        elif tradability_bucket == "usable":
            score += 2.0
        if _truthy(row.get("target_first_before_adverse_5pct")):
            score += 4.0
        reasons: list[str] = []
        if float(row.get("contraction_ratio") or 1.0) > 0.75:
            reasons.append("weak_contraction")
        if float(row.get("breakout_lag_bars") or 99.0) > 15:
            reasons.append("late_breakout")
        if float(row.get("pattern_height_pct") or 0.0) > 45.0:
            reasons.append("very_tall_target")
        score = round(float(max(0.0, min(100.0, score))), 2)
        tier = "premium" if score >= 72 and path_bucket == "clean" else ("standard" if score >= 54 else "loose")
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
        "median_publication_quality_score": _median([row.get("publication_quality_score") for row in rows]),
        "median_expansion_ratio": _median([row.get("expansion_ratio") for row in rows]),
        "median_contraction_ratio": _median([row.get("contraction_ratio") for row in rows]),
        "median_breakout_lag_bars": _median([row.get("breakout_lag_bars") for row in rows]),
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
            "pattern_width_bars": _quantiles([row.get("pattern_width_bars") for row in rows]),
            "expansion_ratio": _quantiles([row.get("expansion_ratio") for row in rows]),
            "contraction_ratio": _quantiles([row.get("contraction_ratio") for row in rows]),
            "breakout_lag_bars": _quantiles([row.get("breakout_lag_bars") for row in rows]),
        },
        "experiment_note": "Diamond scanner uses source-grounded daily geometry: prior trend, widening first half, narrowing second half, and close confirmation beyond the right-side boundary.",
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
    "throwback_pullback_30d",
    "pattern_quality_score",
    "pattern_quality_tier",
    "publication_quality_score",
    "publication_quality_tier",
    "publication_quality_reasons",
    "pattern_width_bars",
    "pattern_height_pct",
    "prior_trend_pct",
    "diamond_shape",
    "expansion_ratio",
    "contraction_ratio",
    "left_high_rise_pct",
    "left_low_drop_pct",
    "right_high_drop_pct",
    "right_low_rise_pct",
    "breakout_lag_bars",
    "breakout_clearance_pct",
    "volume_trend_slope_pct",
    "high_boundary_price",
    "low_boundary_price",
    "right_upper_breakout_level",
    "right_lower_breakout_level",
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


def scan_diamonds_db(
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
    config = DiamondConfig.from_mapping(detector_config)
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
                    series_by_symbol[str(symbol).upper()] = OHLCVNormalizer().normalize(frame)[0]
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
    parser = argparse.ArgumentParser(description="Run Diamond Family scanners against Market Cache latest.sqlite.")
    parser.add_argument("--pattern", choices=[*DIAMOND_PATTERNS, "all"], default="all")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--market-stats-json", default=str(DEFAULT_MARKET_STATS_JSON))
    parser.add_argument("--limit-symbols", type=int, default=None)
    args = parser.parse_args()
    active_meta = _load_active_symbols(Path(args.market_stats_json) if args.market_stats_json else None)
    active_symbols = active_meta.get("active_symbols") if active_meta.get("enabled") else None
    patterns = list(DIAMOND_PATTERNS) if args.pattern == "all" else [args.pattern]
    outputs: dict[str, str] = {}
    for pattern_key in patterns:
        paths = scan_diamonds_db(
            pattern_key=pattern_key,
            db_path=Path(args.db),
            out_dir=Path(args.out_dir) / pattern_key / "db_active",
            allowed_symbols=active_symbols,
            limit_symbols=args.limit_symbols,
        )
        outputs[pattern_key] = str(paths["statistics"])
    print(json.dumps({"status": "PASS", "outputs": outputs}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
