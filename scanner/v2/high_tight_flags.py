"""High-and-Tight Flag scanner for the Flag-like Family.

This detector is deliberately separate from ordinary Flags and Pennants.  The
source morphology requires an exceptional prior advance, then a high-level
consolidation, then an upward continuation breakout.  It is therefore not a
branch of the ordinary Bull Flag scanner.
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
from ..research_support_analysis import PatternArtifacts, target_sensitivity
from .bull_flags_monograph import _add_sensitivity_tables, _enrich_events
from .flags_experiment import (
    DEFAULT_INDEX_DB,
    DEFAULT_INDEX_SYMBOL,
    EVENT_FIELDS,
    _evaluate_detection,
    _path_rows,
    _rate,
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


PATTERN_KEY = "high_tight_flags"
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/high_tight_flags")


@dataclass(frozen=True)
class HighTightFlagConfig:
    advance_lookback_bars: int = 45
    min_prior_advance_pct: float = 90.0
    min_prior_slope_deg: float = 18.0
    consolidation_min_bars: int = 5
    consolidation_max_bars: int = 25
    pullback_min_pct: float = 3.0
    pullback_max_pct: float = 35.0
    consolidation_height_max_pct: float = 38.0
    breakout_search_bars: int = 12
    breakout_threshold: float = 0.0075
    breakout_volume_confirm_ratio: float = 1.2
    require_volume_confirmed: bool = False
    max_events_per_symbol: int = 8
    breakout_cooldown_bars: int = 30

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]] = None) -> "HighTightFlagConfig":
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


def _median(rows: Sequence[Mapping[str, Any]], key: str) -> Optional[float]:
    vals = [float(row[key]) for row in rows if row.get(key) is not None and math.isfinite(float(row[key]))]
    return round(float(np.median(vals)), 2) if vals else None


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


class HighTightFlagDetector:
    def __init__(self, config: Optional[HighTightFlagConfig | Mapping[str, Any]] = None) -> None:
        self.config = config if isinstance(config, HighTightFlagConfig) else HighTightFlagConfig.from_mapping(config)

    def _breakout(
        self,
        df: pd.DataFrame,
        *,
        start_idx: int,
        boundary: float,
    ) -> Tuple[Optional[int], Optional[float], bool, Optional[float]]:
        for idx in range(start_idx, min(len(df), start_idx + self.config.breakout_search_bars)):
            close = _safe_float(df.iloc[idx].get("close"))
            if close is None or boundary <= 0:
                continue
            if close <= boundary * (1.0 + self.config.breakout_threshold):
                continue
            volume_ratio = _safe_float(df.iloc[idx].get("volume_ratio"))
            volume_confirmed = bool(volume_ratio is not None and volume_ratio >= self.config.breakout_volume_confirm_ratio)
            if self.config.require_volume_confirmed and not volume_confirmed:
                continue
            return idx, close, volume_confirmed, volume_ratio
        return None, None, False, None

    def scan_from_peak(self, df: pd.DataFrame, peak_idx: int) -> Optional[dict[str, Any]]:
        if peak_idx < 5 or peak_idx + self.config.consolidation_min_bars + 1 >= len(df):
            return None
        lb = max(0, peak_idx - self.config.advance_lookback_bars)
        prior = df.iloc[lb : peak_idx + 1]
        if len(prior) < 10:
            return None
        lows = prior["low"].to_numpy(dtype=float, copy=False)
        if lows.size == 0 or np.all(np.isnan(lows)):
            return None
        rel_low = int(np.nanargmin(lows))
        pole_idx = lb + rel_low
        pole_price = float(lows[rel_low])
        peak_price = float(df.iloc[peak_idx]["high"])
        if pole_price <= 0 or peak_price <= 0:
            return None
        advance_pct = (peak_price - pole_price) / pole_price * 100.0
        slope_deg = _slope_degrees(pole_idx, pole_price, peak_idx, peak_price)
        if advance_pct < self.config.min_prior_advance_pct or slope_deg < self.config.min_prior_slope_deg:
            return None
        if peak_price < float(df.iloc[max(0, peak_idx - 5) : peak_idx + 1]["high"].max()):
            return None

        for width in range(self.config.consolidation_min_bars, self.config.consolidation_max_bars + 1):
            start = peak_idx + 1
            end = peak_idx + width
            if end + 1 >= len(df):
                break
            body = df.iloc[start : end + 1]
            if body.empty:
                continue
            body_high = float(body["high"].max())
            body_low = float(body["low"].min())
            high_ref = max(peak_price, body_high)
            if high_ref <= 0:
                continue
            pullback_pct = (high_ref - body_low) / high_ref * 100.0
            body_height_pct = (body_high - body_low) / high_ref * 100.0
            if not (self.config.pullback_min_pct <= pullback_pct <= self.config.pullback_max_pct):
                continue
            if body_height_pct > self.config.consolidation_height_max_pct:
                continue
            if body_high > peak_price * 1.25:
                continue
            breakout_idx, breakout_price, volume_confirmed, breakout_volume_ratio = self._breakout(
                df,
                start_idx=end + 1,
                boundary=high_ref,
            )
            if breakout_idx is None or breakout_price is None:
                continue
            pole_height_abs = peak_price - pole_price
            target_price = float(breakout_price) + pole_height_abs
            body_volume = pd.to_numeric(body.get("volume"), errors="coerce").dropna()
            prior_volume = pd.to_numeric(prior.get("volume"), errors="coerce").dropna()
            volume_contracts = bool(not body_volume.empty and not prior_volume.empty and float(body_volume.median()) <= float(prior_volume.median()))
            quality_score = 65
            if advance_pct >= 100:
                quality_score += 10
            if pullback_pct <= 25:
                quality_score += 8
            if width <= 15:
                quality_score += 7
            if volume_contracts:
                quality_score += 5
            if volume_confirmed:
                quality_score += 5
            quality_score = min(100, int(quality_score))
            return {
                "formation_start_idx": int(start),
                "formation_end_idx": int(end),
                "formation_start_date": str(pd.Timestamp(df.iloc[start]["date"]).date()),
                "formation_end_date": str(pd.Timestamp(df.iloc[end]["date"]).date()),
                "breakout_idx": int(breakout_idx),
                "breakout_date": str(pd.Timestamp(df.iloc[int(breakout_idx)]["date"]).date()),
                "breakout_direction": "up",
                "breakout_price": round(float(breakout_price), 4),
                "target_price": round(float(target_price), 4),
                "pattern_width_bars": int(width),
                "pattern_height_pct": round(float(body_height_pct), 2),
                "variant": "high_tight_flag",
                "volume_confirmed": volume_confirmed,
                "volume_contracts": volume_contracts,
                "breakout_volume_ratio": round(float(breakout_volume_ratio), 4) if breakout_volume_ratio is not None else None,
                "pattern_quality_score": quality_score,
                "pattern_quality_tier": "clean" if quality_score >= 85 else ("usable" if quality_score >= 75 else "loose"),
                "upper_slope_deg": 0.0,
                "lower_slope_deg": 0.0,
                "slope_gap_deg": 0.0,
                "compression_ratio": round(float(body_height_pct / max(advance_pct, 1.0)), 4),
                "flag_to_pole_pct": round(float(body_height_pct / max(advance_pct, 1.0) * 100.0), 2),
                "consolidation_pullback_pct": round(float(pullback_pct), 2),
                "flag_upper_idx0": int(start),
                "flag_upper_price0": round(float(high_ref), 4),
                "flag_upper_slope_per_bar": 0.0,
                "flag_lower_idx0": int(start),
                "flag_lower_price0": round(float(body_low), 4),
                "flag_lower_slope_per_bar": 0.0,
                "flag_upper_breakout_value": round(float(high_ref), 4),
                "flag_lower_breakout_value": round(float(body_low), 4),
                "pole_idx": int(pole_idx),
                "pole_price": round(float(pole_price), 4),
                "pole_move_pct": round(float(advance_pct), 2),
                "pole_slope_deg": round(float(slope_deg), 2),
                "pole_bars": int(peak_idx - pole_idx + 1),
            }
        return None


def scan_symbol(
    df_raw: pd.DataFrame,
    *,
    max_events_per_symbol: Optional[int] = None,
    detector_config: Optional[HighTightFlagConfig | Mapping[str, Any]] = None,
) -> Tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(df_raw) < 120:
        return [], {"rows": int(len(df_raw)), "skipped": "too_few_rows"}
    config = detector_config if isinstance(detector_config, HighTightFlagConfig) else HighTightFlagConfig.from_mapping(detector_config)
    max_events = int(max_events_per_symbol if max_events_per_symbol is not None else config.max_events_per_symbol)
    df, norm_stats = OHLCVNormalizer().normalize(df_raw)
    detector = HighTightFlagDetector(config)
    out: list[dict[str, Any]] = []
    used_breakouts: list[int] = []
    symbol = str(df.iloc[0]["symbol"])
    for peak_idx in range(config.advance_lookback_bars, len(df) - config.consolidation_min_bars - config.breakout_search_bars):
        candidate = detector.scan_from_peak(df, peak_idx)
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
    return out, {"rows": int(len(df)), "normalizer": norm_stats, "detector_config": config.to_dict()}


def scan_market_stats(
    source_dir: Path,
    *,
    limit_symbols: Optional[int] = None,
    index_db: Path = DEFAULT_INDEX_DB,
    index_symbol: str = DEFAULT_INDEX_SYMBOL,
    allowed_symbols: Optional[Sequence[str]] = None,
    detector_config: Optional[HighTightFlagConfig | Mapping[str, Any]] = None,
) -> dict[str, Any]:
    config = detector_config if isinstance(detector_config, HighTightFlagConfig) else HighTightFlagConfig.from_mapping(detector_config)
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
        "experiment_status": "source_grounded_high_tight_flag_candidate",
    }


def summarize(scan: Mapping[str, Any], path_rows: Optional[Sequence[Mapping[str, Any]]] = None) -> dict[str, Any]:
    rows = list(scan.get("detections") or [])
    stats: dict[str, Any] = {
        "generated_at": _utc_now(),
        "pattern_key": PATTERN_KEY,
        "symbols_scanned": int(scan.get("symbols_scanned") or 0),
        "detection_count": len(rows),
        "all": _group_stats(rows),
        "variant_table": {"high_tight_flag": _group_stats(rows)},
        "quality_table": {tier: _group_stats([row for row in rows if row.get("pattern_quality_tier") == tier]) for tier in ("clean", "usable", "loose")},
        "experiment_note": "High-and-Tight Flags use an exceptional prior advance and high-level consolidation. The source target is half the prior move; full-pole target rows are retained as stress diagnostics.",
    }
    _add_sensitivity_tables(stats, scan)
    events = pd.DataFrame(rows)
    path = pd.DataFrame(list(path_rows or []))
    if not events.empty:
        stats["target_family_sensitivity"] = target_sensitivity(PatternArtifacts(PATTERN_KEY, events.copy(), path), PATTERN_KEY)
    else:
        stats["target_family_sensitivity"] = []
    return stats


HIGH_TIGHT_FLAG_EVENT_FIELDS = sorted(set(EVENT_FIELDS + ["event_id", "compression_ratio", "consolidation_pullback_pct", "volume_contracts"]))


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
    event_columns = [col for col in HIGH_TIGHT_FLAG_EVENT_FIELDS if col in events_df.columns] if detections else HIGH_TIGHT_FLAG_EVENT_FIELDS
    events_df.to_csv(events_path, index=False, columns=event_columns)
    pd.DataFrame(path_rows).to_csv(path_path, index=False)
    _write_json(stats_path, stats)
    _write_json(scan_path, scan)
    return {"events": events_path, "path": path_path, "statistics": stats_path, "scan_summary": scan_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run High-and-Tight Flag scanner.")
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--limit-symbols", type=int, default=None)
    parser.add_argument("--require-volume-confirmed", action="store_true")
    args = parser.parse_args()
    config = HighTightFlagConfig(require_volume_confirmed=bool(args.require_volume_confirmed))
    scan = scan_market_stats(Path(args.source_dir), limit_symbols=args.limit_symbols, detector_config=config)
    paths = write_artifacts(scan, Path(args.out_dir), source_dir=Path(args.source_dir))
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
