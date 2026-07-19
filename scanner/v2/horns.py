"""Horn Bottoms / Horn Tops scanner.

Horn patterns are weekly-chart formations in Bulkowski: two same-direction
price spikes separated by one center week, then confirmed only after price
closes beyond the opposite boundary of the 3-week formation.  This module keeps
Horn Family separate from Pipe Family because adjacent spikes and separated
spikes have different morphology and failure modes.
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
    _pct,
    _prior_trend_pct,
    _quantiles,
    _rate,
    _rolling_volume_ratio,
    _safe_float,
    _score_band,
    _to_weekly_ohlcv,
    _truthy,
)
from scanner.v2.source_data import attach_current_market_groups, classify_market_regimes  # noqa: E402


HORN_BOTTOMS = "horn_bottoms"
HORN_TOPS = "horn_tops"
HORN_PATTERNS = (HORN_BOTTOMS, HORN_TOPS)
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/horn_family")


@dataclass(frozen=True)
class HornConfig:
    confirmation_search_bars: int = 26
    confirmation_threshold: float = 0.003
    min_spike_pct: float = 4.0
    max_spike_pct: float = 70.0
    max_spike_similarity_pct: float = 12.0
    min_center_clearance_pct: float = 2.4
    prior_visibility_lookback_bars: int = 52
    min_prior_visibility_percentile: float = 0.62
    prior_trend_lookback_bars: int = 45
    prior_trend_min_abs_pct: float = 3.0
    breakout_cooldown_bars: int = 35
    max_events_per_symbol: int = 18

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]] = None) -> "HornConfig":
        if value is None:
            return cls()
        allowed = {field.name for field in fields(cls)}
        return cls(**{key: item for key, item in value.items() if key in allowed})

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _prior_week_spike_percentile(df: pd.DataFrame, idx: int, *, pattern_key: str, lookback: int) -> Optional[float]:
    left = max(1, idx - lookback)
    if idx <= left:
        return None
    prior = df.iloc[left:idx]
    if prior.empty:
        return None
    if pattern_key == HORN_BOTTOMS:
        sizes = (prior["high"] - prior["low"]) / prior["high"].clip(lower=1e-9) * 100.0
    else:
        sizes = (prior["high"] - prior["low"]) / prior["low"].clip(lower=1e-9) * 100.0
    series = pd.to_numeric(sizes, errors="coerce").dropna()
    if series.empty:
        return None
    current = float(series.iloc[-1]) if False else None
    return current


def _spike_visibility_ok(
    df: pd.DataFrame,
    idx: int,
    *,
    spike_pct: float,
    pattern_key: str,
    config: HornConfig,
) -> tuple[bool, Optional[float]]:
    left = max(1, idx - config.prior_visibility_lookback_bars)
    prior = df.iloc[left:idx]
    if len(prior) < 8:
        return True, None
    if pattern_key == HORN_BOTTOMS:
        sizes = (prior["high"] - prior["low"]) / prior["high"].clip(lower=1e-9) * 100.0
    else:
        sizes = (prior["high"] - prior["low"]) / prior["low"].clip(lower=1e-9) * 100.0
    series = pd.to_numeric(sizes, errors="coerce").dropna()
    if series.empty:
        return True, None
    percentile = float((series <= spike_pct).mean())
    return percentile >= float(config.min_prior_visibility_percentile), round(percentile * 100.0, 2)


class HornDetector:
    def __init__(self, pattern_key: str, config: Optional[HornConfig | Mapping[str, Any]] = None) -> None:
        if pattern_key not in HORN_PATTERNS:
            raise ValueError(f"unsupported horn pattern {pattern_key}")
        self.pattern_key = pattern_key
        self.config = config if isinstance(config, HornConfig) else HornConfig.from_mapping(config)

    def _window_metrics(self, df: pd.DataFrame, left_idx: int) -> Optional[dict[str, Any]]:
        i0, ic, i1 = int(left_idx), int(left_idx) + 1, int(left_idx) + 2
        if not (0 <= i0 < ic < i1 < len(df)):
            return None
        window = df.iloc[i0 : i1 + 1]
        left = df.iloc[i0]
        center = df.iloc[ic]
        right = df.iloc[i1]
        if self.pattern_key == HORN_BOTTOMS:
            left_spike = float(left["high"] - left["low"]) / max(float(left["high"]), 1e-9) * 100.0
            right_spike = float(right["high"] - right["low"]) / max(float(right["high"]), 1e-9) * 100.0
            left_price = float(left["low"])
            right_price = float(right["low"])
            center_ref = float(center["low"])
            if center_ref <= max(left_price, right_price):
                return None
            center_clearance = (center_ref - max(left_price, right_price)) / max(center_ref, 1e-9) * 100.0
            high_boundary = float(window["high"].max())
            low_boundary = min(left_price, right_price)
            breakout_level = high_boundary
            support_resistance = low_boundary
            seq = "LHL"
            shape = "two_downward_spikes_center_week"
        else:
            left_spike = float(left["high"] - left["low"]) / max(float(left["low"]), 1e-9) * 100.0
            right_spike = float(right["high"] - right["low"]) / max(float(right["low"]), 1e-9) * 100.0
            left_price = float(left["high"])
            right_price = float(right["high"])
            center_ref = float(center["high"])
            if center_ref >= min(left_price, right_price):
                return None
            center_clearance = (min(left_price, right_price) - center_ref) / max(center_ref, 1e-9) * 100.0
            high_boundary = max(left_price, right_price)
            low_boundary = float(window["low"].min())
            breakout_level = low_boundary
            support_resistance = high_boundary
            seq = "HLH"
            shape = "two_upward_spikes_center_week"
        spike_min = min(left_spike, right_spike)
        spike_max = max(left_spike, right_spike)
        if spike_min < self.config.min_spike_pct or spike_max > self.config.max_spike_pct:
            return None
        avg_anchor = max((abs(left_price) + abs(right_price)) / 2.0, 1e-9)
        similarity_pct = abs(right_price - left_price) / avg_anchor * 100.0
        if similarity_pct > self.config.max_spike_similarity_pct:
            return None
        if center_clearance < self.config.min_center_clearance_pct:
            return None
        left_visible, left_visibility_pct = _spike_visibility_ok(
            df,
            i0,
            spike_pct=left_spike,
            pattern_key=self.pattern_key,
            config=self.config,
        )
        right_visible, right_visibility_pct = _spike_visibility_ok(
            df,
            i1,
            spike_pct=right_spike,
            pattern_key=self.pattern_key,
            config=self.config,
        )
        if not (left_visible and right_visible):
            return None
        height_abs = high_boundary - low_boundary
        if height_abs <= 0:
            return None
        prior = _prior_trend_pct(df, i0, self.config.prior_trend_lookback_bars)
        if prior is not None:
            if self.pattern_key == HORN_BOTTOMS and prior > self.config.prior_trend_min_abs_pct:
                return None
            if self.pattern_key == HORN_TOPS and prior < -self.config.prior_trend_min_abs_pct:
                return None
        height_pct = height_abs / max(float(breakout_level), 1e-9) * 100.0
        return {
            "sequence_tag": seq,
            "formation_start_idx": i0,
            "formation_end_idx": i1,
            "formation_start_date": str(pd.Timestamp(df.iloc[i0]["date"]).date()),
            "formation_end_date": str(pd.Timestamp(df.iloc[i1]["date"]).date()),
            "left_spike_price": round(left_price, 4),
            "right_spike_price": round(right_price, 4),
            "center_week_price": round(center_ref, 4),
            "high_boundary_price": round(high_boundary, 4),
            "low_boundary_price": round(low_boundary, 4),
            "breakout_level": round(float(breakout_level), 4),
            "support_resistance_price": round(float(support_resistance), 4),
            "pattern_width_bars": 3,
            "pattern_height_pct": round(float(height_pct), 2),
            "spike_similarity_pct": round(float(similarity_pct), 2),
            "center_clearance_pct": round(float(center_clearance), 2),
            "left_spike_pct": round(float(left_spike), 2),
            "right_spike_pct": round(float(right_spike), 2),
            "left_spike_visibility_percentile": left_visibility_pct,
            "right_spike_visibility_percentile": right_visibility_pct,
            "left_volume_ratio_20": _rolling_volume_ratio(df, i0),
            "right_volume_ratio_20": _rolling_volume_ratio(df, i1),
            "prior_trend_pct": round(float(prior), 2) if prior is not None else None,
            "horn_shape": shape,
        }

    def _breakout_candidate(self, df: pd.DataFrame, metrics: Mapping[str, Any]) -> Optional[tuple[int, str, float]]:
        end_idx = int(metrics["formation_end_idx"])
        level = float(metrics["breakout_level"])
        if self.pattern_key == HORN_BOTTOMS:
            direction = "up"
            threshold = level * (1.0 + self.config.confirmation_threshold)
        else:
            direction = "down"
            threshold = level * (1.0 - self.config.confirmation_threshold)
        for idx in range(end_idx + 1, min(len(df), end_idx + 1 + self.config.confirmation_search_bars)):
            close = _safe_float(df.iloc[idx].get("close"))
            if close is None:
                continue
            if direction == "up" and close > threshold:
                return idx, direction, float(close)
            if direction == "down" and close < threshold:
                return idx, direction, float(close)
        return None

    def scan_window(self, df: pd.DataFrame, left_idx: int) -> Optional[dict[str, Any]]:
        metrics = self._window_metrics(df, left_idx)
        if not metrics:
            return None
        candidate = self._breakout_candidate(df, metrics)
        if candidate is None:
            return None
        breakout_idx, direction, breakout_price = candidate
        height_abs = float(metrics["high_boundary_price"]) - float(metrics["low_boundary_price"])
        target_price = breakout_price + height_abs if direction == "up" else breakout_price - height_abs
        if target_price <= 0:
            return None
        target_dist_pct = abs(target_price - breakout_price) / breakout_price * 100.0
        if target_dist_pct <= 0 or target_dist_pct > 85:
            return None
        lag = breakout_idx - int(metrics["formation_end_idx"])
        score = 44.0
        score += _score_band(float(metrics["spike_similarity_pct"]), good=1.2, weak=self.config.max_spike_similarity_pct, reverse=True, weight=0.18)
        score += _score_band(float(metrics["center_clearance_pct"]), good=8.0, weak=self.config.min_center_clearance_pct, weight=0.20)
        score += _score_band(min(float(metrics["left_spike_pct"]), float(metrics["right_spike_pct"])), good=9.0, weak=self.config.min_spike_pct, weight=0.16)
        score += _score_band(float(lag), good=3.0, weak=float(self.config.confirmation_search_bars), reverse=True, weight=0.12)
        left_vis = _safe_float(metrics.get("left_spike_visibility_percentile"))
        right_vis = _safe_float(metrics.get("right_spike_visibility_percentile"))
        if left_vis is not None and right_vis is not None:
            score += _score_band(min(left_vis, right_vis), good=85.0, weak=self.config.min_prior_visibility_percentile * 100.0, weight=0.12)
        left_vol = _safe_float(metrics.get("left_volume_ratio_20"))
        right_vol = _safe_float(metrics.get("right_volume_ratio_20"))
        if left_vol is not None and right_vol is not None and max(left_vol, right_vol) >= 1.0:
            score += 3.0
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
            "variant": self.pattern_key,
            "pattern_quality_score": score,
            "pattern_quality_tier": "clean" if score >= 78 else ("usable" if score >= 62 else "loose"),
        }


def scan_symbol(
    df_raw: pd.DataFrame,
    *,
    pattern_key: str,
    max_events_per_symbol: Optional[int] = None,
    detector_config: Optional[HornConfig | Mapping[str, Any]] = None,
) -> Tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(df_raw) < 120:
        return [], {"rows": int(len(df_raw)), "skipped": "too_few_rows"}
    config = detector_config if isinstance(detector_config, HornConfig) else HornConfig.from_mapping(detector_config)
    max_events = int(max_events_per_symbol if max_events_per_symbol is not None else config.max_events_per_symbol)
    weekly_raw = _to_weekly_ohlcv(df_raw)
    if len(weekly_raw) < 80:
        return [], {"rows": int(len(df_raw)), "weekly_rows": int(len(weekly_raw)), "skipped": "too_few_weekly_rows"}
    df, norm_stats = OHLCVNormalizer().normalize(weekly_raw)
    detector = HornDetector(pattern_key, config)
    out: list[dict[str, Any]] = []
    used_breakouts: list[int] = []
    symbol = str(df.iloc[0]["symbol"])
    for left_idx in range(1, len(df) - 3):
        candidate = detector.scan_window(df, left_idx)
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
    return out, {"rows": int(len(df_raw)), "weekly_rows": int(len(df)), "normalizer": norm_stats, "detector_config": config.to_dict()}


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
        score += _score_band(float(row.get("spike_similarity_pct") or 99.0), good=1.2, weak=12.0, reverse=True, weight=0.20)
        score += _score_band(float(row.get("center_clearance_pct") or 0.0), good=8.0, weak=2.4, weight=0.22)
        score += _score_band(min(float(row.get("left_spike_pct") or 0.0), float(row.get("right_spike_pct") or 0.0)), good=9.0, weak=4.0, weight=0.14)
        score += _score_band(float(row.get("breakout_lag_bars") or 99.0), good=3.0, weak=26.0, reverse=True, weight=0.12)
        score += 8.0 if path_bucket == "clean" else 3.0
        score += 5.0 if tradability_bucket == "clean" else (2.0 if tradability_bucket == "usable" else 0.0)
        if _truthy(row.get("target_first_before_adverse_5pct")):
            score += 4.0
        reasons: list[str] = []
        if float(row.get("spike_similarity_pct") or 99.0) > 8.0:
            reasons.append("uneven_spikes")
        if float(row.get("center_clearance_pct") or 0.0) < 4.5:
            reasons.append("weak_center_week_clearance")
        if float(row.get("breakout_lag_bars") or 99.0) > 13.0:
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
        "median_spike_similarity_pct": _median([row.get("spike_similarity_pct") for row in rows]),
        "median_center_clearance_pct": _median([row.get("center_clearance_pct") for row in rows]),
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
            "spike_similarity_pct": _quantiles([row.get("spike_similarity_pct") for row in rows]),
            "center_clearance_pct": _quantiles([row.get("center_clearance_pct") for row in rows]),
            "breakout_lag_bars": _quantiles([row.get("breakout_lag_bars") for row in rows]),
        },
        "experiment_note": "Horn scanner uses source-grounded 3-week weekly geometry: two same-direction spikes separated by one center week and close confirmation beyond the formation.",
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
    "horn_shape",
    "spike_similarity_pct",
    "center_clearance_pct",
    "left_spike_pct",
    "right_spike_pct",
    "left_spike_visibility_percentile",
    "right_spike_visibility_percentile",
    "left_volume_ratio_20",
    "right_volume_ratio_20",
    "breakout_lag_bars",
    "left_spike_price",
    "right_spike_price",
    "center_week_price",
    "high_boundary_price",
    "low_boundary_price",
    "support_resistance_price",
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


def scan_horns_db(
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
    config = HornConfig.from_mapping(detector_config)
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
    parser = argparse.ArgumentParser(description="Run Horn Family scanners against Market Cache latest.sqlite.")
    parser.add_argument("--pattern", choices=[*HORN_PATTERNS, "all"], default="all")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--market-stats-json", default=str(DEFAULT_MARKET_STATS_JSON))
    parser.add_argument("--limit-symbols", type=int, default=None)
    args = parser.parse_args()
    active_meta = _load_active_symbols(Path(args.market_stats_json) if args.market_stats_json else None)
    active_symbols = active_meta.get("active_symbols") if active_meta.get("enabled") else None
    patterns = list(HORN_PATTERNS) if args.pattern == "all" else [args.pattern]
    outputs: dict[str, str] = {}
    for pattern_key in patterns:
        paths = scan_horns_db(
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
