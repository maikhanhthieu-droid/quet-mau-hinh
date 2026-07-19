"""Inside Day scanner.

Inside Day is a two-bar compression pattern: the second bar's range is strictly
inside the prior bar's range, and the event is confirmed only when price closes
outside the inside bar.  This module keeps Inside Day separate from the pivot
families because it is a short-horizon, event-like compression pattern.
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


INSIDE_DAY = "inside_day"
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/inside_day_family")


@dataclass(frozen=True)
class InsideDayConfig:
    confirmation_search_bars: int = 2
    breakout_threshold: float = 0.0
    range_ratio_min: float = 0.10
    range_ratio_max: float = 0.99
    tight_range_ratio: float = 0.50
    very_tight_range_ratio: float = 0.30
    prior_trend_lookback_bars: int = 10
    prior_trend_min_abs_pct: float = 2.0
    max_events_per_symbol: int = 12
    breakout_cooldown_bars: int = 18

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]] = None) -> "InsideDayConfig":
        if value is None:
            return cls()
        allowed = {field.name for field in fields(cls)}
        return cls(**{key: item for key, item in value.items() if key in allowed})

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _variant_for(df: pd.DataFrame, idx: int, range_ratio: float, config: InsideDayConfig) -> tuple[str, int]:
    consecutive = 1
    cursor = idx - 1
    while cursor >= 1:
        today = df.iloc[cursor]
        prev = df.iloc[cursor - 1]
        if float(today["high"]) < float(prev["high"]) and float(today["low"]) > float(prev["low"]):
            consecutive += 1
            cursor -= 1
        else:
            break
    if consecutive >= 2:
        return "consecutive_inside_days", consecutive
    if range_ratio <= config.very_tight_range_ratio:
        return "very_tight_inside_day", consecutive
    if range_ratio <= config.tight_range_ratio:
        return "tight_inside_day", consecutive
    return "standard_inside_day", consecutive


class InsideDayDetector:
    def __init__(self, config: Optional[InsideDayConfig | Mapping[str, Any]] = None) -> None:
        self.config = config if isinstance(config, InsideDayConfig) else InsideDayConfig.from_mapping(config)

    def _breakout_candidate(self, df: pd.DataFrame, idx: int) -> Optional[tuple[int, str, float]]:
        inside_high = float(df.iloc[idx]["high"])
        inside_low = float(df.iloc[idx]["low"])
        upper = inside_high * (1.0 + self.config.breakout_threshold)
        lower = inside_low * (1.0 - self.config.breakout_threshold)
        for j in range(idx + 1, min(len(df), idx + 1 + self.config.confirmation_search_bars)):
            close = _safe_float(df.iloc[j].get("close"))
            if close is None:
                continue
            if close > upper:
                return j, "up", float(close)
            if close < lower:
                return j, "down", float(close)
        return None

    def scan(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        used: list[int] = []
        for idx in range(1, len(df) - 1):
            prev = df.iloc[idx - 1]
            today = df.iloc[idx]
            prev_high = _safe_float(prev.get("high"))
            prev_low = _safe_float(prev.get("low"))
            high = _safe_float(today.get("high"))
            low = _safe_float(today.get("low"))
            if None in (prev_high, prev_low, high, low) or prev_high <= prev_low:
                continue
            if not (float(high) < float(prev_high) and float(low) > float(prev_low)):
                continue
            prior_range = float(prev_high) - float(prev_low)
            inside_range = float(high) - float(low)
            if inside_range <= 0:
                continue
            range_ratio = inside_range / prior_range
            if range_ratio < self.config.range_ratio_min or range_ratio > self.config.range_ratio_max:
                continue
            breakout = self._breakout_candidate(df, idx)
            if breakout is None:
                continue
            breakout_idx, direction, breakout_price = breakout
            if any(abs(breakout_idx - used_idx) <= self.config.breakout_cooldown_bars for used_idx in used):
                continue
            variant, consecutive_count = _variant_for(df, idx, range_ratio, self.config)
            height_abs = inside_range
            target_price = breakout_price + height_abs if direction == "up" else breakout_price - height_abs
            if target_price <= 0:
                continue
            target_dist_pct = abs(target_price - breakout_price) / breakout_price * 100.0
            prior_trend = _prior_trend_pct(df, idx - 1, self.config.prior_trend_lookback_bars)
            volume_ratio = _rolling_volume_ratio(df, idx, lookback=20)
            volume_contracts = volume_ratio is not None and volume_ratio < 0.85
            mother_range_pct = prior_range / max(float(prev.get("close") or prev_high), 1e-9) * 100.0
            inside_range_pct = inside_range / max(float(today.get("close") or high), 1e-9) * 100.0
            mother_breakout = (
                (direction == "up" and breakout_price > float(prev_high))
                or (direction == "down" and breakout_price < float(prev_low))
            )
            score = 34.0
            score += _score_band(range_ratio, good=0.30, weak=0.99, reverse=True, weight=0.22)
            score += _score_band(abs(float(prior_trend or 0.0)), good=6.0, weak=self.config.prior_trend_min_abs_pct, weight=0.12)
            score += _score_band(float(consecutive_count), good=2.0, weak=1.0, weight=0.12)
            score += 8.0 if volume_contracts else 2.0
            score += 8.0 if mother_breakout else 0.0
            score += _score_band(float(target_dist_pct), good=1.2, weak=8.0, reverse=True, weight=0.10)
            score = int(max(0, min(100, round(score))))
            used.append(breakout_idx)
            rows.append(
                {
                    "symbol": str(df.iloc[0]["symbol"]),
                    "pattern_key": INSIDE_DAY,
                    "variant": variant,
                    "formation_start_idx": int(idx - 1),
                    "formation_end_idx": int(idx),
                    "formation_start_date": str(pd.Timestamp(df.iloc[idx - 1]["date"]).date()),
                    "formation_end_date": str(pd.Timestamp(df.iloc[idx]["date"]).date()),
                    "breakout_idx": int(breakout_idx),
                    "breakout_date": str(pd.Timestamp(df.iloc[breakout_idx]["date"]).date()),
                    "breakout_direction": direction,
                    "breakout_price": round(float(breakout_price), 4),
                    "target_price": round(float(target_price), 4),
                    "target_dist_pct": round(float(target_dist_pct), 2),
                    "inside_day_high": round(float(high), 4),
                    "inside_day_low": round(float(low), 4),
                    "mother_bar_high": round(float(prev_high), 4),
                    "mother_bar_low": round(float(prev_low), 4),
                    "pattern_width_bars": 2,
                    "pattern_height_pct": round(float(inside_range_pct), 2),
                    "mother_range_pct": round(float(mother_range_pct), 2),
                    "inside_range_pct": round(float(inside_range_pct), 2),
                    "range_ratio": round(float(range_ratio), 4),
                    "consecutive_inside_count": int(consecutive_count),
                    "prior_trend_pct": round(float(prior_trend), 2) if prior_trend is not None else None,
                    "volume_ratio_20": volume_ratio,
                    "volume_contracts": bool(volume_contracts),
                    "mother_bar_breakout": bool(mother_breakout),
                    "breakout_lag_bars": int(breakout_idx - idx),
                    "pattern_quality_score": score,
                    "pattern_quality_tier": "clean" if score >= 76 else ("usable" if score >= 60 else "loose"),
                }
            )
            if len(rows) >= self.config.max_events_per_symbol:
                break
        return rows


def scan_symbol(
    df_raw: pd.DataFrame,
    *,
    detector_config: Optional[InsideDayConfig | Mapping[str, Any]] = None,
    max_events_per_symbol: Optional[int] = None,
) -> Tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(df_raw) < 80:
        return [], {"rows": int(len(df_raw)), "skipped": "too_few_rows"}
    config = detector_config if isinstance(detector_config, InsideDayConfig) else InsideDayConfig.from_mapping(detector_config)
    if max_events_per_symbol is not None:
        config = InsideDayConfig.from_mapping({**config.to_dict(), "max_events_per_symbol": int(max_events_per_symbol)})
    df, norm_stats = OHLCVNormalizer().normalize(df_raw)
    rows = InsideDayDetector(config).scan(df)
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
        score += _score_band(_safe_float(row.get("range_ratio")), good=0.30, weak=0.99, reverse=True, weight=0.28)
        score += _score_band(_safe_float(row.get("consecutive_inside_count")), good=2.0, weak=1.0, weight=0.14)
        score += _score_band(abs(float(row.get("prior_trend_pct") or 0.0)), good=6.0, weak=2.0, weight=0.12)
        if _truthy(row.get("volume_contracts")):
            score += 10.0
        if _truthy(row.get("mother_bar_breakout")):
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
        if not _truthy(row.get("mother_bar_breakout")):
            reasons.append("not_mother_bar_breakout")
        if not _truthy(row.get("volume_contracts")):
            reasons.append("no_volume_contraction")
        if float(row.get("range_ratio") or 1.0) > 0.75:
            reasons.append("wide_inside_day")
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
        "median_range_ratio": _median([row.get("range_ratio") for row in rows]),
        "median_inside_range_pct": _median([row.get("inside_range_pct") for row in rows]),
    }


def _group_table(rows: Sequence[Mapping[str, Any]], column: str, labels: Sequence[str]) -> Dict[str, Any]:
    return {label: _group_stats([row for row in rows if str(row.get(column) or "unknown") == label]) for label in labels}


def summarize(scan: Mapping[str, Any]) -> Dict[str, Any]:
    rows = list(scan.get("detections") or [])
    evals = [row for row in rows if row.get("mfe_pct") is not None]
    return {
        "generated_at": _utc_now(),
        "pattern_key": INSIDE_DAY,
        "symbols_scanned": int(scan.get("symbols_scanned") or 0),
        "detection_count": len(rows),
        "evaluated_count": len(evals),
        **_group_stats(rows),
        "variant_table": _group_table(rows, "variant", ("standard_inside_day", "tight_inside_day", "very_tight_inside_day", "consecutive_inside_days")),
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
            "range_ratio": _quantiles([row.get("range_ratio") for row in rows]),
            "target_days": _quantiles([row.get("days_to_target") for row in evals]),
        },
        "experiment_note": "Inside Day Family uses two-bar range-compression logic: strict inside bar, close confirmation, then short post-breakout path measurement.",
    }


def _add_target_calibration(stats: Dict[str, Any], scan: Mapping[str, Any], path_rows: Sequence[Mapping[str, Any]]) -> None:
    events = pd.DataFrame(list(scan.get("detections") or []))
    path = pd.DataFrame(list(path_rows))
    if events.empty:
        stats["target_family_sensitivity"] = []
        stats["target_calibration_decision"] = None
        return
    if "event_id" not in events.columns and "detection_id" in events.columns:
        events["event_id"] = events["detection_id"]
    sensitivity = target_sensitivity(PatternArtifacts(INSIDE_DAY, events, path), INSIDE_DAY, horizon_days=60)
    stats["target_family_sensitivity"] = sensitivity
    stats["target_calibration_decision"] = (build_target_calibration_decisions(sensitivity, family_labels=(INSIDE_DAY,)) or [None])[0]
    stats["target_family"] = {"half_inside_range": 0.5, "full_inside_range": 1.0, "two_x_inside_range": 2.0}


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
    "range_ratio",
    "inside_range_pct",
    "mother_range_pct",
    "inside_day_high",
    "inside_day_low",
    "mother_bar_high",
    "mother_bar_low",
    "consecutive_inside_count",
    "prior_trend_pct",
    "volume_ratio_20",
    "volume_contracts",
    "mother_bar_breakout",
    "breakout_lag_bars",
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


def scan_inside_day_db(
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
    config = InsideDayConfig.from_mapping(detector_config)
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
                    series_by_symbol[symbol] = OHLCVNormalizer().normalize(frame)[0]
                detections.extend(rows)
                symbol_stats.append({"symbol": symbol, "detections": len(rows), **stats})
            except Exception as exc:
                symbol_stats.append({"symbol": symbol, "detections": 0, "error": str(exc)})
    finally:
        conn.close()
    for i, row in enumerate(detections):
        row["detection_id"] = f"{INSIDE_DAY}:{i + 1:06d}"
    detections, regime_meta = classify_market_regimes(detections, index_db=index_db, index_symbol=index_symbol)
    market_group_meta = attach_current_market_groups(detections)
    scan: dict[str, Any] = {
        "generated_at": _utc_now(),
        "source": "Market Cache latest.sqlite stock_price_history",
        "db_path": str(db_path),
        "pattern_key": INSIDE_DAY,
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
    stats = summarize(scan)
    stats["source"] = scan["source"]
    stats["db_source_meta"] = _db_meta(db_path)
    stats["detector_config"] = config.to_dict()
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
    parser = argparse.ArgumentParser(description="Run Inside Day Family scanner against Market Cache latest.sqlite.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--market-stats-json", default=str(DEFAULT_MARKET_STATS_JSON))
    parser.add_argument("--limit-symbols", type=int, default=None)
    args = parser.parse_args()
    active_meta = _load_active_symbols(Path(args.market_stats_json) if args.market_stats_json else None)
    active_symbols = active_meta.get("active_symbols") if active_meta.get("enabled") else None
    paths = scan_inside_day_db(
        db_path=Path(args.db),
        out_dir=Path(args.out_dir) / INSIDE_DAY / "db_active",
        allowed_symbols=active_symbols,
        limit_symbols=args.limit_symbols,
    )
    print(json.dumps({"status": "PASS", "outputs": {key: str(value) for key, value in paths.items()}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
