"""Rounding Bottoms / Rounding Tops scanner.

Bulkowski treats rounding turns as long, saucer-like weekly formations.  This
module keeps that geometry separate from Cup, Scallop, and Double patterns:
the scanner looks for a broad bowl or inverted bowl, then waits for close
confirmation beyond the right lip/rim before measuring outcomes.
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
    _quantiles,
    _rate,
    _safe_float,
    _score_band,
    _to_weekly_ohlcv,
    _truthy,
)
from scanner.v2.source_data import attach_current_market_groups, classify_market_regimes  # noqa: E402


ROUNDING_BOTTOMS = "rounding_bottoms"
ROUNDING_TOPS = "rounding_tops"
ROUNDING_PATTERNS = (ROUNDING_BOTTOMS, ROUNDING_TOPS)
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/rounding_family")


@dataclass(frozen=True)
class RoundingConfig:
    min_width_bars: int = 16
    max_width_bars: int = 104
    min_half_width_bars: int = 6
    max_half_width_bars: int = 58
    confirmation_search_bars: int = 52
    confirmation_threshold: float = 0.003
    min_height_pct: float = 10.0
    max_height_pct: float = 90.0
    max_lip_mismatch_pct: float = 28.0
    min_center_position: float = 0.30
    max_center_position: float = 0.72
    min_bottom_zone_fraction: float = 0.10
    bottom_zone_height_fraction: float = 0.30
    min_roundness_corr: float = 0.18
    prior_trend_lookback_bars: int = 52
    breakout_cooldown_bars: int = 70
    max_events_per_symbol: int = 10

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]] = None) -> "RoundingConfig":
        if value is None:
            return cls()
        allowed = {field.name for field in fields(cls)}
        return cls(**{key: item for key, item in value.items() if key in allowed})

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _prior_trend_pct(df: pd.DataFrame, start_idx: int, lookback: int) -> Optional[float]:
    left = max(0, int(start_idx) - int(lookback))
    if start_idx <= left:
        return None
    anchor = _safe_float(df.iloc[left].get("close"))
    start = _safe_float(df.iloc[int(start_idx)].get("close"))
    if anchor is None or start is None or anchor <= 0:
        return None
    return round(float((start - anchor) / anchor * 100.0), 2)


def _safe_corr(a: Sequence[float], b: Sequence[float]) -> float:
    left = pd.to_numeric(pd.Series(list(a)), errors="coerce")
    right = pd.to_numeric(pd.Series(list(b)), errors="coerce")
    frame = pd.concat([left, right], axis=1).dropna()
    if len(frame) < 4 or float(frame.iloc[:, 0].std()) == 0.0 or float(frame.iloc[:, 1].std()) == 0.0:
        return 0.0
    value = float(frame.iloc[:, 0].corr(frame.iloc[:, 1]))
    return value if math.isfinite(value) else 0.0


class RoundingDetector:
    def __init__(self, pattern_key: str, config: Optional[RoundingConfig | Mapping[str, Any]] = None) -> None:
        if pattern_key not in ROUNDING_PATTERNS:
            raise ValueError(f"unsupported rounding pattern {pattern_key}")
        self.pattern_key = pattern_key
        self.config = config if isinstance(config, RoundingConfig) else RoundingConfig.from_mapping(config)

    def _is_local_extreme(self, df: pd.DataFrame, idx: int, *, side: str, radius: int = 4) -> bool:
        left = max(0, idx - radius)
        right = min(len(df), idx + radius + 1)
        if side == "bottom":
            return float(df.iloc[idx]["low"]) <= float(df.iloc[left:right]["low"].min())
        return float(df.iloc[idx]["high"]) >= float(df.iloc[left:right]["high"].max())

    def _confirmation(self, df: pd.DataFrame, end_idx: int, level: float, direction: str) -> Optional[tuple[int, float]]:
        if direction == "up":
            threshold = level * (1.0 + self.config.confirmation_threshold)
        else:
            threshold = level * (1.0 - self.config.confirmation_threshold)
        for idx in range(end_idx + 1, min(len(df), end_idx + 1 + self.config.confirmation_search_bars)):
            close = _safe_float(df.iloc[idx].get("close"))
            if close is None:
                continue
            if direction == "up" and close > threshold:
                return idx, float(close)
            if direction == "down" and close < threshold:
                return idx, float(close)
        return None

    def _candidate(self, df: pd.DataFrame, center_idx: int) -> Optional[dict[str, Any]]:
        if self.pattern_key == ROUNDING_BOTTOMS:
            if not self._is_local_extreme(df, center_idx, side="bottom"):
                return None
            left = df.iloc[max(0, center_idx - self.config.max_half_width_bars) : center_idx - self.config.min_half_width_bars + 1]
            right = df.iloc[center_idx + self.config.min_half_width_bars : min(len(df), center_idx + self.config.max_half_width_bars + 1)]
            if left.empty or right.empty:
                return None
            left_lip_idx = int(left["high"].idxmax())
            right_lip_idx = int(right["high"].idxmax())
            low_idx = center_idx
            left_lip = float(df.iloc[left_lip_idx]["high"])
            right_lip = float(df.iloc[right_lip_idx]["high"])
            extreme = float(df.iloc[low_idx]["low"])
            direction = "up"
            breakout_level = right_lip
            target_sign = 1.0
            shape_label = "rounded_bowl"
            seq = "U"
        else:
            if not self._is_local_extreme(df, center_idx, side="top"):
                return None
            left = df.iloc[max(0, center_idx - self.config.max_half_width_bars) : center_idx - self.config.min_half_width_bars + 1]
            right = df.iloc[center_idx + self.config.min_half_width_bars : min(len(df), center_idx + self.config.max_half_width_bars + 1)]
            if left.empty or right.empty:
                return None
            left_lip_idx = int(left["low"].idxmin())
            right_lip_idx = int(right["low"].idxmin())
            high_idx = center_idx
            left_lip = float(df.iloc[left_lip_idx]["low"])
            right_lip = float(df.iloc[right_lip_idx]["low"])
            extreme = float(df.iloc[high_idx]["high"])
            direction = "down"
            breakout_level = right_lip
            target_sign = -1.0
            shape_label = "inverted_rounded_bowl"
            seq = "INV_U"

        start_idx = int(left_lip_idx)
        end_idx = int(right_lip_idx)
        if not (start_idx < center_idx < end_idx):
            return None
        width = end_idx - start_idx + 1
        if width < self.config.min_width_bars or width > self.config.max_width_bars:
            return None
        center_position = (center_idx - start_idx) / max(width - 1, 1)
        if center_position < self.config.min_center_position or center_position > self.config.max_center_position:
            return None
        lip_avg = (left_lip + right_lip) / 2.0
        if lip_avg <= 0:
            return None
        lip_mismatch_pct = abs(right_lip - left_lip) / lip_avg * 100.0
        if lip_mismatch_pct > self.config.max_lip_mismatch_pct:
            return None
        height_abs = (lip_avg - extreme) if direction == "up" else (extreme - lip_avg)
        if height_abs <= 0:
            return None
        height_pct = height_abs / max(abs(breakout_level), 1e-9) * 100.0
        if height_pct < self.config.min_height_pct or height_pct > self.config.max_height_pct:
            return None
        window = df.iloc[start_idx : end_idx + 1].copy()
        if direction == "up":
            curve = pd.to_numeric(window["low"], errors="coerce").to_numpy(dtype=float)
            zone = curve <= extreme + height_abs * self.config.bottom_zone_height_fraction
            roundness_corr = _safe_corr(np.abs(np.arange(len(curve)) - (center_idx - start_idx)), curve)
        else:
            curve = pd.to_numeric(window["high"], errors="coerce").to_numpy(dtype=float)
            zone = curve >= extreme - height_abs * self.config.bottom_zone_height_fraction
            roundness_corr = _safe_corr(np.abs(np.arange(len(curve)) - (center_idx - start_idx)), -curve)
        bottom_zone_fraction = float(np.mean(zone)) if len(zone) else 0.0
        if bottom_zone_fraction < self.config.min_bottom_zone_fraction:
            return None
        if roundness_corr < self.config.min_roundness_corr:
            return None
        confirmation = self._confirmation(df, end_idx, breakout_level, direction)
        if confirmation is None:
            return None
        breakout_idx, breakout_price = confirmation
        target_price = breakout_price + target_sign * height_abs
        if target_price <= 0:
            return None
        target_dist_pct = abs(target_price - breakout_price) / max(breakout_price, 1e-9) * 100.0
        if target_dist_pct <= 0 or target_dist_pct > 100:
            return None
        prior = _prior_trend_pct(df, start_idx, self.config.prior_trend_lookback_bars)
        lag = int(breakout_idx - end_idx)
        score = 42.0
        score += _score_band(width, good=52.0, weak=float(self.config.min_width_bars), weight=0.14)
        score += _score_band(height_pct, good=24.0, weak=self.config.min_height_pct, weight=0.16)
        score += _score_band(lip_mismatch_pct, good=6.0, weak=self.config.max_lip_mismatch_pct, reverse=True, weight=0.16)
        score += _score_band(bottom_zone_fraction * 100.0, good=22.0, weak=self.config.min_bottom_zone_fraction * 100.0, weight=0.12)
        score += _score_band(roundness_corr, good=0.62, weak=self.config.min_roundness_corr, weight=0.18)
        score += _score_band(lag, good=8.0, weak=float(self.config.confirmation_search_bars), reverse=True, weight=0.12)
        score = round(float(max(0.0, min(100.0, score))), 2)
        return {
            "formation_start_idx": start_idx,
            "formation_end_idx": end_idx,
            "formation_start_date": str(pd.Timestamp(df.iloc[start_idx]["date"]).date()),
            "formation_end_date": str(pd.Timestamp(df.iloc[end_idx]["date"]).date()),
            "center_idx": int(center_idx),
            "center_date": str(pd.Timestamp(df.iloc[center_idx]["date"]).date()),
            "left_lip_idx": int(left_lip_idx),
            "right_lip_idx": int(right_lip_idx),
            "left_lip_price": round(float(left_lip), 4),
            "right_lip_price": round(float(right_lip), 4),
            "extreme_price": round(float(extreme), 4),
            "breakout_level": round(float(breakout_level), 4),
            "pattern_width_bars": int(width),
            "pattern_height_pct": round(float(height_pct), 2),
            "lip_mismatch_pct": round(float(lip_mismatch_pct), 2),
            "center_position": round(float(center_position), 3),
            "bottom_zone_fraction": round(float(bottom_zone_fraction), 3),
            "roundness_corr": round(float(roundness_corr), 3),
            "prior_trend_pct": prior,
            "breakout_idx": int(breakout_idx),
            "breakout_date": str(pd.Timestamp(df.iloc[breakout_idx]["date"]).date()),
            "breakout_direction": direction,
            "breakout_price": round(float(breakout_price), 4),
            "target_price": round(float(target_price), 4),
            "target_dist_pct": round(float(target_dist_pct), 2),
            "breakout_lag_bars": int(lag),
            "variant": self.pattern_key,
            "rounding_shape": shape_label,
            "sequence_tag": seq,
            "pattern_quality_score": score,
            "pattern_quality_tier": "clean" if score >= 74 else ("usable" if score >= 58 else "loose"),
        }

    def scan(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        used_breakouts: list[int] = []
        for center_idx in range(self.config.min_half_width_bars, len(df) - self.config.min_half_width_bars):
            candidate = self._candidate(df, center_idx)
            if not candidate:
                continue
            breakout_idx = int(candidate["breakout_idx"])
            if any(abs(breakout_idx - prev) <= self.config.breakout_cooldown_bars for prev in used_breakouts):
                continue
            out.append(candidate)
            used_breakouts.append(breakout_idx)
            if len(out) >= self.config.max_events_per_symbol:
                break
        return out


def scan_symbol(
    df_raw: pd.DataFrame,
    *,
    pattern_key: str,
    detector_config: Optional[RoundingConfig | Mapping[str, Any]] = None,
) -> Tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(df_raw) < 260:
        return [], {"rows": int(len(df_raw)), "skipped": "too_few_rows"}
    config = detector_config if isinstance(detector_config, RoundingConfig) else RoundingConfig.from_mapping(detector_config)
    weekly_raw = _to_weekly_ohlcv(df_raw)
    if len(weekly_raw) < max(90, config.min_width_bars + config.confirmation_search_bars + 12):
        return [], {"rows": int(len(df_raw)), "weekly_rows": int(len(weekly_raw)), "skipped": "too_few_weekly_rows"}
    df, norm_stats = OHLCVNormalizer().normalize(weekly_raw)
    detector = RoundingDetector(pattern_key, config)
    rows = detector.scan(df)
    symbol = str(df.iloc[0]["symbol"])
    out: list[dict[str, Any]] = []
    for candidate in rows:
        record = {"symbol": symbol, "pattern_key": pattern_key, **candidate}
        record.update(_evaluate_detection(df, record, lookahead=156))
        out.append(record)
    return out, {"rows": int(len(df_raw)), "weekly_rows": int(len(df)), "detections": int(len(out)), "normalizer": norm_stats, "detector_config": config.to_dict()}


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
        score += _score_band(float(row.get("pattern_width_bars") or 0.0), good=52.0, weak=16.0, weight=0.16)
        score += _score_band(float(row.get("pattern_height_pct") or 0.0), good=24.0, weak=10.0, weight=0.16)
        score += _score_band(float(row.get("lip_mismatch_pct") or 99.0), good=6.0, weak=28.0, reverse=True, weight=0.16)
        score += _score_band(float(row.get("roundness_corr") or 0.0), good=0.62, weak=0.18, weight=0.18)
        score += _score_band(float(row.get("breakout_lag_bars") or 99.0), good=8.0, weak=52.0, reverse=True, weight=0.12)
        score += 8.0 if path_bucket == "clean" else 3.0
        score += 5.0 if tradability_bucket == "clean" else (2.0 if tradability_bucket == "usable" else 0.0)
        if _truthy(row.get("target_first_before_adverse_5pct")):
            score += 4.0
        reasons: list[str] = []
        if float(row.get("lip_mismatch_pct") or 99.0) > 18.0:
            reasons.append("uneven_lips")
        if float(row.get("roundness_corr") or 0.0) < 0.35:
            reasons.append("weak_curve")
        if float(row.get("breakout_lag_bars") or 99.0) > 26.0:
            reasons.append("late_confirmation")
        score = round(float(max(0.0, min(100.0, score))), 2)
        if score >= 72 and path_bucket == "clean":
            tier = "premium"
        elif score >= 54:
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
        "median_width_bars": _median([row.get("pattern_width_bars") for row in rows]),
        "median_roundness_corr": _median([row.get("roundness_corr") for row in rows]),
        "median_lip_mismatch_pct": _median([row.get("lip_mismatch_pct") for row in rows]),
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
            "top10_symbol_share_pct": round(float(pd.Series([str(row.get("symbol")) for row in rows if row.get("symbol")]).value_counts().head(10).sum()) / max(len(rows), 1) * 100.0, 2) if rows else None,
        },
        "quantile_metrics": {
            "fav_exc_pct": _quantiles([row.get("mfe_pct") for row in evals]),
            "adv_exc_pct": _quantiles([row.get("mae_pct") for row in evals]),
            "target_dist_pct": _quantiles([row.get("target_dist_pct") for row in evals]),
            "pattern_height_pct": _quantiles([row.get("pattern_height_pct") for row in rows]),
            "pattern_width_bars": _quantiles([row.get("pattern_width_bars") for row in rows]),
            "roundness_corr": _quantiles([row.get("roundness_corr") for row in rows]),
            "lip_mismatch_pct": _quantiles([row.get("lip_mismatch_pct") for row in rows]),
        },
        "experiment_note": "Rounding scanner uses weekly saucer/inverted-saucer geometry and close confirmation beyond the right lip/rim.",
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
    sensitivity = target_sensitivity(PatternArtifacts(pattern_key, events, path), pattern_key, horizon_days=156)
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
    "center_date",
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
    "rounding_shape",
    "lip_mismatch_pct",
    "center_position",
    "bottom_zone_fraction",
    "roundness_corr",
    "breakout_lag_bars",
    "left_lip_price",
    "right_lip_price",
    "extreme_price",
    "breakout_level",
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


def scan_rounding_db(
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
    config = RoundingConfig.from_mapping(detector_config)
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
                    series_by_symbol[symbol] = _to_weekly_ohlcv(frame)
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
    path_rows = _path_rows_from_series(scan, series_by_symbol, horizon_bars=156)
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
    parser = argparse.ArgumentParser(description="Run Rounding Family scanners against Market Cache latest.sqlite.")
    parser.add_argument("--pattern", choices=[*ROUNDING_PATTERNS, "all"], default="all")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--market-stats-json", default=str(DEFAULT_MARKET_STATS_JSON))
    parser.add_argument("--limit-symbols", type=int, default=None)
    args = parser.parse_args()
    active_meta = _load_active_symbols(Path(args.market_stats_json) if args.market_stats_json else None)
    active_symbols = active_meta.get("active_symbols") if active_meta.get("enabled") else None
    patterns = list(ROUNDING_PATTERNS) if args.pattern == "all" else [args.pattern]
    outputs: dict[str, str] = {}
    for pattern_key in patterns:
        paths = scan_rounding_db(
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
