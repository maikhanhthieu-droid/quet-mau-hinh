"""Rising/Falling Three Methods scanner.

Three Methods is a compact five-candle continuation family: a long candle in
the trend direction, three small counter-trend candles contained inside that
first candle, and a final long candle confirming continuation.  The scanner is
kept separate from Inside Day because the pattern requires a prior trend, a
five-bar sequence, and a final confirmation bar rather than a two-bar range
break.
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
from scanner.research_support_analysis import PatternArtifacts, build_target_calibration_decisions, target_sensitivity  # noqa: E402
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


RISING_THREE_METHODS = "rising_three_methods"
FALLING_THREE_METHODS = "falling_three_methods"
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/three_methods_family")


@dataclass(frozen=True)
class ThreeMethodsConfig:
    first_body_atr_min: float = 1.05
    last_body_atr_min: float = 0.95
    middle_body_max_ratio: float = 0.65
    middle_inside_tolerance_pct: float = 0.003
    prior_trend_lookback_bars: int = 10
    prior_trend_min_pct: float = 3.0
    breakout_threshold_pct: float = 0.0
    max_events_per_symbol: int = 10
    breakout_cooldown_bars: int = 15

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]] = None) -> "ThreeMethodsConfig":
        if value is None:
            return cls()
        allowed = {field.name for field in fields(cls)}
        return cls(**{key: item for key, item in value.items() if key in allowed})

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _body(row: Mapping[str, Any]) -> float | None:
    open_ = _safe_float(row.get("open"))
    close = _safe_float(row.get("close"))
    if open_ is None or close is None:
        return None
    return float(close) - float(open_)


def _body_abs(row: Mapping[str, Any]) -> float | None:
    body = _body(row)
    return abs(float(body)) if body is not None else None


def _range(row: Mapping[str, Any]) -> float | None:
    high = _safe_float(row.get("high"))
    low = _safe_float(row.get("low"))
    if high is None or low is None:
        return None
    return max(0.0, float(high) - float(low))


def _median_range(df: pd.DataFrame, idx: int, lookback: int = 20) -> float | None:
    start = max(0, idx - lookback)
    values = [_range(row) for _, row in df.iloc[start:idx].iterrows()]
    values = [value for value in values if value is not None and value > 0]
    return _median(values) if values else None


def _is_inside_first(first: Mapping[str, Any], row: Mapping[str, Any], tolerance_pct: float) -> bool:
    first_high = _safe_float(first.get("high"))
    first_low = _safe_float(first.get("low"))
    high = _safe_float(row.get("high"))
    low = _safe_float(row.get("low"))
    if None in (first_high, first_low, high, low):
        return False
    height = max(float(first_high) - float(first_low), 1e-9)
    tolerance = height * tolerance_pct
    return float(high) <= float(first_high) + tolerance and float(low) >= float(first_low) - tolerance


def _volume_score(df: pd.DataFrame, idx: int) -> tuple[bool, float | None, float | None, float | None]:
    first_vol = _safe_float(df.iloc[idx].get("volume"))
    mids = [_safe_float(df.iloc[idx + offset].get("volume")) for offset in (1, 2, 3)]
    last_vol = _safe_float(df.iloc[idx + 4].get("volume"))
    mids = [value for value in mids if value is not None]
    middle_median = _median(mids) if mids else None
    if first_vol is None or last_vol is None or middle_median is None or middle_median <= 0:
        return False, first_vol, middle_median, last_vol
    contracts = middle_median < first_vol and last_vol > middle_median
    return bool(contracts), first_vol, middle_median, last_vol


class ThreeMethodsDetector:
    def __init__(self, pattern_key: str, config: Optional[ThreeMethodsConfig | Mapping[str, Any]] = None) -> None:
        if pattern_key not in {RISING_THREE_METHODS, FALLING_THREE_METHODS}:
            raise ValueError(f"Unsupported Three Methods pattern: {pattern_key}")
        self.pattern_key = pattern_key
        self.config = config if isinstance(config, ThreeMethodsConfig) else ThreeMethodsConfig.from_mapping(config)

    @property
    def direction(self) -> str:
        return "up" if self.pattern_key == RISING_THREE_METHODS else "down"

    def _candidate_at(self, df: pd.DataFrame, idx: int) -> dict[str, Any] | None:
        if idx + 4 >= len(df):
            return None
        first = df.iloc[idx]
        last = df.iloc[idx + 4]
        first_body = _body(first)
        last_body = _body(last)
        first_abs = _body_abs(first)
        last_abs = _body_abs(last)
        atr = _median_range(df, idx, lookback=20)
        if None in (first_body, last_body, first_abs, last_abs, atr) or float(atr or 0) <= 0:
            return None
        if self.direction == "up":
            if first_body <= 0 or last_body <= 0:
                return None
            prior_trend = _prior_trend_pct(df, idx - 1, self.config.prior_trend_lookback_bars)
            if prior_trend is None or prior_trend < self.config.prior_trend_min_pct:
                return None
        else:
            if first_body >= 0 or last_body >= 0:
                return None
            prior_trend = _prior_trend_pct(df, idx - 1, self.config.prior_trend_lookback_bars)
            if prior_trend is None or prior_trend > -self.config.prior_trend_min_pct:
                return None
        if first_abs < self.config.first_body_atr_min * float(atr):
            return None
        if last_abs < self.config.last_body_atr_min * float(atr):
            return None
        first_high = float(first["high"])
        first_low = float(first["low"])
        first_close = float(first["close"])
        first_open = float(first["open"])
        for offset in (1, 2, 3):
            middle = df.iloc[idx + offset]
            middle_body = _body_abs(middle)
            if middle_body is None or middle_body > self.config.middle_body_max_ratio * first_abs:
                return None
            if not _is_inside_first(first, middle, self.config.middle_inside_tolerance_pct):
                return None
        breakout_price = float(last["close"])
        if self.direction == "up":
            threshold = first_high * (1.0 + self.config.breakout_threshold_pct)
            if breakout_price <= threshold:
                return None
            target_price = breakout_price + (first_high - first_low)
        else:
            threshold = first_low * (1.0 - self.config.breakout_threshold_pct)
            if breakout_price >= threshold:
                return None
            target_price = breakout_price - (first_high - first_low)
        if target_price <= 0:
            return None
        volume_contracts, first_vol, middle_vol, last_vol = _volume_score(df, idx)
        middle_body_ratio = _median([_body_abs(df.iloc[idx + offset]) for offset in (1, 2, 3)]) / max(first_abs, 1e-9)
        target_dist_pct = abs(target_price - breakout_price) / breakout_price * 100.0
        range_pct = (first_high - first_low) / max(first_close, 1e-9) * 100.0
        score = 34.0
        score += _score_band(first_abs / max(float(atr), 1e-9), good=2.0, weak=1.0, weight=0.15)
        score += _score_band(last_abs / max(float(atr), 1e-9), good=1.8, weak=0.9, weight=0.13)
        score += _score_band(middle_body_ratio, good=0.25, weak=self.config.middle_body_max_ratio, reverse=True, weight=0.16)
        score += _score_band(abs(float(prior_trend)), good=8.0, weak=self.config.prior_trend_min_pct, weight=0.12)
        score += _score_band(float(target_dist_pct), good=2.0, weak=10.0, reverse=True, weight=0.10)
        score += 8.0 if volume_contracts else 2.0
        score = int(max(0, min(100, round(score))))
        return {
            "symbol": str(df.iloc[0]["symbol"]),
            "pattern_key": self.pattern_key,
            "variant": f"classic_{self.pattern_key}" if volume_contracts else f"standard_{self.pattern_key}",
            "formation_start_idx": int(idx),
            "formation_end_idx": int(idx + 4),
            "formation_start_date": str(pd.Timestamp(first["date"]).date()),
            "formation_end_date": str(pd.Timestamp(last["date"]).date()),
            "breakout_idx": int(idx + 4),
            "breakout_date": str(pd.Timestamp(last["date"]).date()),
            "breakout_direction": self.direction,
            "breakout_price": round(float(breakout_price), 4),
            "target_price": round(float(target_price), 4),
            "target_dist_pct": round(float(target_dist_pct), 2),
            "pattern_width_bars": 5,
            "pattern_height_pct": round(float(range_pct), 2),
            "first_bar_open": round(first_open, 4),
            "first_bar_close": round(first_close, 4),
            "first_bar_high": round(first_high, 4),
            "first_bar_low": round(first_low, 4),
            "last_bar_close": round(float(last["close"]), 4),
            "first_body_atr": round(first_abs / max(float(atr), 1e-9), 4),
            "last_body_atr": round(last_abs / max(float(atr), 1e-9), 4),
            "middle_body_ratio": round(float(middle_body_ratio), 4),
            "middle_inside_count": 3,
            "prior_trend_pct": round(float(prior_trend), 2),
            "volume_contracts": bool(volume_contracts),
            "volume_first": first_vol,
            "volume_middle_median": middle_vol,
            "volume_last": last_vol,
            "pattern_quality_score": score,
            "pattern_quality_tier": "clean" if score >= 76 else ("usable" if score >= 60 else "loose"),
        }

    def scan(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        if len(df) < 30:
            return []
        symbol = str(df.iloc[0]["symbol"])
        dates = pd.to_datetime(df["date"], errors="coerce").dt.date.astype(str).to_numpy()
        opens = pd.to_numeric(df["open"], errors="coerce").to_numpy(dtype=float)
        highs = pd.to_numeric(df["high"], errors="coerce").to_numpy(dtype=float)
        lows = pd.to_numeric(df["low"], errors="coerce").to_numpy(dtype=float)
        closes = pd.to_numeric(df["close"], errors="coerce").to_numpy(dtype=float)
        volumes = pd.to_numeric(df["volume"], errors="coerce").to_numpy(dtype=float)
        ranges = np.maximum(0.0, highs - lows)
        body = closes - opens
        body_abs = np.abs(body)
        range_median = pd.Series(ranges).rolling(20, min_periods=8).median().shift(1).to_numpy(dtype=float)
        rows: list[dict[str, Any]] = []
        used: list[int] = []
        for idx in range(20, len(df) - 5):
            atr = range_median[idx]
            if not math.isfinite(atr) or atr <= 0:
                continue
            first_body = body[idx]
            last_body = body[idx + 4]
            first_abs = body_abs[idx]
            last_abs = body_abs[idx + 4]
            if first_abs < self.config.first_body_atr_min * atr:
                continue
            if last_abs < self.config.last_body_atr_min * atr:
                continue
            prior_idx = idx - 1 - self.config.prior_trend_lookback_bars
            if prior_idx < 0 or closes[prior_idx] <= 0:
                continue
            prior_trend = (closes[idx - 1] / closes[prior_idx] - 1.0) * 100.0
            if self.direction == "up":
                if first_body <= 0 or last_body <= 0 or prior_trend < self.config.prior_trend_min_pct:
                    continue
            else:
                if first_body >= 0 or last_body >= 0 or prior_trend > -self.config.prior_trend_min_pct:
                    continue
            first_high = highs[idx]
            first_low = lows[idx]
            if not all(math.isfinite(value) for value in (first_high, first_low, opens[idx], closes[idx], closes[idx + 4])):
                continue
            height = first_high - first_low
            if height <= 0:
                continue
            tolerance = height * self.config.middle_inside_tolerance_pct
            middle_body_values = body_abs[idx + 1 : idx + 4]
            if len(middle_body_values) != 3 or not np.isfinite(middle_body_values).all():
                continue
            if float(np.nanmax(middle_body_values)) > self.config.middle_body_max_ratio * first_abs:
                continue
            if np.nanmax(highs[idx + 1 : idx + 4]) > first_high + tolerance:
                continue
            if np.nanmin(lows[idx + 1 : idx + 4]) < first_low - tolerance:
                continue
            breakout_price = closes[idx + 4]
            if self.direction == "up":
                if breakout_price <= first_high * (1.0 + self.config.breakout_threshold_pct):
                    continue
                target_price = breakout_price + height
            else:
                if breakout_price >= first_low * (1.0 - self.config.breakout_threshold_pct):
                    continue
                target_price = breakout_price - height
            if target_price <= 0:
                continue
            breakout_idx = int(idx + 4)
            if any(abs(breakout_idx - used_idx) <= self.config.breakout_cooldown_bars for used_idx in used):
                continue
            middle_vol = float(np.nanmedian(volumes[idx + 1 : idx + 4]))
            first_vol = float(volumes[idx])
            last_vol = float(volumes[idx + 4])
            volume_contracts = all(math.isfinite(value) for value in (first_vol, middle_vol, last_vol)) and middle_vol < first_vol and last_vol > middle_vol
            middle_body_ratio = float(np.nanmedian(middle_body_values)) / max(float(first_abs), 1e-9)
            target_dist_pct = abs(float(target_price) - float(breakout_price)) / float(breakout_price) * 100.0
            range_pct = height / max(float(closes[idx]), 1e-9) * 100.0
            score = 34.0
            score += _score_band(first_abs / max(float(atr), 1e-9), good=2.0, weak=1.0, weight=0.15)
            score += _score_band(last_abs / max(float(atr), 1e-9), good=1.8, weak=0.9, weight=0.13)
            score += _score_band(middle_body_ratio, good=0.25, weak=self.config.middle_body_max_ratio, reverse=True, weight=0.16)
            score += _score_band(abs(float(prior_trend)), good=8.0, weak=self.config.prior_trend_min_pct, weight=0.12)
            score += _score_band(float(target_dist_pct), good=2.0, weak=10.0, reverse=True, weight=0.10)
            score += 8.0 if volume_contracts else 2.0
            score = int(max(0, min(100, round(score))))
            candidate = {
                "symbol": symbol,
                "pattern_key": self.pattern_key,
                "variant": f"classic_{self.pattern_key}" if volume_contracts else f"standard_{self.pattern_key}",
                "formation_start_idx": int(idx),
                "formation_end_idx": int(idx + 4),
                "formation_start_date": str(dates[idx]),
                "formation_end_date": str(dates[idx + 4]),
                "breakout_idx": int(idx + 4),
                "breakout_date": str(dates[idx + 4]),
                "breakout_direction": self.direction,
                "breakout_price": round(float(breakout_price), 4),
                "target_price": round(float(target_price), 4),
                "target_dist_pct": round(float(target_dist_pct), 2),
                "pattern_width_bars": 5,
                "pattern_height_pct": round(float(range_pct), 2),
                "first_bar_open": round(float(opens[idx]), 4),
                "first_bar_close": round(float(closes[idx]), 4),
                "first_bar_high": round(float(first_high), 4),
                "first_bar_low": round(float(first_low), 4),
                "last_bar_close": round(float(closes[idx + 4]), 4),
                "first_body_atr": round(float(first_abs) / max(float(atr), 1e-9), 4),
                "last_body_atr": round(float(last_abs) / max(float(atr), 1e-9), 4),
                "middle_body_ratio": round(float(middle_body_ratio), 4),
                "middle_inside_count": 3,
                "prior_trend_pct": round(float(prior_trend), 2),
                "prior_trend_signed_pct": round(float(prior_trend if self.direction == "up" else -prior_trend), 2),
                "volume_contracts": bool(volume_contracts),
                "volume_first": first_vol,
                "volume_middle_median": middle_vol,
                "volume_last": last_vol,
                "pattern_quality_score": score,
                "pattern_quality_tier": "clean" if score >= 76 else ("usable" if score >= 60 else "loose"),
            }
            breakout_idx = int(candidate["breakout_idx"])
            used.append(breakout_idx)
            rows.append(candidate)
            if len(rows) >= self.config.max_events_per_symbol:
                break
        return rows


def scan_symbol(
    df_raw: pd.DataFrame,
    *,
    pattern_key: str,
    detector_config: Optional[ThreeMethodsConfig | Mapping[str, Any]] = None,
) -> Tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(df_raw) < 100:
        return [], {"rows": int(len(df_raw)), "skipped": "too_few_rows"}
    config = detector_config if isinstance(detector_config, ThreeMethodsConfig) else ThreeMethodsConfig.from_mapping(detector_config)
    df, norm_stats = OHLCVNormalizer().normalize(df_raw)
    rows = ThreeMethodsDetector(pattern_key, config).scan(df)
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append({**row, **_evaluate_detection(df, row, lookahead=60)})
    return out, {"rows": int(len(df)), "normalizer": norm_stats, "detector_config": config.to_dict()}


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
        score += _score_band(_safe_float(row.get("first_body_atr")), good=2.0, weak=1.0, weight=0.18)
        score += _score_band(_safe_float(row.get("last_body_atr")), good=1.8, weak=0.9, weight=0.16)
        score += _score_band(_safe_float(row.get("middle_body_ratio")), good=0.25, weak=0.65, reverse=True, weight=0.18)
        score += _score_band(abs(float(row.get("prior_trend_pct") or 0.0)), good=8.0, weak=3.0, weight=0.12)
        if _truthy(row.get("volume_contracts")):
            score += 10.0
        if path_bucket == "clean":
            score += 10.0
        elif path_bucket == "usable":
            score += 5.0
        if tradability_bucket == "clean":
            score += 6.0
        elif tradability_bucket == "usable":
            score += 3.0
        reasons: list[str] = []
        if not _truthy(row.get("volume_contracts")):
            reasons.append("weak_volume_pattern")
        if float(row.get("middle_body_ratio") or 1.0) > 0.50:
            reasons.append("large_middle_bodies")
        if float(row.get("first_body_atr") or 0.0) < 1.25:
            reasons.append("first_bar_not_very_long")
        score = round(float(max(0.0, min(100.0, score))), 2)
        row["publication_quality_score"] = score
        row["publication_quality_tier"] = "premium" if score >= 70 and path_bucket == "clean" else ("standard" if score >= 52 else "loose")
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
        "median_first_body_atr": _median([row.get("first_body_atr") for row in rows]),
        "median_last_body_atr": _median([row.get("last_body_atr") for row in rows]),
        "median_middle_body_ratio": _median([row.get("middle_body_ratio") for row in rows]),
    }


def _group_table(rows: Sequence[Mapping[str, Any]], column: str, labels: Sequence[str]) -> Dict[str, Any]:
    return {label: _group_stats([row for row in rows if str(row.get(column) or "unknown") == label]) for label in labels}


def summarize(scan: Mapping[str, Any], pattern_key: str) -> Dict[str, Any]:
    rows = list(scan.get("detections") or [])
    evals = [row for row in rows if row.get("mfe_pct") is not None]
    return {
        "generated_at": _utc_now(),
        "pattern_key": pattern_key,
        "symbols_scanned": int(scan.get("symbols_scanned") or 0),
        "detection_count": len(rows),
        "evaluated_count": len(evals),
        **_group_stats(rows),
        "variant_table": _group_table(rows, "variant", (f"classic_{pattern_key}", f"standard_{pattern_key}")),
        "direction_table": _group_table(rows, "breakout_direction", ("up", "down")),
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
            "first_body_atr": _quantiles([row.get("first_body_atr") for row in rows]),
            "last_body_atr": _quantiles([row.get("last_body_atr") for row in rows]),
            "middle_body_ratio": _quantiles([row.get("middle_body_ratio") for row in rows]),
            "target_days": _quantiles([row.get("days_to_target") for row in evals]),
        },
        "experiment_note": "Three Methods Family uses five-candle continuation logic: long first candle, three contained small candles, final continuation close, then 60-bar post-confirmation measurement.",
    }


def _add_target_calibration(stats: Dict[str, Any], scan: Mapping[str, Any], path_rows: Sequence[Mapping[str, Any]], pattern_key: str) -> None:
    events = pd.DataFrame(list(scan.get("detections") or []))
    path = pd.DataFrame(list(path_rows))
    if events.empty:
        stats["target_family_sensitivity"] = []
        stats["target_calibration_decision"] = None
        return
    if "event_id" not in events.columns and "detection_id" in events.columns:
        events["event_id"] = events["detection_id"]
    sensitivity = target_sensitivity(PatternArtifacts(pattern_key, events, path), pattern_key, horizon_days=60)
    stats["target_family_sensitivity"] = sensitivity
    stats["target_calibration_decision"] = (build_target_calibration_decisions(sensitivity, family_labels=(pattern_key,)) or [None])[0]
    stats["target_family"] = {"half_first_bar_range": 0.5, "full_first_bar_range": 1.0}


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
    "first_bar_open",
    "first_bar_close",
    "first_bar_high",
    "first_bar_low",
    "last_bar_close",
    "first_body_atr",
    "last_body_atr",
    "middle_body_ratio",
    "middle_inside_count",
    "prior_trend_pct",
    "volume_contracts",
    "volume_first",
    "volume_middle_median",
    "volume_last",
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


def scan_three_methods_db(
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
    config = ThreeMethodsConfig.from_mapping(detector_config)
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
                    series_by_symbol[symbol] = OHLCVNormalizer().normalize(frame)[0]
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
    path_rows = _path_rows_from_series(scan, series_by_symbol, horizon_bars=60)
    stats = summarize(scan, pattern_key)
    stats["source"] = scan["source"]
    stats["db_source_meta"] = _db_meta(db_path)
    stats["detector_config"] = config.to_dict()
    _add_target_calibration(stats, scan, path_rows, pattern_key)
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
    parser = argparse.ArgumentParser(description="Run Rising/Falling Three Methods scanner against Market Cache latest.sqlite.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--market-stats-json", default=str(DEFAULT_MARKET_STATS_JSON))
    parser.add_argument("--pattern", choices=[RISING_THREE_METHODS, FALLING_THREE_METHODS, "all"], default="all")
    parser.add_argument("--limit-symbols", type=int, default=None)
    args = parser.parse_args()
    active_meta = _load_active_symbols(Path(args.market_stats_json) if args.market_stats_json else None)
    active_symbols = active_meta.get("active_symbols") if active_meta.get("enabled") else None
    patterns = [RISING_THREE_METHODS, FALLING_THREE_METHODS] if args.pattern == "all" else [str(args.pattern)]
    outputs: dict[str, dict[str, str]] = {}
    for pattern_key in patterns:
        paths = scan_three_methods_db(
            pattern_key=pattern_key,
            db_path=Path(args.db),
            out_dir=Path(args.out_dir) / pattern_key / "db_active",
            allowed_symbols=active_symbols,
            limit_symbols=args.limit_symbols,
        )
        outputs[pattern_key] = {key: str(value) for key, value in paths.items()}
    print(json.dumps({"status": "PASS", "outputs": outputs}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
