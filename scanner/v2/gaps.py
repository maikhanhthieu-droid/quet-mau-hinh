"""Gap Family scanner.

Bulkowski treats gaps as a family whose main subtypes behave differently:
area/common gaps close quickly, breakaway gaps begin trends, continuation gaps
appear in the middle of trends, and exhaustion gaps occur near trend ends.  This
module keeps gap logic separate from other pattern families because the central
post-event statistic is gap closure, not only measured-move target attainment.
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
from scanner.v2.source_data import attach_current_market_groups, classify_market_regimes  # noqa: E402


AREA_GAPS = "area_gaps"
BREAKAWAY_GAPS = "breakaway_gaps"
CONTINUATION_GAPS = "continuation_gaps"
EXHAUSTION_GAPS = "exhaustion_gaps"
GAP_PATTERNS = (AREA_GAPS, BREAKAWAY_GAPS, CONTINUATION_GAPS, EXHAUSTION_GAPS)
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/gap_family")


@dataclass(frozen=True)
class GapConfig:
    min_gap_pct: float = 1.0
    max_gap_pct: float = 35.0
    prior_trend_lookback_bars: int = 20
    consolidation_lookback_bars: int = 20
    post_classification_bars: int = 20
    evaluation_bars: int = 120
    min_volume_ratio: float = 1.10
    breakout_cooldown_bars: int = 35
    max_events_per_symbol: int = 10

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]] = None) -> "GapConfig":
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
    return str(value).strip().lower() in {"true", "1", "yes", "y", "có"}


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


def _prior_trend_pct(df: pd.DataFrame, idx: int, lookback: int) -> Optional[float]:
    left = max(0, int(idx) - int(lookback))
    if int(idx) <= left:
        return None
    anchor = _safe_float(df.iloc[left].get("close"))
    current = _safe_float(df.iloc[int(idx) - 1].get("close"))
    if anchor is None or current is None or anchor <= 0:
        return None
    return (current - anchor) / anchor * 100.0


def _range_pct(df: pd.DataFrame, idx: int, lookback: int) -> Optional[float]:
    left = max(0, int(idx) - int(lookback))
    window = df.iloc[left:int(idx)]
    if window.empty:
        return None
    low = _safe_float(window["low"].min())
    high = _safe_float(window["high"].max())
    close = _safe_float(df.iloc[int(idx) - 1].get("close"))
    if low is None or high is None or close is None or close <= 0:
        return None
    return (high - low) / close * 100.0


def _volume_ratio(df: pd.DataFrame, idx: int, lookback: int = 20) -> Optional[float]:
    volume = _safe_float(df.iloc[int(idx)].get("volume")) if 0 <= int(idx) < len(df) else None
    if volume is None:
        return None
    left = max(0, int(idx) - lookback)
    base = pd.to_numeric(df.iloc[left:int(idx)]["volume"], errors="coerce").dropna()
    if base.empty or float(base.mean()) <= 0:
        return None
    return round(float(volume / base.mean()), 3)


def _signed_prior(prior_trend_pct: Optional[float], direction: str) -> Optional[float]:
    if prior_trend_pct is None:
        return None
    return float(prior_trend_pct) if direction == "up" else -float(prior_trend_pct)


def _gap_close_day(df: pd.DataFrame, idx: int, direction: str, rim_price: float, max_bars: int) -> Optional[int]:
    future = df.iloc[int(idx) + 1 : min(len(df), int(idx) + 1 + int(max_bars))]
    for offset, (_, row) in enumerate(future.iterrows(), start=1):
        if direction == "up" and float(row["low"]) <= rim_price:
            return offset
        if direction == "down" and float(row["high"]) >= rim_price:
            return offset
    return None


def _post_new_extremes(df: pd.DataFrame, idx: int, direction: str, bars: int = 10) -> int:
    current_high = float(df.iloc[int(idx)]["high"])
    current_low = float(df.iloc[int(idx)]["low"])
    future = df.iloc[int(idx) + 1 : min(len(df), int(idx) + 1 + int(bars))]
    if future.empty:
        return 0
    if direction == "up":
        return int((pd.to_numeric(future["high"], errors="coerce") > current_high).sum())
    return int((pd.to_numeric(future["low"], errors="coerce") < current_low).sum())


def _post_adverse_pct(df: pd.DataFrame, idx: int, direction: str, bars: int = 10) -> Optional[float]:
    price = _safe_float(df.iloc[int(idx)].get("close"))
    if price is None or price <= 0:
        return None
    future = df.iloc[int(idx) + 1 : min(len(df), int(idx) + 1 + int(bars))]
    if future.empty:
        return None
    if direction == "up":
        return (price - float(future["low"].min())) / price * 100.0
    return (float(future["high"].max()) - price) / price * 100.0


def classify_gap_subtype(
    *,
    direction: str,
    gap_size_pct: float,
    prior_trend_pct: Optional[float],
    consolidation_range_pct: Optional[float],
    volume_ratio: Optional[float],
    close_day: Optional[int],
    post_new_extremes_10d: int,
    post_adverse_10d_pct: Optional[float],
) -> str:
    signed_prior = _signed_prior(prior_trend_pct, direction)
    abs_prior = abs(float(prior_trend_pct or 0.0))
    volume = float(volume_ratio or 0.0)
    consolidation = float(consolidation_range_pct or 999.0)
    adverse = float(post_adverse_10d_pct or 0.0)

    if close_day is not None and close_day <= 5 and abs_prior < 10.0 and post_new_extremes_10d <= 2:
        return AREA_GAPS
    if signed_prior is not None and signed_prior >= 15.0 and (close_day is not None and close_day <= 10 or adverse >= 5.0):
        return EXHAUSTION_GAPS
    if signed_prior is not None and signed_prior >= 10.0 and post_new_extremes_10d >= 2 and not (close_day is not None and close_day <= 10):
        return CONTINUATION_GAPS
    if consolidation <= 18.0 and volume >= 1.10 and post_new_extremes_10d >= 2 and not (close_day is not None and close_day <= 20):
        return BREAKAWAY_GAPS
    if close_day is not None and close_day <= 10:
        return AREA_GAPS if abs_prior < 12.0 else EXHAUSTION_GAPS
    if post_new_extremes_10d >= 2:
        return BREAKAWAY_GAPS if abs_prior < 10.0 else CONTINUATION_GAPS
    return EXHAUSTION_GAPS if gap_size_pct >= 3.0 and signed_prior is not None and signed_prior >= 12.0 else AREA_GAPS


def _evaluate_gap(df: pd.DataFrame, row: Mapping[str, Any], *, lookahead: int) -> dict[str, Any]:
    idx = int(row["breakout_idx"])
    direction = 1 if row["breakout_direction"] == "up" else -1
    breakout_price = float(row["breakout_price"])
    target = float(row["target_price"])
    future = df.iloc[idx + 1 : min(len(df), idx + 1 + int(lookahead))]
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
    for offset, (_, item) in enumerate(future.iterrows(), start=1):
        high = float(item["high"])
        low = float(item["low"])
        target_now = high >= target if direction == 1 else low <= target
        adverse_now = low <= breakout_price * 0.95 if direction == 1 else high >= breakout_price * 1.05
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
        "days_to_throwback_pullback": int(retest_rows.index[0] - idx) if not retest_rows.empty else None,
    }


def scan_symbol(
    df_raw: pd.DataFrame,
    *,
    detector_config: Optional[GapConfig | Mapping[str, Any]] = None,
) -> Tuple[list[dict[str, Any]], dict[str, Any]]:
    config = detector_config if isinstance(detector_config, GapConfig) else GapConfig.from_mapping(detector_config)
    if len(df_raw) < max(80, config.prior_trend_lookback_bars + config.evaluation_bars):
        return [], {"rows": int(len(df_raw)), "skipped": "too_few_rows"}
    df, norm_stats = OHLCVNormalizer().normalize(df_raw)
    symbol = str(df.iloc[0]["symbol"]).upper()
    out: list[dict[str, Any]] = []
    used: list[int] = []
    for idx in range(max(1, config.prior_trend_lookback_bars), len(df) - 2):
        prev = df.iloc[idx - 1]
        cur = df.iloc[idx]
        prev_high, prev_low, prev_close = float(prev["high"]), float(prev["low"]), float(prev["close"])
        cur_high, cur_low, cur_close = float(cur["high"]), float(cur["low"]), float(cur["close"])
        if prev_close <= 0:
            continue
        direction: str | None = None
        gap_top = gap_bottom = rim_price = None
        if cur_low > prev_high:
            direction = "up"
            gap_bottom, gap_top = prev_high, cur_low
            rim_price = prev_high
        elif cur_high < prev_low:
            direction = "down"
            gap_bottom, gap_top = cur_high, prev_low
            rim_price = prev_low
        if direction is None or gap_top is None or gap_bottom is None or rim_price is None:
            continue
        gap_size_abs = abs(float(gap_top) - float(gap_bottom))
        gap_size_pct = gap_size_abs / prev_close * 100.0
        if gap_size_pct < config.min_gap_pct or gap_size_pct > config.max_gap_pct:
            continue
        if any(abs(idx - old) <= config.breakout_cooldown_bars for old in used):
            continue
        prior = _prior_trend_pct(df, idx, config.prior_trend_lookback_bars)
        consolidation = _range_pct(df, idx, config.consolidation_lookback_bars)
        volume = _volume_ratio(df, idx)
        close_day = _gap_close_day(df, idx, direction, float(rim_price), config.evaluation_bars)
        post_extremes = _post_new_extremes(df, idx, direction, 10)
        adverse_10 = _post_adverse_pct(df, idx, direction, 10)
        subtype = classify_gap_subtype(
            direction=direction,
            gap_size_pct=float(gap_size_pct),
            prior_trend_pct=prior,
            consolidation_range_pct=consolidation,
            volume_ratio=volume,
            close_day=close_day,
            post_new_extremes_10d=post_extremes,
            post_adverse_10d_pct=adverse_10,
        )
        breakout_price = cur_close
        target_price = breakout_price + gap_size_abs if direction == "up" else breakout_price - gap_size_abs
        if target_price <= 0:
            continue
        target_dist_pct = abs(target_price - breakout_price) / breakout_price * 100.0
        score = 42.0
        score += _score_band(gap_size_pct, good=4.0, weak=config.min_gap_pct, weight=0.18)
        score += _score_band(float(volume or 0.0), good=1.8, weak=0.9, weight=0.14)
        score += _score_band(float(post_extremes), good=4.0, weak=0.0, weight=0.14)
        signed_prior = _signed_prior(prior, direction)
        if subtype in {BREAKAWAY_GAPS, AREA_GAPS}:
            score += _score_band(float(consolidation or 99.0), good=10.0, weak=28.0, reverse=True, weight=0.16)
        else:
            score += _score_band(float(signed_prior or 0.0), good=18.0, weak=5.0, weight=0.16)
        if subtype == AREA_GAPS:
            score += _score_band(float(close_day or 99.0), good=2.0, weak=10.0, reverse=True, weight=0.16)
        elif subtype == EXHAUSTION_GAPS:
            score += _score_band(float(adverse_10 or 0.0), good=6.0, weak=1.0, weight=0.16)
        else:
            score += 8.0 if close_day is None or close_day > 20 else 0.0
        score = round(float(max(0.0, min(100.0, score))), 2)
        record: dict[str, Any] = {
            "symbol": symbol,
            "pattern_key": subtype,
            "variant": subtype,
            "formation_start_idx": idx - 1,
            "formation_end_idx": idx,
            "breakout_idx": idx,
            "formation_start_date": str(pd.Timestamp(prev["date"]).date()),
            "formation_end_date": str(pd.Timestamp(cur["date"]).date()),
            "breakout_date": str(pd.Timestamp(cur["date"]).date()),
            "breakout_direction": direction,
            "breakout_price": round(float(breakout_price), 4),
            "target_price": round(float(target_price), 4),
            "target_dist_pct": round(float(target_dist_pct), 2),
            "gap_direction": direction,
            "gap_top_price": round(float(gap_top), 4),
            "gap_bottom_price": round(float(gap_bottom), 4),
            "gap_rim_close_price": round(float(rim_price), 4),
            "gap_size_pct": round(float(gap_size_pct), 2),
            "gap_size_abs": round(float(gap_size_abs), 4),
            "gap_closed": close_day is not None,
            "days_to_gap_close": int(close_day) if close_day is not None else None,
            "gap_closed_5d": bool(close_day is not None and close_day <= 5),
            "gap_closed_10d": bool(close_day is not None and close_day <= 10),
            "gap_closed_20d": bool(close_day is not None and close_day <= 20),
            "prior_trend_pct": round(float(prior), 2) if prior is not None else None,
            "signed_prior_trend_pct": round(float(signed_prior), 2) if signed_prior is not None else None,
            "consolidation_range_pct": round(float(consolidation), 2) if consolidation is not None else None,
            "breakout_volume_ratio": volume,
            "post_new_extremes_10d": int(post_extremes),
            "post_adverse_10d_pct": round(float(adverse_10), 2) if adverse_10 is not None else None,
            "pattern_width_bars": 2,
            "pattern_height_pct": round(float(gap_size_pct), 2),
            "pattern_quality_score": score,
            "pattern_quality_tier": "clean" if score >= 76 else ("usable" if score >= 58 else "loose"),
        }
        record.update(_evaluate_gap(df, record, lookahead=config.evaluation_bars))
        out.append(record)
        used.append(idx)
        if len(out) >= config.max_events_per_symbol:
            break
    return out, {"rows": int(len(df_raw)), "normalizer": norm_stats, "detector_config": config.to_dict(), "detections": len(out)}


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
        score = float(row.get("pattern_quality_score") or 0.0)
        if path_bucket == "clean":
            score += 8.0
        if tradability_bucket == "clean":
            score += 4.0
        if _truthy(row.get("target_first_before_adverse_5pct")):
            score += 3.0
        reasons: list[str] = []
        if float(row.get("gap_size_pct") or 0.0) < 1.5:
            reasons.append("small_gap")
        if float(row.get("breakout_volume_ratio") or 0.0) < 1.0:
            reasons.append("weak_volume")
        if row.get("variant") in {BREAKAWAY_GAPS, CONTINUATION_GAPS} and _truthy(row.get("gap_closed_10d")):
            reasons.append("closed_too_fast_for_continuation")
        score = round(float(max(0.0, min(100.0, score))), 2)
        if score >= 78 and path_bucket == "clean":
            tier = "premium"
        elif score >= 58:
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
        "gap_close_rate": _rate(rows, "gap_closed"),
        "gap_close_5d_rate": _rate(rows, "gap_closed_5d"),
        "gap_close_10d_rate": _rate(rows, "gap_closed_10d"),
        "gap_close_20d_rate": _rate(rows, "gap_closed_20d"),
        "median_days_to_gap_close": _median([row.get("days_to_gap_close") for row in rows]),
        "median_gap_size_pct": _median([row.get("gap_size_pct") for row in rows]),
        "median_volume_ratio": _median([row.get("breakout_volume_ratio") for row in rows]),
        "median_quality_score": _median([row.get("pattern_quality_score") for row in rows]),
    }


def _group_table(rows: Sequence[Mapping[str, Any]], column: str, labels: Sequence[str]) -> Dict[str, Any]:
    return {label: _group_stats([row for row in rows if str(row.get(column) or "unknown") == label]) for label in labels}


def summarize(scan: Mapping[str, Any], *, pattern_key: str) -> Dict[str, Any]:
    rows = [row for row in list(scan.get("detections") or []) if row.get("variant") == pattern_key]
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
        "publication_quality_table": {tier: _group_stats([row for row in rows if row.get("publication_quality_tier") == tier]) for tier in ("premium", "standard", "loose", "data_limited")},
        "regime_groups": _group_table(rows, "market_regime", ("bull", "bear", "unknown")),
        "market_group_table": _group_table(rows, "market_group", ("VN30", "VN100 ex VN30", "Outside VN100")),
        "liquidity_proxy_table": _group_table(rows, "liquidity_bucket", ("high", "mid", "low", "unknown")),
        "path_quality_audit": {
            "bucket_counts": dict(pd.Series([str(row.get("path_quality_bucket") or "unknown") for row in rows]).value_counts().sort_index()),
            "median_coverage_60d": _median([row.get("evaluated_bars") for row in rows]),
        },
        "quantile_metrics": {
            "fav_exc_pct": _quantiles([row.get("mfe_pct") for row in evals]),
            "adv_exc_pct": _quantiles([row.get("mae_pct") for row in evals]),
            "target_dist_pct": _quantiles([row.get("target_dist_pct") for row in evals]),
            "gap_size_pct": _quantiles([row.get("gap_size_pct") for row in rows]),
            "days_to_gap_close": _quantiles([row.get("days_to_gap_close") for row in rows]),
            "volume_ratio": _quantiles([row.get("breakout_volume_ratio") for row in rows]),
        },
        "experiment_note": "Gap scanner classifies area, breakaway, continuation, and exhaustion gaps with gap-closure and trend-context diagnostics.",
    }


def _add_target_calibration(stats: Dict[str, Any], events: pd.DataFrame, path_rows: Sequence[Mapping[str, Any]], *, pattern_key: str) -> None:
    path = pd.DataFrame(list(path_rows))
    if events.empty:
        stats["target_family_sensitivity"] = []
        stats["target_calibration_decision"] = None
        return
    if "event_id" not in events.columns and "detection_id" in events.columns:
        events = events.assign(event_id=events["detection_id"])
    sensitivity = target_sensitivity(PatternArtifacts(pattern_key, events, path), pattern_key, horizon_days=120)
    stats["target_family_sensitivity"] = sensitivity
    stats["target_calibration_decision"] = (build_target_calibration_decisions(sensitivity, family_labels=(pattern_key,)) or [None])[0]
    stats["target_family"] = {"half_gap": 0.5, "three_quarter_gap": 0.75, "full_gap": 1.0}


EVENT_FIELDS = [
    "detection_id", "symbol", "variant", "market_group", "market_regime",
    "formation_start_date", "formation_end_date", "breakout_date", "breakout_direction",
    "breakout_price", "b_exec_price", "target_price", "target_dist_pct",
    "mfe_pct", "mae_pct", "target_hit", "failure_5pct", "target_first_before_adverse_5pct",
    "days_to_target", "pattern_quality_score", "pattern_quality_tier",
    "publication_quality_score", "publication_quality_tier", "publication_quality_reasons",
    "pattern_width_bars", "pattern_height_pct", "gap_direction", "gap_top_price",
    "gap_bottom_price", "gap_rim_close_price", "gap_size_pct", "gap_size_abs",
    "gap_closed", "days_to_gap_close", "gap_closed_5d", "gap_closed_10d", "gap_closed_20d",
    "prior_trend_pct", "signed_prior_trend_pct", "consolidation_range_pct",
    "breakout_volume_ratio", "post_new_extremes_10d", "post_adverse_10d_pct",
    "evaluated_bars", "is_primary_event_60d", "liquidity_bucket", "path_quality_bucket",
    "tradability_quality_bucket", "tradability_quality_score", "missing_bar_rate_60d",
    "zero_volume_rate_60d", "price_limit_proxy_rate_60d",
]


def scan_gaps_db(
    *,
    db_path: Path,
    out_dir: Path,
    allowed_symbols: Optional[Sequence[str]] = None,
    detector_config: Optional[Mapping[str, Any]] = None,
    limit_symbols: Optional[int] = None,
    index_db: Path = DEFAULT_INDEX_DB,
    index_symbol: str = DEFAULT_INDEX_SYMBOL,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    config = GapConfig.from_mapping(detector_config)
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
                rows, stats = scan_symbol(frame, detector_config=config)
                if rows:
                    series_by_symbol[symbol] = frame
                detections.extend(rows)
                symbol_stats.append({"symbol": symbol, "detections": len(rows), **stats})
            except Exception as exc:
                symbol_stats.append({"symbol": symbol, "detections": 0, "error": str(exc)})
    finally:
        conn.close()
    for i, row in enumerate(detections):
        row["detection_id"] = f"gap_family:{i + 1:06d}"
    detections, regime_meta = classify_market_regimes(detections, index_db=index_db, index_symbol=index_symbol, anchor_field="breakout_date")
    market_group_meta = attach_current_market_groups(detections)
    scan: dict[str, Any] = {
        "generated_at": _utc_now(),
        "source": "Market Cache latest.sqlite stock_price_history",
        "db_path": str(db_path),
        "pattern_key": "gap_family",
        "symbols_scanned": len(symbols),
        "detections": detections,
        "symbol_stats": symbol_stats,
        "regime": regime_meta,
        "market_group": market_group_meta,
        "detector_config": config.to_dict(),
    }
    _enrich_events_from_series(scan, series_by_symbol, corporate_db=index_db)
    _assign_publication_quality_tiers(scan["detections"])
    path_rows = _path_rows_from_series(scan, series_by_symbol, horizon_bars=config.evaluation_bars)
    paths: dict[str, Path] = {"detections": out_dir / "detections.json"}
    _write_json(paths["detections"], scan)
    for pattern_key in GAP_PATTERNS:
        subtype_rows = [row for row in scan.get("detections") or [] if row.get("variant") == pattern_key]
        subtype_dir = out_dir / pattern_key / "db_active"
        subtype_dir.mkdir(parents=True, exist_ok=True)
        subtype_scan = dict(scan)
        subtype_scan["pattern_key"] = pattern_key
        subtype_scan["detections"] = subtype_rows
        subtype_path_rows = [row for row in path_rows if row.get("event_id") in {item.get("detection_id") for item in subtype_rows}]
        stats = summarize(scan, pattern_key=pattern_key)
        stats["source"] = scan["source"]
        stats["db_source_meta"] = _db_meta(db_path)
        stats["detector_config"] = config.to_dict()
        _add_target_calibration(stats, pd.DataFrame(subtype_rows), subtype_path_rows, pattern_key=pattern_key)
        paths[f"{pattern_key}_detections"] = subtype_dir / "detections.json"
        paths[f"{pattern_key}_statistics"] = subtype_dir / "statistics.json"
        paths[f"{pattern_key}_events_csv"] = subtype_dir / "events.csv"
        paths[f"{pattern_key}_post_breakout_path_csv"] = subtype_dir / "post_breakout_path.csv"
        _write_json(paths[f"{pattern_key}_detections"], subtype_scan)
        _write_json(paths[f"{pattern_key}_statistics"], stats)
        _write_csv(paths[f"{pattern_key}_events_csv"], subtype_rows, EVENT_FIELDS)
        _write_csv(
            paths[f"{pattern_key}_post_breakout_path_csv"],
            subtype_path_rows,
            ["event_id", "symbol", "trade_date", "bar_after_breakout", "open", "high", "low", "close", "volume", "signed_close_return_pct", "signed_high_excursion_pct", "signed_low_excursion_pct"],
        )
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Gap Family scanner against Market Cache latest.sqlite.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--market-stats-json", default=str(DEFAULT_MARKET_STATS_JSON))
    parser.add_argument("--limit-symbols", type=int, default=None)
    args = parser.parse_args()
    active_meta = _load_active_symbols(Path(args.market_stats_json) if args.market_stats_json else None)
    active_symbols = active_meta.get("active_symbols") if active_meta.get("enabled") else None
    paths = scan_gaps_db(
        db_path=Path(args.db),
        out_dir=Path(args.out_dir),
        allowed_symbols=active_symbols,
        limit_symbols=args.limit_symbols,
    )
    print(json.dumps({"status": "PASS", "outputs": {key: str(value) for key, value in paths.items()}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
