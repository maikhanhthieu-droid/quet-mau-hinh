"""Experimental Scanner V2 flag detector.

This began as a diagnostic experiment and is now the shared data runner for
the Flag Family lane. Official Bull/Bear Flag promotion still happens through
the contract and release-gate modules.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

from ..ohlcv_normalizer import OHLCVNormalizer
from ..pivot_detector import Pivot, PivotDetector, PivotType
from .source_data import DEFAULT_SOURCE_DIR
from .source_data import attach_current_market_groups as _attach_current_market_groups
from .source_data import classify_market_regimes as _classify_market_regimes
from .source_data import load_market_stats_symbol as _load_market_stats_symbol
from .source_data import symbol_concentration as _symbol_concentration
from .source_data import symbol_from_path as _symbol_from_path


PATTERN_KEY = "flags_experiment"
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/flags_experiment")
DEFAULT_INDEX_DB = Path("vietnam_stocks.db")
DEFAULT_INDEX_SYMBOL = "VNINDEX"


@dataclass(frozen=True)
class Trendline:
    idx0: int
    price0: float
    slope_per_bar: float

    def value_at(self, idx: int) -> float:
        return self.price0 + self.slope_per_bar * (idx - self.idx0)


@dataclass(frozen=True)
class FlagDetectorConfig:
    width_min_bars: int = 5
    width_max_bars: int = 25
    pole_lookback_bars: int = 40
    pole_min_change_pct: float = 10.0
    pole_min_slope_deg: float = 8.0
    parallel_tol_deg: float = 4.0
    bull_avg_slope_min: float = -12.0
    bull_avg_slope_max: float = 4.0
    bear_avg_slope_min: float = -4.0
    bear_avg_slope_max: float = 12.0
    height_min_pct: float = 3.0
    height_max_pct: float = 15.0
    flag_to_pole_max_pct: float = 55.0
    breakout_search_bars: int = 12
    breakout_threshold: float = 0.0075
    breakout_volume_confirm_ratio: float = 1.2
    require_volume_confirmed: bool = False
    max_events_per_symbol: int = 10
    breakout_cooldown_bars: int = 15

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]] = None) -> "FlagDetectorConfig":
        if value is None:
            return cls()
        allowed = {field.name for field in fields(cls)}
        clean: Dict[str, Any] = {}
        for key, item in value.items():
            if key in allowed:
                clean[key] = item
        return cls(**clean)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def _safe_float(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _slope_degrees(idx1: int, price1: float, idx2: int, price2: float) -> float:
    bars = max(1, int(idx2) - int(idx1))
    if price1 == 0:
        return 0.0
    change_pct = (price2 - price1) / price1 * 100.0
    return float(np.degrees(np.arctan(change_pct / bars)))


def _median(values: Iterable[Optional[float]]) -> Optional[float]:
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if not vals:
        return None
    return round(float(np.median(vals)), 2)


def _mean(values: Iterable[Optional[float]]) -> Optional[float]:
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if not vals:
        return None
    return round(float(np.mean(vals)), 2)


def _pct(numerator: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100.0, 2)


def _rate(rows: Sequence[Mapping[str, Any]], key: str) -> Optional[float]:
    vals = [row.get(key) for row in rows if row.get(key) is not None]
    if not vals:
        return None
    return _pct(sum(1 for val in vals if val is True), len(vals))


def _quantiles(values: Iterable[Optional[float]]) -> Dict[str, Optional[float]]:
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    points = [1, 5, 10, 25, 50, 75, 90, 95, 99]
    if not vals:
        return {f"P{p}": None for p in points}
    return {f"P{p}": round(float(np.percentile(vals, p)), 2) for p in points}


class FlagExperimentDetector:
    """Detect short flag continuations with a required prior flagpole."""

    def __init__(self, config: Optional[FlagDetectorConfig | Mapping[str, Any]] = None) -> None:
        self.config = config if isinstance(config, FlagDetectorConfig) else FlagDetectorConfig.from_mapping(config)
        for key, value in self.config.to_dict().items():
            setattr(self, key, value)

    def _prior_pole(self, df: pd.DataFrame, *, start_idx: int, direction: str, anchor_price: float) -> Optional[Dict[str, Any]]:
        lb = max(0, start_idx - self.pole_lookback_bars)
        window = df.iloc[lb : start_idx + 1]
        if len(window) < 4 or anchor_price <= 0:
            return None
        if direction == "up":
            vals = window["low"].to_numpy(dtype=float, copy=False)
            if len(vals) == 0 or np.all(np.isnan(vals)):
                return None
            rel = int(np.nanargmin(vals))
            pole_idx = lb + rel
            pole_price = float(vals[rel])
            move_pct = (anchor_price - pole_price) / pole_price * 100.0 if pole_price > 0 else 0.0
            slope_deg = _slope_degrees(pole_idx, pole_price, start_idx, anchor_price)
        else:
            vals = window["high"].to_numpy(dtype=float, copy=False)
            if len(vals) == 0 or np.all(np.isnan(vals)):
                return None
            rel = int(np.nanargmax(vals))
            pole_idx = lb + rel
            pole_price = float(vals[rel])
            move_pct = (pole_price - anchor_price) / pole_price * 100.0 if pole_price > 0 else 0.0
            slope_deg = abs(_slope_degrees(pole_idx, pole_price, start_idx, anchor_price))
        pole_bars = start_idx - pole_idx + 1
        if pole_bars <= 1 or pole_bars > self.pole_lookback_bars:
            return None
        if move_pct < self.pole_min_change_pct or slope_deg < self.pole_min_slope_deg:
            return None
        return {
            "pole_idx": int(pole_idx),
            "pole_price": round(float(pole_price), 4),
            "pole_move_pct": round(float(move_pct), 2),
            "pole_slope_deg": round(float(slope_deg), 2),
            "pole_bars": int(pole_bars),
        }

    def _breakout(self, df: pd.DataFrame, *, start_idx: int, line: Trendline, direction: str) -> Tuple[Optional[int], Optional[float], bool, Optional[float]]:
        for idx in range(start_idx, min(len(df), start_idx + self.breakout_search_bars)):
            close = _safe_float(df.iloc[idx].get("close"))
            boundary = line.value_at(idx)
            if close is None or boundary <= 0:
                continue
            if direction == "up":
                ok = close > boundary * (1.0 + self.breakout_threshold)
            else:
                ok = close < boundary * (1.0 - self.breakout_threshold)
            if not ok:
                continue
            volume_ratio = _safe_float(df.iloc[idx].get("volume_ratio"))
            volume_confirmed = bool(volume_ratio is not None and volume_ratio >= self.breakout_volume_confirm_ratio)
            if self.require_volume_confirmed and not volume_confirmed:
                continue
            return idx, close, volume_confirmed, volume_ratio
        return None, None, False, None

    def scan_window(self, df: pd.DataFrame, pivots: Sequence[Pivot]) -> Optional[Dict[str, Any]]:
        if len(pivots) != 4:
            return None
        idxs = [int(p.idx) for p in pivots]
        if not (idxs[0] < idxs[1] < idxs[2] < idxs[3]):
            return None
        width = idxs[-1] - idxs[0] + 1
        if width < self.width_min_bars or width > self.width_max_bars:
            return None
        kinds = [p.type for p in pivots]
        if kinds == [PivotType.HIGH, PivotType.LOW, PivotType.HIGH, PivotType.LOW]:
            direction = "up"
            upper_points = [(idxs[0], float(df.iloc[idxs[0]]["high"])), (idxs[2], float(df.iloc[idxs[2]]["high"]))]
            lower_points = [(idxs[1], float(df.iloc[idxs[1]]["low"])), (idxs[3], float(df.iloc[idxs[3]]["low"]))]
            anchor_price = upper_points[0][1]
            variant = "bull_flag"
        elif kinds == [PivotType.LOW, PivotType.HIGH, PivotType.LOW, PivotType.HIGH]:
            direction = "down"
            upper_points = [(idxs[1], float(df.iloc[idxs[1]]["high"])), (idxs[3], float(df.iloc[idxs[3]]["high"]))]
            lower_points = [(idxs[0], float(df.iloc[idxs[0]]["low"])), (idxs[2], float(df.iloc[idxs[2]]["low"]))]
            anchor_price = lower_points[0][1]
            variant = "bear_flag"
        else:
            return None

        upper = Trendline(upper_points[0][0], upper_points[0][1], (upper_points[1][1] - upper_points[0][1]) / max(1, upper_points[1][0] - upper_points[0][0]))
        lower = Trendline(lower_points[0][0], lower_points[0][1], (lower_points[1][1] - lower_points[0][1]) / max(1, lower_points[1][0] - lower_points[0][0]))
        upper_deg = _slope_degrees(upper_points[0][0], upper_points[0][1], upper_points[1][0], upper_points[1][1])
        lower_deg = _slope_degrees(lower_points[0][0], lower_points[0][1], lower_points[1][0], lower_points[1][1])
        slope_gap = abs(upper_deg - lower_deg)
        if slope_gap > self.parallel_tol_deg:
            return None
        avg_slope = (upper_deg + lower_deg) / 2.0
        if direction == "up" and not (self.bull_avg_slope_min <= avg_slope <= self.bull_avg_slope_max):
            return None
        if direction == "down" and not (self.bear_avg_slope_min <= avg_slope <= self.bear_avg_slope_max):
            return None

        mid_idx = (idxs[1] + idxs[2]) // 2
        gap_mid = upper.value_at(mid_idx) - lower.value_at(mid_idx)
        mid_ref = (upper.value_at(mid_idx) + lower.value_at(mid_idx)) / 2.0
        if gap_mid <= 0 or mid_ref <= 0:
            return None
        flag_height_pct = gap_mid / mid_ref * 100.0
        if flag_height_pct < self.height_min_pct or flag_height_pct > self.height_max_pct:
            return None

        pole = self._prior_pole(df, start_idx=idxs[0], direction=direction, anchor_price=anchor_price)
        if not pole:
            return None
        flag_to_pole_pct = flag_height_pct / float(pole["pole_move_pct"]) * 100.0 if float(pole["pole_move_pct"]) > 0 else 999.0
        if flag_to_pole_pct > self.flag_to_pole_max_pct:
            return None

        breakout_line = upper if direction == "up" else lower
        breakout_idx, breakout_price, volume_confirmed, breakout_volume_ratio = self._breakout(df, start_idx=idxs[-1] + 1, line=breakout_line, direction=direction)
        if breakout_idx is None or breakout_price is None:
            return None
        pole_height_abs = abs(anchor_price - float(pole["pole_price"]))
        target_price = float(breakout_price) + pole_height_abs if direction == "up" else float(breakout_price) - pole_height_abs
        quality_score = 70
        if float(pole["pole_move_pct"]) >= 14.0:
            quality_score += 8
        if slope_gap <= 2.0:
            quality_score += 7
        if flag_to_pole_pct <= 35.0:
            quality_score += 8
        if volume_confirmed:
            quality_score += 5
        quality_score = min(100, int(quality_score))
        return {
            "formation_start_idx": idxs[0],
            "formation_end_idx": idxs[-1],
            "formation_start_date": str(pd.Timestamp(df.iloc[idxs[0]]["date"]).date()),
            "formation_end_date": str(pd.Timestamp(df.iloc[idxs[-1]]["date"]).date()),
            "breakout_idx": int(breakout_idx),
            "breakout_date": str(pd.Timestamp(df.iloc[int(breakout_idx)]["date"]).date()),
            "breakout_direction": direction,
            "breakout_price": round(float(breakout_price), 4),
            "target_price": round(float(target_price), 4),
            "pattern_width_bars": int(width),
            "pattern_height_pct": round(float(flag_height_pct), 2),
            "pivot_indices": idxs,
            "variant": variant,
            "volume_confirmed": volume_confirmed,
            "breakout_volume_ratio": round(float(breakout_volume_ratio), 4) if breakout_volume_ratio is not None else None,
            "pattern_quality_score": quality_score,
            "pattern_quality_tier": "clean" if quality_score >= 85 else ("usable" if quality_score >= 75 else "loose"),
            "upper_slope_deg": round(float(upper_deg), 2),
            "lower_slope_deg": round(float(lower_deg), 2),
            "slope_gap_deg": round(float(slope_gap), 2),
            "flag_to_pole_pct": round(float(flag_to_pole_pct), 2),
            "flag_upper_idx0": int(upper.idx0),
            "flag_upper_price0": round(float(upper.price0), 4),
            "flag_upper_slope_per_bar": round(float(upper.slope_per_bar), 8),
            "flag_lower_idx0": int(lower.idx0),
            "flag_lower_price0": round(float(lower.price0), 4),
            "flag_lower_slope_per_bar": round(float(lower.slope_per_bar), 8),
            "flag_upper_breakout_value": round(float(upper.value_at(int(breakout_idx))), 4),
            "flag_lower_breakout_value": round(float(lower.value_at(int(breakout_idx))), 4),
            **pole,
        }


def _evaluate_detection(df: pd.DataFrame, detection: Mapping[str, Any], *, lookahead: int = 60) -> Dict[str, Any]:
    breakout_idx = int(detection["breakout_idx"])
    breakout_price = float(detection["breakout_price"])
    target = float(detection["target_price"])
    direction = str(detection["breakout_direction"])
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
        }
    target_dist_pct = abs(target - breakout_price) / breakout_price * 100.0
    if direction == "up":
        mfe = (float(future["high"].max()) - breakout_price) / breakout_price * 100.0
        mae = (breakout_price - float(future["low"].min())) / breakout_price * 100.0
        target_hit = bool(float(future["high"].max()) >= target)
    else:
        mfe = (breakout_price - float(future["low"].min())) / breakout_price * 100.0
        mae = (float(future["high"].max()) - breakout_price) / breakout_price * 100.0
        target_hit = bool(float(future["low"].min()) <= target)
    days_to_target: Optional[int] = None
    days_to_adverse_5: Optional[int] = None
    for offset, (_, row) in enumerate(future.iterrows(), start=1):
        high = float(row["high"])
        low = float(row["low"])
        if direction == "up":
            if days_to_target is None and high >= target:
                days_to_target = offset
            if days_to_adverse_5 is None and low <= breakout_price * 0.95:
                days_to_adverse_5 = offset
        else:
            if days_to_target is None and low <= target:
                days_to_target = offset
            if days_to_adverse_5 is None and high >= breakout_price * 1.05:
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
    }


def scan_symbol(
    df_raw: pd.DataFrame,
    *,
    max_events_per_symbol: Optional[int] = None,
    detector_config: Optional[FlagDetectorConfig | Mapping[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if len(df_raw) < 120:
        return [], {"rows": int(len(df_raw)), "skipped": "too_few_rows"}
    config = detector_config if isinstance(detector_config, FlagDetectorConfig) else FlagDetectorConfig.from_mapping(detector_config)
    max_events = int(max_events_per_symbol if max_events_per_symbol is not None else config.max_events_per_symbol)
    df, norm_stats = OHLCVNormalizer().normalize(df_raw)
    pivots = PivotDetector().detect_pivots(df, pivot_type="minor")
    detector = FlagExperimentDetector(config)
    out: List[Dict[str, Any]] = []
    used_breakouts: List[int] = []
    symbol = str(df.iloc[0]["symbol"])
    for i in range(len(pivots) - 3):
        candidate = detector.scan_window(df, pivots[i : i + 4])
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
            break
    return out, {"rows": int(len(df)), "pivots": int(len(pivots)), "normalizer": norm_stats, "detector_config": config.to_dict()}


def scan_market_stats(
    source_dir: Path,
    *,
    limit_symbols: Optional[int] = None,
    index_db: Path = DEFAULT_INDEX_DB,
    index_symbol: str = DEFAULT_INDEX_SYMBOL,
    allowed_symbols: Optional[Sequence[str]] = None,
    detector_config: Optional[FlagDetectorConfig | Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    config = detector_config if isinstance(detector_config, FlagDetectorConfig) else FlagDetectorConfig.from_mapping(detector_config)
    allowed = {str(symbol).strip().upper() for symbol in allowed_symbols or [] if str(symbol).strip()}
    paths_by_symbol: Dict[str, Path] = {}
    for path in sorted(source_dir.glob("*.json")):
        symbol = _symbol_from_path(path)
        if allowed and symbol not in allowed:
            continue
        current = paths_by_symbol.get(symbol)
        exact_name = f"{symbol}.json".upper()
        rank = (0 if path.name.upper() == exact_name else 1, len(path.name), path.name)
        current_rank = (2, 9999, "") if current is None else (0 if current.name.upper() == exact_name else 1, len(current.name), current.name)
        if current is None or rank < current_rank:
            paths_by_symbol[symbol] = path
    paths = [paths_by_symbol[symbol] for symbol in sorted(paths_by_symbol)]
    if limit_symbols is not None:
        paths = paths[: int(limit_symbols)]
    detections: List[Dict[str, Any]] = []
    symbol_stats: List[Dict[str, Any]] = []
    for path in paths:
        try:
            df = _load_market_stats_symbol(path)
            rows, stats = scan_symbol(df, detector_config=config)
            detections.extend(rows)
            symbol_stats.append({"symbol": _symbol_from_path(path), "detections": len(rows), **stats})
        except Exception as exc:
            symbol_stats.append({"symbol": _symbol_from_path(path), "detections": 0, "error": str(exc)})
    for i, row in enumerate(detections):
        row["detection_id"] = f"{PATTERN_KEY}:{i + 1:06d}"
    detections, regime_meta = _classify_market_regimes(detections, index_db=index_db, index_symbol=index_symbol)
    market_group_meta = _attach_current_market_groups(detections)
    return {
        "generated_at": _utc_now(),
        "source": "Market Stats V1 stock_series JSON",
        "source_dir": str(source_dir),
        "pattern_key": PATTERN_KEY,
        "symbols_scanned": len(paths),
        "detections": detections,
        "symbol_stats": symbol_stats,
        "regime": regime_meta,
        "market_group": market_group_meta,
        "detector_config": config.to_dict(),
        "experiment_status": "diagnostic_only_not_official_p1_p5",
    }


def _group_stats(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    evals = [row for row in rows if row.get("mfe_pct") is not None]
    return {
        "detection_count": len(rows),
        "evaluated_count": len(evals),
        "median_mfe_pct": _median(row.get("mfe_pct") for row in evals),
        "median_mae_pct": _median(row.get("mae_pct") for row in evals),
        "average_mfe_pct": _mean(row.get("mfe_pct") for row in evals),
        "average_mae_pct": _mean(row.get("mae_pct") for row in evals),
        "target_hit_rate": _rate(evals, "target_hit"),
        "failure_5pct_rate": _rate(evals, "failure_5pct"),
        "target_first_before_adverse_5pct_rate": _rate(evals, "target_first_before_adverse_5pct"),
        "median_target_dist_pct": _median(row.get("target_dist_pct") for row in evals),
        "median_quality_score": _median(row.get("pattern_quality_score") for row in rows),
    }


def summarize(scan: Mapping[str, Any]) -> Dict[str, Any]:
    rows = list(scan.get("detections") or [])
    evals = [row for row in rows if row.get("mfe_pct") is not None]
    up = [row for row in rows if row.get("breakout_direction") == "up"]
    down = [row for row in rows if row.get("breakout_direction") == "down"]
    return {
        "generated_at": _utc_now(),
        "pattern_key": PATTERN_KEY,
        "symbols_scanned": int(scan.get("symbols_scanned") or 0),
        "detection_count": len(rows),
        "evaluated_count": len(evals),
        "up_breakouts": len(up),
        "down_breakouts": len(down),
        **_group_stats(rows),
        "breakout_groups": {"all": _group_stats(rows), "up": _group_stats(up), "down": _group_stats(down)},
        "variant_table": {
            variant: _group_stats([row for row in rows if row.get("variant") == variant])
            for variant in ("bull_flag", "bear_flag")
        },
        "quality_table": {
            tier: _group_stats([row for row in rows if row.get("pattern_quality_tier") == tier])
            for tier in ("clean", "usable", "loose")
        },
        "regime_groups": {
            regime: _group_stats([row for row in rows if str(row.get("market_regime") or "unknown") == regime])
            for regime in ("bull", "bear", "unknown")
        },
        "market_group_table": {
            group: _group_stats([row for row in rows if str(row.get("market_group") or "Outside VN100") == group])
            for group in ("VN30", "VN100 ex VN30", "Outside VN100")
        },
        "quantile_metrics": {
            "fav_exc_pct": _quantiles(row.get("mfe_pct") for row in evals),
            "adv_exc_pct": _quantiles(row.get("mae_pct") for row in evals),
            "target_dist_pct": _quantiles(row.get("target_dist_pct") for row in evals),
        },
        "symbol_concentration": _symbol_concentration(rows),
        "experiment_note": "Flags experiment uses required flagpole + short channel continuation logic. It is not official P1-P5 provenance.",
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
    "pattern_width_bars",
    "pattern_height_pct",
    "pole_move_pct",
    "pole_slope_deg",
    "pole_bars",
    "flag_to_pole_pct",
    "upper_slope_deg",
    "lower_slope_deg",
    "slope_gap_deg",
    "volume_confirmed",
    "breakout_volume_ratio",
    "flag_upper_idx0",
    "flag_upper_price0",
    "flag_upper_slope_per_bar",
    "flag_lower_idx0",
    "flag_lower_price0",
    "flag_lower_slope_per_bar",
    "flag_upper_breakout_value",
    "flag_lower_breakout_value",
]


def _path_rows(scan: Mapping[str, Any], *, source_dir: Path, horizon_bars: int = 120) -> List[Dict[str, Any]]:
    symbol_paths = {_symbol_from_path(path): path for path in sorted(source_dir.glob("*.json"))}
    cache: Dict[str, pd.DataFrame] = {}
    out: List[Dict[str, Any]] = []
    for det in scan.get("detections") or []:
        symbol = str(det.get("symbol") or "").upper()
        path = symbol_paths.get(symbol)
        if path is None:
            continue
        if symbol not in cache:
            cache[symbol] = _load_market_stats_symbol(path).reset_index(drop=True)
        df = cache[symbol]
        breakout_idx = int(det["breakout_idx"])
        breakout_price = float(det["breakout_price"])
        direction = 1 if det.get("breakout_direction") == "up" else -1
        for offset, (_, row) in enumerate(df.iloc[breakout_idx + 1 : min(len(df), breakout_idx + 1 + horizon_bars)].iterrows(), start=1):
            close = float(row["close"])
            high = float(row["high"])
            low = float(row["low"])
            if direction == 1:
                signed_close = (close - breakout_price) / breakout_price * 100.0
                signed_high = (high - breakout_price) / breakout_price * 100.0
                signed_low = (low - breakout_price) / breakout_price * 100.0
            else:
                signed_close = (breakout_price - close) / breakout_price * 100.0
                signed_high = (breakout_price - low) / breakout_price * 100.0
                signed_low = (breakout_price - high) / breakout_price * 100.0
            out.append(
                {
                    "event_id": det.get("detection_id"),
                    "symbol": symbol,
                    "trade_date": str(pd.Timestamp(row["date"]).date()),
                    "bar_after_breakout": offset,
                    "open": round(float(row["open"]), 4),
                    "high": round(high, 4),
                    "low": round(low, 4),
                    "close": round(close, 4),
                    "volume": int(row["volume"]) if pd.notna(row["volume"]) else None,
                    "signed_close_return_pct": round(float(signed_close), 4),
                    "signed_high_excursion_pct": round(float(signed_high), 4),
                    "signed_low_excursion_pct": round(float(signed_low), 4),
                }
            )
    return out


def _render_pdf(path: Path, stats: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(path) as pdf:
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.patch.set_facecolor("#fffdf8")
        fig.text(0.5, 0.91, "Flags Experiment", ha="center", va="top", fontsize=22, weight="bold")
        fig.text(0.5, 0.875, "Đối chứng dữ liệu trong Flag Family", ha="center", va="top", fontsize=11)
        rows = [
            ("Số mã quét", stats.get("symbols_scanned")),
            ("Số mẫu Flag", stats.get("detection_count")),
            ("Mẫu có đánh giá", stats.get("evaluated_count")),
            ("Phá vỡ lên", stats.get("up_breakouts")),
            ("Phá vỡ xuống", stats.get("down_breakouts")),
            ("MFE trung vị", f"{stats.get('median_mfe_pct')}%"),
            ("MAE trung vị", f"{stats.get('median_mae_pct')}%"),
            ("Target hit", f"{stats.get('target_hit_rate')}%"),
            ("Fail 5%", f"{stats.get('failure_5pct_rate')}%"),
            ("Target-first trước adverse 5%", f"{stats.get('target_first_before_adverse_5pct_rate')}%"),
        ]
        y = 0.80
        for label, value in rows:
            fig.text(0.18, y, str(label), fontsize=10, weight="bold", ha="left", va="top")
            fig.text(0.62, y, str(value), fontsize=10, ha="left", va="top")
            y -= 0.035
        fig.text(
            0.14,
            0.18,
            "Ghi chú: đây là experiment chưa có provenance P1-P5 cho chương Flag. "
            "Mục tiêu là kiểm tra nhanh liệu nhánh Flag nào có thống kê hậu phá vỡ đủ ổn định để nâng lên chapter chính.",
            fontsize=9,
            ha="left",
            va="top",
            wrap=True,
        )
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)


def run_experiment(
    *,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    out_dir: Path = DEFAULT_OUT_DIR,
    limit_symbols: Optional[int] = None,
    index_db: Path = DEFAULT_INDEX_DB,
    index_symbol: str = DEFAULT_INDEX_SYMBOL,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    scan = scan_market_stats(source_dir, limit_symbols=limit_symbols, index_db=index_db, index_symbol=index_symbol)
    stats = summarize(scan)
    path_rows = _path_rows(scan, source_dir=source_dir)
    paths = {
        "detections": out_dir / "detections.json",
        "statistics": out_dir / "statistics.json",
        "events_csv": out_dir / "events.csv",
        "post_breakout_path_csv": out_dir / "post_breakout_path.csv",
        "pdf": out_dir / "flags_experiment.pdf",
    }
    _write_json(paths["detections"], scan)
    _write_json(paths["statistics"], stats)
    _write_csv(paths["events_csv"], scan.get("detections") or [], EVENT_FIELDS)
    _write_csv(
        paths["post_breakout_path_csv"],
        path_rows,
        [
            "event_id",
            "symbol",
            "trade_date",
            "bar_after_breakout",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "signed_close_return_pct",
            "signed_high_excursion_pct",
            "signed_low_excursion_pct",
        ],
    )
    _render_pdf(paths["pdf"], stats)
    return paths
