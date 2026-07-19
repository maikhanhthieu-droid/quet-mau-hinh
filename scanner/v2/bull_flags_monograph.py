"""Bull Flag Scanner V2 watchlist chapter pipeline."""

from __future__ import annotations

import json
import sqlite3
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

from .source_data import DEFAULT_SOURCE_DIR
from .flags_experiment import (
    DEFAULT_INDEX_DB,
    DEFAULT_INDEX_SYMBOL,
    EVENT_FIELDS,
    FlagDetectorConfig,
    _path_rows,
    _write_csv,
    _write_json,
    scan_market_stats,
    summarize,
)


PATTERN_KEY = "bull_flags"
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bull_flags")
DEFAULT_MARKET_STATS_JSON = Path("../market_stats/web/market_stats_data.json")
LIQUIDITY_LOOKBACK_DAYS = 20
PRIMARY_EVENT_COOLDOWN_DAYS = 60


BULL_FLAG_EVENT_FIELDS = [
    *EVENT_FIELDS,
    "breakout_gap_pct",
    "breakout_volume_ratio_20",
    "breakout_close_location",
    "breakout_body_to_range",
    "volume_trend_slope_pct_per_bar",
    "volume_trend_direction",
    "flag_volume_to_pole_ratio",
    "yearly_range_position_pct",
    "flag_upper_breakout_value",
    "flag_lower_breakout_value",
    "throwback_exact_30d",
    "days_to_throwback_exact",
    "throwback_to_breakout_30d",
    "days_to_throwback_to_breakout",
    "days_to_trend_end",
    "post_flag_trend_move_pct",
    "trend_end_censored",
    "busted_pattern_flag",
    "days_to_bust",
    "stop_hit_5pct",
    "days_to_stop_5pct",
    "stop_hit_7pct",
    "days_to_stop_7pct",
    "stop_hit_10pct",
    "days_to_stop_10pct",
    "corp_action_overlap_flag",
    "corp_action_near_breakout_flag",
    "corp_action_in_forward_window_flag",
    "corp_action_event_count_pattern",
    "corp_action_event_count_near_breakout",
    "corp_action_event_count_forward",
    "corp_action_event_types",
    "corp_action_event_titles",
    "missing_bar_rate_60d",
    "zero_volume_rate_60d",
    "unchanged_close_streak_max_60d",
    "price_limit_proxy_days_60d",
    "price_limit_proxy_rate_60d",
    "tradability_quality_score",
    "tradability_quality_bucket",
    "tradability_risk_reasons",
    "adtv20_value",
    "zero_volume_days_20",
    "liquidity_bucket",
    "is_primary_event_60d",
    "corp_action_proxy_flag",
    "corp_action_proxy_reason",
    "halted_delisted_proxy_flag",
    "halted_delisted_proxy_reason",
    "post_breakout_path_coverage_60d",
    "post_breakout_zero_volume_days_60d",
    "post_breakout_unchanged_close_days_60d",
    "path_quality_bucket",
    "path_quality_reason",
    "breakout_year",
    "time_split",
]


def _filter_bull_flags(scan: Mapping[str, Any]) -> Dict[str, Any]:
    detections = [
        {**row, "pattern_key": PATTERN_KEY}
        for row in scan.get("detections") or []
        if row.get("variant") == "bull_flag" and row.get("breakout_direction") == "up"
    ]
    for i, row in enumerate(detections):
        row["detection_id"] = f"{PATTERN_KEY}:{i + 1:06d}"
    return {
        **dict(scan),
        "pattern_key": PATTERN_KEY,
        "detections": detections,
        "experiment_status": "promoted_watchlist_candidate_from_flags_experiment",
        "chapter_lane": "watchlist-reference candidate",
    }


def _num(row: Mapping[str, Any], key: str) -> Optional[float]:
    value = row.get(key)
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(out):
        return None
    return out


def _event_passes_filter(row: Mapping[str, Any], config: Mapping[str, Any]) -> bool:
    for key, op, field in (
        ("min_pole_move_pct", ">=", "pole_move_pct"),
        ("max_flag_to_pole_pct", "<=", "flag_to_pole_pct"),
        ("max_slope_gap_deg", "<=", "slope_gap_deg"),
        ("min_pattern_width_bars", ">=", "pattern_width_bars"),
        ("max_pattern_width_bars", "<=", "pattern_width_bars"),
        ("min_pattern_quality_score", ">=", "pattern_quality_score"),
        ("min_adtv20_value", ">=", "adtv20_value"),
        ("max_zero_volume_days_20", "<=", "zero_volume_days_20"),
        ("max_post_zero_volume_days_60d", "<=", "post_breakout_zero_volume_days_60d"),
        ("max_post_unchanged_close_days_60d", "<=", "post_breakout_unchanged_close_days_60d"),
    ):
        if key not in config or config.get(key) is None:
            continue
        value = _num(row, field)
        if value is None:
            return False
        threshold = float(config[key])
        if op == ">=" and value < threshold:
            return False
        if op == "<=" and value > threshold:
            return False
    if config.get("require_volume_confirmed") is True and row.get("volume_confirmed") is not True:
        return False
    if config.get("require_primary_event_60d") is True and row.get("is_primary_event_60d") is not True:
        return False
    allowed_path = config.get("allowed_path_quality_buckets")
    if allowed_path and str(row.get("path_quality_bucket") or "") not in {str(item) for item in allowed_path}:
        return False
    allowed_liquidity = config.get("allowed_liquidity_buckets")
    if allowed_liquidity and str(row.get("liquidity_bucket") or "") not in {str(item) for item in allowed_liquidity}:
        return False
    allowed_regimes = config.get("allowed_regimes")
    if allowed_regimes and str(row.get("market_regime") or "") not in {str(item) for item in allowed_regimes}:
        return False
    allowed_time_splits = config.get("allowed_time_splits")
    if allowed_time_splits and str(row.get("time_split") or "") not in {str(item) for item in allowed_time_splits}:
        return False
    min_year = config.get("min_breakout_year")
    max_year = config.get("max_breakout_year")
    if min_year is not None or max_year is not None:
        year = _num(row, "breakout_year")
        if year is None:
            return False
        if min_year is not None and year < float(min_year):
            return False
        if max_year is not None and year > float(max_year):
            return False
    return True


def _apply_event_filter(scan: Dict[str, Any], event_filter_config: Optional[Mapping[str, Any]]) -> None:
    if not event_filter_config:
        scan["event_filter_config"] = None
        return
    rows = list(scan.get("detections") or [])
    kept = [row for row in rows if _event_passes_filter(row, event_filter_config)]
    scan["detections"] = kept
    scan["event_filter_config"] = dict(event_filter_config)
    scan["event_filter_report"] = {
        "profile_id": event_filter_config.get("profile_id"),
        "input_detection_count": len(rows),
        "kept_detection_count": len(kept),
        "removed_detection_count": len(rows) - len(kept),
        "kept_share_pct": round(len(kept) / len(rows) * 100.0, 2) if rows else None,
    }


def _load_active_symbols(market_stats_json: Optional[Path]) -> Dict[str, Any]:
    if market_stats_json is None or not market_stats_json.exists():
        return {
            "enabled": False,
            "source": str(market_stats_json) if market_stats_json is not None else None,
            "active_symbols": None,
            "active_symbol_count": None,
            "excluded_symbol_count": None,
        }
    metadata = json.loads(market_stats_json.read_text(encoding="utf-8"))
    stocks = metadata.get("stocks") if isinstance(metadata.get("stocks"), list) else []
    active_symbols = {
        str(row.get("symbol") or "").strip().upper()
        for row in stocks
        if isinstance(row, Mapping) and str(row.get("symbol") or "").strip()
    }
    stock_source = (metadata.get("sources") or {}).get("stock_ohlcv") if isinstance(metadata.get("sources"), Mapping) else {}
    return {
        "enabled": bool(active_symbols),
        "source": str(market_stats_json),
        "active_symbols": active_symbols,
        "active_symbol_count": len(active_symbols),
        "excluded_symbol_count": stock_source.get("excluded_symbol_count") if isinstance(stock_source, Mapping) else None,
        "market_stats_symbol_count": stock_source.get("symbol_count") if isinstance(stock_source, Mapping) else None,
    }


