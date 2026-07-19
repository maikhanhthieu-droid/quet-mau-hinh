"""Triple Bottoms / Triple Tops scanner.

Triple patterns are horizontal reversal structures: three bottoms/tops form in
roughly the same price zone, with two intervening reaction swings defining the
confirmation boundary.  This stays separate from Three Rising Valleys/Falling
Peaks, where each successive point must step higher/lower.
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
from scanner.v2.measured_moves import _evaluate_detection, _mean, _median, _pct, _quantiles, _rate, _score_band, _truthy  # noqa: E402
from scanner.v2.source_data import attach_current_market_groups, classify_market_regimes  # noqa: E402


TRIPLE_TOPS = "triple_tops"
TRIPLE_BOTTOMS = "triple_bottoms"
TRIPLE_PATTERNS = (TRIPLE_TOPS, TRIPLE_BOTTOMS)
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/triple_family")


@dataclass(frozen=True)
class TriplePatternsConfig:
    width_min_bars: int = 42
    width_max_bars: int = 270
    height_min_pct: float = 6.0
    height_max_pct: float = 80.0
    extreme_similarity_tol_pct: float = 4.0
    min_inner_swing_pct: float = 4.0
    prior_trend_lookback_bars: int = 45
    prior_trend_min_pct: float = 8.0
    confirmation_search_bars: int = 60
    confirmation_threshold: float = 0.005
    max_spacing_imbalance: float = 2.8
    breakout_cooldown_bars: int = 55
    max_events_per_symbol: int = 14

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]] = None) -> "TriplePatternsConfig":
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


def _prior_trend_pct(df: pd.DataFrame, start_idx: int, lookback: int) -> Optional[float]:
    left = max(0, int(start_idx) - int(lookback))
    if start_idx <= left:
        return None
    anchor = _safe_float(df.iloc[left].get("close"))
    start = _safe_float(df.iloc[int(start_idx)].get("close"))
    if anchor is None or start is None or anchor <= 0:
        return None
    return (start - anchor) / anchor * 100.0


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


def _spacing_imbalance(pivots: Sequence[Pivot]) -> float:
    gaps = [int(b.idx) - int(a.idx) for a, b in zip(pivots[:-1], pivots[1:]) if int(b.idx) > int(a.idx)]
    if not gaps:
        return float("inf")
    return float(max(gaps) / max(min(gaps), 1))


class TriplePatternsDetector:
    def __init__(self, pattern_key: str, config: Optional[TriplePatternsConfig | Mapping[str, Any]] = None) -> None:
        if pattern_key not in TRIPLE_PATTERNS:
            raise ValueError(f"unsupported triple patterns pattern {pattern_key}")
        self.pattern_key = pattern_key
        self.config = config if isinstance(config, TriplePatternsConfig) else TriplePatternsConfig.from_mapping(config)

    @property
    def direction(self) -> int:
        return -1 if self.pattern_key == TRIPLE_TOPS else 1

    @property
    def expected_sequence(self) -> tuple[PivotType, ...]:
        if self.pattern_key == TRIPLE_TOPS:
            return (PivotType.HIGH, PivotType.LOW, PivotType.HIGH, PivotType.LOW, PivotType.HIGH)
        return (PivotType.LOW, PivotType.HIGH, PivotType.LOW, PivotType.HIGH, PivotType.LOW)

    def _confirm(self, df: pd.DataFrame, end_idx: int, boundary: float) -> Tuple[Optional[int], Optional[float], Optional[float]]:
        for idx in range(end_idx + 1, min(len(df), end_idx + 1 + self.config.confirmation_search_bars)):
            close = _safe_float(df.iloc[idx].get("close"))
            if close is None:
                continue
            if self.direction == -1 and close < boundary * (1.0 - self.config.confirmation_threshold):
                return idx, close, _rolling_volume_ratio(df, idx)
            if self.direction == 1 and close > boundary * (1.0 + self.config.confirmation_threshold):
                return idx, close, _rolling_volume_ratio(df, idx)
        return None, None, None

    def scan_window(self, df: pd.DataFrame, pivots: Sequence[Pivot]) -> Optional[Dict[str, Any]]:
        if len(pivots) < 5 or tuple(p.type for p in pivots[:5]) != self.expected_sequence:
            return None
        window = list(pivots[:5])
        start_idx = int(window[0].idx)
        end_idx = int(window[-1].idx)
        width = end_idx - start_idx + 1
        if width < self.config.width_min_bars or width > self.config.width_max_bars:
            return None

        highs = [float(p.price) for p in window if p.type == PivotType.HIGH]
        lows = [float(p.price) for p in window if p.type == PivotType.LOW]
        if not highs or not lows:
            return None
        high, low = max(highs), min(lows)
        mid = (high + low) / 2.0 if high + low else max(high, 1e-9)
        height_pct = (high - low) / mid * 100.0
        if height_pct < self.config.height_min_pct or height_pct > self.config.height_max_pct:
            return None

        prior = _prior_trend_pct(df, start_idx, self.config.prior_trend_lookback_bars)
        if prior is None:
            return None
        if self.pattern_key == TRIPLE_TOPS and prior < self.config.prior_trend_min_pct:
            return None
        if self.pattern_key == TRIPLE_BOTTOMS and prior > -self.config.prior_trend_min_pct:
            return None

        spacing_imbalance = _spacing_imbalance(window)
        if spacing_imbalance > self.config.max_spacing_imbalance:
            return None

        if self.pattern_key == TRIPLE_TOPS:
            p1, p2, p3 = highs[0], highs[1], highs[2]
            avg_extreme = (p1 + p2 + p3) / 3.0
            extreme_spread_pct = (max(p1, p2, p3) - min(p1, p2, p3)) / max(avg_extreme, 1e-9) * 100.0
            if extreme_spread_pct > self.config.extreme_similarity_tol_pct:
                return None
            boundary = min(lows)
            inner_swing_pct = (avg_extreme - boundary) / max(avg_extreme, 1e-9) * 100.0
            if inner_swing_pct < self.config.min_inner_swing_pct:
                return None
            target = boundary - (avg_extreme - boundary)
        else:
            v1, v2, v3 = lows[0], lows[1], lows[2]
            avg_extreme = (v1 + v2 + v3) / 3.0
            extreme_spread_pct = (max(v1, v2, v3) - min(v1, v2, v3)) / max(avg_extreme, 1e-9) * 100.0
            if extreme_spread_pct > self.config.extreme_similarity_tol_pct:
                return None
            boundary = max(highs)
            inner_swing_pct = (boundary - avg_extreme) / max(boundary, 1e-9) * 100.0
            if inner_swing_pct < self.config.min_inner_swing_pct:
                return None
            target = boundary + (boundary - avg_extreme)
        if target <= 0:
            return None

        confirmation_idx, confirmation_price, volume_ratio = self._confirm(df, end_idx, boundary)
        if confirmation_idx is None or confirmation_price is None:
            return None
        target_dist_pct = abs(target - confirmation_price) / confirmation_price * 100.0
        if target_dist_pct <= 0 or target_dist_pct > 90:
            return None

        score = 50.0
        score += _score_band(abs(float(prior)), good=16.0, weak=self.config.prior_trend_min_pct, weight=0.12)
        score += _score_band(height_pct, good=16.0, weak=self.config.height_min_pct, weight=0.12)
        score += _score_band(extreme_spread_pct, good=1.0, weak=self.config.extreme_similarity_tol_pct, reverse=True, weight=0.18)
        score += _score_band(inner_swing_pct, good=10.0, weak=self.config.min_inner_swing_pct, weight=0.10)
        score += _score_band(spacing_imbalance, good=1.4, weak=self.config.max_spacing_imbalance, reverse=True, weight=0.14)
        if volume_ratio is not None and volume_ratio >= 1.05:
            score += 4.0
        score = int(max(0, min(100, round(score))))

        return {
            "formation_start_idx": start_idx,
            "formation_end_idx": end_idx,
            "formation_start_date": str(pd.Timestamp(df.iloc[start_idx]["date"]).date()),
            "formation_end_date": str(pd.Timestamp(df.iloc[end_idx]["date"]).date()),
            "breakout_idx": int(confirmation_idx),
            "breakout_date": str(pd.Timestamp(df.iloc[int(confirmation_idx)]["date"]).date()),
            "breakout_direction": "up" if self.direction == 1 else "down",
            "breakout_price": round(float(confirmation_price), 4),
            "target_price": round(float(target), 4),
            "pattern_width_bars": int(width),
            "pattern_height_pct": round(float(height_pct), 2),
            "variant": self.pattern_key,
            "prior_trend_pct": round(float(prior), 2),
            "boundary_price": round(float(boundary), 4),
            "extreme_spread_pct": round(float(extreme_spread_pct), 2),
            "inner_swing_pct": round(float(inner_swing_pct), 2),
            "spacing_imbalance": round(float(spacing_imbalance), 3),
            "pivot_1_idx": int(window[0].idx),
            "pivot_2_idx": int(window[1].idx),
            "pivot_3_idx": int(window[2].idx),
            "pivot_4_idx": int(window[3].idx),
            "pivot_5_idx": int(window[4].idx),
            "pivot_1_price": round(float(window[0].price), 4),
            "pivot_2_price": round(float(window[1].price), 4),
            "pivot_3_price": round(float(window[2].price), 4),
            "pivot_4_price": round(float(window[3].price), 4),
            "pivot_5_price": round(float(window[4].price), 4),
            "confirmation_clearance_pct": round(abs(float(confirmation_price - boundary)) / boundary * 100.0, 2),
            "volume_confirmed": bool(volume_ratio is not None and volume_ratio >= 1.05),
            "breakout_volume_ratio": round(float(volume_ratio), 4) if volume_ratio is not None else None,
            "pattern_quality_score": score,
            "pattern_quality_tier": "clean" if score >= 84 else ("usable" if score >= 70 else "loose"),
        }


def scan_symbol(
    df_raw: pd.DataFrame,
    *,
    pattern_key: str,
    max_events_per_symbol: Optional[int] = None,
    detector_config: Optional[TriplePatternsConfig | Mapping[str, Any]] = None,
) -> Tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(df_raw) < 170:
        return [], {"rows": int(len(df_raw)), "skipped": "too_few_rows"}
    config = detector_config if isinstance(detector_config, TriplePatternsConfig) else TriplePatternsConfig.from_mapping(detector_config)
    max_events = int(max_events_per_symbol if max_events_per_symbol is not None else config.max_events_per_symbol)
    df, norm_stats = OHLCVNormalizer().normalize(df_raw)
    pivots_raw = PivotDetector().detect_pivots(df, pivot_type="intermediate")
    pivots = PivotDetector().get_filtered_pivots(pivots_raw, min_spacing=8)
    detector = TriplePatternsDetector(pattern_key, config)
    out: list[dict[str, Any]] = []
    used_confirmations: list[int] = []
    symbol = str(df.iloc[0]["symbol"])
    for i in range(len(pivots) - 4):
        candidate = detector.scan_window(df, pivots[i : i + 5])
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
        score += _score_band(_safe_float(row.get("pattern_quality_score")), good=84.0, weak=65.0, weight=0.35)
        score += _score_band(_safe_float(row.get("spacing_imbalance")), good=1.4, weak=2.8, reverse=True, weight=0.18)
        score += _score_band(_safe_float(row.get("extreme_spread_pct")), good=1.0, weak=4.0, reverse=True, weight=0.18)
        score += _score_band(_safe_float(row.get("inner_swing_pct")), good=10.0, weak=4.0, weight=0.10)
        score += 9.0 if path_bucket == "clean" else 4.0
        score += 6.0 if tradability_bucket == "clean" else (3.0 if tradability_bucket == "usable" else 0.0)
        reasons: list[str] = []
        if _safe_float(row.get("spacing_imbalance")) is not None and float(row["spacing_imbalance"]) > 2.1:
            reasons.append("unbalanced_peak_spacing")
        if _safe_float(row.get("extreme_spread_pct")) is not None and float(row["extreme_spread_pct"]) > 3.0:
            reasons.append("extremes_not_level")
        if _safe_float(row.get("inner_swing_pct")) is not None and float(row["inner_swing_pct"]) < 6.0:
            reasons.append("weak_inner_swing")
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
        "median_extreme_spread_pct": _median([row.get("extreme_spread_pct") for row in rows]),
        "median_inner_swing_pct": _median([row.get("inner_swing_pct") for row in rows]),
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
            "extreme_spread_pct": _quantiles([row.get("extreme_spread_pct") for row in rows]),
            "inner_swing_pct": _quantiles([row.get("inner_swing_pct") for row in rows]),
        },
        "experiment_note": "Triple Patterns scanner uses five alternating pivots, near-level three extremes, confirmation beyond the two inner swing boundary, and full-height target as legacy benchmark.",
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
    "prior_trend_pct",
    "boundary_price",
    "extreme_spread_pct",
    "inner_swing_pct",
    "spacing_imbalance",
    "pivot_1_idx",
    "pivot_2_idx",
    "pivot_3_idx",
    "pivot_4_idx",
    "pivot_5_idx",
    "pivot_1_price",
    "pivot_2_price",
    "pivot_3_price",
    "pivot_4_price",
    "pivot_5_price",
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


def scan_triple_patterns_db(
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
    config = TriplePatternsConfig.from_mapping(detector_config)
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
    parser = argparse.ArgumentParser(description="Run Triple Patterns Family scanners against Market Cache latest.sqlite.")
    parser.add_argument("--pattern", choices=[*TRIPLE_PATTERNS, "all"], default="all")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--market-stats-json", default=str(DEFAULT_MARKET_STATS_JSON))
    parser.add_argument("--limit-symbols", type=int, default=None)
    args = parser.parse_args()
    active_meta = _load_active_symbols(Path(args.market_stats_json) if args.market_stats_json else None)
    active_symbols = active_meta.get("active_symbols") if active_meta.get("enabled") else None
    patterns = list(TRIPLE_PATTERNS) if args.pattern == "all" else [args.pattern]
    outputs: dict[str, str] = {}
    for pattern_key in patterns:
        paths = scan_triple_patterns_db(
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
