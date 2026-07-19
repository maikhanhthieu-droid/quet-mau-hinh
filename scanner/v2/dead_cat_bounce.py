"""Dead-Cat Bounce / Inverted Dead-Cat Bounce scanner.

Bulkowski treats these as event patterns rather than ordinary geometric
formations.  The scanner therefore uses event-time logic:

* Dead-Cat Bounce: a sharp decline, a recovery bounce, then the post-bounce
  path is measured from the bounce high.
* Inverted Dead-Cat Bounce: a sharp one-day rise, a day-2 push, then the
  giveback path is measured from day 2.

This module is intentionally separate from the legacy digitized engine so that
publication chapters can use a source-aligned v2 artifact path.
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
    _rolling_volume_ratio,
    _safe_float,
    _score_band,
    _truthy,
)
from scanner.v2.source_data import attach_current_market_groups, classify_market_regimes  # noqa: E402


DEAD_CAT_BOUNCE = "dead_cat_bounce"
DEAD_CAT_BOUNCE_INVERTED = "dead_cat_bounce_inverted"
DEAD_CAT_PATTERNS = (DEAD_CAT_BOUNCE, DEAD_CAT_BOUNCE_INVERTED)
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/dead_cat_bounce_family")


@dataclass(frozen=True)
class DeadCatConfig:
    event_decline_min_pct: float = 15.0
    event_decline_max_pct: float = 75.0
    event_decline_max_bars: int = 8
    bounce_min_pct: float = 15.0
    bounce_max_pct: float = 35.0
    bounce_min_bars: int = 5
    bounce_max_bars: int = 25
    inverted_rise_min_pct: float = 5.0
    inverted_rise_max_pct: float = 20.0
    inverted_day2_required: bool = True
    event_volume_ratio_preferred: float = 2.0
    gap_preferred: bool = True
    breakout_cooldown_bars: int = 80
    max_events_per_symbol: int = 8

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]] = None) -> "DeadCatConfig":
        if value is None:
            return cls()
        allowed = {field.name for field in fields(cls)}
        return cls(**{key: item for key, item in value.items() if key in allowed})

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _pct_change(a: float, b: float) -> float:
    if a <= 0:
        return 0.0
    return (b - a) / a * 100.0


def _gap_down(df: pd.DataFrame, idx: int) -> bool:
    if idx <= 0 or idx >= len(df):
        return False
    try:
        return float(df.iloc[idx]["high"]) < float(df.iloc[idx - 1]["low"])
    except Exception:
        return False


def _gap_up(df: pd.DataFrame, idx: int) -> bool:
    if idx <= 0 or idx >= len(df):
        return False
    try:
        return float(df.iloc[idx]["low"]) > float(df.iloc[idx - 1]["high"])
    except Exception:
        return False


def _volume_spike_ratio(df: pd.DataFrame, idx: int) -> Optional[float]:
    return _rolling_volume_ratio(df, idx, lookback=20)


class DeadCatDetector:
    def __init__(self, pattern_key: str, config: Optional[DeadCatConfig | Mapping[str, Any]] = None) -> None:
        if pattern_key not in DEAD_CAT_PATTERNS:
            raise ValueError(f"unsupported dead-cat pattern {pattern_key}")
        self.pattern_key = pattern_key
        self.config = config if isinstance(config, DeadCatConfig) else DeadCatConfig.from_mapping(config)

    def _scan_dead_cat_bounce(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        n = len(df)
        used: list[int] = []
        for event_start in range(1, max(1, n - self.config.bounce_max_bars - 2)):
            pre_high = _safe_float(df.iloc[event_start - 1].get("high"))
            if pre_high is None or pre_high <= 0:
                continue
            end = min(n - 1, event_start + self.config.event_decline_max_bars)
            event_window = df.iloc[event_start : end + 1]
            if event_window.empty:
                continue
            lows = pd.to_numeric(event_window["low"], errors="coerce")
            if lows.dropna().empty:
                continue
            event_low_rel = int(lows.to_numpy().argmin())
            event_low_idx = event_start + event_low_rel
            event_low = float(lows.iloc[event_low_rel])
            if event_low <= 0:
                continue
            decline_pct = (pre_high - event_low) / pre_high * 100.0
            if decline_pct < self.config.event_decline_min_pct or decline_pct > self.config.event_decline_max_pct:
                continue

            b0 = event_low_idx + self.config.bounce_min_bars
            b1 = min(n - 1, event_low_idx + self.config.bounce_max_bars)
            if b0 > b1:
                continue
            bounce_window = df.iloc[b0 : b1 + 1]
            highs = pd.to_numeric(bounce_window["high"], errors="coerce")
            if highs.dropna().empty:
                continue
            bounce_rel = int(highs.to_numpy().argmax())
            bounce_idx = b0 + bounce_rel
            bounce_high = float(highs.iloc[bounce_rel])
            bounce_pct = (bounce_high - event_low) / event_low * 100.0
            if bounce_pct < self.config.bounce_min_pct or bounce_pct > self.config.bounce_max_pct:
                continue
            if any(abs(bounce_idx - prev) <= self.config.breakout_cooldown_bars for prev in used):
                continue
            breakout_price = _safe_float(df.iloc[bounce_idx].get("close"))
            if breakout_price is None or breakout_price <= event_low:
                continue
            target_price = event_low
            target_dist_pct = abs(target_price - breakout_price) / breakout_price * 100.0
            gap = _gap_down(df, event_start)
            volume_ratio = _volume_spike_ratio(df, event_start)
            score = 38.0
            score += _score_band(decline_pct, good=32.0, weak=15.0, weight=0.18)
            score += _score_band(bounce_pct, good=22.0, weak=self.config.bounce_min_pct, weight=0.16)
            score += _score_band(float(bounce_idx - event_low_idx), good=10.0, weak=float(self.config.bounce_max_bars), reverse=True, weight=0.10)
            if gap:
                score += 8.0
            if volume_ratio is not None and volume_ratio >= self.config.event_volume_ratio_preferred:
                score += 8.0
            if decline_pct <= 45.0:
                score += 5.0
            score = int(max(0, min(100, round(score))))
            used.append(bounce_idx)
            out.append(
                {
                    "symbol": str(df.iloc[0]["symbol"]),
                    "pattern_key": DEAD_CAT_BOUNCE,
                    "variant": DEAD_CAT_BOUNCE,
                    "formation_start_idx": int(event_start),
                    "formation_end_idx": int(bounce_idx),
                    "formation_start_date": str(pd.Timestamp(df.iloc[event_start]["date"]).date()),
                    "formation_end_date": str(pd.Timestamp(df.iloc[bounce_idx]["date"]).date()),
                    "breakout_idx": int(bounce_idx),
                    "breakout_date": str(pd.Timestamp(df.iloc[bounce_idx]["date"]).date()),
                    "breakout_direction": "down",
                    "breakout_price": round(float(breakout_price), 4),
                    "target_price": round(float(target_price), 4),
                    "target_dist_pct": round(float(target_dist_pct), 2),
                    "event_start_idx": int(event_start),
                    "event_low_idx": int(event_low_idx),
                    "event_low_price": round(float(event_low), 4),
                    "event_decline_pct": round(float(decline_pct), 2),
                    "event_decline_bars": int(event_low_idx - event_start + 1),
                    "bounce_high_idx": int(bounce_idx),
                    "bounce_high_price": round(float(bounce_high), 4),
                    "bounce_pct": round(float(bounce_pct), 2),
                    "bounce_bars": int(bounce_idx - event_low_idx),
                    "gap_on_event": bool(gap),
                    "event_volume_ratio": volume_ratio,
                    "pattern_width_bars": int(bounce_idx - event_start + 1),
                    "pattern_height_pct": round(float(decline_pct), 2),
                    "pattern_quality_score": score,
                    "pattern_quality_tier": "clean" if score >= 76 else ("usable" if score >= 60 else "loose"),
                    "dead_cat_phase": "decline_bounce_postbounce",
                }
            )
            if len(out) >= self.config.max_events_per_symbol:
                break
        return out

    def _scan_inverted(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        n = len(df)
        used: list[int] = []
        for day1 in range(1, n - 1):
            ref_close = _safe_float(df.iloc[day1 - 1].get("close"))
            day1_close = _safe_float(df.iloc[day1].get("close"))
            if ref_close is None or day1_close is None or ref_close <= 0:
                continue
            rise_pct = (day1_close - ref_close) / ref_close * 100.0
            if rise_pct < self.config.inverted_rise_min_pct or rise_pct > self.config.inverted_rise_max_pct:
                continue
            day2 = day1 + 1
            try:
                h1 = float(df.iloc[day1]["high"])
                l1 = float(df.iloc[day1]["low"])
                h2 = float(df.iloc[day2]["high"])
                l2 = float(df.iloc[day2]["low"])
            except Exception:
                continue
            day2_push = h2 >= h1 and l2 >= l1
            if self.config.inverted_day2_required and not day2_push:
                continue
            if any(abs(day2 - prev) <= self.config.breakout_cooldown_bars for prev in used):
                continue
            breakout_price = _safe_float(df.iloc[day2].get("close"))
            if breakout_price is None or breakout_price <= ref_close:
                continue
            target_price = ref_close
            target_dist_pct = abs(target_price - breakout_price) / breakout_price * 100.0
            gap = _gap_up(df, day1)
            volume_ratio = _volume_spike_ratio(df, day1)
            score = 42.0
            score += _score_band(rise_pct, good=12.0, weak=self.config.inverted_rise_min_pct, weight=0.18)
            if day2_push:
                score += 12.0
            if gap:
                score += 7.0
            if volume_ratio is not None and volume_ratio >= self.config.event_volume_ratio_preferred:
                score += 7.0
            score += _score_band(target_dist_pct, good=8.0, weak=3.0, weight=0.08)
            score = int(max(0, min(100, round(score))))
            used.append(day2)
            out.append(
                {
                    "symbol": str(df.iloc[0]["symbol"]),
                    "pattern_key": DEAD_CAT_BOUNCE_INVERTED,
                    "variant": DEAD_CAT_BOUNCE_INVERTED,
                    "formation_start_idx": int(day1),
                    "formation_end_idx": int(day2),
                    "formation_start_date": str(pd.Timestamp(df.iloc[day1]["date"]).date()),
                    "formation_end_date": str(pd.Timestamp(df.iloc[day2]["date"]).date()),
                    "breakout_idx": int(day2),
                    "breakout_date": str(pd.Timestamp(df.iloc[day2]["date"]).date()),
                    "breakout_direction": "down",
                    "breakout_price": round(float(breakout_price), 4),
                    "target_price": round(float(target_price), 4),
                    "target_dist_pct": round(float(target_dist_pct), 2),
                    "reference_close": round(float(ref_close), 4),
                    "event_rise_pct": round(float(rise_pct), 2),
                    "day2_push": bool(day2_push),
                    "gap_on_event": bool(gap),
                    "event_volume_ratio": volume_ratio,
                    "pattern_width_bars": 2,
                    "pattern_height_pct": round(float(rise_pct), 2),
                    "pattern_quality_score": score,
                    "pattern_quality_tier": "clean" if score >= 76 else ("usable" if score >= 60 else "loose"),
                    "dead_cat_phase": "rise_day2_giveback",
                }
            )
            if len(out) >= self.config.max_events_per_symbol:
                break
        return out

    def scan(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        if self.pattern_key == DEAD_CAT_BOUNCE:
            return self._scan_dead_cat_bounce(df)
        return self._scan_inverted(df)


def scan_symbol(
    df_raw: pd.DataFrame,
    *,
    pattern_key: str,
    detector_config: Optional[DeadCatConfig | Mapping[str, Any]] = None,
    max_events_per_symbol: Optional[int] = None,
) -> Tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(df_raw) < 80:
        return [], {"rows": int(len(df_raw)), "skipped": "too_few_rows"}
    config = detector_config if isinstance(detector_config, DeadCatConfig) else DeadCatConfig.from_mapping(detector_config)
    if max_events_per_symbol is not None:
        config = DeadCatConfig.from_mapping({**config.to_dict(), "max_events_per_symbol": int(max_events_per_symbol)})
    df, norm_stats = OHLCVNormalizer().normalize(df_raw)
    rows = DeadCatDetector(pattern_key, config).scan(df)
    out: list[dict[str, Any]] = []
    for row in rows:
        evaluated = _evaluate_detection(df, row)
        out.append({**row, **evaluated})
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
        if row.get("pattern_key") == DEAD_CAT_BOUNCE:
            score = 0.0
            score += _score_band(_safe_float(row.get("event_decline_pct")), good=32.0, weak=15.0, weight=0.20)
            score += _score_band(_safe_float(row.get("bounce_pct")), good=22.0, weak=8.0, weight=0.18)
            score += _score_band(_safe_float(row.get("bounce_bars")), good=8.0, weak=25.0, reverse=True, weight=0.12)
        else:
            score = 0.0
            score += _score_band(_safe_float(row.get("event_rise_pct")), good=12.0, weak=5.0, weight=0.24)
            if _truthy(row.get("day2_push")):
                score += 14.0
        if _truthy(row.get("gap_on_event")):
            score += 8.0
        if row.get("event_volume_ratio") is not None and float(row.get("event_volume_ratio") or 0.0) >= 2.0:
            score += 8.0
        if path_bucket == "clean":
            score += 10.0
        else:
            score += 4.0
        if tradability_bucket == "clean":
            score += 5.0
        elif tradability_bucket == "usable":
            score += 2.0
        if _truthy(row.get("target_first_before_adverse_5pct")):
            score += 4.0
        reasons: list[str] = []
        if row.get("pattern_key") == DEAD_CAT_BOUNCE and float(row.get("bounce_pct") or 0.0) < 12.0:
            reasons.append("small_bounce")
        if row.get("pattern_key") == DEAD_CAT_BOUNCE_INVERTED and float(row.get("event_rise_pct") or 0.0) < 7.0:
            reasons.append("small_rise")
        if not _truthy(row.get("gap_on_event")):
            reasons.append("no_gap")
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
        "median_event_decline_pct": _median([row.get("event_decline_pct") for row in rows]),
        "median_bounce_pct": _median([row.get("bounce_pct") for row in rows]),
        "median_event_rise_pct": _median([row.get("event_rise_pct") for row in rows]),
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
        **_group_stats(rows),
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
            "event_decline_pct": _quantiles([row.get("event_decline_pct") for row in rows]),
            "bounce_pct": _quantiles([row.get("bounce_pct") for row in rows]),
            "event_rise_pct": _quantiles([row.get("event_rise_pct") for row in rows]),
            "target_days": _quantiles([row.get("days_to_target") for row in evals]),
        },
        "experiment_note": "Dead-Cat Bounce Family uses event-time OHLCV logic: event shock, recovery/push, then post-event giveback/decline measurement.",
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
    stats["target_family"] = {"half_giveback": 0.5, "three_quarter_giveback": 0.75, "full_event_retest": 1.0}


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
    "event_decline_pct",
    "event_decline_bars",
    "bounce_pct",
    "bounce_bars",
    "event_rise_pct",
    "day2_push",
    "gap_on_event",
    "event_volume_ratio",
    "event_low_price",
    "bounce_high_price",
    "reference_close",
    "dead_cat_phase",
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


def scan_dead_cat_family_db(
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
    config = DeadCatConfig.from_mapping(detector_config)
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
    parser = argparse.ArgumentParser(description="Run Dead-Cat Bounce Family scanners against Market Cache latest.sqlite.")
    parser.add_argument("--pattern", choices=[*DEAD_CAT_PATTERNS, "all"], default="all")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--market-stats-json", default=str(DEFAULT_MARKET_STATS_JSON))
    parser.add_argument("--limit-symbols", type=int, default=None)
    args = parser.parse_args()
    active_meta = _load_active_symbols(Path(args.market_stats_json) if args.market_stats_json else None)
    active_symbols = active_meta.get("active_symbols") if active_meta.get("enabled") else None
    patterns = list(DEAD_CAT_PATTERNS) if args.pattern == "all" else [args.pattern]
    outputs: dict[str, str] = {}
    for pattern_key in patterns:
        paths = scan_dead_cat_family_db(
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