def _restrict_scan_to_active_universe(scan: Dict[str, Any], market_stats_json: Optional[Path]) -> Dict[str, Any]:
    active_meta = _load_active_symbols(market_stats_json)
    active_symbols = active_meta.get("active_symbols")
    if not active_symbols:
        scan["active_universe_filter"] = {key: value for key, value in active_meta.items() if key != "active_symbols"}
        return scan
    detections = list(scan.get("detections") or [])
    symbol_stats = list(scan.get("symbol_stats") or [])
    kept_detections = [row for row in detections if str(row.get("symbol") or "").strip().upper() in active_symbols]
    kept_symbol_stats = [row for row in symbol_stats if str(row.get("symbol") or "").strip().upper() in active_symbols]
    filtered_scan = {
        **scan,
        "detections": kept_detections,
        "symbol_stats": kept_symbol_stats,
        "symbols_scanned": len(kept_symbol_stats),
        "active_universe_filter": {
            key: value for key, value in active_meta.items() if key != "active_symbols"
        }
        | {
            "removed_detection_count": len(detections) - len(kept_detections),
            "removed_symbol_stats_count": len(symbol_stats) - len(kept_symbol_stats),
            "scope_note": "Bull Flag chapter is restricted to current active Market Stats V1 symbols.",
        },
    }
    return filtered_scan


def _load_series_by_symbol(source_dir: Path, symbols: Sequence[str]) -> Dict[str, pd.DataFrame]:
    paths = {path.stem.split()[0].upper(): path for path in source_dir.glob("*.json")}
    out: Dict[str, pd.DataFrame] = {}
    for symbol in {str(symbol).upper() for symbol in symbols}:
        path = paths.get(symbol)
        if path is None:
            continue
        df = pd.DataFrame(json.loads(path.read_text(encoding="utf-8")))
        if not df.empty and "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
        out[symbol] = df
    return out


def _load_corporate_actions_by_symbol(db_path: Path, symbols: Sequence[str]) -> Dict[str, pd.DataFrame]:
    symbols_clean = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
    if not symbols_clean or not db_path.exists():
        return {}
    placeholders = ",".join(["?"] * len(symbols_clean))
    query = f"""
        SELECT
            symbol,
            event_title,
            event_list_name,
            event_list_code,
            public_date,
            issue_date,
            record_date,
            exright_date,
            ratio,
            value
        FROM events
        WHERE upper(symbol) IN ({placeholders})
    """
    conn = sqlite3.connect(str(db_path))
    try:
        frame = pd.read_sql_query(query, conn, params=symbols_clean)
    finally:
        conn.close()
    if frame.empty:
        return {}
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    date_cols = ["exright_date", "record_date", "issue_date", "public_date"]
    for col in date_cols:
        frame[col] = pd.to_datetime(frame[col], errors="coerce")
        frame.loc[frame[col].dt.year < 1990, col] = pd.NaT
    frame["action_date"] = frame[date_cols].bfill(axis=1).iloc[:, 0]
    frame = frame.dropna(subset=["action_date"]).copy()
    return {symbol: group.copy().reset_index(drop=True) for symbol, group in frame.groupby("symbol")}


def _corporate_action_metrics_for_event(actions: pd.DataFrame, row: Mapping[str, Any]) -> Dict[str, Any]:
    if actions.empty or "action_date" not in actions.columns:
        return {
            "corp_action_overlap_flag": False,
            "corp_action_near_breakout_flag": False,
            "corp_action_in_forward_window_flag": False,
            "corp_action_event_count_pattern": 0,
            "corp_action_event_count_near_breakout": 0,
            "corp_action_event_count_forward": 0,
            "corp_action_event_types": "",
            "corp_action_event_titles": "",
        }
    start = pd.to_datetime(row.get("formation_start_date"), errors="coerce")
    end = pd.to_datetime(row.get("formation_end_date"), errors="coerce")
    breakout = pd.to_datetime(row.get("breakout_date"), errors="coerce")
    if pd.isna(breakout):
        return {}
    action_dates = pd.to_datetime(actions["action_date"], errors="coerce")
    pattern_mask = pd.Series(False, index=actions.index)
    if not pd.isna(start) and not pd.isna(end):
        pattern_mask = action_dates.between(start, end, inclusive="both")
    near_mask = action_dates.between(breakout - pd.Timedelta(days=5), breakout + pd.Timedelta(days=5), inclusive="both")
    forward_mask = action_dates.between(breakout + pd.Timedelta(days=1), breakout + pd.Timedelta(days=90), inclusive="both")
    scoped = actions[pattern_mask | near_mask | forward_mask].copy()
    types = []
    titles = []
    if not scoped.empty:
        type_series = scoped.get("event_list_name", pd.Series(dtype=str)).fillna(scoped.get("event_list_code", pd.Series(dtype=str))).astype(str)
        title_series = scoped.get("event_title", pd.Series(dtype=str)).fillna("").astype(str)
        types = sorted({value for value in type_series if value and value.lower() != "nan"})[:6]
        titles = [value for value in title_series if value and value.lower() != "nan"][:4]
    return {
        "corp_action_overlap_flag": bool(pattern_mask.any()),
        "corp_action_near_breakout_flag": bool(near_mask.any()),
        "corp_action_in_forward_window_flag": bool(forward_mask.any()),
        "corp_action_event_count_pattern": int(pattern_mask.sum()),
        "corp_action_event_count_near_breakout": int(near_mask.sum()),
        "corp_action_event_count_forward": int(forward_mask.sum()),
        "corp_action_event_types": " | ".join(types),
        "corp_action_event_titles": " | ".join(titles),
    }


def _liquidity_metrics_for_event(series: pd.DataFrame, breakout_date: Any) -> Dict[str, Any]:
    if series.empty or "date" not in series.columns or "value" not in series.columns:
        return {"adtv20_value": None, "zero_volume_days_20": None}
    breakout = pd.to_datetime(breakout_date, errors="coerce")
    if pd.isna(breakout):
        return {"adtv20_value": None, "zero_volume_days_20": None}
    window = series[series["date"] < breakout].tail(LIQUIDITY_LOOKBACK_DAYS)
    if window.empty:
        return {"adtv20_value": None, "zero_volume_days_20": None}
    values = pd.to_numeric(window["value"], errors="coerce")
    volumes = pd.to_numeric(window.get("volume", pd.Series(dtype=float)), errors="coerce")
    return {
        "adtv20_value": round(float(values.dropna().mean()), 2) if values.notna().any() else None,
        "zero_volume_days_20": int((volumes.fillna(0) <= 0).sum()) if not volumes.empty else None,
    }


def _bar_index_on_or_after(series: pd.DataFrame, value: Any) -> Optional[int]:
    if series.empty or "date" not in series.columns:
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    matches = series.index[series["date"] >= ts]
    if len(matches) == 0:
        return None
    return int(matches[0])


def _line_value(row: Mapping[str, Any], *, side: str, idx: int) -> Optional[float]:
    try:
        idx0 = int(row[f"flag_{side}_idx0"])
        price0 = float(row[f"flag_{side}_price0"])
        slope = float(row[f"flag_{side}_slope_per_bar"])
    except (KeyError, TypeError, ValueError):
        return None
    return price0 + slope * (int(idx) - idx0)


def _first_true_day(mask: pd.Series) -> Optional[int]:
    if mask.empty or not bool(mask.any()):
        return None
    idx = mask[mask].index[0]
    try:
        return int(idx) + 1
    except (TypeError, ValueError):
        return None


