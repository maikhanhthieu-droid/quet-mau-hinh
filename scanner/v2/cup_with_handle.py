"""Cup-with-Handle family scanner.

This family is intentionally separate from the Flag, Triangle, Double, and
Wedge scanners. Cups are long, rounded formations with a right-side handle;
the scanner keeps the shared event/path/statistics contract but uses
Cup-specific geometry and target rules.
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
from scanner.v2.double_patterns import (  # noqa: E402
    _evaluate_detection,
    _group_stats,
    _group_table,
    _path_quality_audit,
    _quantiles,
    _rate,
    _safe_float,
    _score_band,
    _truthy,
)
from scanner.v2.flags_experiment import DEFAULT_INDEX_DB, DEFAULT_INDEX_SYMBOL, _write_csv, _write_json  # noqa: E402
from scanner.v2.source_data import attach_current_market_groups, classify_market_regimes  # noqa: E402


PATTERN_KEY = "cup_with_handle_family"
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/cup_with_handle_family")


@dataclass(frozen=True)
class CupWithHandleConfig:
    cup_width_min_bars: int = 35
    cup_width_max_bars: int = 325
    prior_trend_lookback_bars: int = 180
    prior_trend_min_pct: float = 30.0
    rim_similarity_tol_pct: float = 9.0
    cup_depth_min_pct: float = 10.0
    cup_depth_max_pct: float = 55.0
    bottom_pos_min_pct: float = 25.0
    bottom_pos_max_pct: float = 75.0
    roundness_band_pct: float = 35.0
    roundness_min_bars: int = 5
    handle_min_bars: int = 5
    handle_max_bars: int = 45
    handle_max_width_pct_of_cup: float = 45.0
    handle_max_retrace_pct_of_cup: float = 50.0
    handle_min_decline_pct: float = 1.0
    handle_max_decline_pct: float = 18.0
    breakout_search_bars: int = 35
    breakout_threshold: float = 0.0075
    breakout_cooldown_bars: int = 60
    max_events_per_symbol: int = 6
    max_pair_candidates_per_symbol: int = 16000
    inverted_enabled: bool = True
    inverted_rim_similarity_tol_pct: float = 6.0
    inverted_handle_retrace_min_pct: float = 18.0
    inverted_handle_retrace_max_pct: float = 70.0

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]] = None) -> "CupWithHandleConfig":
        if value is None:
            return cls()
        allowed = {field.name for field in fields(cls)}
        return cls(**{key: item for key, item in value.items() if key in allowed})

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _pct_diff(a: float, b: float) -> float:
    denom = max((abs(a) + abs(b)) / 2.0, 1e-9)
    return abs(a - b) / denom * 100.0


def _median(values: Sequence[Any]) -> Optional[float]:
    series = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna()
    return None if series.empty else round(float(series.median()), 2)


def _mean(values: Sequence[Any]) -> Optional[float]:
    series = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna()
    return None if series.empty else round(float(series.mean()), 2)


def _find_prior_rise(df: pd.DataFrame, rim_idx: int, rim_price: float, lookback: int) -> Optional[float]:
    if rim_idx <= 0 or rim_price <= 0:
        return None
    prior = df.iloc[max(0, rim_idx - lookback) : rim_idx + 1]
    if prior.empty:
        return None
    base = _safe_float(prior["low"].min())
    if base is None or base <= 0:
        return None
    return round((rim_price - base) / base * 100.0, 2)


def _find_prior_advance_to_top(df: pd.DataFrame, idx: int, top_price: float, lookback: int) -> Optional[float]:
    return _find_prior_rise(df, idx, top_price, lookback)


def _handle_volume_trend(hseg: pd.DataFrame) -> str:
    vols = pd.to_numeric(hseg.get("volume"), errors="coerce").dropna()
    if len(vols) < 4:
        return "unknown"
    x = np.arange(len(vols), dtype=float)
    slope = float(np.polyfit(x, vols.to_numpy(dtype=float), 1)[0])
    denom = max(float(vols.median()), 1.0)
    pct = slope / denom * 100.0
    if pct < -1.0:
        return "down"
    if pct > 1.0:
        return "up"
    return "flat"


class CupWithHandleDetector:
    def __init__(self, config: Optional[CupWithHandleConfig | Mapping[str, Any]] = None) -> None:
        self.config = config if isinstance(config, CupWithHandleConfig) else CupWithHandleConfig.from_mapping(config)

    def _breakout_up(self, df: pd.DataFrame, start_idx: int, level: float) -> Tuple[Optional[int], Optional[float], Optional[float], Optional[float]]:
        for idx in range(start_idx, min(len(df), start_idx + self.config.breakout_search_bars)):
            close = _safe_float(df.iloc[idx].get("close"))
            if close is None or close <= level * (1.0 + self.config.breakout_threshold):
                continue
            volume_ratio = _safe_float(df.iloc[idx].get("volume_ratio"))
            clearance = (close - level) / level * 100.0 if level > 0 else None
            return idx, close, volume_ratio, clearance
        return None, None, None, None

    def _breakout_down(self, df: pd.DataFrame, start_idx: int, level: float) -> Tuple[Optional[int], Optional[float], Optional[float], Optional[float]]:
        for idx in range(start_idx, min(len(df), start_idx + self.config.breakout_search_bars)):
            close = _safe_float(df.iloc[idx].get("close"))
            if close is None or close >= level * (1.0 - self.config.breakout_threshold):
                continue
            volume_ratio = _safe_float(df.iloc[idx].get("volume_ratio"))
            clearance = (level - close) / level * 100.0 if level > 0 else None
            return idx, close, volume_ratio, clearance
        return None, None, None, None

    def _bullish(self, df: pd.DataFrame, left: Pivot, right: Pivot) -> Optional[Dict[str, Any]]:
        width = int(right.idx) - int(left.idx) + 1
        if width < self.config.cup_width_min_bars or width > self.config.cup_width_max_bars:
            return None
        rim_diff = _pct_diff(float(left.price), float(right.price))
        if rim_diff > self.config.rim_similarity_tol_pct:
            return None
        prior_rise = _find_prior_rise(df, int(left.idx), float(left.price), self.config.prior_trend_lookback_bars)
        if prior_rise is None or prior_rise < self.config.prior_trend_min_pct:
            return None
        cup = df.iloc[int(left.idx) : int(right.idx) + 1]
        if cup.empty:
            return None
        bottom_low = _safe_float(cup["low"].min())
        if bottom_low is None or bottom_low <= 0:
            return None
        rim_avg = (float(left.price) + float(right.price)) / 2.0
        depth_abs = rim_avg - bottom_low
        depth_pct = depth_abs / rim_avg * 100.0 if rim_avg > 0 else 0.0
        if depth_pct < self.config.cup_depth_min_pct or depth_pct > self.config.cup_depth_max_pct:
            return None
        bottom_idx = int(left.idx) + int(np.nanargmin(cup["low"].to_numpy(dtype=float)))
        bottom_pos_pct = (bottom_idx - int(left.idx)) / max(width - 1, 1) * 100.0
        if bottom_pos_pct < self.config.bottom_pos_min_pct or bottom_pos_pct > self.config.bottom_pos_max_pct:
            return None
        near_bottom_level = bottom_low + depth_abs * self.config.roundness_band_pct / 100.0
        near_bottom_bars = int((cup["low"] <= near_bottom_level).sum())
        if near_bottom_bars < max(3, min(self.config.roundness_min_bars, width // 8)):
            return None

        handle_start = int(right.idx) + 1
        handle_end_max = min(len(df) - 1, handle_start + self.config.handle_max_bars - 1)
        if handle_start + self.config.handle_min_bars >= len(df):
            return None
        for handle_end in range(handle_start + self.config.handle_min_bars - 1, handle_end_max + 1):
            hseg = df.iloc[handle_start : handle_end + 1]
            if hseg.empty:
                continue
            handle_width = len(hseg)
            if handle_width > max(self.config.handle_min_bars, int(round(width * self.config.handle_max_width_pct_of_cup / 100.0))):
                continue
            handle_low = _safe_float(hseg["low"].min())
            handle_res = _safe_float(hseg["high"].max())
            if handle_low is None or handle_res is None:
                continue
            decline_pct = (rim_avg - handle_low) / rim_avg * 100.0
            if decline_pct < self.config.handle_min_decline_pct or decline_pct > self.config.handle_max_decline_pct:
                continue
            handle_retrace_pct = decline_pct / max(depth_pct, 1e-9) * 100.0
            if handle_retrace_pct > self.config.handle_max_retrace_pct_of_cup:
                continue
            handle_pos_pct = (handle_low - bottom_low) / max(depth_abs, 1e-9) * 100.0
            if handle_pos_pct < 50.0:
                continue
            level = max(handle_res, float(right.price))
            breakout_idx, breakout_price, volume_ratio, clearance_pct = self._breakout_up(df, handle_end + 1, level)
            if breakout_idx is None or breakout_price is None:
                continue
            target_price = float(right.price) + depth_abs
            return self._record(
                df,
                variant="cup_with_handle",
                direction="up",
                start_idx=int(left.idx),
                end_idx=int(handle_end),
                breakout_idx=int(breakout_idx),
                breakout_price=float(breakout_price),
                target_price=float(target_price),
                stop_loss_price=float(handle_low),
                cup_width=width,
                handle_width=handle_width,
                rim_diff=rim_diff,
                depth_pct=depth_pct,
                bottom_pos_pct=bottom_pos_pct,
                near_bottom_bars=near_bottom_bars,
                prior_trend_pct=prior_rise,
                handle_move_pct=decline_pct,
                handle_retrace_pct=handle_retrace_pct,
                handle_pos_pct=handle_pos_pct,
                breakout_clearance_pct=clearance_pct,
                breakout_volume_ratio=volume_ratio,
                volume_trend_direction=_handle_volume_trend(hseg),
                left_rim_price=float(left.price),
                right_rim_price=float(right.price),
                cup_extreme_price=float(bottom_low),
                handle_extreme_price=float(handle_low),
            )
        return None

    def _inverted(self, df: pd.DataFrame, left: Pivot, right: Pivot) -> Optional[Dict[str, Any]]:
        width = int(right.idx) - int(left.idx) + 1
        if width < self.config.cup_width_min_bars or width > self.config.cup_width_max_bars:
            return None
        rim_diff = _pct_diff(float(left.price), float(right.price))
        if rim_diff > self.config.inverted_rim_similarity_tol_pct:
            return None
        cup = df.iloc[int(left.idx) : int(right.idx) + 1]
        if cup.empty:
            return None
        cup_top = _safe_float(cup["high"].max())
        if cup_top is None or cup_top <= 0:
            return None
        rim_avg = (float(left.price) + float(right.price)) / 2.0
        depth_abs = cup_top - rim_avg
        depth_pct = depth_abs / rim_avg * 100.0 if rim_avg > 0 else 0.0
        if depth_pct < self.config.cup_depth_min_pct or depth_pct > self.config.cup_depth_max_pct:
            return None
        top_idx = int(left.idx) + int(np.nanargmax(cup["high"].to_numpy(dtype=float)))
        top_pos_pct = (top_idx - int(left.idx)) / max(width - 1, 1) * 100.0
        if top_pos_pct < self.config.bottom_pos_min_pct or top_pos_pct > self.config.bottom_pos_max_pct:
            return None
        near_top_level = cup_top - depth_abs * self.config.roundness_band_pct / 100.0
        near_top_bars = int((cup["high"] >= near_top_level).sum())
        if near_top_bars < max(3, min(self.config.roundness_min_bars, width // 8)):
            return None

        handle_start = int(right.idx) + 1
        handle_end_max = min(len(df) - 1, handle_start + self.config.handle_max_bars - 1)
        if handle_start + self.config.handle_min_bars >= len(df):
            return None
        for handle_end in range(handle_start + self.config.handle_min_bars - 1, handle_end_max + 1):
            hseg = df.iloc[handle_start : handle_end + 1]
            if hseg.empty:
                continue
            handle_width = len(hseg)
            handle_high = _safe_float(hseg["high"].max())
            if handle_high is None:
                continue
            rebound_abs = handle_high - rim_avg
            rebound_pct = rebound_abs / rim_avg * 100.0 if rim_avg > 0 else 0.0
            retrace_pct = rebound_abs / max(depth_abs, 1e-9) * 100.0
            if retrace_pct < self.config.inverted_handle_retrace_min_pct or retrace_pct > self.config.inverted_handle_retrace_max_pct:
                continue
            if handle_high >= cup_top:
                continue
            breakout_idx, breakout_price, volume_ratio, clearance_pct = self._breakout_down(df, handle_end + 1, float(right.price))
            if breakout_idx is None or breakout_price is None:
                continue
            # Bulkowski changed the inverted-cup target to handle height, not cup height.
            target_price = float(right.price) - rebound_abs
            return self._record(
                df,
                variant="cup_with_handle_inverted",
                direction="down",
                start_idx=int(left.idx),
                end_idx=int(handle_end),
                breakout_idx=int(breakout_idx),
                breakout_price=float(breakout_price),
                target_price=float(target_price),
                stop_loss_price=float(handle_high),
                cup_width=width,
                handle_width=handle_width,
                rim_diff=rim_diff,
                depth_pct=depth_pct,
                bottom_pos_pct=top_pos_pct,
                near_bottom_bars=near_top_bars,
                prior_trend_pct=_find_prior_advance_to_top(df, top_idx, float(cup_top), self.config.prior_trend_lookback_bars),
                handle_move_pct=rebound_pct,
                handle_retrace_pct=retrace_pct,
                handle_pos_pct=None,
                breakout_clearance_pct=clearance_pct,
                breakout_volume_ratio=volume_ratio,
                volume_trend_direction=_handle_volume_trend(hseg),
                left_rim_price=float(left.price),
                right_rim_price=float(right.price),
                cup_extreme_price=float(cup_top),
                handle_extreme_price=float(handle_high),
            )
        return None

    def _record(self, df: pd.DataFrame, **kwargs: Any) -> Dict[str, Any]:
        start_idx = int(kwargs["start_idx"])
        end_idx = int(kwargs["end_idx"])
        breakout_idx = int(kwargs["breakout_idx"])
        variant = str(kwargs["variant"])
        direction = str(kwargs["direction"])
        depth_pct = float(kwargs["depth_pct"])
        rim_diff = float(kwargs["rim_diff"])
        handle_width = int(kwargs["handle_width"])
        near_bottom_bars = int(kwargs["near_bottom_bars"])
        volume_ratio = kwargs.get("breakout_volume_ratio")
        quality = 55.0
        quality += _score_band(rim_diff, good=2.0 if variant.endswith("inverted") else 3.0, weak=9.0, reverse=True, weight=0.13)
        quality += _score_band(depth_pct, good=22.0, weak=10.0, weight=0.12)
        quality += _score_band(abs(float(kwargs["bottom_pos_pct"]) - 50.0), good=6.0, weak=25.0, reverse=True, weight=0.10)
        quality += _score_band(float(kwargs["handle_retrace_pct"]), good=28.0, weak=55.0, reverse=True, weight=0.10)
        quality += _score_band(handle_width, good=8.0, weak=35.0, reverse=True, weight=0.08)
        quality += min(7.0, near_bottom_bars)
        if volume_ratio is not None and float(volume_ratio) >= 1.2:
            quality += 5.0
        tier = "clean" if quality >= 82 else ("usable" if quality >= 65 else "loose")
        return {
            "formation_start_idx": start_idx,
            "formation_end_idx": end_idx,
            "formation_start_date": str(pd.Timestamp(df.iloc[start_idx]["date"]).date()),
            "formation_end_date": str(pd.Timestamp(df.iloc[end_idx]["date"]).date()),
            "breakout_idx": breakout_idx,
            "breakout_date": str(pd.Timestamp(df.iloc[breakout_idx]["date"]).date()),
            "breakout_direction": direction,
            "breakout_price": round(float(kwargs["breakout_price"]), 4),
            "target_price": round(float(kwargs["target_price"]), 4),
            "stop_loss_price": round(float(kwargs["stop_loss_price"]), 4),
            "variant": variant,
            "pattern_width_bars": end_idx - start_idx + 1,
            "pattern_height_pct": round(depth_pct, 2),
            "pattern_quality_score": int(max(0, min(100, round(quality)))),
            "pattern_quality_tier": tier,
            "cup_width_bars": int(kwargs["cup_width"]),
            "handle_width_bars": handle_width,
            "rim_diff_pct": round(rim_diff, 2),
            "bottom_pos_pct": round(float(kwargs["bottom_pos_pct"]), 2),
            "near_bottom_bars": near_bottom_bars,
            "prior_trend_pct": kwargs.get("prior_trend_pct"),
            "handle_move_pct": round(float(kwargs["handle_move_pct"]), 2),
            "handle_retrace_pct": round(float(kwargs["handle_retrace_pct"]), 2),
            "handle_pos_pct": round(float(kwargs["handle_pos_pct"]), 2) if kwargs.get("handle_pos_pct") is not None else None,
            "breakout_clearance_pct": round(float(kwargs["breakout_clearance_pct"] or 0.0), 2),
            "volume_confirmed": bool(volume_ratio is not None and float(volume_ratio) >= 1.2),
            "breakout_volume_ratio": round(float(volume_ratio), 4) if volume_ratio is not None else None,
            "volume_trend_direction": kwargs.get("volume_trend_direction") or "unknown",
            "left_rim_price": round(float(kwargs["left_rim_price"]), 4),
            "right_rim_price": round(float(kwargs["right_rim_price"]), 4),
            "cup_extreme_price": round(float(kwargs["cup_extreme_price"]), 4),
            "handle_extreme_price": round(float(kwargs["handle_extreme_price"]), 4),
        }

    def scan(self, df: pd.DataFrame, *, variant: str) -> list[dict[str, Any]]:
        pivots = PivotDetector().detect_pivots(df, pivot_type="minor")
        rows: list[dict[str, Any]] = []
        inspected = 0
        if variant == "cup_with_handle":
            highs = [p for p in pivots if p.type == PivotType.HIGH]
            for i, left in enumerate(highs[:-1]):
                for right in highs[i + 1 :]:
                    width = int(right.idx) - int(left.idx) + 1
                    if width > self.config.cup_width_max_bars:
                        break
                    if width < self.config.cup_width_min_bars:
                        continue
                    if _pct_diff(float(left.price), float(right.price)) > self.config.rim_similarity_tol_pct:
                        continue
                    inspected += 1
                    if inspected > self.config.max_pair_candidates_per_symbol:
                        return rows
                    row = self._bullish(df, left, right)
                    if row:
                        rows.append(row)
                        break
        elif variant == "cup_with_handle_inverted":
            if not self.config.inverted_enabled:
                return []
            lows = [p for p in pivots if p.type == PivotType.LOW]
            for i, left in enumerate(lows[:-1]):
                for right in lows[i + 1 :]:
                    width = int(right.idx) - int(left.idx) + 1
                    if width > self.config.cup_width_max_bars:
                        break
                    if width < self.config.cup_width_min_bars:
                        continue
                    if _pct_diff(float(left.price), float(right.price)) > self.config.inverted_rim_similarity_tol_pct:
                        continue
                    inspected += 1
                    if inspected > self.config.max_pair_candidates_per_symbol:
                        return rows
                    row = self._inverted(df, left, right)
                    if row:
                        rows.append(row)
                        break
        else:
            raise ValueError(f"Unsupported Cup variant: {variant}")
        return rows


def scan_symbol(
    df_raw: pd.DataFrame,
    *,
    variant: str,
    detector_config: Optional[CupWithHandleConfig | Mapping[str, Any]] = None,
    max_events_per_symbol: Optional[int] = None,
) -> Tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(df_raw) < 220:
        return [], {"rows": int(len(df_raw)), "skipped": "too_few_rows"}
    config = detector_config if isinstance(detector_config, CupWithHandleConfig) else CupWithHandleConfig.from_mapping(detector_config)
    max_events = int(max_events_per_symbol if max_events_per_symbol is not None else config.max_events_per_symbol)
    df, norm_stats = OHLCVNormalizer().normalize(df_raw)
    detector = CupWithHandleDetector(config)
    candidates = detector.scan(df, variant=variant)
    out: list[dict[str, Any]] = []
    used_breakouts: list[int] = []
    symbol = str(df.iloc[0]["symbol"])
    for candidate in sorted(candidates, key=lambda row: (int(row["breakout_idx"]), -int(row["pattern_quality_score"]))):
        breakout_idx = int(candidate["breakout_idx"])
        if any(abs(breakout_idx - prev) <= config.breakout_cooldown_bars for prev in used_breakouts):
            continue
        record = {"symbol": symbol, "pattern_key": variant, **candidate}
        record.update(_evaluate_detection(df, record))
        out.append(record)
        used_breakouts.append(breakout_idx)
        if len(out) >= max_events:
            break
    return out, {"rows": int(len(df)), "normalizer": norm_stats, "detector_config": config.to_dict(), "candidate_count": len(candidates)}


def _assign_publication_quality_tiers(rows: list[dict[str, Any]], *, defensive: bool = False) -> None:
    data_limited_path = {"short_path", "zero_and_stale", "zero_volume", "mixed_flag"}
    for row in rows:
        path_bucket = str(row.get("path_quality_bucket") or "unknown")
        tradability_bucket = str(row.get("tradability_quality_bucket") or "unknown")
        quality = _safe_float(row.get("pattern_quality_score")) or 0.0
        rim_diff = _safe_float(row.get("rim_diff_pct"))
        handle_retrace = _safe_float(row.get("handle_retrace_pct"))
        handle_width = _safe_float(row.get("handle_width_bars"))
        prior_trend = _safe_float(row.get("prior_trend_pct"))
        handle_pos = _safe_float(row.get("handle_pos_pct"))
        volume_ratio = _safe_float(row.get("breakout_volume_ratio"))
        reasons: list[str] = []
        if path_bucket in data_limited_path or tradability_bucket == "impaired":
            row["publication_quality_score"] = 0.0
            row["publication_quality_tier"] = "data_limited"
            row["publication_quality_reasons"] = ",".join([f"path:{path_bucket}", f"tradability:{tradability_bucket}"])
            continue
        # Publication quality must be ex-ante: geometry, setup, handle shape,
        # liquidity/path quality, and breakout confirmation only. Outcome
        # metrics such as target_hit/failure/MFE/MAE are deliberately excluded.
        score = 0.45 * quality
        score += _score_band(rim_diff, good=3.0, weak=9.0, reverse=True, weight=0.12)
        score += _score_band(handle_retrace, good=35.0, weak=55.0, reverse=True, weight=0.10)
        score += _score_band(handle_width, good=8.0, weak=35.0, reverse=True, weight=0.08)
        score += _score_band(prior_trend, good=30.0, weak=10.0, weight=0.08)
        if handle_pos is not None:
            score += _score_band(handle_pos, good=65.0, weak=50.0, weight=0.08)
        if volume_ratio is not None and volume_ratio >= 1.2:
            score += 4.0
        if path_bucket == "clean":
            score += 8.0
        elif path_bucket != "unknown":
            reasons.append(f"path:{path_bucket}")
        if defensive:
            score -= 4.0
            reasons.append("defensive_scope")
        score = round(max(0.0, min(100.0, score)), 2)
        row["publication_quality_score"] = score
        row["publication_quality_tier"] = "premium" if score >= 78.0 else ("standard" if score >= 60.0 else "loose")
        row["publication_quality_reasons"] = ",".join(sorted(set(reasons)))


def _group_stats_with_count(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    return _group_stats(rows)


def summarize(scan: Mapping[str, Any]) -> Dict[str, Any]:
    rows = list(scan.get("detections") or [])
    evals = [row for row in rows if row.get("mfe_pct") is not None]
    return {
        "generated_at": _utc_now(),
        "pattern_key": str(scan.get("pattern_key") or PATTERN_KEY),
        "symbols_scanned": int(scan.get("symbols_scanned") or 0),
        "detection_count": len(rows),
        "evaluated_count": len(evals),
        "up_breakouts": sum(1 for row in rows if row.get("breakout_direction") == "up"),
        "down_breakouts": sum(1 for row in rows if row.get("breakout_direction") == "down"),
        **_group_stats_with_count(rows),
        "breakout_groups": {
            "all": _group_stats(rows),
            "up": _group_stats([row for row in rows if row.get("breakout_direction") == "up"]),
            "down": _group_stats([row for row in rows if row.get("breakout_direction") == "down"]),
        },
        "variant_table": {
            label: _group_stats([row for row in rows if row.get("variant") == label])
            for label in ("cup_with_handle", "cup_with_handle_inverted")
        },
        "quality_table": {tier: _group_stats([row for row in rows if row.get("pattern_quality_tier") == tier]) for tier in ("clean", "usable", "loose")},
        "publication_quality_table": {tier: _group_stats([row for row in rows if row.get("publication_quality_tier") == tier]) for tier in ("premium", "standard", "loose", "data_limited")},
        "regime_groups": {regime: _group_stats([row for row in rows if str(row.get("market_regime") or "unknown") == regime]) for regime in ("bull", "bear", "unknown")},
        "market_group_table": {group: _group_stats([row for row in rows if str(row.get("market_group") or "Outside VN100") == group]) for group in ("VN30", "VN100 ex VN30", "Outside VN100")},
        "liquidity_proxy_table": _group_table(rows, "liquidity_bucket", ("high", "mid", "low", "unknown")),
        "regime_proxy_table": _group_table(rows, "market_regime", ("bull", "bear", "unknown")),
        "volume_trend_table": _group_table(rows, "volume_trend_direction", ("down", "flat", "up", "unknown")),
        "path_quality_audit": _path_quality_audit(rows),
        "symbol_concentration": {
            "symbols_with_events": len({str(row.get("symbol")) for row in rows if row.get("symbol")}),
            "top10_symbol_share_pct": round(float(pd.Series([str(row.get("symbol")) for row in rows if row.get("symbol")]).value_counts().head(10).sum()) / max(len(rows), 1) * 100.0, 2),
        },
        "quantile_metrics": {
            "fav_exc_pct": _quantiles([row.get("mfe_pct") for row in evals]),
            "adv_exc_pct": _quantiles([row.get("mae_pct") for row in evals]),
            "target_dist_pct": _quantiles([row.get("target_dist_pct") for row in evals]),
            "cup_width_bars": _quantiles([row.get("cup_width_bars") for row in rows]),
            "handle_width_bars": _quantiles([row.get("handle_width_bars") for row in rows]),
        },
        "experiment_note": "Cup Family scanner uses rounded cup rims, prior trend, right-side handle, and close-confirmed breakout.",
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
    "cup_width_bars",
    "handle_width_bars",
    "rim_diff_pct",
    "bottom_pos_pct",
    "near_bottom_bars",
    "prior_trend_pct",
    "handle_move_pct",
    "handle_retrace_pct",
    "handle_pos_pct",
    "breakout_clearance_pct",
    "volume_confirmed",
    "breakout_volume_ratio",
    "volume_trend_direction",
    "left_rim_price",
    "right_rim_price",
    "cup_extreme_price",
    "handle_extreme_price",
    "stop_loss_price",
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
    family = str(scan.get("pattern_key") or PATTERN_KEY)
    if events.empty:
        stats["target_family_sensitivity"] = []
        stats["target_calibration_decision"] = None
        return
    if "event_id" not in events.columns and "detection_id" in events.columns:
        events["event_id"] = events["detection_id"]
    sensitivity = target_sensitivity(PatternArtifacts(family, events, path), family, horizon_days=120)
    stats["target_family_sensitivity"] = sensitivity
    stats["target_calibration_decision"] = (build_target_calibration_decisions(sensitivity, family_labels=(family,)) or [None])[0]
    stats["target_family"] = {"local_base": 0.5, "local_stretch": 0.75, "legacy_full_height": 1.0}


def scan_cup_with_handle_db(
    *,
    variant: str,
    db_path: Path,
    out_dir: Path,
    allowed_symbols: Optional[Sequence[str]] = None,
    detector_config: Optional[Mapping[str, Any]] = None,
    limit_symbols: Optional[int] = None,
    index_db: Path = DEFAULT_INDEX_DB,
    index_symbol: str = DEFAULT_INDEX_SYMBOL,
) -> dict[str, Path]:
    if variant not in {"cup_with_handle", "cup_with_handle_inverted"}:
        raise ValueError("variant must be cup_with_handle or cup_with_handle_inverted")
    out_dir.mkdir(parents=True, exist_ok=True)
    config = CupWithHandleConfig.from_mapping(detector_config)
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
                rows, stats = scan_symbol(frame, variant=variant, detector_config=config)
                if rows:
                    series_by_symbol[symbol] = frame
                detections.extend(rows)
                symbol_stats.append({"symbol": symbol, "detections": len(rows), **stats})
            except Exception as exc:
                symbol_stats.append({"symbol": symbol, "detections": 0, "error": str(exc)})
    finally:
        conn.close()
    for i, row in enumerate(detections):
        row["detection_id"] = f"{variant}:{i + 1:06d}"
    detections, regime_meta = classify_market_regimes(detections, index_db=index_db, index_symbol=index_symbol, anchor_field="breakout_date")
    market_group_meta = attach_current_market_groups(detections)
    scan: dict[str, Any] = {
        "generated_at": _utc_now(),
        "source": "Market Cache latest.sqlite stock_price_history",
        "db_path": str(db_path),
        "pattern_key": variant,
        "symbols_scanned": len(symbols),
        "detections": detections,
        "symbol_stats": symbol_stats,
        "regime": regime_meta,
        "market_group": market_group_meta,
        "detector_config": config.to_dict(),
    }
    _enrich_events_from_series(scan, series_by_symbol, corporate_db=index_db)
    _assign_publication_quality_tiers(scan["detections"], defensive=(variant.endswith("inverted")))
    stats = summarize(scan)
    stats["source"] = scan["source"]
    stats["db_source_meta"] = _db_meta(db_path)
    stats["detector_config"] = config.to_dict()
    path_rows = _path_rows_from_series(scan, series_by_symbol, horizon_bars=120)
    _add_target_calibration(stats, scan, path_rows)
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
    parser = argparse.ArgumentParser(description="Run Cup-with-Handle family scanner against Market Cache latest.sqlite.")
    parser.add_argument("--variant", choices=["cup_with_handle", "cup_with_handle_inverted"], required=True)
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--market-stats-json", default=str(DEFAULT_MARKET_STATS_JSON))
    parser.add_argument("--limit-symbols", type=int, default=None)
    args = parser.parse_args()
    active_meta = _load_active_symbols(Path(args.market_stats_json) if args.market_stats_json else None)
    active_symbols = active_meta.get("active_symbols") if active_meta.get("enabled") else None
    paths = scan_cup_with_handle_db(
        variant=args.variant,
        db_path=Path(args.db),
        out_dir=Path(args.out_dir) / args.variant / "db_active",
        allowed_symbols=active_symbols,
        limit_symbols=args.limit_symbols,
    )
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
