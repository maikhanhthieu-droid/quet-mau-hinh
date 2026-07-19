"""Head-and-Shoulders Family scanner.

This module wraps the source-grounded digitized Head-and-Shoulders geometry in
the Scanner V2 data contract.  The family has four Bulkowski chapters:
standard/complex bottoms and standard/complex tops.  Geometry stays in the
digitized family scanner; this file owns DB scanning, path outcomes, quality
tiers, and portable artifacts for the public chapter factory.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.digitized_pattern_engine import (  # noqa: E402
    DigitizedPatternLibrary,
    HeadShouldersBottomFamilyScanner,
    HeadShouldersTopFamilyScanner,
)
from scanner.ohlcv_normalizer import OHLCVNormalizer  # noqa: E402
from scanner.pivot_detector import PivotDetector  # noqa: E402
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


HEAD_SHOULDERS_PATTERNS = (
    "head_and_shoulders_bottoms",
    "head_and_shoulders_bottoms_complex",
    "head_and_shoulders_tops",
    "head_and_shoulders_tops_complex",
)
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/head_shoulders_family")
DEFAULT_PROFILE = "source_aligned_recall"


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


def _load_metrics(row: Mapping[str, Any]) -> Dict[str, Any]:
    raw = row.get("family_metrics_json")
    if isinstance(raw, Mapping):
        return dict(raw)
    try:
        loaded = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _source_aligned_spec(library: DigitizedPatternLibrary, base_key: str, *, profile: str) -> dict[str, Any]:
    spec = dict(library.load(base_key))
    if profile == "strict_source":
        return spec
    if profile != "source_aligned_recall":
        raise ValueError(f"unsupported H&S profile {profile}")
    spec = json.loads(json.dumps(spec))
    geom = spec.setdefault("geometry_constraints", {})
    geom["height_ratio_min"] = 6.0
    geom["height_ratio_max"] = 55.0
    geom["symmetry_tolerance_pct"] = 8.0
    geom["near_equal_tolerance_pct"] = 4.0
    geom.setdefault("slope_constraints", {})["neckline_max_slope_degrees"] = 4.0
    prominence_key = "head_above_shoulders_pct" if base_key.endswith("_top") else "head_below_shoulders_pct"
    geom.setdefault(prominence_key, {})["min"] = 1.5
    prior = spec.setdefault("prior_trend_requirements", {})
    prior["min_period_bars"] = 42
    prior["min_change_pct"] = 8.0
    breakout = spec.setdefault("breakout_confirmation", {})
    breakout["volume_required"] = False
    breakout["volume_multiplier_min"] = 1.0
    return spec


def _build_base_scanners(*, profile: str) -> dict[str, Any]:
    library = DigitizedPatternLibrary()
    bottom = HeadShouldersBottomFamilyScanner(
        "head_and_shoulders_bottom",
        _source_aligned_spec(library, "head_and_shoulders_bottom", profile=profile),
    )
    top = HeadShouldersTopFamilyScanner(
        "head_and_shoulders_top",
        _source_aligned_spec(library, "head_and_shoulders_top", profile=profile),
    )
    if profile == "source_aligned_recall":
        for scanner in (bottom, top):
            scanner.side_span_ratio_max = 3.2
            scanner.neckline_max_slope_deg = 4.0
            scanner.height_min_pct = 6.0
            scanner.height_max_pct = 55.0
        bottom.bottom_min_shoulder_clearance_pct = 4.0
        bottom.bottom_relaxed_neckline_max_deg = 5.0
        bottom.bottom_relaxed_neckline_diff_pct = 8.0
        bottom.bottom_relaxed_shoulder_diff_pct = 5.0
        bottom.bottom_relaxed_span_ratio_max = 2.4
    return {"bottom": bottom, "top": top}


def _base_key_for_pattern(pattern_key: str) -> str:
    return "bottom" if "bottom" in pattern_key else "top"


def _keep_variant(pattern_key: str, row: Mapping[str, Any]) -> bool:
    variant = str(row.get("variant_code") or "standard")
    if pattern_key.endswith("_complex"):
        return variant == "complex"
    return variant != "complex"


def _quality_score(row: Mapping[str, Any], metrics: Mapping[str, Any]) -> float:
    score = 0.0
    score += _score_band(_safe_float(row.get("confidence_score")), good=86.0, weak=58.0, weight=0.18)
    score += _score_band(_safe_float(row.get("variant_confidence")), good=82.0, weak=58.0, weight=0.10)
    score += _score_band(_safe_float(metrics.get("shoulder_diff_pct")), good=1.5, weak=7.5, reverse=True, weight=0.18)
    score += _score_band(_safe_float(metrics.get("head_prominence_pct")), good=6.0, weak=2.0, weight=0.18)
    score += _score_band(_safe_float(metrics.get("neckline_slope_deg")), good=1.6, weak=5.0, reverse=True, weight=0.14)
    score += _score_band(_safe_float(metrics.get("side_span_ratio")), good=1.25, weak=2.6, reverse=True, weight=0.10)
    score += _score_band(_safe_float(metrics.get("shoulder_clearance_pct")), good=8.0, weak=2.5, weight=0.12)
    return round(float(max(0.0, min(100.0, score))), 2)


def _normalize_detection(row: Mapping[str, Any], df: pd.DataFrame, pattern_key: str) -> Dict[str, Any]:
    metrics = _load_metrics(row)
    breakout_idx = int(row.get("breakout_idx"))
    formation_start = str(row.get("formation_start"))
    formation_end = str(row.get("formation_end"))
    quality = _quality_score(row, metrics)
    out = {
        "source_pattern_key": pattern_key,
        "symbol": str(row.get("symbol") or "").upper(),
        "variant": str(row.get("variant_code") or ("complex" if pattern_key.endswith("_complex") else "standard")),
        "variant_confidence": int(row.get("variant_confidence") or 0),
        "base_pattern_name": row.get("base_pattern_name"),
        "formation_start_date": formation_start,
        "formation_end_date": formation_end,
        "breakout_date": str(row.get("breakout_date")),
        "breakout_idx": breakout_idx,
        "breakout_direction": row.get("breakout_direction"),
        "breakout_price": round(float(row.get("breakout_price")), 4),
        "target_price": round(float(row.get("target_price")), 4),
        "stop_loss_price": round(float(row.get("stop_loss_price")), 4) if _safe_float(row.get("stop_loss_price")) is not None else None,
        "pattern_width_bars": int(row.get("pattern_width_bars") or 0),
        "pattern_height_pct": round(float(row.get("pattern_height_pct") or metrics.get("height_pct") or 0.0), 2),
        "touch_count": int(row.get("touch_count") or 0),
        "confidence_score": int(row.get("confidence_score") or 0),
        "volume_confirmed": bool(_truthy(row.get("volume_confirmed"))),
        "breakout_volume_ratio": round(float(df.iloc[breakout_idx].get("volume_ratio")), 4) if "volume_ratio" in df.columns and breakout_idx < len(df) and pd.notna(df.iloc[breakout_idx].get("volume_ratio")) else None,
        "pivot_indices": json.dumps(row.get("pivot_indices") or [], ensure_ascii=False),
        "variant_evidence_json": row.get("variant_evidence_json"),
        "family_metrics_json": row.get("family_metrics_json"),
        "neckline_price": round(float(metrics.get("neckline_level")), 4) if _safe_float(metrics.get("neckline_level")) is not None else None,
        "neckline_slope_deg": round(float(metrics.get("neckline_slope_deg")), 4) if _safe_float(metrics.get("neckline_slope_deg")) is not None else None,
        "shoulder_diff_pct": round(float(metrics.get("shoulder_diff_pct")), 4) if _safe_float(metrics.get("shoulder_diff_pct")) is not None else None,
        "head_prominence_pct": round(float(metrics.get("head_prominence_pct")), 4) if _safe_float(metrics.get("head_prominence_pct")) is not None else None,
        "shoulder_clearance_pct": round(float(metrics.get("shoulder_clearance_pct")), 4) if _safe_float(metrics.get("shoulder_clearance_pct")) is not None else None,
        "side_span_ratio": round(float(metrics.get("side_span_ratio")), 4) if _safe_float(metrics.get("side_span_ratio")) is not None else None,
        "head_price": round(float(metrics.get("head_price")), 4) if _safe_float(metrics.get("head_price")) is not None else None,
        "left_shoulder_price": round(float(metrics.get("ls_price")), 4) if _safe_float(metrics.get("ls_price")) is not None else None,
        "right_shoulder_price": round(float(metrics.get("rs_price")), 4) if _safe_float(metrics.get("rs_price")) is not None else None,
        "pattern_quality_score": quality,
        "pattern_quality_tier": "clean" if quality >= 78.0 else ("usable" if quality >= 61.0 else "loose"),
    }
    out.update(_evaluate_detection(df, out))
    return out


def scan_symbol(frame: pd.DataFrame, *, pattern_key: str, scanner: Any, normalizer: OHLCVNormalizer, pivot_detector: PivotDetector) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    df_norm, _ = normalizer.normalize(frame)
    raw_pivots = pivot_detector.detect_pivots(df_norm, "intermediate")
    pivots = pivot_detector.get_filtered_pivots(raw_pivots, min_spacing=10)
    rows = scanner.scan(symbol=str(frame.iloc[0]["symbol"]).upper(), df=df_norm, pivots_filtered=pivots, pivots_raw=raw_pivots)
    normalized = [_normalize_detection(row, df_norm, pattern_key) for row in rows]
    return normalized, {"raw_pivots": len(raw_pivots), "filtered_pivots": len(pivots)}


def _assign_publication_quality_tiers(rows: list[dict[str, Any]], *, defensive: bool = False) -> None:
    data_limited_path = {"short_path", "zero_and_stale", "zero_volume", "mixed_flag"}
    for row in rows:
        path_bucket = str(row.get("path_quality_bucket") or "unknown")
        tradability_bucket = str(row.get("tradability_quality_bucket") or "unknown")
        quality = _safe_float(row.get("pattern_quality_score"))
        neckline_slope = _safe_float(row.get("neckline_slope_deg"))
        shoulder_diff = _safe_float(row.get("shoulder_diff_pct"))
        head_prominence = _safe_float(row.get("head_prominence_pct"))
        mfe_pct = _safe_float(row.get("mfe_pct"))
        mae_pct = _safe_float(row.get("mae_pct"))
        mfe_mae_ratio = None if mfe_pct is None or mae_pct is None else float(mfe_pct) / max(float(mae_pct), 1.0)
        target_hit = _truthy(row.get("target_hit"))
        target_first = _truthy(row.get("target_first_before_adverse_5pct"))
        failure = _truthy(row.get("failure_5pct"))
        reasons: list[str] = []
        if path_bucket in data_limited_path or tradability_bucket == "impaired":
            row["publication_quality_score"] = 0.0
            row["publication_quality_tier"] = "data_limited"
            row["publication_quality_reasons"] = ",".join(filter(None, [f"path:{path_bucket}", f"tradability:{tradability_bucket}"]))
            continue
        score = 0.0
        score += _score_band(quality, good=82.0, weak=55.0, weight=0.36)
        score += _score_band(shoulder_diff, good=2.0, weak=7.0, reverse=True, weight=0.12)
        score += _score_band(head_prominence, good=6.0, weak=2.0, weight=0.12)
        score += _score_band(neckline_slope, good=1.6, weak=5.0, reverse=True, weight=0.10)
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
            score += 5.0
        else:
            reasons.append("no_target_hit")
        if target_first:
            score += 5.0
        else:
            reasons.append("not_target_first")
        if failure:
            reasons.append("failure_5pct")
        if mfe_mae_ratio is not None and mfe_mae_ratio < (1.10 if defensive else 1.25):
            reasons.append("weak_mfe_mae_ratio")
        score = round(float(max(0.0, min(100.0, score))), 2)
        premium_ok = (
            score >= 78.0
            and path_bucket == "clean"
            and target_hit
            and target_first
            and not failure
            and (mfe_mae_ratio is not None and mfe_mae_ratio >= (1.12 if defensive else 1.35))
            and (mae_pct is not None and mae_pct <= 24.0)
        )
        row["publication_quality_score"] = score
        row["publication_quality_tier"] = "premium" if premium_ok else ("standard" if score >= 61.0 else "loose")
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
        "median_days_to_target": _median([row.get("days_to_target") for row in evals]),
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
    pattern_key = str(scan.get("pattern_key") or "head_shoulders")
    direction = "up" if "bottom" in pattern_key else "down"
    return {
        "generated_at": _utc_now(),
        "pattern_key": pattern_key,
        "symbols_scanned": int(scan.get("symbols_scanned") or 0),
        "detection_count": len(rows),
        "evaluated_count": len(evals),
        "up_breakouts": len(rows) if direction == "up" else 0,
        "down_breakouts": len(rows) if direction == "down" else 0,
        **_group_stats(rows),
        "breakout_groups": {"all": _group_stats(rows), "up": _group_stats(rows if direction == "up" else []), "down": _group_stats(rows if direction == "down" else [])},
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
            "width_bars": _quantiles([row.get("pattern_width_bars") for row in rows]),
            "height_pct": _quantiles([row.get("pattern_height_pct") for row in rows]),
        },
        "experiment_note": "Head-and-Shoulders scanner uses five-pivot shoulder-head-shoulder geometry, neckline breakout, and standard/complex shoulder count classification.",
    }


EVENT_FIELDS = [
    "detection_id",
    "source_pattern_key",
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
    "throwback_pullback_30d",
    "days_to_target",
    "days_to_throwback_pullback",
    "pattern_quality_score",
    "pattern_quality_tier",
    "publication_quality_score",
    "publication_quality_tier",
    "publication_quality_reasons",
    "pattern_width_bars",
    "pattern_height_pct",
    "neckline_price",
    "neckline_slope_deg",
    "shoulder_diff_pct",
    "head_prominence_pct",
    "shoulder_clearance_pct",
    "side_span_ratio",
    "head_price",
    "left_shoulder_price",
    "right_shoulder_price",
    "confidence_score",
    "volume_confirmed",
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


def _add_target_calibration(stats: Dict[str, Any], scan: Mapping[str, Any], path_rows: Sequence[Mapping[str, Any]]) -> None:
    from scanner.research_support_analysis import PatternArtifacts, build_target_calibration_decisions, target_sensitivity

    events = pd.DataFrame(list(scan.get("detections") or []))
    path = pd.DataFrame(list(path_rows))
    pattern_key = str(scan.get("pattern_key") or "head_shoulders")
    if events.empty:
        stats["target_family_sensitivity"] = []
        stats["target_calibration_decision"] = None
        stats["target_family"] = {"local_base": 0.5, "local_stretch": 0.75, "legacy_full_height": 1.0}
        return
    if "event_id" not in events.columns and "detection_id" in events.columns:
        events["event_id"] = events["detection_id"]
    sensitivity = target_sensitivity(PatternArtifacts(pattern_key, events, path), pattern_key, horizon_days=120)
    stats["target_family_sensitivity"] = sensitivity
    stats["target_calibration_decision"] = (build_target_calibration_decisions(sensitivity, family_labels=(pattern_key,)) or [None])[0]
    stats["target_family"] = {"local_base": 0.5, "local_stretch": 0.75, "legacy_full_height": 1.0}


def scan_head_shoulders_db(
    *,
    pattern_key: str,
    db_path: Path,
    out_dir: Path,
    allowed_symbols: Optional[Sequence[str]] = None,
    limit_symbols: Optional[int] = None,
    index_db: Path = DEFAULT_INDEX_DB,
    index_symbol: str = DEFAULT_INDEX_SYMBOL,
    profile: str = DEFAULT_PROFILE,
) -> dict[str, Path]:
    outputs = scan_head_shoulders_patterns_db(
        pattern_keys=[pattern_key],
        db_path=db_path,
        out_dir=out_dir.parent.parent if out_dir.name == "db_active" else out_dir,
        allowed_symbols=allowed_symbols,
        limit_symbols=limit_symbols,
        index_db=index_db,
        index_symbol=index_symbol,
        profile=profile,
    )
    return outputs[pattern_key]


def scan_head_shoulders_patterns_db(
    *,
    pattern_keys: Sequence[str],
    db_path: Path,
    out_dir: Path,
    allowed_symbols: Optional[Sequence[str]] = None,
    limit_symbols: Optional[int] = None,
    index_db: Path = DEFAULT_INDEX_DB,
    index_symbol: str = DEFAULT_INDEX_SYMBOL,
    profile: str = DEFAULT_PROFILE,
) -> dict[str, dict[str, Path]]:
    """Scan several H&S chapter keys in one pass over the DB.

    Bottom standard/complex share the same base geometry scanner; top
    standard/complex do too.  Running them in one pass avoids re-normalizing
    and re-pivoting each symbol four times.
    """

    keys = [str(key) for key in pattern_keys]
    for key in keys:
        if key not in HEAD_SHOULDERS_PATTERNS:
            raise ValueError(f"unsupported Head-and-Shoulders pattern {key}")
    out_dir.mkdir(parents=True, exist_ok=True)
    symbols = _symbols_in_db(db_path, allowed_symbols)
    if limit_symbols is not None:
        symbols = symbols[: int(limit_symbols)]
    base_scanners = _build_base_scanners(profile=profile)
    normalizer = OHLCVNormalizer()
    pivot_detector = PivotDetector()
    detections_by_key: dict[str, list[dict[str, Any]]] = {key: [] for key in keys}
    symbol_stats_by_key: dict[str, list[dict[str, Any]]] = {key: [] for key in keys}
    series_by_symbol: dict[str, pd.DataFrame] = {}
    conn = sqlite3.connect(str(db_path))
    try:
        for symbol in symbols:
            try:
                frame = _load_symbol_from_db(conn, symbol)
                df_norm, _ = normalizer.normalize(frame)
                raw_pivots = pivot_detector.detect_pivots(df_norm, "intermediate")
                pivots = pivot_detector.get_filtered_pivots(raw_pivots, min_spacing=10)
                any_rows = False
                base_rows: dict[str, list[Mapping[str, Any]]] = {}
                for base_key, scanner in base_scanners.items():
                    base_rows[base_key] = scanner.scan(symbol=symbol, df=df_norm, pivots_filtered=pivots, pivots_raw=raw_pivots)
                for key in keys:
                    try:
                        rows_raw = [row for row in base_rows[_base_key_for_pattern(key)] if _keep_variant(key, row)]
                        rows = [_normalize_detection(row, df_norm, key) for row in rows_raw]
                    except Exception as exc:  # keep per-pattern audit trail without killing the family run
                        rows = []
                        symbol_stats_by_key[key].append({"symbol": symbol, "detections": 0, "error": str(exc), "raw_pivots": len(raw_pivots), "filtered_pivots": len(pivots)})
                        continue
                    detections_by_key[key].extend(rows)
                    symbol_stats_by_key[key].append({"symbol": symbol, "detections": len(rows), "raw_pivots": len(raw_pivots), "filtered_pivots": len(pivots)})
                    any_rows = any_rows or bool(rows)
                if any_rows:
                    series_by_symbol[symbol] = frame
            except Exception as exc:
                for key in keys:
                    symbol_stats_by_key[key].append({"symbol": symbol, "detections": 0, "error": str(exc)})
    finally:
        conn.close()

    outputs: dict[str, dict[str, Path]] = {}
    for pattern_key in keys:
        detections = detections_by_key[pattern_key]
        for i, row in enumerate(detections):
            row["detection_id"] = f"{pattern_key}:{i + 1:06d}"
        detections, regime_meta = classify_market_regimes(detections, index_db=index_db, index_symbol=index_symbol, anchor_field="breakout_date")
        market_group_meta = attach_current_market_groups(detections)
        scan: dict[str, Any] = {
            "generated_at": _utc_now(),
            "source": "Market Cache latest.sqlite stock_price_history",
            "db_path": str(db_path),
            "pattern_key": pattern_key,
            "symbols_scanned": len(symbols),
            "detections": detections,
            "symbol_stats": symbol_stats_by_key[pattern_key],
            "regime": regime_meta,
            "market_group": market_group_meta,
            "detector_config": {
                "family_scanner": "digitized_head_shoulders_family",
                "pivot_type": "intermediate",
                "pivot_min_spacing": 10,
                "source_family": "bulkowski_53_strict",
                "profile": profile,
                "multi_pattern_one_pass": True,
            },
        }
        _enrich_events_from_series(scan, series_by_symbol, corporate_db=index_db)
        _assign_publication_quality_tiers(scan["detections"], defensive=("tops" in pattern_key))
        path_rows = _path_rows_from_series(scan, series_by_symbol, horizon_bars=120)
        stats = summarize(scan)
        stats["source"] = scan["source"]
        stats["db_source_meta"] = _db_meta(db_path)
        stats["detector_config"] = scan["detector_config"]
        _add_target_calibration(stats, scan, path_rows)
        chapter_dir = out_dir / pattern_key / "db_active"
        chapter_dir.mkdir(parents=True, exist_ok=True)
        paths = {
            "detections": chapter_dir / "detections.json",
            "statistics": chapter_dir / "statistics.json",
            "events_csv": chapter_dir / "events.csv",
            "post_breakout_path_csv": chapter_dir / "post_breakout_path.csv",
        }
        _write_json(paths["detections"], scan)
        _write_json(paths["statistics"], stats)
        _write_csv(paths["events_csv"], scan.get("detections") or [], EVENT_FIELDS)
        _write_csv(
            paths["post_breakout_path_csv"],
            path_rows,
            ["event_id", "symbol", "trade_date", "bar_after_breakout", "open", "high", "low", "close", "volume", "signed_close_return_pct", "signed_high_excursion_pct", "signed_low_excursion_pct"],
        )
        outputs[pattern_key] = paths
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Head-and-Shoulders Family scanners against Market Cache latest.sqlite.")
    parser.add_argument("--pattern", choices=[*HEAD_SHOULDERS_PATTERNS, "all"], default="all")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--market-stats-json", default=str(DEFAULT_MARKET_STATS_JSON))
    parser.add_argument("--limit-symbols", type=int, default=None)
    parser.add_argument("--profile", choices=["source_aligned_recall", "strict_source"], default=DEFAULT_PROFILE)
    args = parser.parse_args()
    active_meta = _load_active_symbols(Path(args.market_stats_json) if args.market_stats_json else None)
    active_symbols = active_meta.get("active_symbols") if active_meta.get("enabled") else None
    patterns = list(HEAD_SHOULDERS_PATTERNS) if args.pattern == "all" else [args.pattern]
    if args.pattern == "all":
        raw_outputs = scan_head_shoulders_patterns_db(
            pattern_keys=patterns,
            db_path=Path(args.db),
            out_dir=Path(args.out_dir),
            allowed_symbols=active_symbols,
            limit_symbols=args.limit_symbols,
            profile=args.profile,
        )
        outputs = {pattern_key: {key: str(value) for key, value in paths.items()} for pattern_key, paths in raw_outputs.items()}
    else:
        paths = scan_head_shoulders_db(
            pattern_key=args.pattern,
            db_path=Path(args.db),
            out_dir=Path(args.out_dir) / args.pattern / "db_active",
            allowed_symbols=active_symbols,
            limit_symbols=args.limit_symbols,
            profile=args.profile,
        )
        outputs = {args.pattern: {key: str(value) for key, value in paths.items()}}
    print(json.dumps(outputs, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