def _bulkowski_equivalent_metrics_for_event(series: pd.DataFrame, row: Mapping[str, Any], *, horizon_days: int = 120) -> Dict[str, Any]:
    if series.empty or "date" not in series.columns:
        return {
            "breakout_gap_pct": None,
            "breakout_volume_ratio_20": None,
            "volume_trend_slope_pct_per_bar": None,
            "volume_trend_direction": "unknown",
            "yearly_range_position_pct": None,
            "throwback_exact_30d": None,
            "days_to_throwback_exact": None,
            "busted_pattern_flag": None,
            "days_to_bust": None,
        }
    working = series.sort_values("date").reset_index(drop=True).copy()
    for col in ("open", "high", "low", "close", "volume"):
        working[col] = pd.to_numeric(working.get(col), errors="coerce")
    breakout_idx = _bar_index_on_or_after(working, row.get("breakout_date"))
    formation_start_idx = _bar_index_on_or_after(working, row.get("formation_start_date"))
    formation_end_idx = _bar_index_on_or_after(working, row.get("formation_end_date"))
    if breakout_idx is None:
        return {}
    direction = str(row.get("breakout_direction") or "up")
    is_down = direction == "down"

    breakout = working.iloc[breakout_idx]
    prev = working.iloc[breakout_idx - 1] if breakout_idx > 0 else None
    breakout_close = float(breakout["close"])
    breakout_open = float(breakout["open"])
    breakout_high = float(breakout["high"])
    breakout_low = float(breakout["low"])
    if not np.isfinite(breakout_close) or breakout_close <= 0:
        return {
            "breakout_gap_pct": None,
            "breakout_volume_ratio_20": None,
            "volume_trend_slope_pct_per_bar": None,
            "volume_trend_direction": "unknown",
            "yearly_range_position_pct": None,
            "throwback_exact_30d": None,
            "days_to_throwback_exact": None,
            "busted_pattern_flag": None,
            "days_to_bust": None,
        }
    breakout_range = max(1e-9, breakout_high - breakout_low)
    prior_20 = working.iloc[max(0, breakout_idx - 20) : breakout_idx].copy()
    future = working.iloc[breakout_idx + 1 : min(len(working), breakout_idx + 1 + horizon_days)].copy().reset_index(drop=True)
    future_60 = future.head(60).copy()

    breakout_gap_pct = None
    if prev is not None and float(prev["close"]) > 0:
        breakout_gap_pct = (breakout_open / float(prev["close"]) - 1.0) * 100.0
    prior_volume = pd.to_numeric(prior_20.get("volume"), errors="coerce").dropna()
    breakout_volume_ratio_20 = float(breakout["volume"]) / float(prior_volume.median()) if not prior_volume.empty and float(prior_volume.median()) > 0 else None

    volume_slope = None
    volume_direction = "unknown"
    flag_volume_to_pole_ratio = None
    if formation_start_idx is not None and formation_end_idx is not None and formation_end_idx >= formation_start_idx:
        flag = working.iloc[formation_start_idx : formation_end_idx + 1]
        vols = pd.to_numeric(flag.get("volume"), errors="coerce").dropna()
        if len(vols) >= 3 and float(vols.median()) > 0:
            x = np.arange(len(vols), dtype=float)
            slope = float(np.polyfit(x, vols.to_numpy(dtype=float), 1)[0])
            volume_slope = slope / float(vols.median()) * 100.0
            volume_direction = "down" if volume_slope < -1.0 else ("up" if volume_slope > 1.0 else "flat")
        pole_idx = int(row.get("pole_idx") or max(0, formation_start_idx - 20))
        pole = working.iloc[max(0, pole_idx) : formation_start_idx]
        pole_vols = pd.to_numeric(pole.get("volume"), errors="coerce").dropna()
        if not pole_vols.empty and len(vols) > 0 and float(pole_vols.median()) > 0:
            flag_volume_to_pole_ratio = float(vols.median()) / float(pole_vols.median())

    yearly_position = None
    yearly = working.iloc[max(0, breakout_idx - 251) : breakout_idx + 1]
    if not yearly.empty:
        yearly_low = float(yearly["low"].min())
        yearly_high = float(yearly["high"].max())
        if yearly_high > yearly_low:
            yearly_position = (breakout_close - yearly_low) / (yearly_high - yearly_low) * 100.0

    upper_breakout = _line_value(row, side="upper", idx=breakout_idx)
    lower_breakout = _line_value(row, side="lower", idx=breakout_idx)
    first_lift_bar: Optional[int] = None
    if not future_60.empty:
        if is_down:
            lift = future_60[(breakout_close / future_60["low"].replace(0, np.nan) - 1.0) * 100.0 >= 2.0]
        else:
            lift = future_60[(future_60["high"] / breakout_close - 1.0) * 100.0 >= 2.0]
        if not lift.empty:
            first_lift_bar = int(lift.index[0])
    throwback_exact = False
    days_to_throwback_exact = None
    throwback_to_breakout = False
    days_to_throwback_to_breakout = None
    if first_lift_bar is not None:
        check = future_60.iloc[first_lift_bar + 1 : 30].copy()
        for rel_idx, frow in check.iterrows():
            absolute_idx = breakout_idx + 1 + int(rel_idx)
            boundary_value = _line_value(row, side="lower" if is_down else "upper", idx=absolute_idx)
            if boundary_value is not None and (
                float(frow["high"]) >= boundary_value * 0.995 if is_down else float(frow["low"]) <= boundary_value * 1.005
            ):
                throwback_exact = True
                days_to_throwback_exact = int(rel_idx) + 1
                break
        for rel_idx, frow in check.iterrows():
            if float(frow["high"]) >= breakout_close * 0.995 if is_down else float(frow["low"]) <= breakout_close * 1.005:
                throwback_to_breakout = True
                days_to_throwback_to_breakout = int(rel_idx) + 1
                break

    days_to_trend_end = None
    post_flag_trend_move_pct = None
    trend_end_censored = True
    if not future.empty:
        if is_down:
            running_low = np.inf
            low_day = 0
            reversal_day = None
            for idx, frow in future.iterrows():
                low = float(frow["low"])
                close = float(frow["close"])
                if low < running_low:
                    running_low = low
                    low_day = int(idx) + 1
                if running_low > 0 and close >= running_low * 1.20:
                    reversal_day = int(idx) + 1
                    break
            days_to_trend_end = low_day
            post_flag_trend_move_pct = (breakout_close / running_low - 1.0) * 100.0 if running_low > 0 and np.isfinite(running_low) else None
        else:
            running_high = -np.inf
            high_day = 0
            reversal_day = None
            for idx, frow in future.iterrows():
                high = float(frow["high"])
                close = float(frow["close"])
                if high > running_high:
                    running_high = high
                    high_day = int(idx) + 1
                if running_high > 0 and close <= running_high * 0.80:
                    reversal_day = int(idx) + 1
                    break
            days_to_trend_end = high_day
            post_flag_trend_move_pct = (running_high / breakout_close - 1.0) * 100.0 if running_high > 0 else None
        trend_end_censored = reversal_day is None

    busted = False
    days_to_bust = None
    if not future_60.empty:
        max_fav_before = 0.0
        flag_low = None
        flag_high = None
        if formation_start_idx is not None and formation_end_idx is not None:
            flag_low = float(working.iloc[formation_start_idx : formation_end_idx + 1]["low"].min())
            flag_high = float(working.iloc[formation_start_idx : formation_end_idx + 1]["high"].max())
        for idx, frow in future_60.iterrows():
            high = float(frow["high"])
            low = float(frow["low"])
            close = float(frow["close"])
            if is_down:
                max_fav_before = max(max_fav_before, (breakout_close / max(low, 1e-9) - 1.0) * 100.0)
            else:
                max_fav_before = max(max_fav_before, (high / breakout_close - 1.0) * 100.0)
            absolute_idx = breakout_idx + 1 + int(idx)
            boundary_value = _line_value(row, side="upper" if is_down else "lower", idx=absolute_idx)
            busted_level = boundary_value if boundary_value is not None else (flag_high if is_down else flag_low)
            busted_now = (close > busted_level or high > busted_level) if is_down else (close < busted_level or low < busted_level)
            if busted_level is not None and max_fav_before < 10.0 and busted_now:
                busted = True
                days_to_bust = int(idx) + 1
                break

    stop_metrics: Dict[str, Any] = {}
    for stop in (5, 7, 10):
        hit = False
        hit_day = None
        if not future_60.empty:
            if is_down:
                mask = future_60["high"] >= breakout_close * (1.0 + stop / 100.0)
            else:
                mask = future_60["low"] <= breakout_close * (1.0 - stop / 100.0)
            hit = bool(mask.any())
            if hit:
                hit_day = int(mask[mask].index[0]) + 1
        stop_metrics[f"stop_hit_{stop}pct"] = hit
        stop_metrics[f"days_to_stop_{stop}pct"] = hit_day

    return {
        "breakout_gap_pct": round(float(breakout_gap_pct), 2) if breakout_gap_pct is not None else None,
        "breakout_volume_ratio_20": round(float(breakout_volume_ratio_20), 4) if breakout_volume_ratio_20 is not None else None,
        "breakout_close_location": round(float((breakout_close - breakout_low) / breakout_range), 4),
        "breakout_body_to_range": round(float(abs(breakout_close - breakout_open) / breakout_range), 4),
        "volume_trend_slope_pct_per_bar": round(float(volume_slope), 4) if volume_slope is not None else None,
        "volume_trend_direction": volume_direction,
        "flag_volume_to_pole_ratio": round(float(flag_volume_to_pole_ratio), 4) if flag_volume_to_pole_ratio is not None else None,
        "yearly_range_position_pct": round(float(yearly_position), 2) if yearly_position is not None else None,
        "flag_upper_breakout_value": round(float(upper_breakout), 4) if upper_breakout is not None else row.get("flag_upper_breakout_value"),
        "flag_lower_breakout_value": round(float(lower_breakout), 4) if lower_breakout is not None else row.get("flag_lower_breakout_value"),
        "throwback_exact_30d": bool(throwback_exact),
        "days_to_throwback_exact": days_to_throwback_exact,
        "throwback_to_breakout_30d": bool(throwback_to_breakout),
        "days_to_throwback_to_breakout": days_to_throwback_to_breakout,
        "days_to_trend_end": days_to_trend_end,
        "post_flag_trend_move_pct": round(float(post_flag_trend_move_pct), 2) if post_flag_trend_move_pct is not None else None,
        "trend_end_censored": bool(trend_end_censored),
        "busted_pattern_flag": bool(busted),
        "days_to_bust": days_to_bust,
        **stop_metrics,
    }


