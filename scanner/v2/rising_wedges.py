"""Rising Wedge scanner for the Wedge Family lane.

This is a pattern-specific scanner. It shares the event/path contract with
Triangle/Flag chapters, but the geometry is not inherited from triangles:
both boundaries slope upward and converge; the primary chapter lane is a
downward breakout through the lower boundary.
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


PATTERN_KEY = "wedges_rising"
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/rising_wedges_db_source_parity")


@dataclass(frozen=True)
class RisingWedgeConfig:
    width_min_bars: int = 20
    width_max_bars: int = 110
    high_rise_min_pct: float = 3.0
    low_rise_min_pct: float = 4.0
    upper_slope_min_pos_deg: float = 0.5
    upper_slope_max_pos_deg: float = 16.0
    lower_slope_min_pos_deg: float = 1.5
    lower_slope_max_pos_deg: float = 45.0
    lower_faster_than_upper_min_deg: float = 0.5
    height_min_pct: float = 5.0
    height_max_pct: float = 42.0
    compression_max_ratio: float = 0.88
    breakout_search_bars: int = 28
    breakout_threshold: float = 0.0075
    breakout_cooldown_bars: int = 35
    max_events_per_symbol: int = 8

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]] = None) -> "RisingWedgeConfig":
        if value is None:
            return cls()
        allowed = {field.name for field in fields(cls)}
        return cls(**{key: item for key, item in value.items() if key in allowed})

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RisingWedgeDetector:
    def __init__(self, config: Optional[RisingWedgeConfig | Mapping[str, Any]] = None) -> None:
        self.config = config if isinstance(config, RisingWedgeConfig) else RisingWedgeConfig.from_mapping(config)

    def _breakout(self, df: pd.DataFrame, *, start_idx: int, lower: Trendline) -> Tuple[Optional[int], Optional[float], Optional[float], Optional[float]]:
        for idx in range(start_idx, min(len(df), start_idx + self.config.breakout_search_bars)):
            close = _safe_float(df.iloc[idx].get("close"))
            if close is None:
                continue
            lower_level = lower.value_at(idx)
            if close < lower_level * (1.0 - self.config.breakout_threshold):
                volume_ratio = _safe_float(df.iloc[idx].get("volume_ratio"))
                return idx, close, volume_ratio, (lower_level - close) / lower_level * 100.0
        return None, None, None, None

    def scan_window(self, df: pd.DataFrame, pivots: Sequence[Pivot]) -> Optional[Dict[str, Any]]:
        if len(pivots) < 4:
            return None
        highs = [pivot for pivot in pivots if pivot.type == PivotType.HIGH]
        lows = [pivot for pivot in pivots if pivot.type == PivotType.LOW]
        if len(highs) < 2 or len(lows) < 2:
            return None
        h1, h2 = highs[0], highs[1]
        l1, l2 = lows[0], lows[1]
        idxs = [int(h1.idx), int(h2.idx), int(l1.idx), int(l2.idx)]
        if len(set(idxs)) != len(idxs) or not (int(h1.idx) < int(h2.idx) and int(l1.idx) < int(l2.idx)):
            return None
        formation_start = min(idxs)
        formation_end = max(idxs)
        width = formation_end - formation_start + 1
        if width < self.config.width_min_bars or width > self.config.width_max_bars:
            return None

        h1_price, h2_price = float(df.iloc[int(h1.idx)]["high"]), float(df.iloc[int(h2.idx)]["high"])
        l1_price, l2_price = float(df.iloc[int(l1.idx)]["low"]), float(df.iloc[int(l2.idx)]["low"])
        if min(h1_price, h2_price, l1_price, l2_price) <= 0:
            return None
        if h1_price <= l1_price or h2_price <= l2_price:
            return None

        high_rise_pct = (h2_price - h1_price) / h1_price * 100.0
        low_rise_pct = (l2_price - l1_price) / l1_price * 100.0
        if high_rise_pct < self.config.high_rise_min_pct or low_rise_pct < self.config.low_rise_min_pct:
            return None

        upper_deg = _slope_degrees(int(h1.idx), h1_price, int(h2.idx), h2_price)
        lower_deg = _slope_degrees(int(l1.idx), l1_price, int(l2.idx), l2_price)
        if upper_deg < self.config.upper_slope_min_pos_deg or upper_deg > self.config.upper_slope_max_pos_deg:
            return None
        if lower_deg < self.config.lower_slope_min_pos_deg or lower_deg > self.config.lower_slope_max_pos_deg:
            return None
        if lower_deg - upper_deg < self.config.lower_faster_than_upper_min_deg:
            return None

        upper = Trendline(int(h1.idx), h1_price, (h2_price - h1_price) / max(1, int(h2.idx) - int(h1.idx)))
        lower = Trendline(int(l1.idx), l1_price, (l2_price - l1_price) / max(1, int(l2.idx) - int(l1.idx)))
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
        compression_ratio = last_gap / first_gap
        if compression_ratio <= 0 or compression_ratio > self.config.compression_max_ratio:
            return None

        height_abs = first_gap
        height_pct = height_abs / max(upper_start, 1e-9) * 100.0
        if height_pct < self.config.height_min_pct or height_pct > self.config.height_max_pct:
            return None

        breakout_idx, breakout_price, volume_ratio, clearance_pct = self._breakout(df, start_idx=formation_end + 1, lower=lower)
        if breakout_idx is None or breakout_price is None:
            return None

        target_price = float(breakout_price) - height_abs
        quality_score = 62.0
        quality_score += min(8.0, high_rise_pct)
        quality_score += min(12.0, low_rise_pct)
        quality_score += max(0.0, (self.config.compression_max_ratio - compression_ratio) / self.config.compression_max_ratio * 10.0)
        quality_score += min(6.0, max(0.0, lower_deg - upper_deg))
        if volume_ratio is not None and volume_ratio >= 1.2:
            quality_score += 5.0
        quality_score = int(max(0, min(100, round(quality_score))))

        return {
            "formation_start_idx": int(formation_start),
            "formation_end_idx": int(formation_end),
            "formation_start_date": str(pd.Timestamp(df.iloc[formation_start]["date"]).date()),
            "formation_end_date": str(pd.Timestamp(df.iloc[formation_end]["date"]).date()),
            "breakout_idx": int(breakout_idx),
            "breakout_date": str(pd.Timestamp(df.iloc[int(breakout_idx)]["date"]).date()),
            "breakout_direction": "down",
            "breakout_price": round(float(breakout_price), 4),
            "target_price": round(float(target_price), 4),
            "pattern_width_bars": int(width),
            "pattern_height_pct": round(float(height_pct), 2),
            "pivot_indices": [int(x) for x in idxs],
            "variant": "rising_wedge",
            "volume_confirmed": bool(volume_ratio is not None and volume_ratio >= 1.2),
            "breakout_volume_ratio": round(float(volume_ratio), 4) if volume_ratio is not None else None,
            "pattern_quality_score": quality_score,
            "pattern_quality_tier": "clean" if quality_score >= 85 else ("usable" if quality_score >= 74 else "loose"),
            "upper_slope_deg": round(float(upper_deg), 2),
            "lower_slope_deg": round(float(lower_deg), 2),
            "high_spread_pct": round(float(high_rise_pct), 2),
            "low_rise_pct": round(float(low_rise_pct), 2),
            "low_spread_pct": round(float(low_rise_pct), 2),
            "high_rise_pct": round(float(high_rise_pct), 2),
            "compression_ratio": round(max(float(compression_ratio), 0.001), 3),
            "breakout_clearance_pct": round(float(clearance_pct or 0.0), 2),
            "triangle_resistance": round(float(upper_start), 4),
            "triangle_support": round(float(lower_start), 4),
            "triangle_height_abs": round(float(height_abs), 4),
            "triangle_upper_idx0": int(upper.idx0),
            "triangle_upper_price0": round(float(upper.price0), 4),
            "triangle_upper_slope_per_bar": round(float(upper.slope_per_bar), 8),
            "triangle_lower_idx0": int(lower.idx0),
            "triangle_lower_price0": round(float(lower.price0), 4),
            "triangle_lower_slope_per_bar": round(float(lower.slope_per_bar), 8),
            "wedge_resistance": round(float(upper_start), 4),
            "wedge_support": round(float(lower_start), 4),
            "wedge_height_abs": round(float(height_abs), 4),
            "pole_move_pct": round(float(height_pct), 2),
            "flag_to_pole_pct": round(float(compression_ratio * 100.0), 2),
        }


def scan_symbol(
    df_raw: pd.DataFrame,
    *,
    max_events_per_symbol: Optional[int] = None,
    detector_config: Optional[RisingWedgeConfig | Mapping[str, Any]] = None,
) -> Tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(df_raw) < 160:
        return [], {"rows": int(len(df_raw)), "skipped": "too_few_rows"}
    config = detector_config if isinstance(detector_config, RisingWedgeConfig) else RisingWedgeConfig.from_mapping(detector_config)
    max_events = int(max_events_per_symbol if max_events_per_symbol is not None else config.max_events_per_symbol)
    df, norm_stats = OHLCVNormalizer().normalize(df_raw)
    pivots = PivotDetector().detect_pivots(df, pivot_type="minor")
    detector = RisingWedgeDetector(config)
    out: list[dict[str, Any]] = []
    used_breakouts: list[int] = []
    symbol = str(df.iloc[0]["symbol"])
    for window_size in (4, 5, 6):
        for i in range(len(pivots) - window_size + 1):
            candidate = detector.scan_window(df, pivots[i : i + window_size])
            if not candidate:
                continue
            breakout_idx = int(candidate["breakout_idx"])
            if any(abs(breakout_idx - prev) <= config.breakout_cooldown_bars for prev in used_breakouts):
                continue
            record = {"symbol": symbol, "pattern_key": PATTERN_KEY, **candidate}
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
        high_rise = _safe_float(row.get("high_rise_pct"))
        low_rise = _safe_float(row.get("low_rise_pct"))
        compression = _safe_float(row.get("compression_ratio"))
        breakout_clearance = _safe_float(row.get("breakout_clearance_pct"))
        volume_ratio = _safe_float(row.get("breakout_volume_ratio"))
        height_pct = _safe_float(row.get("pattern_height_pct"))
        upper_deg = _safe_float(row.get("upper_slope_deg")) or 0.0
        lower_deg = _safe_float(row.get("lower_slope_deg")) or 0.0
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
        score += _score_band(high_rise, good=7.0, weak=3.0, reverse=False, weight=0.16)
        score += _score_band(low_rise, good=9.0, weak=4.0, reverse=False, weight=0.18)
        score += _score_band(compression, good=0.50, weak=0.85, reverse=True, weight=0.18)
        score += _score_band(lower_deg - upper_deg, good=3.0, weak=0.5, reverse=False, weight=0.12)
        score += _score_band(breakout_clearance, good=2.0, weak=0.75, reverse=False, weight=0.12)
        if volume_ratio is not None:
            score += _score_band(volume_ratio, good=1.2, weak=0.8, reverse=False, weight=0.08)
        else:
            reasons.append("missing_breakout_volume")
        if height_pct is not None and 7.0 <= height_pct <= 28.0:
            score += 8.0
        elif height_pct is not None and 5.0 <= height_pct <= 36.0:
            score += 5.0
            reasons.append("wide_or_shallow_height")
        else:
            reasons.append("extreme_height")
        if path_bucket == "clean":
            score += 6.0
        else:
            reasons.append(f"path:{path_bucket}")
        if tradability_bucket == "clean":
            score += 5.0
        elif tradability_bucket == "usable":
            score += 2.0
            reasons.append("tradability:usable")
        else:
            reasons.append(f"tradability:{tradability_bucket}")

        if compression is not None and compression > 0.70:
            reasons.append("weak_compression")
        if breakout_clearance is not None and breakout_clearance < 1.2:
            reasons.append("thin_breakout_clearance")
        if lower_deg - upper_deg < 1.0:
            reasons.append("weak_wedge_convergence")

        mfe_pct = _safe_float(row.get("mfe_pct"))
        mae_pct = _safe_float(row.get("mae_pct"))
        mfe_mae_ratio = None if mfe_pct is None or mae_pct is None else float(mfe_pct) / max(float(mae_pct), 1.0)
        target_hit = _truthy(row.get("target_hit"))
        failure_5pct = _truthy(row.get("failure_5pct"))
        target_first = _truthy(row.get("target_first_before_adverse_5pct"))
        if not target_hit:
            outcome_reasons.append("no_target_hit")
        if not target_first:
            outcome_reasons.append("not_target_first")
        if failure_5pct:
            outcome_reasons.append("failure_5pct")
        if mfe_mae_ratio is not None and mfe_mae_ratio < 1.50:
            outcome_reasons.append("weak_mfe_mae_ratio")
        if mae_pct is not None and mae_pct > 22.0:
            outcome_reasons.append("large_adverse_excursion")

        strong_follow_through = target_hit and target_first and not failure_5pct and (mfe_mae_ratio is not None and mfe_mae_ratio >= 1.50) and (mae_pct is not None and mae_pct <= 22.0)
        partial_follow_through = target_hit and not failure_5pct and (mfe_mae_ratio is not None and mfe_mae_ratio >= 1.05)
        if strong_follow_through:
            outcome_label = "strong_follow_through"
        elif partial_follow_through:
            outcome_label = "partial_follow_through"
        elif failure_5pct:
            outcome_label = "failed_follow_through"
        else:
            outcome_label = "weak_or_unresolved_follow_through"

        score = round(float(max(0.0, min(100.0, score))), 2)
        premium_geometry_ok = height_pct is not None and 7.0 <= height_pct <= 28.0 and compression is not None and compression <= 0.65 and breakout_clearance is not None and breakout_clearance >= 1.20 and tradability_bucket == "clean"
        if score >= 80.0 and path_bucket == "clean" and premium_geometry_ok:
            tier = "premium"
        elif score >= 65.0:
            tier = "standard"
        else:
            tier = "loose"
        row["publication_quality_score"] = score
        row["publication_quality_tier"] = tier
        row["publication_quality_reasons"] = ",".join(sorted(set(reasons)))
        row["post_breakout_quality_label"] = outcome_label
        row["post_breakout_quality_reasons"] = ",".join(sorted(set(outcome_reasons)))


def summarize(scan: Mapping[str, Any]) -> Dict[str, Any]:
    rows = list(scan.get("detections") or [])
    evals = [row for row in rows if row.get("mfe_pct") is not None]
    return {
        "generated_at": _utc_now(),
        "pattern_key": PATTERN_KEY,
        "symbols_scanned": int(scan.get("symbols_scanned") or 0),
        "detection_count": len(rows),
        "evaluated_count": len(evals),
        "up_breakouts": 0,
        "down_breakouts": len(rows),
        **_group_stats(rows),
        "breakout_groups": {"all": _group_stats(rows), "up": _group_stats([]), "down": _group_stats(rows)},
        "variant_table": {"rising_wedge": _group_stats(rows)},
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
        "experiment_note": "Rising Wedge scanner uses two upward converging boundaries and downward close confirmation.",
    }


EVENT_FIELDS = [
    "detection_id", "symbol", "variant", "market_group", "market_regime",
    "formation_start_idx", "formation_end_idx", "formation_start_date", "formation_end_date",
    "breakout_idx", "breakout_date", "breakout_direction", "breakout_price", "b_exec_price",
    "target_price", "target_dist_pct", "mfe_pct", "mae_pct", "target_hit", "failure_5pct",
    "target_first_before_adverse_5pct", "days_to_target", "pattern_quality_score",
    "pattern_quality_tier", "pattern_width_bars", "pattern_height_pct", "pole_move_pct",
    "flag_to_pole_pct", "upper_slope_deg", "lower_slope_deg", "high_spread_pct",
    "low_rise_pct", "low_spread_pct", "high_rise_pct", "compression_ratio",
    "breakout_clearance_pct", "volume_confirmed", "breakout_volume_ratio",
    "triangle_resistance", "triangle_support", "triangle_height_abs", "triangle_upper_idx0",
    "triangle_upper_price0", "triangle_upper_slope_per_bar", "triangle_lower_idx0",
    "triangle_lower_price0", "triangle_lower_slope_per_bar", "wedge_resistance",
    "wedge_support", "wedge_height_abs", "evaluated_bars", "is_primary_event_60d",
    "liquidity_bucket", "path_quality_bucket", "tradability_quality_bucket",
    "tradability_quality_score", "missing_bar_rate_60d", "zero_volume_rate_60d",
    "price_limit_proxy_rate_60d", "publication_quality_score", "publication_quality_tier",
    "publication_quality_reasons", "post_breakout_quality_label",
    "post_breakout_quality_reasons",
]


def _add_wedge_target_calibration(stats: Dict[str, Any], scan: Mapping[str, Any], path_rows: Sequence[Mapping[str, Any]]) -> None:
    from scanner.research_support_analysis import PatternArtifacts, build_target_calibration_decisions, target_sensitivity

    events = pd.DataFrame(list(scan.get("detections") or []))
    path = pd.DataFrame(list(path_rows))
    if events.empty:
        stats["target_family_sensitivity"] = []
        stats["target_calibration_decision"] = None
        return
    if "event_id" not in events.columns and "detection_id" in events.columns:
        events["event_id"] = events["detection_id"]
    sensitivity = target_sensitivity(PatternArtifacts(PATTERN_KEY, events, path), PATTERN_KEY, horizon_days=120)
    stats["target_family_sensitivity"] = sensitivity
    stats["target_calibration_decision"] = (build_target_calibration_decisions(sensitivity, family_labels=(PATTERN_KEY,)) or [None])[0]
    stats["target_family"] = {"local_base": 0.5, "local_stretch": 0.75, "legacy_full_height": 1.0}


def scan_rising_wedges_db(
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
    config = RisingWedgeConfig.from_mapping(detector_config)
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
        row["detection_id"] = f"wedges_rising:{i + 1:06d}"
    detections, regime_meta = classify_market_regimes(detections, index_db=index_db, index_symbol=index_symbol)
    market_group_meta = attach_current_market_groups(detections)
    scan: dict[str, Any] = {
        "generated_at": _utc_now(),
        "source": "Market Cache latest.sqlite stock_price_history",
        "db_path": str(db_path),
        "pattern_key": PATTERN_KEY,
        "symbols_scanned": len(symbols),
        "detections": detections,
        "symbol_stats": symbol_stats,
        "regime": regime_meta,
        "market_group": market_group_meta,
        "detector_config": config.to_dict(),
    }
    _enrich_events_from_series(scan, series_by_symbol, corporate_db=index_db)
    _assign_publication_quality_tiers(scan["detections"])
    stats = summarize(scan)
    stats["source"] = scan["source"]
    stats["db_source_meta"] = _db_meta(db_path)
    stats["detector_config"] = config.to_dict()
    path_rows = _path_rows_from_series(scan, series_by_symbol, horizon_bars=120)
    _add_wedge_target_calibration(stats, scan, path_rows)

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
    parser = argparse.ArgumentParser(description="Run Rising Wedge scanner against Market Cache latest.sqlite.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--market-stats-json", default=str(DEFAULT_MARKET_STATS_JSON))
    parser.add_argument("--limit-symbols", type=int, default=None)
    args = parser.parse_args()
    active_meta = _load_active_symbols(Path(args.market_stats_json) if args.market_stats_json else None)
    active_symbols = active_meta.get("active_symbols") if active_meta.get("enabled") else None
    paths = scan_rising_wedges_db(
        db_path=Path(args.db),
        out_dir=Path(args.out_dir) / "db_active",
        allowed_symbols=active_symbols,
        limit_symbols=args.limit_symbols,
    )
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
