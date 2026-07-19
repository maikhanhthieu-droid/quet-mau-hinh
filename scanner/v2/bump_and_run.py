"""Bump-and-Run Reversal Family scanner.

Bulkowski's BARR structure is a three-phase trendline pattern: lead-in,
bump, then run/confirmation back through the lead-in trendline.  This detector
keeps that anatomy separate from pivot-only reversal families.
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
from scanner.v2.measured_moves import _mean, _median, _quantiles, _rate, _score_band, _truthy  # noqa: E402
from scanner.v2.source_data import attach_current_market_groups, classify_market_regimes  # noqa: E402


BARR_BOTTOMS = "bump_and_run_reversal_bottoms"
BARR_TOPS = "bump_and_run_reversal_tops"
BARR_PATTERNS = (BARR_BOTTOMS, BARR_TOPS)
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bump_and_run_family")


@dataclass(frozen=True)
class BumpAndRunConfig:
    lead_in_min_bars: int = 35
    lead_in_max_bars: int = 95
    bump_min_bars_after_lead: int = 8
    bump_max_bars_after_lead: int = 95
    lead_in_min_pct: float = 5.0
    lead_in_max_pct: float = 90.0
    lead_in_min_r2: float = 0.32
    bump_min_height_pct: float = 9.0
    bump_max_height_pct: float = 95.0
    bump_slope_ratio_min: float = 1.75
    confirmation_search_bars: int = 70
    confirmation_threshold: float = 0.004
    pivot_min_spacing: int = 8
    breakout_cooldown_bars: int = 70
    max_events_per_symbol: int = 10

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]] = None) -> "BumpAndRunConfig":
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


def _line_fit(values: Sequence[float]) -> tuple[Optional[float], Optional[float], Optional[float]]:
    if len(values) < 8:
        return None, None, None
    y = np.asarray(values, dtype=float)
    if not np.isfinite(y).all() or float(np.var(y)) <= 1e-12:
        return None, None, None
    x = np.arange(len(y), dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    pred = slope * x + intercept
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - float(np.mean(y))) ** 2))
    r2 = max(0.0, min(1.0, 1.0 - ss_res / max(ss_tot, 1e-12)))
    return float(slope), float(intercept), float(r2)


def _rolling_volume_ratio(df: pd.DataFrame, idx: int, lookback: int = 20) -> Optional[float]:
    if idx < 0 or idx >= len(df):
        return None
    volume = _safe_float(df.iloc[idx].get("volume"))
    if volume is None:
        return None
    left = max(0, idx - lookback)
    base = pd.to_numeric(df.iloc[left:idx]["volume"], errors="coerce").dropna()
    if base.empty or float(base.mean()) <= 0:
        return None
    return round(float(volume / base.mean()), 3)


class BumpAndRunDetector:
    def __init__(self, pattern_key: str, config: Optional[BumpAndRunConfig | Mapping[str, Any]] = None) -> None:
        if pattern_key not in BARR_PATTERNS:
            raise ValueError(f"unsupported BARR pattern {pattern_key}")
        self.pattern_key = pattern_key
        self.config = config if isinstance(config, BumpAndRunConfig) else BumpAndRunConfig.from_mapping(config)

    @property
    def direction(self) -> int:
        return 1 if self.pattern_key == BARR_BOTTOMS else -1

    @property
    def bump_pivot_type(self) -> PivotType:
        return PivotType.LOW if self.direction == 1 else PivotType.HIGH

    def _trend_at(self, lead_start: int, slope: float, intercept: float, idx: int) -> float:
        return float(intercept + slope * (int(idx) - int(lead_start)))

    def _confirm(self, df: pd.DataFrame, *, lead_start: int, slope: float, intercept: float, bump_idx: int) -> Tuple[Optional[int], Optional[float], Optional[float], Optional[float]]:
        for idx in range(bump_idx + 1, min(len(df), bump_idx + 1 + self.config.confirmation_search_bars)):
            close = _safe_float(df.iloc[idx].get("close"))
            if close is None:
                continue
            trend = self._trend_at(lead_start, slope, intercept, idx)
            if trend <= 0:
                continue
            if self.direction == 1 and close > trend * (1.0 + self.config.confirmation_threshold):
                return idx, close, trend, _rolling_volume_ratio(df, idx)
            if self.direction == -1 and close < trend * (1.0 - self.config.confirmation_threshold):
                return idx, close, trend, _rolling_volume_ratio(df, idx)
        return None, None, None, None

    def scan_candidate(self, df: pd.DataFrame, bump: Pivot, lead_bars: int) -> Optional[Dict[str, Any]]:
        bump_idx = int(bump.idx)
        lead_end = bump_idx - self.config.bump_min_bars_after_lead
        lead_start = lead_end - int(lead_bars) + 1
        if lead_start < 0 or lead_end <= lead_start:
            return None
        bump_gap = bump_idx - lead_end
        if bump_gap < self.config.bump_min_bars_after_lead or bump_gap > self.config.bump_max_bars_after_lead:
            return None

        lead_close = pd.to_numeric(df.iloc[lead_start : lead_end + 1]["close"], errors="coerce").dropna()
        if len(lead_close) < int(lead_bars) * 0.85:
            return None
        slope, intercept, r2 = _line_fit(lead_close.to_list())
        if slope is None or intercept is None or r2 is None or r2 < self.config.lead_in_min_r2:
            return None
        lead_first = float(lead_close.iloc[0])
        lead_last = float(lead_close.iloc[-1])
        if lead_first <= 0:
            return None
        lead_change_pct = (lead_last - lead_first) / lead_first * 100.0
        if self.direction == 1:
            if lead_change_pct > -self.config.lead_in_min_pct:
                return None
            lead_abs_pct = abs(lead_change_pct)
        else:
            if lead_change_pct < self.config.lead_in_min_pct:
                return None
            lead_abs_pct = abs(lead_change_pct)
        if lead_abs_pct > self.config.lead_in_max_pct:
            return None

        trend_at_bump = self._trend_at(lead_start, slope, intercept, bump_idx)
        bump_price = float(bump.price)
        if trend_at_bump <= 0 or bump_price <= 0:
            return None
        bump_height_abs = abs(bump_price - trend_at_bump)
        bump_height_pct = bump_height_abs / trend_at_bump * 100.0
        if bump_height_pct < self.config.bump_min_height_pct or bump_height_pct > self.config.bump_max_height_pct:
            return None
        if self.direction == 1 and bump_price >= trend_at_bump:
            return None
        if self.direction == -1 and bump_price <= trend_at_bump:
            return None

        bump_slope = (bump_price - lead_last) / max(bump_gap, 1)
        lead_slope_abs = abs(float(slope))
        bump_slope_ratio = abs(bump_slope) / max(lead_slope_abs, 1e-9)
        if bump_slope_ratio < self.config.bump_slope_ratio_min:
            return None

        confirmation_idx, confirmation_price, trend_at_confirm, volume_ratio = self._confirm(
            df, lead_start=lead_start, slope=float(slope), intercept=float(intercept), bump_idx=bump_idx
        )
        if confirmation_idx is None or confirmation_price is None or trend_at_confirm is None:
            return None
        target = confirmation_price + bump_height_abs if self.direction == 1 else confirmation_price - bump_height_abs
        if target <= 0:
            return None
        target_dist_pct = abs(target - confirmation_price) / confirmation_price * 100.0
        if target_dist_pct <= 0 or target_dist_pct > 110:
            return None

        score = 48.0
        score += _score_band(lead_abs_pct, good=18.0, weak=self.config.lead_in_min_pct, weight=0.12)
        score += _score_band(r2, good=0.62, weak=self.config.lead_in_min_r2, weight=0.12)
        score += _score_band(bump_height_pct, good=22.0, weak=self.config.bump_min_height_pct, weight=0.16)
        score += _score_band(bump_slope_ratio, good=3.0, weak=self.config.bump_slope_ratio_min, weight=0.16)
        clearance = abs(float(confirmation_price - trend_at_confirm)) / trend_at_confirm * 100.0
        score += _score_band(clearance, good=2.2, weak=0.35, weight=0.10)
        if volume_ratio is not None and volume_ratio >= 1.05:
            score += 4.0
        score = int(max(0, min(100, round(score))))

        return {
            "formation_start_idx": int(lead_start),
            "formation_end_idx": int(bump_idx),
            "formation_start_date": str(pd.Timestamp(df.iloc[lead_start]["date"]).date()),
            "formation_end_date": str(pd.Timestamp(df.iloc[bump_idx]["date"]).date()),
            "breakout_idx": int(confirmation_idx),
            "breakout_date": str(pd.Timestamp(df.iloc[int(confirmation_idx)]["date"]).date()),
            "breakout_direction": "up" if self.direction == 1 else "down",
            "breakout_price": round(float(confirmation_price), 4),
            "target_price": round(float(target), 4),
            "pattern_width_bars": int(bump_idx - lead_start + 1),
            "pattern_height_pct": round(float(bump_height_pct), 2),
            "variant": self.pattern_key,
            "lead_in_start_idx": int(lead_start),
            "lead_in_end_idx": int(lead_end),
            "lead_in_bars": int(lead_bars),
            "lead_in_change_pct": round(float(lead_change_pct), 2),
            "lead_in_r2": round(float(r2), 3),
            "lead_in_slope": round(float(slope), 6),
            "bump_idx": int(bump_idx),
            "bump_price": round(float(bump_price), 4),
            "bump_height_pct": round(float(bump_height_pct), 2),
            "bump_slope_ratio": round(float(bump_slope_ratio), 3),
            "trendline_at_bump": round(float(trend_at_bump), 4),
            "trendline_at_confirmation": round(float(trend_at_confirm), 4),
            "confirmation_clearance_pct": round(float(clearance), 2),
            "volume_confirmed": bool(volume_ratio is not None and volume_ratio >= 1.05),
            "breakout_volume_ratio": round(float(volume_ratio), 4) if volume_ratio is not None else None,
            "target_dist_pct": round(float(target_dist_pct), 2),
            "pattern_quality_score": score,
            "pattern_quality_tier": "clean" if score >= 84 else ("usable" if score >= 70 else "loose"),
        }


def scan_symbol(
    df_raw: pd.DataFrame,
    *,
    pattern_key: str,
    max_events_per_symbol: Optional[int] = None,
    detector_config: Optional[BumpAndRunConfig | Mapping[str, Any]] = None,
) -> Tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(df_raw) < 170:
        return [], {"rows": int(len(df_raw)), "skipped": "too_few_rows"}
    config = detector_config if isinstance(detector_config, BumpAndRunConfig) else BumpAndRunConfig.from_mapping(detector_config)
    max_events = int(max_events_per_symbol if max_events_per_symbol is not None else config.max_events_per_symbol)
    df, norm_stats = OHLCVNormalizer().normalize(df_raw)
    pivots_raw = PivotDetector().detect_pivots(df, pivot_type="intermediate")
    pivots = PivotDetector().get_filtered_pivots(pivots_raw, min_spacing=config.pivot_min_spacing)
    detector = BumpAndRunDetector(pattern_key, config)
    out: list[dict[str, Any]] = []
    used_confirmations: list[int] = []
    symbol = str(df.iloc[0]["symbol"])
    lead_lengths = sorted(set([config.lead_in_min_bars, 50, 70, config.lead_in_max_bars]))
    for pivot in pivots:
        if pivot.type != detector.bump_pivot_type:
            continue
        for lead_bars in lead_lengths:
            candidate = detector.scan_candidate(df, pivot, lead_bars)
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


def _evaluate_detection(df: pd.DataFrame, det: Mapping[str, Any], horizon: int = 120) -> Dict[str, Any]:
    breakout_idx = int(det["breakout_idx"])
    breakout_price = float(det["breakout_price"])
    direction = 1 if det["breakout_direction"] == "up" else -1
    forward = df.iloc[breakout_idx + 1 : min(len(df), breakout_idx + 1 + horizon)].copy()
    if forward.empty or breakout_price <= 0:
        return {"mfe_pct": None, "mae_pct": None, "target_hit": False, "failure_5pct": True, "evaluated_bars": 0}
    if direction == 1:
        favorable = (pd.to_numeric(forward["high"], errors="coerce") / breakout_price - 1.0) * 100.0
        adverse = (1.0 - pd.to_numeric(forward["low"], errors="coerce") / breakout_price) * 100.0
    else:
        favorable = (1.0 - pd.to_numeric(forward["low"], errors="coerce") / breakout_price) * 100.0
        adverse = (pd.to_numeric(forward["high"], errors="coerce") / breakout_price - 1.0) * 100.0
    target_dist = float(det.get("target_dist_pct") or 0.0)
    mfe = float(favorable.max()) if not favorable.dropna().empty else 0.0
    mae = float(adverse.max()) if not adverse.dropna().empty else 0.0
    bars = pd.Series(range(1, len(forward) + 1), index=forward.index)
    target_bars = bars[favorable >= target_dist]
    adverse_bars = bars[adverse >= 5.0]
    target_day = int(target_bars.iloc[0]) if not target_bars.empty else None
    adverse_day = int(adverse_bars.iloc[0]) if not adverse_bars.empty else None
    return {
        "mfe_pct": round(mfe, 2),
        "mae_pct": round(mae, 2),
        "target_hit": bool(target_day is not None),
        "failure_5pct": bool(mfe < 5.0),
        "target_first_before_adverse_5pct": bool(target_day is not None and (adverse_day is None or target_day < adverse_day)),
        "days_to_target": target_day,
        "evaluated_bars": int(len(forward)),
        "throwback_pullback_30d": bool(adverse.iloc[: min(30, len(adverse))].max() >= 1.0) if not adverse.dropna().empty else False,
    }


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
        score += _score_band(_safe_float(row.get("pattern_quality_score")), good=84.0, weak=65.0, weight=0.34)
        score += _score_band(_safe_float(row.get("lead_in_r2")), good=0.62, weak=0.32, weight=0.15)
        score += _score_band(_safe_float(row.get("bump_slope_ratio")), good=3.0, weak=1.75, weight=0.18)
        score += _score_band(_safe_float(row.get("bump_height_pct")), good=22.0, weak=9.0, weight=0.14)
        score += 8.0 if path_bucket == "clean" else 4.0
        score += 6.0 if tradability_bucket == "clean" else (3.0 if tradability_bucket == "usable" else 0.0)
        reasons: list[str] = []
        if _safe_float(row.get("lead_in_r2")) is not None and float(row["lead_in_r2"]) < 0.45:
            reasons.append("weak_lead_in_linearity")
        if _safe_float(row.get("bump_slope_ratio")) is not None and float(row["bump_slope_ratio"]) < 2.2:
            reasons.append("weak_bump_acceleration")
        if not _truthy(row.get("target_hit")):
            reasons.append("no_full_target_hit")
        score = round(float(max(0.0, min(100.0, score))), 2)
        if score >= 72 and path_bucket == "clean":
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
        "median_width_bars": _median([row.get("pattern_width_bars") for row in rows]),
        "median_height_pct": _median([row.get("pattern_height_pct") for row in rows]),
        "median_bump_slope_ratio": _median([row.get("bump_slope_ratio") for row in rows]),
        "median_lead_in_r2": _median([row.get("lead_in_r2") for row in rows]),
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
        "quantile_metrics": {
            "fav_exc_pct": _quantiles([row.get("mfe_pct") for row in evals]),
            "adv_exc_pct": _quantiles([row.get("mae_pct") for row in evals]),
            "target_dist_pct": _quantiles([row.get("target_dist_pct") for row in evals]),
            "width_bars": _quantiles([row.get("pattern_width_bars") for row in rows]),
            "height_pct": _quantiles([row.get("pattern_height_pct") for row in rows]),
            "bump_slope_ratio": _quantiles([row.get("bump_slope_ratio") for row in rows]),
            "lead_in_r2": _quantiles([row.get("lead_in_r2") for row in rows]),
        },
        "experiment_note": "BARR scanner uses lead-in regression line, bump slope/height away from that line, and confirmation back through the lead-in trendline.",
    }


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
    "lead_in_start_idx",
    "lead_in_end_idx",
    "lead_in_bars",
    "lead_in_change_pct",
    "lead_in_r2",
    "lead_in_slope",
    "bump_idx",
    "bump_price",
    "bump_height_pct",
    "bump_slope_ratio",
    "trendline_at_bump",
    "trendline_at_confirmation",
    "confirmation_clearance_pct",
    "breakout_volume_ratio",
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


def scan_bump_and_run_db(
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
    config = BumpAndRunConfig.from_mapping(detector_config)
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
    parser = argparse.ArgumentParser(description="Run Bump-and-Run Reversal Family scanners against Market Cache latest.sqlite.")
    parser.add_argument("--pattern", choices=[*BARR_PATTERNS, "all"], default="all")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--market-stats-json", default=str(DEFAULT_MARKET_STATS_JSON))
    parser.add_argument("--limit-symbols", type=int, default=None)
    args = parser.parse_args()
    active_meta = _load_active_symbols(Path(args.market_stats_json) if args.market_stats_json else None)
    active_symbols = active_meta.get("active_symbols") if active_meta.get("enabled") else None
    patterns = list(BARR_PATTERNS) if args.pattern == "all" else [args.pattern]
    outputs: dict[str, str] = {}
    for pattern_key in patterns:
        paths = scan_bump_and_run_db(
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