def _proxy_risk_flags_for_event(series: pd.DataFrame, breakout_date: Any, *, horizon_days: int = 60) -> Dict[str, Any]:
    if series.empty or "date" not in series.columns:
        return {
            "corp_action_proxy_flag": True,
            "corp_action_proxy_reason": "missing_series",
            "halted_delisted_proxy_flag": True,
            "halted_delisted_proxy_reason": "missing_series",
            "post_breakout_path_coverage_60d": 0,
        }
    breakout = pd.to_datetime(breakout_date, errors="coerce")
    if pd.isna(breakout):
        return {
            "corp_action_proxy_flag": True,
            "corp_action_proxy_reason": "invalid_breakout_date",
            "halted_delisted_proxy_flag": True,
            "halted_delisted_proxy_reason": "invalid_breakout_date",
            "post_breakout_path_coverage_60d": 0,
        }
    local = series[(series["date"] >= breakout - pd.Timedelta(days=7)) & (series["date"] <= breakout + pd.Timedelta(days=7))].copy()
    reasons = []
    if "ret_1d" in local.columns:
        ret = pd.to_numeric(local["ret_1d"], errors="coerce").abs()
        if bool((ret > 25.0).any()):
            reasons.append("abs_ret_1d_gt_25pct_near_breakout")
    if "range_pct" in local.columns:
        ranges = pd.to_numeric(local["range_pct"], errors="coerce")
        if bool((ranges > 25.0).any()):
            reasons.append("range_pct_gt_25pct_near_breakout")
    if {"open", "close"}.issubset(local.columns):
        open_px = pd.to_numeric(local["open"], errors="coerce")
        close_px = pd.to_numeric(local["close"], errors="coerce")
        prev_close = close_px.shift(1)
        gap = ((open_px - prev_close).abs() / prev_close.replace(0, np.nan) * 100.0).dropna()
        if bool((gap > 25.0).any()):
            reasons.append("open_gap_gt_25pct_near_breakout")

    future = series[series["date"] > breakout].head(horizon_days).copy()
    coverage = int(len(future))
    halt_reasons = []
    if coverage < horizon_days:
        halt_reasons.append("future_path_shorter_than_60d")
    zero_volume_days = 0
    unchanged_close_days = 0
    if "volume" in future.columns and not future.empty:
        volumes = pd.to_numeric(future["volume"], errors="coerce").fillna(0)
        zero_volume_days = int((volumes <= 0).sum())
        if zero_volume_days >= 5:
            halt_reasons.append("five_or_more_zero_volume_days_post_breakout")
    if "close" in future.columns and not future.empty:
        close = pd.to_numeric(future["close"], errors="coerce")
        unchanged_close_days = int((close.diff().abs().fillna(1) == 0).sum())
        if unchanged_close_days >= 10:
            halt_reasons.append("ten_or_more_unchanged_close_days_post_breakout")

    return {
        "corp_action_proxy_flag": bool(reasons),
        "corp_action_proxy_reason": ",".join(reasons) if reasons else "",
        "halted_delisted_proxy_flag": bool(halt_reasons),
        "halted_delisted_proxy_reason": ",".join(halt_reasons) if halt_reasons else "",
        "post_breakout_path_coverage_60d": coverage,
        "post_breakout_zero_volume_days_60d": zero_volume_days,
        "post_breakout_unchanged_close_days_60d": unchanged_close_days,
    }


def _max_true_streak(values: pd.Series) -> int:
    best = 0
    current = 0
    for value in values.fillna(False).astype(bool).tolist():
        if value:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return int(best)


