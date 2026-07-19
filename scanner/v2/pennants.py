"""Pennant scanner candidate for the Flag-like Family.

This module is intentionally separate from the Flag scanner. Pennants share the
flagpole/continuation idea with Flags, but their body is converging, not
parallel. The output schema mirrors the Flag data runner so the shared
statistics/calibration layer can consume it without inheriting Flag geometry.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from ..ohlcv_normalizer import OHLCVNormalizer
from ..pivot_detector import Pivot, PivotDetector, PivotType
from ..research_support_analysis import PatternArtifacts, target_sensitivity
from .bull_flags_monograph import _add_sensitivity_tables, _enrich_events
from .flags_experiment import (
    DEFAULT_INDEX_DB,
    DEFAULT_INDEX_SYMBOL,
    EVENT_FIELDS,
    Trendline,
    _evaluate_detection,
    _path_rows,
    _safe_float,
    _slope_degrees,
)
from .source_data import (
    DEFAULT_SOURCE_DIR,
    attach_current_market_groups,
    classify_market_regimes,
    load_market_stats_symbol,
    symbol_from_path,
)


PATTERN_KEY = "pennants"
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/pennants")


@dataclass(frozen=True)
class PennantDetectorConfig:
    width_min_bars: int = 2
    width_max_bars: int = 15
    pole_lookback_bars: int = 40
    pole_min_change_pct: float = 10.0
    pole_min_slope_deg: float = 8.0
    height_min_pct: float = 2.0
    height_max_pct: float = 16.0
    pennant_to_pole_max_pct: float = 65.0
    compression_max_ratio: float = 0.82
    compression_min_ratio: float = 0.12
    bull_avg_slope_min: float = -18.0
    bull_avg_slope_max: float = 10.0
    bear_avg_slope_min: float = -10.0
    bear_avg_slope_max: float = 18.0
    breakout_search_bars: int = 12
    breakout_threshold: float = 0.0075
    breakout_volume_confirm_ratio: float = 1.2
    require_volume_confirmed: bool = False
    max_events_per_symbol: int = 10
    breakout_cooldown_bars: int = 15

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]] = None) -> "PennantDetectorConfig":
        if value is None:
            return cls()
        allowed = {field.name for field in fields(cls)}
        return cls(**{key: item for key, item in value.items() if key in allowed})

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _line_gap(upper: Trendline, lower: Trendline, idx: int) -> float:
    return float(upper.value_at(idx) - lower.value_at(idx))


class PennantDetector:
    """Detect short converging pennants after a steep flagpole."""

    def __init__(self, config: Optional[PennantDetectorConfig | Mapping[str, Any]] = None) -> None:
        self.config = config if isinstance(config, PennantDetectorConfig) else PennantDetectorConfig.from_mapping(config)

    def _prior_pole(self, df: pd.DataFrame, *, start_idx: int, direction: str, anchor_price: float) -> Optional[Dict[str, Any]]:
        lb = max(0, start_idx - self.config.pole_lookback_bars)
        window = df.iloc[lb : start_idx + 1]
        if len(window) < 4 or anchor_price <= 0:
            return None
        if direction == "up":
            vals = window["low"].to_numpy(dtype=float, copy=False)
            if vals.size == 0 or np.all(np.isnan(vals)):
                return None
            rel = int(np.nanargmin(vals))
            pole_idx = lb + rel
            pole_price = float(vals[rel])
            move_pct = (anchor_price - pole_price) / pole_price * 100.0 if pole_price > 0 else 0.0
            slope_deg = _slope_degrees(pole_idx, pole_price, start_idx, anchor_price)
        else:
            vals = window["high"].to_numpy(dtype=float, copy=False)
            if vals.size == 0 or np.all(np.isnan(vals)):
                return None
            rel = int(np.nanargmax(vals))
            pole_idx = lb + rel
            pole_price = float(vals[rel])
            move_pct = (pole_price - anchor_price) / pole_price * 100.0 if pole_price > 0 else 0.0
            slope_deg = abs(_slope_degrees(pole_idx, pole_price, start_idx, anchor_price))
        pole_bars = start_idx - pole_idx + 1
        if pole_bars <= 1 or pole_bars > self.config.pole_lookback_bars:
            return None
        if move_pct < self.config.pole_min_change_pct or slope_deg < self.config.pole_min_slope_deg:
            return None
        return {
            "pole_idx": int(pole_idx),
            "pole_price": round(float(pole_price), 4),
            "pole_move_pct": round(float(move_pct), 2),
            "pole_slope_deg": round(float(slope_deg), 2),
            "pole_bars": int(pole_bars),
        }

    def _breakout(self, df: pd.DataFrame, *, start_idx: int, line: Trendline, direction: str) -> Tuple[Optional[int], Optional[float], bool, Optional[float]]:
        for idx in range(start_idx, min(len(df), start_idx + self.config.breakout_search_bars)):
            close = _safe_float(df.iloc[idx].get("close"))
            boundary = line.value_at(idx)
            if close is None or boundary <= 0:
                continue
            ok = close > boundary * (1.0 + self.config.breakout_threshold) if direction == "up" else close < boundary * (1.0 - self.config.breakout_threshold)
            if not ok:
                continue
            volume_ratio = _safe_float(df.iloc[idx].get("volume_ratio"))
            volume_confirmed = bool(volume_ratio is not None and volume_ratio >= self.config.breakout_volume_confirm_ratio)
            if self.config.require_volume_confirmed and not volume_confirmed:
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
        if width < self.config.width_min_bars or width > self.config.width_max_bars:
            return None
        kinds = [p.type for p in pivots]
        if kinds == [PivotType.HIGH, PivotType.LOW, PivotType.HIGH, PivotType.LOW]:
            direction = "up"
            variant = "bull_pennant"
            upper_points = [(idxs[0], float(df.iloc[idxs[0]]["high"])), (idxs[2], float(df.iloc[idxs[2]]["high"]))]
            lower_points = [(idxs[1], float(df.iloc[idxs[1]]["low"])), (idxs[3], float(df.iloc[idxs[3]]["low"]))]
            anchor_price = upper_points[0][1]
        elif kinds == [PivotType.LOW, PivotType.HIGH, PivotType.LOW, PivotType.HIGH]:
            direction = "down"
            variant = "bear_pennant"
            upper_points = [(idxs[1], float(df.iloc[idxs[1]]["high"])), (idxs[3], float(df.iloc[idxs[3]]["high"]))]
            lower_points = [(idxs[0], float(df.iloc[idxs[0]]["low"])), (idxs[2], float(df.iloc[idxs[2]]["low"]))]
            anchor_price = lower_points[0][1]
        else:
            return None

        upper = Trendline(upper_points[0][0], upper_points[0][1], (upper_points[1][1] - upper_points[0][1]) / max(1, upper_points[1][0] - upper_points[0][0]))
        lower = Trendline(lower_points[0][0], lower_points[0][1], (lower_points[1][1] - lower_points[0][1]) / max(1, lower_points[1][0] - lower_points[0][0]))
        upper_deg = _slope_degrees(upper_points[0][0], upper_points[0][1], upper_points[1][0], upper_points[1][1])
        lower_deg = _slope_degrees(lower_points[0][0], lower_points[0][1], lower_points[1][0], lower_points[1][1])
        if upper.slope_per_bar >= lower.slope_per_bar:
            return None
        gap_start_idx = min(upper_points[0][0], lower_points[0][0])
        gap_end_idx = max(upper_points[1][0], lower_points[1][0])
        gap_start = _line_gap(upper, lower, gap_start_idx)
        gap_end = _line_gap(upper, lower, gap_end_idx)
        if gap_start <= 0 or gap_end <= 0 or gap_end >= gap_start:
            return None
        compression_ratio = gap_end / gap_start
        if not (self.config.compression_min_ratio <= compression_ratio <= self.config.compression_max_ratio):
            return None

        avg_slope = (upper_deg + lower_deg) / 2.0
        if direction == "up" and not (self.config.bull_avg_slope_min <= avg_slope <= self.config.bull_avg_slope_max):
            return None
        if direction == "down" and not (self.config.bear_avg_slope_min <= avg_slope <= self.config.bear_avg_slope_max):
            return None

        mid_idx = (idxs[1] + idxs[2]) // 2
        gap_mid = _line_gap(upper, lower, mid_idx)
        mid_ref = (upper.value_at(mid_idx) + lower.value_at(mid_idx)) / 2.0
        if gap_mid <= 0 or mid_ref <= 0:
            return None
        pennant_height_pct = gap_mid / mid_ref * 100.0
        if pennant_height_pct < self.config.height_min_pct or pennant_height_pct > self.config.height_max_pct:
            return None

        pole = self._prior_pole(df, start_idx=idxs[0], direction=direction, anchor_price=anchor_price)
        if not pole:
            return None
        pennant_to_pole_pct = pennant_height_pct / float(pole["pole_move_pct"]) * 100.0 if float(pole["pole_move_pct"]) > 0 else 999.0
        if pennant_to_pole_pct > self.config.pennant_to_pole_max_pct:
            return None

        breakout_line = upper if direction == "up" else lower
        breakout_idx, breakout_price, volume_confirmed, breakout_volume_ratio = self._breakout(df, start_idx=idxs[-1] + 1, line=breakout_line, direction=direction)
        if breakout_idx is None or breakout_price is None:
            return None

        pole_height_abs = abs(anchor_price - float(pole["pole_price"]))
        target_price = float(breakout_price) + pole_height_abs if direction == "up" else float(breakout_price) - pole_height_abs
        quality_score = 68
        if float(pole["pole_move_pct"]) >= 14.0:
            quality_score += 8
        if compression_ratio <= 0.65:
            quality_score += 8
        if pennant_to_pole_pct <= 35.0:
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
            "pattern_height_pct": round(float(pennant_height_pct), 2),
            "pivot_indices": idxs,
            "variant": variant,
            "volume_confirmed": volume_confirmed,
            "breakout_volume_ratio": round(float(breakout_volume_ratio), 4) if breakout_volume_ratio is not None else None,
            "pattern_quality_score": quality_score,
            "pattern_quality_tier": "clean" if quality_score >= 85 else ("usable" if quality_score >= 75 else "loose"),
            "upper_slope_deg": round(float(upper_deg), 2),
            "lower_slope_deg": round(float(lower_deg), 2),
            "slope_gap_deg": round(float(abs(upper_deg - lower_deg)), 2),
            "compression_ratio": round(float(compression_ratio), 4),
            "pennant_to_pole_pct": round(float(pennant_to_pole_pct), 2),
            "flag_to_pole_pct": round(float(pennant_to_pole_pct), 2),
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


def scan_symbol(
    df_raw: pd.DataFrame,
    *,
    max_events_per_symbol: Optional[int] = None,
    detector_config: Optional[PennantDetectorConfig | Mapping[str, Any]] = None,
) -> Tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(df_raw) < 120:
        return [], {"rows": int(len(df_raw)), "skipped": "too_few_rows"}
    config = detector_config if isinstance(detector_config, PennantDetectorConfig) else PennantDetectorConfig.from_mapping(detector_config)
    max_events = int(max_events_per_symbol if max_events_per_symbol is not None else config.max_events_per_symbol)
    df, norm_stats = OHLCVNormalizer().normalize(df_raw)
    pivots = PivotDetector().detect_pivots(df, pivot_type="minor")
    detector = PennantDetector(config)
    out: list[dict[str, Any]] = []
    used_breakouts: list[int] = []
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
    detector_config: Optional[PennantDetectorConfig | Mapping[str, Any]] = None,
) -> dict[str, Any]:
    config = detector_config if isinstance(detector_config, PennantDetectorConfig) else PennantDetectorConfig.from_mapping(detector_config)
    allowed = {str(symbol).strip().upper() for symbol in allowed_symbols or [] if str(symbol).strip()}
    paths_by_symbol: dict[str, Path] = {}
    for path in sorted(source_dir.glob("*.json")):
        symbol = symbol_from_path(path)
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
    detections: list[dict[str, Any]] = []
    symbol_stats: list[dict[str, Any]] = []
    for path in paths:
        try:
            df = load_market_stats_symbol(path)
            rows, stats = scan_symbol(df, detector_config=config)
            detections.extend(rows)
            symbol_stats.append({"symbol": symbol_from_path(path), "detections": len(rows), **stats})
        except Exception as exc:
            symbol_stats.append({"symbol": symbol_from_path(path), "detections": 0, "error": str(exc)})
    for i, row in enumerate(detections):
        row["detection_id"] = f"{PATTERN_KEY}:{i + 1:06d}"
        row["event_id"] = row["detection_id"]
    detections, regime_meta = classify_market_regimes(detections, index_db=index_db, index_symbol=index_symbol)
    market_group_meta = attach_current_market_groups(detections)
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
        "experiment_status": "candidate_flag_like_family_not_final",
    }


def _median(rows: Sequence[Mapping[str, Any]], key: str) -> Optional[float]:
    vals = [float(row[key]) for row in rows if row.get(key) is not None and math.isfinite(float(row[key]))]
    return round(float(np.median(vals)), 2) if vals else None


def _rate(rows: Sequence[Mapping[str, Any]], key: str) -> Optional[float]:
    vals = [row.get(key) for row in rows if row.get(key) is not None]
    return round(sum(1 for val in vals if val is True) / len(vals) * 100.0, 2) if vals else None


def _group_stats(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    evals = [row for row in rows if row.get("mfe_pct") is not None]
    return {
        "n": len(rows),
        "evaluated_n": len(evals),
        "median_mfe_pct": _median(evals, "mfe_pct"),
        "median_mae_pct": _median(evals, "mae_pct"),
        "target_hit_rate": _rate(evals, "target_hit"),
        "failure_5pct_rate": _rate(evals, "failure_5pct"),
        "target_first_before_adverse_5pct_rate": _rate(evals, "target_first_before_adverse_5pct"),
        "median_target_dist_pct": _median(evals, "target_dist_pct"),
        "median_quality_score": _median(rows, "pattern_quality_score"),
    }


def summarize(scan: Mapping[str, Any], path_rows: Optional[Sequence[Mapping[str, Any]]] = None) -> dict[str, Any]:
    rows = list(scan.get("detections") or [])
    stats: dict[str, Any] = {
        "generated_at": _utc_now(),
        "pattern_key": PATTERN_KEY,
        "symbols_scanned": int(scan.get("symbols_scanned") or 0),
        "detection_count": len(rows),
        "variant_table": {
            "bull_pennant": _group_stats([row for row in rows if row.get("variant") == "bull_pennant"]),
            "bear_pennant": _group_stats([row for row in rows if row.get("variant") == "bear_pennant"]),
        },
        "all": _group_stats(rows),
        "quality_table": {
            tier: _group_stats([row for row in rows if row.get("pattern_quality_tier") == tier])
            for tier in ("clean", "usable", "loose")
        },
        "experiment_note": "Pennants use converging trendlines plus a steep flagpole. This is a candidate scanner, not a final chapter gate.",
    }
    _add_sensitivity_tables(stats, scan)
    events = pd.DataFrame(rows)
    path = pd.DataFrame(list(path_rows or []))
    if not events.empty:
        if "event_id" not in events.columns:
            events["event_id"] = events["detection_id"]
        sensitivity = target_sensitivity(PatternArtifacts(PATTERN_KEY, events.copy(), path), PATTERN_KEY)
        for variant in ("bull_pennant", "bear_pennant"):
            subgroup = events[events["variant"] == variant].copy()
            if not subgroup.empty:
                sensitivity.extend(target_sensitivity(PatternArtifacts(variant, subgroup, path), variant))
        stats["target_family_sensitivity"] = sensitivity
    else:
        stats["target_family_sensitivity"] = []
    return stats


PENNANT_EVENT_FIELDS = sorted(set(EVENT_FIELDS + ["event_id", "compression_ratio", "pennant_to_pole_pct"]))


def write_artifacts(scan: dict[str, Any], out_dir: Path, *, source_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    _enrich_events(scan, source_dir=source_dir)
    path_rows = _path_rows(scan, source_dir=source_dir, horizon_bars=120)
    stats = summarize(scan, path_rows)

    detections = list(scan.get("detections") or [])
    events_path = out_dir / "events.csv"
    path_path = out_dir / "post_breakout_path.csv"
    stats_path = out_dir / "statistics.json"
    scan_path = out_dir / "scan_summary.json"
    events_df = pd.DataFrame(detections)
    event_columns = [col for col in PENNANT_EVENT_FIELDS if col in events_df.columns] if detections else PENNANT_EVENT_FIELDS
    events_df.to_csv(events_path, index=False, columns=event_columns)
    pd.DataFrame(path_rows).to_csv(path_path, index=False)
    _write_json(stats_path, stats)
    _write_json(scan_path, scan)
    return {"events": events_path, "path": path_path, "statistics": stats_path, "scan_summary": scan_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run candidate Pennant scanner.")
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--limit-symbols", type=int, default=None)
    parser.add_argument("--require-volume-confirmed", action="store_true")
    args = parser.parse_args()
    config = PennantDetectorConfig(require_volume_confirmed=bool(args.require_volume_confirmed))
    scan = scan_market_stats(Path(args.source_dir), limit_symbols=args.limit_symbols, detector_config=config)
    paths = write_artifacts(scan, Path(args.out_dir), source_dir=Path(args.source_dir))
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
