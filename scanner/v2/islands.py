"""Island Family scanner for Scanner V2.

Island patterns are gap-defined reversal formations: price is isolated by a
true gap on the way into the island and a true opposite gap on the way out.
This module deliberately reuses only shared data/enrichment helpers. The
geometry is family-specific because Island quality depends on true gap
isolation, island duration, prior trend, and post-gap confirmation.
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
from typing import Any, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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


ISLAND_REVERSALS = "island_reversals"
ISLANDS_LONG = "islands_long"
ISLAND_PATTERNS = (ISLAND_REVERSALS, ISLANDS_LONG)
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/island_family")


@dataclass(frozen=True)
class IslandConfig:
    min_gap_pct: float = 0.50
    max_gap_pct: float = 12.0
    min_regular_bars: int = 1
    max_regular_bars: int = 10
    max_long_bars: int = 40
    prior_trend_lookback_bars: int = 20
    min_prior_trend_pct: float = 3.0
    evaluation_bars: int = 120
    min_volume_ratio: float = 0.0
    cooldown_bars: int = 20
    max_events_per_symbol: int = 12

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]] = None) -> "IslandConfig":
        if value is None:
            return cls()
        allowed = {field.name for field in fields(cls)}
        return cls(**{key: item for key, item in value.items() if key in allowed})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _csv_fields(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    preferred = [
        "event_id",
        "detection_id",
        "pattern_id",
        "pattern_name",
        "symbol",
        "variant",
        "formation_start_date",
        "formation_end_date",
        "breakout_date",
        "breakout_idx",
        "breakout_direction",
        "breakout_price",
        "target_price",
        "target_dist_pct",
        "pattern_width_bars",
        "pattern_height_pct",
        "publication_quality_score",
        "publication_quality_tier",
        "mfe_pct",
        "mae_pct",
        "target_hit",
        "failure_5pct",
        "target_first_before_adverse_5pct",
    ]
    keys: set[str] = set()
    for row in rows:
        keys.update(str(key) for key in row.keys())
    return [key for key in preferred if key in keys] + sorted(keys.difference(preferred))


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


def _volume_ratio(df: pd.DataFrame, idx: int, lookback: int = 20) -> Optional[float]:
    volume = _safe_float(df.iloc[int(idx)].get("volume")) if 0 <= int(idx) < len(df) else None
    if volume is None:
        return None
    left = max(0, int(idx) - lookback)
    base = pd.to_numeric(df.iloc[left:int(idx)]["volume"], errors="coerce").dropna()
    if base.empty or float(base.mean()) <= 0:
        return None
    return round(float(volume / base.mean()), 3)


def _prior_trend_pct(df: pd.DataFrame, idx: int, lookback: int) -> Optional[float]:
    left = max(0, int(idx) - int(lookback))
    if int(idx) <= left:
        return None
    anchor = _safe_float(df.iloc[left].get("close"))
    current = _safe_float(df.iloc[int(idx) - 1].get("close"))
    if anchor is None or current is None or anchor <= 0:
        return None
    return (current - anchor) / anchor * 100.0


def _gap_up(df: pd.DataFrame, idx: int, cfg: IslandConfig) -> Optional[dict[str, float]]:
    if idx <= 0 or idx >= len(df):
        return None
    prev_high = _safe_float(df.iloc[idx - 1].get("high"))
    cur_low = _safe_float(df.iloc[idx].get("low"))
    if prev_high is None or cur_low is None or prev_high <= 0:
        return None
    gap_pct = (cur_low - prev_high) / prev_high * 100.0
    if gap_pct < cfg.min_gap_pct or gap_pct > cfg.max_gap_pct:
        return None
    return {"gap_pct": float(gap_pct), "mainland_edge": float(prev_high), "island_edge": float(cur_low)}


def _gap_down(df: pd.DataFrame, idx: int, cfg: IslandConfig) -> Optional[dict[str, float]]:
    if idx <= 0 or idx >= len(df):
        return None
    prev_low = _safe_float(df.iloc[idx - 1].get("low"))
    cur_high = _safe_float(df.iloc[idx].get("high"))
    if prev_low is None or cur_high is None or prev_low <= 0:
        return None
    gap_pct = (prev_low - cur_high) / prev_low * 100.0
    if gap_pct < cfg.min_gap_pct or gap_pct > cfg.max_gap_pct:
        return None
    return {"gap_pct": float(gap_pct), "mainland_edge": float(prev_low), "island_edge": float(cur_high)}


def _evaluate_island(df: pd.DataFrame, row: Mapping[str, Any], *, lookahead: int) -> dict[str, Any]:
    idx = int(row["breakout_idx"])
    direction = 1 if row["breakout_direction"] == "up" else -1
    breakout_price = float(row["breakout_price"])
    target = float(row["target_price"])
    future = df.iloc[idx + 1 : min(len(df), idx + 1 + int(lookahead))]
    if future.empty or breakout_price <= 0:
        return {
            "evaluated_bars": 0,
            "mfe_pct": None,
            "mae_pct": None,
            "target_hit": None,
            "failure_5pct": None,
            "target_first_before_adverse_5pct": None,
            "time_to_target_bars": None,
        }
    if direction == 1:
        high = pd.to_numeric(future["high"], errors="coerce")
        low = pd.to_numeric(future["low"], errors="coerce")
        mfe_series = (high - breakout_price) / breakout_price * 100.0
        mae_series = (breakout_price - low) / breakout_price * 100.0
        target_series = high >= target
    else:
        low = pd.to_numeric(future["low"], errors="coerce")
        high = pd.to_numeric(future["high"], errors="coerce")
        mfe_series = (breakout_price - low) / breakout_price * 100.0
        mae_series = (high - breakout_price) / breakout_price * 100.0
        target_series = low <= target
    adverse_series = mae_series >= 5.0
    target_hit = bool(target_series.fillna(False).any())
    first_target = int(np.argmax(target_series.to_numpy())) + 1 if target_hit else None
    adverse_hit = bool(adverse_series.fillna(False).any())
    first_adverse = int(np.argmax(adverse_series.to_numpy())) + 1 if adverse_hit else None
    return {
        "evaluated_bars": int(len(future)),
        "mfe_pct": round(float(mfe_series.max()), 2) if not mfe_series.dropna().empty else None,
        "mae_pct": round(float(mae_series.max()), 2) if not mae_series.dropna().empty else None,
        "target_hit": target_hit,
        "failure_5pct": bool(float(mfe_series.max()) < 5.0) if not mfe_series.dropna().empty else None,
        "target_first_before_adverse_5pct": bool(target_hit and (first_adverse is None or int(first_target or 10**9) < first_adverse)),
        "time_to_target_bars": first_target,
    }


def _score_quality(*, width: int, gap1_pct: float, gap2_pct: float, prior_signed_pct: float, volume_ratio: Optional[float]) -> float:
    gap_score = min(100.0, max(45.0, (min(gap1_pct, gap2_pct) / 2.0) * 60.0 + 35.0))
    duration_score = 100.0 if 1 <= width <= 3 else (78.0 if width <= 7 else (58.0 if width <= 10 else 42.0))
    trend_score = min(100.0, max(35.0, prior_signed_pct / 12.0 * 100.0))
    volume_score = 55.0 if volume_ratio is None else min(100.0, max(45.0, float(volume_ratio) / 1.4 * 100.0))
    return round(0.32 * gap_score + 0.26 * duration_score + 0.24 * trend_score + 0.18 * volume_score, 2)


def _quality_tier(score: float, *, width: int) -> str:
    if width > 10:
        return "data_limited" if score < 78 else "standard"
    if score >= 86:
        return "premium"
    if score >= 72:
        return "standard"
    if score >= 58:
        return "loose"
    return "data_limited"


def scan_symbol_islands(df: pd.DataFrame, *, symbol: str, config: IslandConfig) -> list[dict[str, Any]]:
    if df.empty or len(df) < config.prior_trend_lookback_bars + config.min_regular_bars + 3:
        return []
    df = df.sort_values("date").reset_index(drop=True)
    detections: list[dict[str, Any]] = []
    last_breakout_idx = -10**9
    for i in range(max(1, config.prior_trend_lookback_bars), len(df) - 2):
        first_up = _gap_up(df, i, config)
        first_down = _gap_down(df, i, config)
        if not first_up and not first_down:
            continue
        for j in range(i + config.min_regular_bars, min(len(df), i + config.max_long_bars + 1)):
            if j - i < config.min_regular_bars:
                continue
            width = j - i
            if first_up:
                second = _gap_down(df, j, config)
                variant = "island_top"
                direction = "down"
                prior = _prior_trend_pct(df, i, config.prior_trend_lookback_bars)
                prior_signed = float(prior or 0.0)
            else:
                second = _gap_up(df, j, config)
                variant = "island_bottom"
                direction = "up"
                prior = _prior_trend_pct(df, i, config.prior_trend_lookback_bars)
                prior_signed = -float(prior or 0.0)
            if second is None or prior_signed < config.min_prior_trend_pct:
                continue
            if j - last_breakout_idx <= config.cooldown_bars:
                continue
            island = df.iloc[i:j]
            if island.empty:
                continue
            island_high = float(pd.to_numeric(island["high"], errors="coerce").max())
            island_low = float(pd.to_numeric(island["low"], errors="coerce").min())
            breakout_price = float(df.iloc[j]["close"])
            if breakout_price <= 0:
                continue
            if direction == "up":
                target_dist = max(config.min_gap_pct, (float(first_down["mainland_edge"]) - island_low) / breakout_price * 100.0)
                target_price = breakout_price * (1.0 + target_dist / 100.0)
            else:
                target_dist = max(config.min_gap_pct, (island_high - float(first_up["mainland_edge"])) / breakout_price * 100.0)
                target_price = breakout_price * (1.0 - target_dist / 100.0)
            first_gap = first_up or first_down
            if first_gap is None:
                continue
            first_gap_pct = float(first_gap["gap_pct"])
            second_gap_pct = float(second["gap_pct"])
            gap_similarity = min(first_gap_pct, second_gap_pct) / max(first_gap_pct, second_gap_pct)
            volume_ratio = _volume_ratio(df, j)
            quality_score = _score_quality(
                width=width,
                gap1_pct=first_gap_pct,
                gap2_pct=second_gap_pct,
                prior_signed_pct=prior_signed,
                volume_ratio=volume_ratio,
            )
            pattern_id = f"islands:{symbol}:{i}:{j}:{variant}"
            row: dict[str, Any] = {
                "event_id": pattern_id,
                "detection_id": pattern_id,
                "pattern_id": ISLANDS_LONG if width > config.max_regular_bars else ISLAND_REVERSALS,
                "pattern_name": ISLANDS_LONG if width > config.max_regular_bars else ISLAND_REVERSALS,
                "symbol": symbol,
                "variant": variant,
                "formation_start_date": str(pd.Timestamp(df.iloc[i]["date"]).date()),
                "formation_start": str(pd.Timestamp(df.iloc[i]["date"]).date()),
                "formation_end_date": str(pd.Timestamp(df.iloc[j - 1]["date"]).date()),
                "formation_end": str(pd.Timestamp(df.iloc[j - 1]["date"]).date()),
                "breakout_date": str(pd.Timestamp(df.iloc[j]["date"]).date()),
                "breakout_idx": int(j),
                "breakout_direction": direction,
                "breakout_price": round(breakout_price, 4),
                "target_price": round(float(target_price), 4),
                "target_dist_pct": round(float(target_dist), 2),
                "pattern_width_bars": int(width),
                "pattern_height_pct": round((island_high - island_low) / breakout_price * 100.0, 2),
                "island_duration_bars": int(width),
                "first_gap_pct": round(first_gap_pct, 2),
                "second_gap_pct": round(second_gap_pct, 2),
                "gap_similarity_ratio": round(float(gap_similarity), 3),
                "prior_trend_pct": round(float(prior or 0.0), 2),
                "prior_trend_signed_pct": round(float(prior_signed), 2),
                "volume_ratio": volume_ratio,
                "confidence_score": quality_score,
                "publication_quality_score": quality_score,
                "publication_quality_tier": _quality_tier(quality_score, width=width),
                "pattern_quality_tier": _quality_tier(quality_score, width=width),
                "is_primary_event_60d": True,
                "source_gap_isolation_ok": True,
                "pivot_indices": json.dumps([i - 1, i, j - 1, j]),
                "created_at": _utc_now(),
            }
            row.update(_evaluate_island(df, row, lookahead=config.evaluation_bars))
            detections.append(row)
            last_breakout_idx = j
            break
        if len(detections) >= config.max_events_per_symbol:
            break
    return detections


def _summarize(rows: Sequence[Mapping[str, Any]], *, config: IslandConfig, symbols_scanned: int, db_path: Path) -> dict[str, Any]:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return {
            "pattern_key": "island_family",
            "symbols_scanned": symbols_scanned,
            "detection_count": 0,
            "config": config.to_dict(),
            "db": _db_meta(db_path) if db_path.exists() else {},
        }
    return {
        "pattern_key": "island_family",
        "symbols_scanned": symbols_scanned,
        "detection_count": int(len(frame)),
        "pattern_counts": frame["pattern_id"].value_counts().to_dict(),
        "variant_counts": frame["variant"].value_counts().to_dict(),
        "direction_counts": frame["breakout_direction"].value_counts().to_dict(),
        "quality_tier_counts": frame["publication_quality_tier"].value_counts().to_dict(),
        "median_mfe_pct": round(float(pd.to_numeric(frame["mfe_pct"], errors="coerce").median()), 2),
        "median_mae_pct": round(float(pd.to_numeric(frame["mae_pct"], errors="coerce").median()), 2),
        "target_hit_rate": round(float(frame["target_hit"].map(_truthy).mean() * 100.0), 2),
        "failure_5pct_rate": round(float(frame["failure_5pct"].map(_truthy).mean() * 100.0), 2),
        "config": config.to_dict(),
        "db": _db_meta(db_path) if db_path.exists() else {},
    }


def scan_island_family_db(
    *,
    db_path: Path = DEFAULT_DB,
    out_dir: Path = DEFAULT_OUT_DIR,
    allowed_symbols: Optional[Sequence[str]] = None,
    detector_config: Optional[Mapping[str, Any]] = None,
    limit_symbols: Optional[int] = None,
    index_db: Path = DEFAULT_INDEX_DB,
    index_symbol: str = DEFAULT_INDEX_SYMBOL,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    config = IslandConfig.from_mapping(detector_config)
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
                rows = scan_symbol_islands(frame, symbol=symbol, config=config)
                if rows:
                    series_by_symbol[symbol] = frame
                detections.extend(rows)
                symbol_stats.append({"symbol": symbol, "detections": len(rows)})
            except Exception as exc:
                symbol_stats.append({"symbol": symbol, "detections": 0, "error": str(exc)})
    finally:
        conn.close()
    detections, regime_meta = classify_market_regimes(detections, index_db=index_db, index_symbol=index_symbol)
    market_group_meta = attach_current_market_groups(detections)
    scan: dict[str, Any] = {
        "generated_at": _utc_now(),
        "source": "Market Cache latest.sqlite stock_price_history",
        "db_path": str(db_path),
        "pattern_key": "island_family",
        "symbols_scanned": len(symbols),
        "detections": detections,
        "symbol_stats": symbol_stats,
        "regime": regime_meta,
        "market_group": market_group_meta,
        "detector_config": config.to_dict(),
    }
    _enrich_events_from_series(scan, series_by_symbol)
    paths = {}
    for pattern_id in ISLAND_PATTERNS:
        pattern_rows = [row for row in scan["detections"] if row.get("pattern_id") == pattern_id]
        pattern_dir = out_dir / pattern_id / "db_active"
        pattern_dir.mkdir(parents=True, exist_ok=True)
        pattern_scan = dict(scan)
        pattern_scan["pattern_key"] = pattern_id
        pattern_scan["detections"] = pattern_rows
        pattern_scan["statistics"] = _summarize(pattern_rows, config=config, symbols_scanned=len(symbols), db_path=db_path)
        _write_json(pattern_dir / "scan.json", pattern_scan)
        _write_json(pattern_dir / "statistics.json", pattern_scan["statistics"])
        path_rows = _path_rows_from_series(pattern_scan, series_by_symbol, horizon_bars=config.evaluation_bars)
        _write_csv(pattern_dir / "events.csv", pattern_rows, _csv_fields(pattern_rows))
        _write_csv(pattern_dir / "post_breakout_path.csv", path_rows, _csv_fields(path_rows))
        paths[f"{pattern_id}_scan"] = pattern_dir / "scan.json"
        paths[f"{pattern_id}_events"] = pattern_dir / "events.csv"
        paths[f"{pattern_id}_path"] = pattern_dir / "post_breakout_path.csv"
    _write_json(out_dir / "island_family_scan_summary.json", {"statistics": _summarize(scan["detections"], config=config, symbols_scanned=len(symbols), db_path=db_path)})
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan Island Family against Market Cache OHLCV DB.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--limit-symbols", type=int, default=None)
    parser.add_argument("--active-only", action="store_true", default=True)
    parser.add_argument("--all-symbols", action="store_true", help="Scan every symbol in the OHLCV DB instead of the active-symbol subset.")
    parser.add_argument("--config-json", default=None)
    args = parser.parse_args()
    allowed = None if args.all_symbols else (sorted(_load_active_symbols(DEFAULT_MARKET_STATS_JSON)) if args.active_only else None)
    config = json.loads(args.config_json) if args.config_json else None
    outputs = scan_island_family_db(
        db_path=Path(args.db),
        out_dir=Path(args.out_dir),
        allowed_symbols=allowed,
        detector_config=config,
        limit_symbols=args.limit_symbols,
    )
    print(json.dumps({"status": "PASS", "outputs": {k: str(v) for k, v in outputs.items()}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