def _tradability_quality_metrics_for_event(series: pd.DataFrame, breakout_date: Any, corp_metrics: Mapping[str, Any], *, horizon_days: int = 60) -> Dict[str, Any]:
    if series.empty or "date" not in series.columns:
        return {
            "missing_bar_rate_60d": 100.0,
            "zero_volume_rate_60d": 100.0,
            "unchanged_close_streak_max_60d": None,
            "price_limit_proxy_days_60d": None,
            "price_limit_proxy_rate_60d": None,
            "tradability_quality_score": 0.0,
            "tradability_quality_bucket": "impaired",
            "tradability_risk_reasons": "missing_series",
        }
    breakout = pd.to_datetime(breakout_date, errors="coerce")
    if pd.isna(breakout):
        return {
            "missing_bar_rate_60d": 100.0,
            "zero_volume_rate_60d": 100.0,
            "unchanged_close_streak_max_60d": None,
            "price_limit_proxy_days_60d": None,
            "price_limit_proxy_rate_60d": None,
            "tradability_quality_score": 0.0,
            "tradability_quality_bucket": "impaired",
            "tradability_risk_reasons": "invalid_breakout_date",
        }
    future = series[series["date"] > breakout].head(horizon_days).copy()
    coverage = int(len(future))
    missing_rate = max(0.0, (horizon_days - coverage) / horizon_days * 100.0)
    zero_rate = 100.0
    unchanged_streak: Optional[int] = None
    limit_days: Optional[int] = None
    limit_rate: Optional[float] = None
    if not future.empty:
        for col in ("open", "high", "low", "close", "volume"):
            future[col] = pd.to_numeric(future.get(col), errors="coerce")
        volumes = future["volume"].fillna(0)
        zero_rate = float((volumes <= 0).mean() * 100.0)
        close_diff = future["close"].diff().abs()
        unchanged_streak = _max_true_streak(close_diff.fillna(1.0) == 0)
        close = future["close"].replace(0, np.nan)
        open_px = future["open"].replace(0, np.nan)
        range_pct = (future["high"] - future["low"]) / close * 100.0
        open_close_abs_pct = (future["close"] / open_px - 1.0).abs() * 100.0
        limit_mask = (range_pct >= 6.5) | (open_close_abs_pct >= 6.5)
        limit_days = int(limit_mask.fillna(False).sum())
        limit_rate = float(limit_days / len(future) * 100.0)

    reasons: list[str] = []
    score = 100.0
    score -= min(35.0, missing_rate * 0.8)
    score -= min(25.0, zero_rate * 0.5)
    if unchanged_streak is not None:
        score -= min(20.0, unchanged_streak * 2.0)
        if unchanged_streak >= 5:
            reasons.append("stale_close_streak")
    if limit_rate is not None:
        score -= min(15.0, limit_rate * 0.4)
        if limit_rate >= 20.0:
            reasons.append("many_price_limit_proxy_days")
    if missing_rate > 0:
        reasons.append("short_forward_path")
    if zero_rate >= 10:
        reasons.append("zero_volume_risk")
    if corp_metrics.get("corp_action_near_breakout_flag") is True:
        score -= 10.0
        reasons.append("corp_action_near_breakout")
    if corp_metrics.get("corp_action_overlap_flag") is True:
        score -= 5.0
        reasons.append("corp_action_inside_pattern")
    if corp_metrics.get("corp_action_in_forward_window_flag") is True:
        score -= 5.0
        reasons.append("corp_action_forward_window")
    score = max(0.0, min(100.0, score))
    bucket = "clean" if score >= 85.0 else ("usable" if score >= 70.0 else ("caution" if score >= 55.0 else "impaired"))
    return {
        "missing_bar_rate_60d": round(float(missing_rate), 2),
        "zero_volume_rate_60d": round(float(zero_rate), 2),
        "unchanged_close_streak_max_60d": unchanged_streak,
        "price_limit_proxy_days_60d": limit_days,
        "price_limit_proxy_rate_60d": round(float(limit_rate), 2) if limit_rate is not None else None,
        "tradability_quality_score": round(float(score), 2),
        "tradability_quality_bucket": bucket,
        "tradability_risk_reasons": ",".join(sorted(set(reasons))),
    }


def _assign_liquidity_buckets(rows: List[Dict[str, Any]]) -> None:
    vals = np.array([float(row["adtv20_value"]) for row in rows if row.get("adtv20_value") is not None], dtype=float)
    if vals.size < 3:
        for row in rows:
            row["liquidity_bucket"] = "unknown"
        return
    q33, q66 = np.percentile(vals, [33.333, 66.667])
    for row in rows:
        value = row.get("adtv20_value")
        if value is None:
            row["liquidity_bucket"] = "unknown"
        elif float(value) <= q33:
            row["liquidity_bucket"] = "low"
        elif float(value) <= q66:
            row["liquidity_bucket"] = "mid"
        else:
            row["liquidity_bucket"] = "high"


def _mark_primary_events(rows: List[Dict[str, Any]], *, cooldown_days: int = PRIMARY_EVENT_COOLDOWN_DAYS) -> None:
    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        by_symbol.setdefault(str(row.get("symbol") or ""), []).append(row)
        row["is_primary_event_60d"] = False
    for symbol_rows in by_symbol.values():
        last_kept: Optional[pd.Timestamp] = None
        for row in sorted(symbol_rows, key=lambda item: str(item.get("breakout_date") or "")):
            breakout = pd.to_datetime(row.get("breakout_date"), errors="coerce")
            if pd.isna(breakout):
                continue
            if last_kept is None or (breakout - last_kept).days > cooldown_days:
                row["is_primary_event_60d"] = True
                last_kept = breakout


def _assign_path_quality_buckets(rows: List[Dict[str, Any]]) -> None:
    for row in rows:
        coverage = int(row.get("post_breakout_path_coverage_60d") or 0)
        zero_days = int(row.get("post_breakout_zero_volume_days_60d") or 0)
        unchanged_days = int(row.get("post_breakout_unchanged_close_days_60d") or 0)
        reasons = []
        if coverage < 60:
            reasons.append("short_path")
        if zero_days >= 5:
            reasons.append("zero_volume")
        if unchanged_days >= 10:
            reasons.append("stale_close")
        if not reasons:
            row["path_quality_bucket"] = "clean"
            row["path_quality_reason"] = ""
        elif set(reasons) == {"short_path"}:
            row["path_quality_bucket"] = "short_path"
            row["path_quality_reason"] = ",".join(reasons)
        elif "zero_volume" in reasons and "stale_close" in reasons:
            row["path_quality_bucket"] = "zero_and_stale"
            row["path_quality_reason"] = ",".join(reasons)
        elif "zero_volume" in reasons:
            row["path_quality_bucket"] = "zero_volume"
            row["path_quality_reason"] = ",".join(reasons)
        elif "stale_close" in reasons:
            row["path_quality_bucket"] = "stale_close"
            row["path_quality_reason"] = ",".join(reasons)
        else:
            row["path_quality_bucket"] = "mixed_flag"
            row["path_quality_reason"] = ",".join(reasons)


def _assign_time_splits(rows: List[Dict[str, Any]]) -> None:
    parsed: List[tuple[pd.Timestamp, Dict[str, Any]]] = []
    for row in rows:
        breakout = pd.to_datetime(row.get("breakout_date"), errors="coerce")
        row["breakout_year"] = int(breakout.year) if not pd.isna(breakout) else None
        row["time_split"] = "unknown"
        if not pd.isna(breakout):
            parsed.append((breakout, row))
    if not parsed:
        return
    ordered = [row for _, row in sorted(parsed, key=lambda item: item[0])]
    n = len(ordered)
    train_end = int(np.floor(n * 0.60))
    validation_end = int(np.floor(n * 0.80))
    train_end = max(1, train_end)
    validation_end = max(train_end + 1, validation_end) if n >= 3 else n
    for idx, row in enumerate(ordered):
        if idx < train_end:
            row["time_split"] = "train_60"
        elif idx < validation_end:
            row["time_split"] = "validation_20"
        else:
            row["time_split"] = "holdout_20"


def _enrich_events(scan: Dict[str, Any], *, source_dir: Path, corporate_db: Path = DEFAULT_INDEX_DB) -> None:
    detections = list(scan.get("detections") or [])
    series_by_symbol = _load_series_by_symbol(source_dir, [row.get("symbol") for row in detections])
    corp_actions_by_symbol = _load_corporate_actions_by_symbol(corporate_db, [row.get("symbol") for row in detections])
    for row in detections:
        symbol = str(row.get("symbol") or "").upper()
        series = series_by_symbol.get(symbol, pd.DataFrame())
        metrics = _liquidity_metrics_for_event(series, row.get("breakout_date"))
        corp_metrics = _corporate_action_metrics_for_event(corp_actions_by_symbol.get(symbol, pd.DataFrame()), row)
        row.update(metrics)
        row.update(_bulkowski_equivalent_metrics_for_event(series, row))
        row.update(corp_metrics)
        row.update(_tradability_quality_metrics_for_event(series, row.get("breakout_date"), corp_metrics))
        row.update(_proxy_risk_flags_for_event(series, row.get("breakout_date")))
    _assign_liquidity_buckets(detections)
    _mark_primary_events(detections)
    _assign_path_quality_buckets(detections)
    _assign_time_splits(detections)
    scan["detections"] = detections


def _rate(rows: Sequence[Mapping[str, Any]], key: str) -> Optional[float]:
    vals = [row.get(key) for row in rows if row.get(key) is not None]
    if not vals:
        return None
    return round(sum(1 for val in vals if bool(val)) / len(vals) * 100.0, 2)


def _median(rows: Sequence[Mapping[str, Any]], key: str) -> Optional[float]:
    vals = [float(row[key]) for row in rows if row.get(key) is not None]
    if not vals:
        return None
    return round(float(np.median(vals)), 2)


def _simple_group_stats(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    evals = [row for row in rows if row.get("mfe_pct") is not None]
    return {
        "n": len(evals),
        "median_mfe_pct": _median(evals, "mfe_pct"),
        "median_mae_pct": _median(evals, "mae_pct"),
        "target_hit_rate": _rate(evals, "target_hit"),
        "failure_5pct_rate": _rate(evals, "failure_5pct"),
        "target_first_before_adverse_5pct_rate": _rate(evals, "target_first_before_adverse_5pct"),
    }


def _add_sensitivity_tables(stats: Dict[str, Any], scan: Mapping[str, Any]) -> None:
    rows = list(scan.get("detections") or [])
    stats["liquidity_proxy_table"] = {
        bucket: _simple_group_stats([row for row in rows if str(row.get("liquidity_bucket") or "unknown") == bucket])
        for bucket in ("high", "mid", "low", "unknown")
    }
    stats["overlap_sensitivity"] = {
        "all_events": _simple_group_stats(rows),
        "primary_event_60d": _simple_group_stats([row for row in rows if row.get("is_primary_event_60d") is True]),
        "repeat_events_within_60d": _simple_group_stats([row for row in rows if row.get("is_primary_event_60d") is False]),
    }
    stats["proxy_audit_table"] = {
        "all_events": _simple_group_stats(rows),
        "corp_action_proxy_clean": _simple_group_stats([row for row in rows if row.get("corp_action_proxy_flag") is False]),
        "corp_action_proxy_flagged": _simple_group_stats([row for row in rows if row.get("corp_action_proxy_flag") is True]),
        "halted_delisted_proxy_clean": _simple_group_stats([row for row in rows if row.get("halted_delisted_proxy_flag") is False]),
        "halted_delisted_proxy_flagged": _simple_group_stats([row for row in rows if row.get("halted_delisted_proxy_flag") is True]),
    }
    stats["regime_proxy_table"] = {
        regime: _simple_group_stats([row for row in rows if str(row.get("market_regime") or "unknown") == regime])
        for regime in ("bull", "bear", "unknown")
    }
    stats["time_split_table"] = {
        split: _simple_group_stats([row for row in rows if str(row.get("time_split") or "unknown") == split])
        for split in ("train_60", "validation_20", "holdout_20", "unknown")
    }
    path_buckets = sorted({str(row.get("path_quality_bucket") or "unknown") for row in rows})
    stats["path_quality_table"] = {
        bucket: _simple_group_stats([row for row in rows if str(row.get("path_quality_bucket") or "unknown") == bucket])
        for bucket in path_buckets
    }
    reason_counts: Dict[str, int] = {}
    for row in rows:
        reason = str(row.get("path_quality_reason") or "clean")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    stats["path_quality_audit"] = {
        "bucket_counts": {bucket: sum(1 for row in rows if str(row.get("path_quality_bucket") or "unknown") == bucket) for bucket in path_buckets},
        "reason_counts": reason_counts,
        "median_coverage_60d": _median(rows, "post_breakout_path_coverage_60d"),
        "median_zero_volume_days_60d": _median(rows, "post_breakout_zero_volume_days_60d"),
        "median_unchanged_close_days_60d": _median(rows, "post_breakout_unchanged_close_days_60d"),
    }
    stats["proxy_audit_counts"] = {
        "corp_action_proxy_flagged": sum(1 for row in rows if row.get("corp_action_proxy_flag") is True),
        "halted_delisted_proxy_flagged": sum(1 for row in rows if row.get("halted_delisted_proxy_flag") is True),
    }
    stats["corporate_action_audit"] = {
        "overlap_pattern_rate": _rate(rows, "corp_action_overlap_flag"),
        "near_breakout_rate": _rate(rows, "corp_action_near_breakout_flag"),
        "forward_window_rate": _rate(rows, "corp_action_in_forward_window_flag"),
        "pattern_event_count": int(sum(int(row.get("corp_action_event_count_pattern") or 0) for row in rows)),
        "near_breakout_event_count": int(sum(int(row.get("corp_action_event_count_near_breakout") or 0) for row in rows)),
        "forward_event_count": int(sum(int(row.get("corp_action_event_count_forward") or 0) for row in rows)),
    }
    tradability_buckets = sorted({str(row.get("tradability_quality_bucket") or "unknown") for row in rows})
    stats["tradability_quality_table"] = {
        bucket: _simple_group_stats([row for row in rows if str(row.get("tradability_quality_bucket") or "unknown") == bucket])
        | {"median_score": _median([row for row in rows if str(row.get("tradability_quality_bucket") or "unknown") == bucket], "tradability_quality_score")}
        for bucket in tradability_buckets
    }
    stats["tradability_quality_audit"] = {
        "bucket_counts": {
            bucket: sum(1 for row in rows if str(row.get("tradability_quality_bucket") or "unknown") == bucket)
            for bucket in tradability_buckets
        },
        "median_score": _median(rows, "tradability_quality_score"),
        "median_missing_bar_rate_60d": _median(rows, "missing_bar_rate_60d"),
        "median_zero_volume_rate_60d": _median(rows, "zero_volume_rate_60d"),
        "median_price_limit_proxy_rate_60d": _median(rows, "price_limit_proxy_rate_60d"),
        "median_unchanged_close_streak_max_60d": _median(rows, "unchanged_close_streak_max_60d"),
    }
    evals = [row for row in rows if row.get("mfe_pct") is not None]
    stats["bulkowski_equivalent_coverage"] = {
        "breakout_gap_pct": _median(evals, "breakout_gap_pct"),
        "breakout_volume_ratio_20": _median(evals, "breakout_volume_ratio_20"),
        "volume_trend_slope_pct_per_bar": _median(evals, "volume_trend_slope_pct_per_bar"),
        "yearly_range_position_pct": _median(evals, "yearly_range_position_pct"),
        "throwback_exact_30d_rate": _rate(evals, "throwback_exact_30d"),
        "throwback_to_breakout_30d_rate": _rate(evals, "throwback_to_breakout_30d"),
        "median_days_to_throwback_exact": _median(evals, "days_to_throwback_exact"),
        "median_days_to_trend_end": _median(evals, "days_to_trend_end"),
        "median_post_flag_trend_move_pct": _median(evals, "post_flag_trend_move_pct"),
        "trend_end_censored_rate": _rate(evals, "trend_end_censored"),
        "busted_pattern_rate": _rate(evals, "busted_pattern_flag"),
        "stop_hit_5pct_rate": _rate(evals, "stop_hit_5pct"),
        "stop_hit_7pct_rate": _rate(evals, "stop_hit_7pct"),
        "stop_hit_10pct_rate": _rate(evals, "stop_hit_10pct"),
    }
    stats["volume_trend_table"] = {
        bucket: _simple_group_stats([row for row in rows if str(row.get("volume_trend_direction") or "unknown") == bucket])
        for bucket in ("down", "flat", "up", "unknown")
    }
    stats["yearly_position_table"] = {
        "lower_third": _simple_group_stats([row for row in rows if row.get("yearly_range_position_pct") is not None and float(row["yearly_range_position_pct"]) < 33.33]),
        "middle_third": _simple_group_stats([row for row in rows if row.get("yearly_range_position_pct") is not None and 33.33 <= float(row["yearly_range_position_pct"]) <= 66.67]),
        "upper_third": _simple_group_stats([row for row in rows if row.get("yearly_range_position_pct") is not None and float(row["yearly_range_position_pct"]) > 66.67]),
    }


def _add_target_calibration(
    stats: Dict[str, Any],
    scan: Mapping[str, Any],
    path_rows: Sequence[Mapping[str, Any]],
    *,
    data_gate_report: Optional[Mapping[str, Any]] = None,
) -> None:
    from ..research_support_analysis import (  # local import avoids making the PDF runner own research-support imports at module load time
        PatternArtifacts,
        _bull_flag_subgroups,
        build_bull_flag_robustness_checks,
        build_target_calibration_decisions,
        target_sensitivity,
    )

    events = pd.DataFrame(list(scan.get("detections") or []))
    path = pd.DataFrame(list(path_rows))
    if events.empty:
        stats["target_family_sensitivity"] = []
        stats["target_calibration_decision"] = None
        return
    if "event_id" not in events.columns and "detection_id" in events.columns:
        events["event_id"] = events["detection_id"]
    sensitivity = target_sensitivity(PatternArtifacts(PATTERN_KEY, events, path), PATTERN_KEY)
    for label, subgroup in _bull_flag_subgroups(events):
        if label == PATTERN_KEY:
            continue
        sensitivity.extend(target_sensitivity(PatternArtifacts(label, subgroup.copy(), path), label))
    decisions = build_target_calibration_decisions(sensitivity)
    stats["target_family_sensitivity"] = sensitivity
    stats["target_calibration_decision"] = decisions[0] if decisions else None
    stats["robustness_checks"] = build_bull_flag_robustness_checks(
        {
            "target_sensitivity": sensitivity,
            "target_calibration_decisions": decisions,
            "data_gate_audits": {"bull_flags": dict(data_gate_report or {})} if data_gate_report else {},
        }
    )


def _text_block(
    fig: plt.Figure,
    x: float,
    y: float,
    text: str,
    *,
    width: int = 95,
    fontsize: float = 8.5,
    line_step: float = 0.018,
    weight: Optional[str] = None,
) -> float:
    for line in textwrap.wrap(str(text), width=width) or [""]:
        fig.text(x, y, line, fontsize=fontsize, ha="left", va="top", weight=weight)
        y -= line_step
    return y


def _find_target_row(stats: Mapping[str, Any], multiple: float, label: str = PATTERN_KEY) -> Mapping[str, Any]:
    for row in stats.get("target_family_sensitivity") or []:
        if row.get("label") == label and float(row.get("target_multiple") or -1) == float(multiple):
            return row
    return {}


def _check_status(stats: Mapping[str, Any], check_id: str) -> Mapping[str, Any]:
    for row in stats.get("robustness_checks") or []:
        if row.get("check_id") == check_id:
            return row
    return {}


def _render_table(fig: plt.Figure, rows: Sequence[Sequence[Any]], *, x: float, y: float, col_x: Sequence[float], fontsize: float = 8.0) -> float:
    for row_index, row in enumerate(rows):
        weight = "bold" if row_index == 0 else None
        for col_index, value in enumerate(row):
            fig.text(x + col_x[col_index], y, str(value), fontsize=fontsize, ha="left", va="top", weight=weight)
        y -= 0.028
    return y


def _render_pdf(path: Path, stats: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(path) as pdf:
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.patch.set_facecolor("#fffdf8")
        decision = stats.get("target_calibration_decision") if isinstance(stats.get("target_calibration_decision"), Mapping) else {}
        decision_metrics = decision.get("selected_metrics") if isinstance(decision.get("selected_metrics"), Mapping) else {}
        base = _find_target_row(stats, 0.46)
        legacy = _find_target_row(stats, 1.0)
        classification = (_check_status(stats, "classification_after_robustness").get("evidence") or {}).get(
            "classification", "watchlist-reference"
        )

        fig.text(0.5, 0.92, "Bull Flag", ha="center", va="top", fontsize=22, weight="bold")
        fig.text(0.5, 0.887, "Scanner V2 available-series chapter", ha="center", va="top", fontsize=11)
        rows = [
            ("Số mã quét", stats.get("symbols_scanned")),
            ("Số mẫu Bull Flag", stats.get("detection_count")),
            ("Mẫu có đánh giá", stats.get("evaluated_count")),
            ("MFE trung vị", f"{stats.get('median_mfe_pct')}%"),
            ("MAE trung vị", f"{stats.get('median_mae_pct')}%"),
            ("Base target", f"{decision.get('selected_target_multiple')}x ({decision.get('selected_target_role')})" if decision else "chưa chọn"),
            ("Base target hit", f"{decision_metrics.get('target_hit_rate')}%" if decision_metrics else "n/a"),
            ("Base target-first", f"{decision_metrics.get('target_first_before_adverse_5pct_rate')}%" if decision_metrics else "n/a"),
            ("Target hit legacy 1.0x", f"{legacy.get('target_hit_rate') or stats.get('target_hit_rate')}%"),
            ("Fail 5%", f"{stats.get('failure_5pct_rate')}%"),
            ("Target-first trước adverse 5%", f"{stats.get('target_first_before_adverse_5pct_rate')}%"),
            ("High-liquidity N", (stats.get("liquidity_proxy_table") or {}).get("high", {}).get("n")),
            ("Primary 60d N", (stats.get("overlap_sensitivity") or {}).get("primary_event_60d", {}).get("n")),
            ("Corp-action proxy flagged", (stats.get("proxy_audit_counts") or {}).get("corp_action_proxy_flagged")),
            ("Halted/delist proxy flagged", (stats.get("proxy_audit_counts") or {}).get("halted_delisted_proxy_flagged")),
            ("Target family", "0.46x / 0.5x / 0.75x / 1.0x pole"),
            ("Phân loại", classification),
        ]
        y = 0.80
        for label, value in rows:
            fig.text(0.16, y, str(label), fontsize=10, weight="bold", ha="left", va="top")
            fig.text(0.58, y, str(value), fontsize=10, ha="left", va="top")
            y -= 0.036
        fig.text(
            0.12,
            0.22,
            "Ghi chú: Bull Flag đã được tách khỏi Flags experiment để trở thành ứng viên chapter V2. "
            "Mốc 1.0x là legacy full-pole benchmark; base target thực nghiệm cho Việt Nam cần đọc ở 0.46x/0.5x trong research support packet. "
            "Phạm vi hiện tại là active Market Stats universe; không claim full point-in-time universe hay historical VN30/VN100 membership.",
            fontsize=9,
            ha="left",
            va="top",
            wrap=True,
        )
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        fig = plt.figure(figsize=(8.27, 11.69))
        fig.patch.set_facecolor("#fffdf8")
        fig.text(0.08, 0.93, "1. Methodology Contract", fontsize=16, weight="bold", ha="left", va="top")
        y = 0.88
        y = _text_block(
            fig,
            0.08,
            y,
            "Bull Flag được xử lý như continuation pattern: có flagpole đi lên, đoạn flag ngắn/điều chỉnh, và breakout lên xác nhận event. "
            "Mọi kết quả trong chapter neo vào breakout event, không được viết như khuyến nghị giao dịch.",
            width=105,
            fontsize=9,
        )
        y -= 0.02
        table_rows = [
            ("Scope", "Available active Market Stats V1 series"),
            ("Universe claim", "Không claim point-in-time toàn thị trường"),
            ("Index membership", "Không dùng historical VN30/VN100 làm headline"),
            ("Base target family", "0.46x / 0.5x / 0.75x / 1.0x pole"),
            ("Primary horizon", "60 trading sessions after breakout"),
            ("Classification lane", "Watchlist/reference, not trading system"),
        ]
        for label, value in table_rows:
            fig.text(0.10, y, label, fontsize=9, weight="bold", ha="left", va="top")
            fig.text(0.38, y, value, fontsize=9, ha="left", va="top")
            y -= 0.034
        y -= 0.02
        _text_block(
            fig,
            0.08,
            y,
            "Giới hạn có chủ ý: chapter hiện không dùng historical VN30/VN100 membership và không tuyên bố tái dựng full security master point-in-time. "
            "Thay vào đó, kết quả được dán nhãn available-series để tránh overclaim.",
            width=105,
            fontsize=8.8,
        )
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        fig = plt.figure(figsize=(8.27, 11.69))
        fig.patch.set_facecolor("#fffdf8")
        fig.text(0.08, 0.93, "2. Important Results", fontsize=16, weight="bold", ha="left", va="top")
        y = 0.87
        table = [
            ("Metric", "0.46x base", "1.0x legacy"),
            ("N", base.get("n"), legacy.get("n")),
            ("Target hit", f"{base.get('target_hit_rate')}%", f"{legacy.get('target_hit_rate')}%"),
            ("Wilson low", f"{base.get('target_hit_ci_low')}%", f"{legacy.get('target_hit_ci_low')}%"),
            ("Target-first before -5%", f"{base.get('target_first_before_adverse_5pct_rate')}%", f"{legacy.get('target_first_before_adverse_5pct_rate')}%"),
            ("Failure 5%", f"{base.get('failure_5pct_rate')}%", f"{legacy.get('failure_5pct_rate')}%"),
            ("Median effective target", f"{base.get('median_effective_target_pct')}%", f"{legacy.get('median_effective_target_pct')}%"),
            ("MFE/MAE median ratio", base.get("mfe_mae_median_ratio"), legacy.get("mfe_mae_median_ratio")),
        ]
        y = _render_table(fig, table, x=0.08, y=y, col_x=[0.00, 0.36, 0.62], fontsize=8.8)
        y -= 0.035
        _text_block(
            fig,
            0.08,
            y,
            "Cách đọc: Bull Flag có continuation tendency rõ hơn ở fractional target. 1.0x pole-height vẫn được giữ để so sánh với measure rule đầy đủ, nhưng không còn là headline target cho thị trường Việt Nam trong run này.",
            width=105,
            fontsize=9,
        )
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        fig = plt.figure(figsize=(8.27, 11.69))
        fig.patch.set_facecolor("#fffdf8")
        fig.text(0.08, 0.93, "3. Robustness Checks", fontsize=16, weight="bold", ha="left", va="top")
        y = 0.87
        robust_rows = [("Check", "Status")]
        for check in stats.get("robustness_checks") or []:
            robust_rows.append((check.get("check_id"), check.get("status")))
        y = _render_table(fig, robust_rows, x=0.08, y=y, col_x=[0.00, 0.52], fontsize=8.5)
        y -= 0.02
        _text_block(
            fig,
            0.08,
            y,
            "Kết luận robustness: base target pass, 1.0x chỉ là stretch benchmark, primary-event sensitivity ổn. "
            "Liquidity buckets, regime split và holdout được đọc bằng cùng base target 0.46x. Các bucket mỏng hoặc path flagged yếu sẽ giữ chapter ở watchlist-reference.",
            width=105,
            fontsize=9,
        )
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        fig = plt.figure(figsize=(8.27, 11.69))
        fig.patch.set_facecolor("#fffdf8")
        fig.text(0.08, 0.93, "4. Deep Splits", fontsize=16, weight="bold", ha="left", va="top")
        y = 0.87
        split_rows = [("Split", "N", "Hit", "T-first", "Fail")]
        for label in (
            "bull_flags:regime=bull",
            "bull_flags:regime=bear",
            "bull_flags:time=train_60",
            "bull_flags:time=validation_20",
            "bull_flags:time=holdout_20",
            "bull_flags:path_quality=clean",
            "bull_flags:path_quality=stale_close",
            "bull_flags:path_quality=zero_and_stale",
            "bull_flags:path_quality=short_path",
        ):
            row = _find_target_row(stats, 0.46, label=label)
            if not row:
                continue
            split_rows.append(
                (
                    label.replace("bull_flags:", ""),
                    row.get("n"),
                    f"{row.get('target_hit_rate')}%",
                    f"{row.get('target_first_before_adverse_5pct_rate')}%",
                    f"{row.get('failure_5pct_rate')}%",
                )
            )
        y = _render_table(fig, split_rows, x=0.08, y=y, col_x=[0.00, 0.38, 0.48, 0.60, 0.74], fontsize=7.7)
        y -= 0.02
        path_audit = stats.get("path_quality_audit") if isinstance(stats.get("path_quality_audit"), Mapping) else {}
        _text_block(
            fig,
            0.08,
            y,
            f"Path audit buckets: {path_audit.get('bucket_counts')}. "
            "Các split này dùng để kiểm tra độ bền, không phải để chọn lại target sau khi xem kết quả.",
            width=105,
            fontsize=8.7,
        )
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        fig = plt.figure(figsize=(8.27, 11.69))
        fig.patch.set_facecolor("#fffdf8")
        fig.text(0.08, 0.93, "5. Chapter Decision", fontsize=16, weight="bold", ha="left", va="top")
        y = 0.87
        y = _text_block(
            fig,
            0.08,
            y,
            "Decision: Bull Flag được nâng lên watchlist-reference trong phạm vi available-series. "
            "Nó chưa phải investment-reference đầy đủ vì vẫn cần kiểm định dữ liệu sâu hơn và split bổ sung, nhưng chất lượng đã vượt khỏi mức diagnostic-only.",
            width=105,
            fontsize=9.2,
        )
        y -= 0.02
        y = _text_block(
            fig,
            0.08,
            y,
            "Next: mở rộng cùng framework sang Bear Flag để hoàn thiện Flag Family trước khi chuyển sang họ mẫu hình khác. Với bearish patterns trên cash equities Việt Nam, default vẫn nên là informational/defensive-reference.",
            width=105,
            fontsize=9.2,
        )
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)


def run_pipeline(
    *,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    out_dir: Path = DEFAULT_OUT_DIR,
    limit_symbols: Optional[int] = None,
    index_db: Path = DEFAULT_INDEX_DB,
    index_symbol: str = DEFAULT_INDEX_SYMBOL,
    market_stats_json: Optional[Path] = DEFAULT_MARKET_STATS_JSON,
    detector_config: Optional[FlagDetectorConfig | Mapping[str, Any]] = None,
    event_filter_config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    active_meta = _load_active_symbols(market_stats_json)
    allowed_symbols = active_meta.get("active_symbols") if active_meta.get("enabled") else None
    raw_scan = scan_market_stats(
        source_dir,
        limit_symbols=limit_symbols,
        index_db=index_db,
        index_symbol=index_symbol,
        allowed_symbols=allowed_symbols,
        detector_config=detector_config,
    )
    raw_scan = _restrict_scan_to_active_universe(raw_scan, market_stats_json)
    scan = _filter_bull_flags(raw_scan)
    _enrich_events(scan, source_dir=source_dir, corporate_db=index_db)
    _apply_event_filter(scan, event_filter_config)
    stats = summarize(scan)
    stats["pattern_key"] = PATTERN_KEY
    stats["chapter_lane"] = "watchlist-reference candidate"
    stats["detector_config"] = FlagDetectorConfig.from_mapping(detector_config).to_dict()
    stats["event_filter_config"] = dict(event_filter_config or {})
    stats["event_filter_report"] = scan.get("event_filter_report")
    stats["target_family"] = {
        "bulkowski_adjusted_base": 0.46,
        "rounded_local_base": 0.5,
        "local_stretch": 0.75,
        "legacy_full_pole": 1.0,
    }
    _add_sensitivity_tables(stats, scan)
    path_rows = _path_rows(scan, source_dir=source_dir)
    existing_gate_report: Optional[Dict[str, Any]] = None
    existing_gate_path = out_dir / "data_gate_audit.json"
    if existing_gate_path.exists():
        existing_gate_report = json.loads(existing_gate_path.read_text(encoding="utf-8"))
    _add_target_calibration(stats, scan, path_rows, data_gate_report=existing_gate_report)
    paths = {
        "detections": out_dir / "detections.json",
        "statistics": out_dir / "statistics.json",
        "events_csv": out_dir / "events.csv",
        "post_breakout_path_csv": out_dir / "post_breakout_path.csv",
        "pdf": out_dir / "bull_flags.pdf",
    }
    _write_json(paths["detections"], scan)
    _write_json(paths["statistics"], stats)
    _write_csv(paths["events_csv"], scan.get("detections") or [], BULL_FLAG_EVENT_FIELDS)
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


__all__ = ["DEFAULT_OUT_DIR", "PATTERN_KEY", "run_pipeline"]
