from __future__ import annotations

import math
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Mapping

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle


DEFAULT_PRICE_DB = Path("../market_cache/stock_ohlcv/latest.sqlite")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "có"}


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _date(value: Any) -> pd.Timestamp | None:
    out = pd.to_datetime(value, errors="coerce")
    return out if pd.notna(out) else None


def _load_ohlcv(price_db: Path, symbol: str) -> pd.DataFrame:
    conn = sqlite3.connect(str(price_db))
    try:
        df = pd.read_sql_query(
            "SELECT time AS date, open, high, low, close, volume FROM stock_price_history WHERE symbol = ? ORDER BY time",
            conn,
            params=[symbol],
        )
    finally:
        conn.close()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)


def _slice_window(df: pd.DataFrame, event: Mapping[str, Any], *, pre_bars: int = 45, post_bars: int = 45) -> tuple[pd.DataFrame, int]:
    fs = _date(event.get("formation_start_date") or event.get("formation_start"))
    fe = _date(event.get("formation_end_date") or event.get("formation_end"))
    bd = _date(event.get("breakout_date"))
    if df.empty or fs is None:
        return df.iloc[:0].copy(), 0
    start_idx = int(df["date"].searchsorted(fs, side="left"))
    end_anchor = bd or fe or fs
    end_idx = int(df["date"].searchsorted(end_anchor, side="left"))
    w0 = max(0, start_idx - int(pre_bars))
    w1 = min(len(df), max(end_idx + int(post_bars) + 1, start_idx + 2))
    return df.iloc[w0:w1].copy().reset_index(drop=True), w0


def _nearest_idx(df: pd.DataFrame, ts: pd.Timestamp | None) -> int | None:
    if ts is None or df.empty:
        return None
    idx = int(df["date"].searchsorted(ts, side="left"))
    return max(0, min(idx, len(df) - 1))


def _event_lookup(events: pd.DataFrame, event: Mapping[str, Any]) -> Mapping[str, Any]:
    detection_id = str(event.get("detection_id") or event.get("event_id") or "").strip()
    if detection_id and "detection_id" in events.columns:
        matched = events[events["detection_id"].astype(str) == detection_id]
        if not matched.empty:
            row = matched.iloc[0].to_dict()
            row.update({k: v for k, v in event.items() if v is not None})
            return row
    symbol = str(event.get("symbol") or "").strip()
    breakout = str(event.get("breakout_date") or "").strip()
    if symbol and breakout and {"symbol", "breakout_date"}.issubset(events.columns):
        matched = events[(events["symbol"].astype(str) == symbol) & (events["breakout_date"].astype(str) == breakout)]
        if not matched.empty:
            row = matched.iloc[0].to_dict()
            row.update({k: v for k, v in event.items() if v is not None})
            return row
    return event


def _ranked_source(events: pd.DataFrame) -> pd.DataFrame:
    source = events.copy()
    if "market_group" in source.columns:
        source["_market_rank"] = source["market_group"].map({"VN30": 0, "VN100 ex VN30": 1}).fillna(2)
    else:
        source["_market_rank"] = 2
    for column in ("target_hit", "failure_5pct", "target_first_before_adverse_5pct"):
        if column in source.columns:
            source[column] = source[column].map(_truthy)
    for column in ("publication_quality_score", "pattern_quality_score", "mfe_pct", "mae_pct"):
        if column in source.columns:
            source[column] = pd.to_numeric(source[column], errors="coerce")
    return source


def _numeric_column(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _visual_candidate_source(events: pd.DataFrame, pattern_id: str) -> pd.DataFrame:
    source = _ranked_source(events)
    if source.empty:
        return source
    source = _add_visual_sort_columns(source)

    tier = source.get("pattern_quality_tier", source.get("publication_quality_tier", pd.Series("", index=source.index))).astype(str).str.lower()
    publication_tier = source.get("publication_quality_tier", pd.Series("", index=source.index)).astype(str).str.lower()
    path_quality = source.get("path_quality_bucket", pd.Series("", index=source.index)).astype(str).str.lower()
    width = _numeric_column(source, "pattern_width_bars")
    height = _numeric_column(source, "pattern_height_pct")
    price_limit_proxy = _numeric_column(source, "price_limit_proxy_rate_60d")

    mask = source["_visual_score"] >= max(70.0, float(source["_visual_score"].quantile(0.55)))
    if tier.notna().any():
        mask &= ~tier.isin({"data_limited", "loose", "poor", "nan"})
    if publication_tier.notna().any():
        # Publication tier can be low because the example failed after breakout.
        # Do not reject those if the geometric pattern tier itself is clean.
        mask &= ~publication_tier.isin({"data_limited", "poor", "nan"})
    if path_quality.notna().any():
        cleanish = path_quality.isin({"clean", "stale_close", ""})
        if cleanish.any():
            mask &= cleanish
    if width.notna().sum() >= 8:
        lower = float(width.quantile(0.05))
        upper = float(width.quantile(0.85))
        mask &= width.between(lower, upper, inclusive="both")
    if height.notna().sum() >= 8:
        lower = float(height.quantile(0.05))
        upper = float(height.quantile(0.92))
        mask &= height.between(lower, upper, inclusive="both")
    if price_limit_proxy.notna().sum() >= 8:
        ceiling = max(10.0, float(price_limit_proxy.quantile(0.80)))
        if "three_falling_peaks" in pattern_id or "three_rising_valleys" in pattern_id or "triple_tops" in pattern_id or "triple_bottoms" in pattern_id:
            ceiling = min(ceiling, 10.0)
        mask &= price_limit_proxy <= ceiling

    if "flag" in pattern_id or "pennant" in pattern_id:
        pole = _numeric_column(source, "pole_move_pct")
        ratio = _numeric_column(source, "flag_to_pole_pct")
        if pole.notna().sum() >= 8:
            mask &= pole >= float(pole.quantile(0.35))
        if ratio.notna().sum() >= 8:
            mask &= ratio <= float(ratio.quantile(0.80))
    if "head_and_shoulders" in pattern_id:
        prominence = _numeric_column(source, "head_prominence_pct")
        shoulder_diff = _numeric_column(source, "shoulder_diff_pct")
        if prominence.notna().sum() >= 5:
            mask &= prominence >= float(prominence.quantile(0.25))
        if shoulder_diff.notna().sum() >= 5:
            mask &= shoulder_diff <= float(shoulder_diff.quantile(0.80))
    if "cup_with_handle" in pattern_id:
        handle_pos = _numeric_column(source, "handle_pos_pct")
        handle_retrace = _numeric_column(source, "handle_retrace_pct")
        if handle_pos.notna().sum() >= 8:
            mask &= handle_pos.between(float(handle_pos.quantile(0.15)), float(handle_pos.quantile(0.90)), inclusive="both")
        if handle_retrace.notna().sum() >= 8:
            mask &= handle_retrace <= float(handle_retrace.quantile(0.85))

    visual = source[mask].copy()
    if len(visual) < 3:
        relaxed = source[source["_visual_score"] >= max(65.0, float(source["_visual_score"].quantile(0.35)))].copy()
        visual = relaxed if not relaxed.empty else source.copy()
    return _add_visual_sort_columns(visual)


def _add_visual_sort_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if out.empty:
        return out
    score = pd.Series(np.nan, index=out.index, dtype=float)
    for column in ("manual_visual_score_1_to_5", "pattern_quality_score", "publication_quality_score", "tradability_quality_score"):
        if column not in out.columns:
            continue
        current = pd.to_numeric(out[column], errors="coerce")
        if column == "manual_visual_score_1_to_5":
            current = current * 20.0
        score = score.fillna(current)
    out["_visual_score"] = score.fillna(50.0).clip(0.0, 100.0)
    width = _numeric_column(out, "pattern_width_bars")
    height = _numeric_column(out, "pattern_height_pct")
    out["_width_distance"] = 0.0
    if width.notna().any():
        out["_width_distance"] = (width - float(width.median())).abs()
    out["_height_distance"] = 0.0
    if height.notna().any():
        out["_height_distance"] = (height - float(height.median())).abs()
    return out


def _event_key(row: Mapping[str, Any]) -> str:
    detection_id = str(row.get("detection_id") or row.get("event_id") or "").strip()
    if detection_id:
        return detection_id
    return "|".join(str(row.get(part) or "").strip() for part in ("symbol", "ticker", "breakout_date"))


def _select_examples(events: pd.DataFrame, existing: Mapping[str, Any] | None, pattern_id: str) -> dict[str, Mapping[str, Any]]:
    selected: dict[str, Mapping[str, Any]] = {}
    if events.empty:
        return selected
    source = _ranked_source(events)
    if source.empty:
        return selected
    source = _add_visual_sort_columns(source)
    visual_source = _visual_candidate_source(events, pattern_id)
    used = {_event_key(v) for v in selected.values()}

    def pick(frame: pd.DataFrame, sort_cols: list[str], ascending: list[bool], *, prefer_market: bool = True) -> Mapping[str, Any] | None:
        pool = frame.copy()
        if used:
            pool = pool[[(_event_key(row.to_dict()) not in used) for _, row in pool.iterrows()]]
        if pool.empty:
            return None
        if prefer_market and "_market_rank" in pool.columns and len(pool) >= 3:
            preferred = pool[pd.to_numeric(pool["_market_rank"], errors="coerce") <= 1]
            if not preferred.empty and len(preferred) < len(pool):
                visual_floor = float(pd.to_numeric(pool.get("_visual_score"), errors="coerce").quantile(0.35)) if "_visual_score" in pool.columns else 0.0
                width_ceiling = float(pd.to_numeric(pool.get("_width_distance"), errors="coerce").quantile(0.75)) if "_width_distance" in pool.columns else math.inf
                height_ceiling = float(pd.to_numeric(pool.get("_height_distance"), errors="coerce").quantile(0.85)) if "_height_distance" in pool.columns else math.inf
                preferred = preferred[
                    (pd.to_numeric(preferred.get("_visual_score"), errors="coerce").fillna(50.0) >= visual_floor)
                    & (pd.to_numeric(preferred.get("_width_distance"), errors="coerce").fillna(0.0) <= width_ceiling)
                    & (pd.to_numeric(preferred.get("_height_distance"), errors="coerce").fillna(0.0) <= height_ceiling)
                ]
                if not preferred.empty:
                    pool = preferred
        cols = [col for col in sort_cols if col in pool.columns]
        pool = pool.sort_values(cols, ascending=ascending[: len(cols)]) if cols else pool
        return pool.iloc[0].to_dict()

    success = visual_source
    if {"target_hit", "target_first_before_adverse_5pct"}.issubset(visual_source.columns):
        success = visual_source[visual_source["target_hit"] & visual_source["target_first_before_adverse_5pct"]]
    if success.empty and {"target_hit", "target_first_before_adverse_5pct"}.issubset(source.columns):
        success = source[source["target_hit"] & source["target_first_before_adverse_5pct"]]
    row = pick(success if not success.empty else visual_source, ["_width_distance", "_height_distance", "_visual_score", "_market_rank", "mfe_pct"], [True, True, False, True, False])
    if row:
        selected["textbook_success"] = row
        used.add(_event_key(row))

    failure = visual_source[visual_source["failure_5pct"]] if "failure_5pct" in visual_source.columns else visual_source.iloc[:0]
    if failure.empty and "failure_5pct" in source.columns:
        failure = source[source["failure_5pct"]]
    row = pick(failure if not failure.empty else visual_source, ["_width_distance", "_height_distance", "_visual_score", "_market_rank", "mae_pct"], [True, True, False, True, False])
    if row:
        selected["failure"] = row
        used.add(_event_key(row))

    middle = visual_source.copy()
    if len(middle) < 3:
        middle = source.copy()
    if "mfe_pct" in middle.columns:
        med = float(pd.to_numeric(source["mfe_pct"], errors="coerce").median()) if "mfe_pct" in source.columns else float(pd.to_numeric(middle["mfe_pct"], errors="coerce").median())
        middle["_median_distance"] = (pd.to_numeric(middle["mfe_pct"], errors="coerce") - med).abs()
    row = pick(middle, ["_median_distance", "_visual_score", "_width_distance", "_height_distance", "_market_rank"], [True, False, True, True, True], prefer_market=False)
    if row:
        selected["middle_case"] = row
        used.add(_event_key(row))
    for role in ("textbook_success", "middle_case", "failure"):
        if role in selected:
            continue
        row = pick(source, ["_visual_score", "_width_distance", "_height_distance", "_market_rank"], [False, True, True, True])
        if row:
            selected[role] = row
            used.add(_event_key(row))
    return selected


def _draw_candles(ax: Any, df: pd.DataFrame) -> None:
    for i, row in df.iterrows():
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        color = "#16865c" if c >= o else "#c84c4c"
        ax.vlines(i, l, h, color="#333333", linewidth=0.65, alpha=0.75, zorder=2)
        ax.add_patch(Rectangle((i - 0.31, min(o, c)), 0.62, max(abs(c - o), 1e-6), facecolor=color, edgecolor=color, linewidth=0.45, alpha=0.9, zorder=3))
    ax.plot(np.arange(len(df)), df["close"].to_numpy(), color="#111111", linewidth=0.85, alpha=0.26, zorder=1)


def _annotate(ax: Any, x: float, y: float, text: str, color: str) -> None:
    ax.text(x, y, text, fontsize=7.6, color=color, va="bottom", ha="left", bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.72, "pad": 1.0}, zorder=8)


def _trend_pair(ax: Any, *, event: Mapping[str, Any], df: pd.DataFrame, offset: int, prefix: str, label_upper: str, label_lower: str, color: str = "#245b5a") -> bool:
    vals = [_num(event.get(f"{prefix}_{part}")) for part in ("upper_idx0", "upper_price0", "upper_slope_per_bar", "lower_idx0", "lower_price0", "lower_slope_per_bar")]
    if any(v is None for v in vals):
        return False
    upper_idx0, upper_p0, upper_slope, lower_idx0, lower_p0, lower_slope = [float(v) for v in vals if v is not None]
    fs = _nearest_idx(df, _date(event.get("formation_start_date")))
    fe = _nearest_idx(df, _date(event.get("formation_end_date")))
    bd = _nearest_idx(df, _date(event.get("breakout_date")))
    start = 0 if fs is None else fs
    stop = max(start + 1, bd if bd is not None else (fe if fe is not None else len(df) - 1))
    xs = np.arange(start, min(len(df), stop + 1))
    if len(xs) == 0:
        return False
    gx = xs + int(offset)
    uy = upper_p0 + upper_slope * (gx - upper_idx0)
    ly = lower_p0 + lower_slope * (gx - lower_idx0)
    ax.plot(xs, uy, color=color, linewidth=1.35, alpha=0.9, zorder=5)
    ax.plot(xs, ly, color=color, linewidth=1.35, alpha=0.9, zorder=5)
    _annotate(ax, float(xs[max(0, len(xs) // 4)]), float(uy[max(0, len(uy) // 4)]), label_upper, color)
    _annotate(ax, float(xs[max(0, len(xs) // 2)]), float(ly[max(0, len(ly) // 2)]), label_lower, color)
    return True


def _horizontal_band(ax: Any, df: pd.DataFrame, *, event: Mapping[str, Any], top: float | None, bottom: float | None, top_label: str, bottom_label: str, color: str = "#245b5a") -> bool:
    if top is None or bottom is None:
        return False
    fs = _nearest_idx(df, _date(event.get("formation_start_date"))) or 0
    fe = _nearest_idx(df, _date(event.get("formation_end_date"))) or max(fs + 1, len(df) - 1)
    ax.hlines(float(top), fs, fe, color=color, linewidth=1.25, alpha=0.9, zorder=5)
    ax.hlines(float(bottom), fs, fe, color=color, linewidth=1.25, alpha=0.9, zorder=5)
    ax.fill_between([fs, fe], [float(top), float(top)], [float(bottom), float(bottom)], color=color, alpha=0.035, zorder=0)
    _annotate(ax, fs + 0.4, float(top), top_label, color)
    _annotate(ax, fs + 0.4, float(bottom), bottom_label, color)
    return True


def _label_extrema(ax: Any, df: pd.DataFrame, event: Mapping[str, Any], pattern_id: str) -> None:
    fs = _nearest_idx(df, _date(event.get("formation_start_date"))) or 0
    fe = _nearest_idx(df, _date(event.get("formation_end_date"))) or max(fs + 1, len(df) - 1)
    seg = df.iloc[fs : fe + 1]
    if seg.empty:
        return
    is_top = "top" in pattern_id or str(event.get("breakout_direction")).lower() == "down"
    col = "high" if is_top else "low"
    mid = fs + max(1, len(seg) // 2)
    first, second = df.iloc[fs:mid], df.iloc[mid : fe + 1]
    if first.empty or second.empty:
        return
    labels = ("đỉnh 1", "đỉnh 2") if is_top else ("đáy 1", "đáy 2")
    idxs = [int(first[col].idxmax() if is_top else first[col].idxmin()), int(second[col].idxmax() if is_top else second[col].idxmin())]
    for idx, label in zip(idxs, labels):
        y = float(df.loc[idx, col])
        ax.scatter([idx], [y], s=28, color="#6f4aa8", zorder=7)
        _annotate(ax, idx + 0.25, y, label, "#6f4aa8")


def _label_head_shoulders(ax: Any, df: pd.DataFrame, event: Mapping[str, Any], pattern_id: str) -> None:
    fs = _nearest_idx(df, _date(event.get("formation_start_date"))) or 0
    fe = _nearest_idx(df, _date(event.get("formation_end_date"))) or max(fs + 1, len(df) - 1)
    is_top = "tops" in pattern_id
    col = "high" if is_top else "low"
    for seg, label in zip(np.array_split(np.arange(fs, fe + 1), 3), ("vai trái", "đầu", "vai phải")):
        if len(seg) == 0:
            continue
        sub = df.iloc[seg]
        idx = int(sub[col].idxmax() if is_top else sub[col].idxmin())
        y = float(df.loc[idx, col])
        ax.scatter([idx], [y], s=30, color="#6f4aa8", zorder=7)
        _annotate(ax, idx + 0.25, y, label, "#6f4aa8")


def _label_cup_handle(ax: Any, df: pd.DataFrame, event: Mapping[str, Any], pattern_id: str) -> None:
    fs = _nearest_idx(df, _date(event.get("formation_start_date"))) or 0
    fe = _nearest_idx(df, _date(event.get("formation_end_date"))) or max(fs + 1, len(df) - 1)
    inverted = "inverted" in pattern_id
    col = "high" if inverted else "low"
    seg = df.iloc[fs : fe + 1]
    if seg.empty:
        return
    extreme = int(seg[col].idxmax() if inverted else seg[col].idxmin())
    _annotate(ax, fs + 0.4, float(df.iloc[fs]["close"]), "vành trái", "#245b5a")
    _annotate(ax, extreme + 0.25, float(df.loc[extreme, col]), "đỉnh cốc" if inverted else "đáy cốc", "#245b5a")
    _annotate(ax, max(fs, fe - max(2, (fe - fs) // 5)), float(df.iloc[fe]["close"]), "tay cầm", "#245b5a")


def _label_three_peaks_valleys(ax: Any, df: pd.DataFrame, event: Mapping[str, Any], pattern_id: str, offset: int) -> bool:
    is_peaks = "three_falling_peaks" in pattern_id or "triple_tops" in pattern_id
    is_triple = "triple_tops" in pattern_id or "triple_bottoms" in pattern_id
    labels = ("đỉnh 1", "đáy xác nhận", "đỉnh 2", "đáy xác nhận", "đỉnh 3") if is_peaks and is_triple else (
        ("đỉnh 1", "đáy xen giữa", "đỉnh 2", "đáy xen giữa", "đỉnh 3") if is_peaks else (
        "đáy 1",
        "đỉnh xác nhận" if is_triple else "đỉnh xen giữa",
        "đáy 2",
        "đỉnh xác nhận" if is_triple else "đỉnh xen giữa",
        "đáy 3",
        )
    )
    color = "#6f4aa8"
    plotted = False
    for i, label in enumerate(labels, start=1):
        pivot_idx = _num(event.get(f"pivot_{i}_idx"))
        pivot_price = _num(event.get(f"pivot_{i}_price"))
        if pivot_idx is None or pivot_price is None:
            continue
        local_idx = int(round(pivot_idx - offset))
        if local_idx < 0 or local_idx >= len(df):
            continue
        ax.scatter([local_idx], [pivot_price], s=30, color=color, zorder=7)
        _annotate(ax, local_idx + 0.25, pivot_price, label, color)
        plotted = True
    if plotted:
        boundary = _num(event.get("boundary_price"))
        if boundary is not None:
            ax.axhline(boundary, color="#245b5a", linestyle="-", linewidth=1.15, alpha=0.85, zorder=5)
            _annotate(ax, 0.5, boundary, "đường xác nhận", "#245b5a")
        return True

    fs = _nearest_idx(df, _date(event.get("formation_start_date"))) or 0
    fe = _nearest_idx(df, _date(event.get("formation_end_date"))) or max(fs + 1, len(df) - 1)
    segments = np.array_split(np.arange(fs, fe + 1), 5)
    extrema_col = "high" if is_peaks else "low"
    for seg, label in zip(segments, labels):
        if len(seg) == 0:
            continue
        sub = df.iloc[seg]
        idx = int(sub[extrema_col].idxmax() if is_peaks else sub[extrema_col].idxmin())
        y = float(df.loc[idx, extrema_col])
        ax.scatter([idx], [y], s=30, color=color, zorder=7)
        _annotate(ax, idx + 0.25, y, label, color)
        plotted = True
    return plotted


def _label_gap(ax: Any, df: pd.DataFrame, event: Mapping[str, Any]) -> bool:
    gap_top = _num(event.get("gap_top_price"))
    gap_bottom = _num(event.get("gap_bottom_price"))
    bd = _nearest_idx(df, _date(event.get("breakout_date")))
    if gap_top is None or gap_bottom is None or bd is None:
        return False
    top = max(gap_top, gap_bottom)
    bottom = min(gap_top, gap_bottom)
    if top <= bottom:
        return False
    start = max(0, bd - 1)
    stop = min(len(df) - 1, bd + 1)
    ax.axhspan(bottom, top, xmin=max(0.0, (start + 0.5) / max(len(df), 1)), xmax=min(1.0, (stop + 0.5) / max(len(df), 1)), color="#6baed6", alpha=0.22, zorder=0)
    ax.hlines([top, bottom], start, stop, color="#245b5a", linestyle=":", linewidth=1.05, alpha=0.9, zorder=5)
    direction = str(event.get("gap_direction") or event.get("breakout_direction") or "").lower()
    close_label = ""
    if "gap_closed_20d" in event:
        close_label = " - đã đóng trong 20 phiên" if _truthy(event.get("gap_closed_20d")) else " - chưa đóng trong 20 phiên"
    label = "gap lên" if direction == "up" else "gap xuống" if direction == "down" else "khoảng trống giá"
    _annotate(ax, float(bd) + 0.25, top, f"{label}{close_label}", "#245b5a")
    _annotate(ax, max(0.5, float(start)), bottom, "vùng gap", "#245b5a")
    return True


def _label_diamond(ax: Any, df: pd.DataFrame, event: Mapping[str, Any], offset: int) -> bool:
    raw_indices = event.get("pivot_indices")
    raw_prices = event.get("pivot_prices")
    if isinstance(raw_indices, str):
        try:
            import ast

            raw_indices = ast.literal_eval(raw_indices)
        except Exception:
            raw_indices = None
    if isinstance(raw_prices, str):
        try:
            import ast

            raw_prices = ast.literal_eval(raw_prices)
        except Exception:
            raw_prices = None
    if isinstance(raw_indices, (list, tuple)) and isinstance(raw_prices, (list, tuple)) and len(raw_indices) == len(raw_prices) and len(raw_indices) >= 5:
        points = []
        for idx, price in zip(raw_indices, raw_prices):
            idx_num = _num(idx)
            price_num = _num(price)
            if idx_num is None or price_num is None:
                continue
            local_idx = int(round(idx_num - offset))
            if 0 <= local_idx < len(df):
                points.append((local_idx, float(price_num)))
        if len(points) >= 4:
            ax.plot([x for x, _ in points], [y for _, y in points], color="#245b5a", linewidth=1.25, alpha=0.92, zorder=6)
            for n, (x, y) in enumerate(points, start=1):
                ax.scatter([x], [y], s=22, color="#6f4aa8", zorder=7)
                if n in (1, len(points) // 2, len(points)):
                    _annotate(ax, x + 0.2, y, "pivot", "#6f4aa8")
            _annotate(ax, points[0][0] + 0.2, points[0][1], "mở rộng", "#245b5a")
            _annotate(ax, points[-2][0] + 0.2, points[-2][1], "thu hẹp", "#245b5a")
            return True
    top = _num(event.get("high_boundary_price"))
    bottom = _num(event.get("low_boundary_price"))
    if _horizontal_band(ax, df, event=event, top=top, bottom=bottom, top_label="đỉnh diamond", bottom_label="đáy diamond", color="#245b5a"):
        _annotate(ax, 0.5, (float(top) + float(bottom)) / 2.0 if top is not None and bottom is not None else float(df["close"].median()), "vùng mở rộng rồi thu hẹp", "#245b5a")
        return True
    return False


def _label_dead_cat(ax: Any, df: pd.DataFrame, event: Mapping[str, Any], pattern_id: str, offset: int) -> bool:
    def local_idx(name: str) -> int | None:
        value = _num(event.get(name))
        if value is None:
            return None
        idx = int(round(value - offset))
        return idx if 0 <= idx < len(df) else None

    if pattern_id == "dead_cat_bounce":
        event_start = local_idx("event_start_idx")
        event_low = local_idx("event_low_idx")
        bounce_high = local_idx("bounce_high_idx")
        if event_start is None or event_low is None or bounce_high is None:
            return False
        low_price = _num(event.get("event_low_price"))
        bounce_price = _num(event.get("bounce_high_price"))
        if low_price is None or bounce_price is None:
            return False
        ax.axvspan(event_start, bounce_high, color="#6baed6", alpha=0.12, zorder=0)
        ax.scatter([event_low, bounce_high], [low_price, bounce_price], s=26, color=["#C43B3B", "#7A5195"], zorder=7)
        _annotate(ax, event_start + 0.2, float(df.iloc[event_start]["high"]), "cú rơi", "#C43B3B")
        _annotate(ax, event_low + 0.2, low_price, "đáy sự kiện", "#C43B3B")
        _annotate(ax, bounce_high + 0.2, bounce_price, "đỉnh hồi", "#7A5195")
        return True

    if pattern_id == "dead_cat_bounce_inverted":
        fs = _nearest_idx(df, _date(event.get("formation_start_date")))
        fe = _nearest_idx(df, _date(event.get("formation_end_date")))
        if fs is None or fe is None:
            return False
        ref = _num(event.get("reference_close"))
        ax.axvspan(fs, fe, color="#6baed6", alpha=0.12, zorder=0)
        ax.scatter([fs, fe], [float(df.iloc[fs]["close"]), float(df.iloc[fe]["close"])], s=26, color=["#2E8B57", "#7A5195"], zorder=7)
        _annotate(ax, fs + 0.2, float(df.iloc[fs]["high"]), "cú tăng", "#2E8B57")
        _annotate(ax, fe + 0.2, float(df.iloc[fe]["high"]), "ngày thứ hai", "#7A5195")
        if ref is not None:
            ax.axhline(ref, color="#C43B3B", linestyle="--", linewidth=1.0, alpha=0.82, zorder=5)
            _annotate(ax, max(0.5, fs - 1), ref, "vùng trước cú tăng", "#C43B3B")
        return True
    return False


def _label_inside_day(ax: Any, df: pd.DataFrame, event: Mapping[str, Any]) -> bool:
    fs = _nearest_idx(df, _date(event.get("formation_start_date")))
    fe = _nearest_idx(df, _date(event.get("formation_end_date")))
    if fs is None or fe is None:
        return False
    mother_high = _num(event.get("mother_bar_high"))
    mother_low = _num(event.get("mother_bar_low"))
    inside_high = _num(event.get("inside_day_high"))
    inside_low = _num(event.get("inside_day_low"))
    if None in (mother_high, mother_low, inside_high, inside_low):
        return False
    ax.axvspan(fs - 0.5, fs + 0.5, color="#9ecae1", alpha=0.16, zorder=0)
    ax.axvspan(fe - 0.5, fe + 0.5, color="#4C78A8", alpha=0.18, zorder=0)
    ax.axhline(mother_high, color="#7f7f7f", linestyle=":", linewidth=0.95, alpha=0.75, zorder=4)
    ax.axhline(mother_low, color="#7f7f7f", linestyle=":", linewidth=0.95, alpha=0.75, zorder=4)
    ax.axhline(inside_high, color="#245b5a", linestyle="-", linewidth=1.1, alpha=0.9, zorder=5)
    ax.axhline(inside_low, color="#245b5a", linestyle="-", linewidth=1.1, alpha=0.9, zorder=5)
    _annotate(ax, fs + 0.12, mother_high, "biên nến mẹ", "#7f7f7f")
    _annotate(ax, fe + 0.12, inside_high, "đỉnh nến trong", "#245b5a")
    _annotate(ax, fe + 0.12, inside_low, "đáy nến trong", "#245b5a")
    ax.text(fs, float(df["low"].min()), "nến mẹ", ha="center", va="bottom", fontsize=7.5, color="#377aa3", zorder=8)
    ax.text(fe, float(df["low"].min()), "nến trong", ha="center", va="bottom", fontsize=7.5, color="#245b5a", zorder=8)
    return True


def _label_three_methods(ax: Any, df: pd.DataFrame, event: Mapping[str, Any], pattern_id: str) -> bool:
    fs = _nearest_idx(df, _date(event.get("formation_start_date")))
    fe = _nearest_idx(df, _date(event.get("formation_end_date")))
    if fs is None or fe is None or fe - fs < 4:
        return False
    first_high = _num(event.get("first_bar_high"))
    first_low = _num(event.get("first_bar_low"))
    if None in (first_high, first_low):
        return False
    ax.axvspan(fs - 0.5, fe + 0.5, color="#6baed6", alpha=0.10, zorder=0)
    ax.axvspan(fs - 0.5, fs + 0.5, color="#245b5a", alpha=0.14, zorder=0)
    ax.axvspan(fs + 0.5, fe - 0.5, color="#9ecae1", alpha=0.14, zorder=0)
    ax.axvspan(fe - 0.5, fe + 0.5, color="#7A5195", alpha=0.15, zorder=0)
    ax.axhline(first_high, color="#245b5a", linestyle="--", linewidth=1.0, alpha=0.82, zorder=5)
    ax.axhline(first_low, color="#245b5a", linestyle="--", linewidth=1.0, alpha=0.82, zorder=5)
    _annotate(ax, fs + 0.15, first_high, "biên nến đầu", "#245b5a")
    ax.text(fs, float(df["low"].min()), "nến đầu", ha="center", va="bottom", fontsize=7.5, color="#245b5a", zorder=8)
    ax.text((fs + fe) / 2, float(df["low"].min()), "3 nến nghỉ", ha="center", va="bottom", fontsize=7.5, color="#377aa3", zorder=8)
    ax.text(fe, float(df["low"].min()), "xác nhận", ha="center", va="bottom", fontsize=7.5, color="#7A5195", zorder=8)
    label = "đóng cửa vượt biên trên" if pattern_id == "rising_three_methods" else "đóng cửa vượt biên dưới"
    y = first_high if pattern_id == "rising_three_methods" else first_low
    _annotate(ax, fe + 0.12, y, label, "#7A5195")
    return True


def _draw_geometry(ax: Any, df: pd.DataFrame, event: Mapping[str, Any], pattern_id: str, offset: int) -> None:
    if pattern_id in {"rising_three_methods", "falling_three_methods"}:
        if _label_three_methods(ax, df, event, pattern_id):
            return
    if pattern_id == "inside_day":
        if _label_inside_day(ax, df, event):
            return
    if "dead_cat_bounce" in pattern_id:
        if _label_dead_cat(ax, df, event, pattern_id, offset):
            return
    if "diamond" in pattern_id:
        if _label_diamond(ax, df, event, offset):
            return
    if "gap" in pattern_id or event.get("gap_top_price") is not None:
        if _label_gap(ax, df, event):
            return
    if "three_falling_peaks" in pattern_id or "three_rising_valleys" in pattern_id or "triple_tops" in pattern_id or "triple_bottoms" in pattern_id:
        if _label_three_peaks_valleys(ax, df, event, pattern_id, offset):
            return
    if _trend_pair(ax, event=event, df=df, offset=offset, prefix="flag", label_upper="biên trên thân mẫu", label_lower="biên dưới thân mẫu"):
        fs = _nearest_idx(df, _date(event.get("formation_start_date"))) or 0
        pole_bars = int(_num(event.get("pole_bars")) or 0)
        if pole_bars > 0:
            start = max(0, fs - pole_bars)
            ax.annotate("nhịp dẫn trước", xy=(fs, float(df.iloc[fs]["close"])), xytext=(start, float(df.iloc[start]["close"])), arrowprops={"arrowstyle": "->", "color": "#555555", "lw": 1.0}, fontsize=7.5, color="#555555", zorder=8)
        return
    for prefix, upper, lower in (
        ("triangle", "biên trên", "biên dưới"),
        ("wedge", "biên trên nêm", "biên dưới nêm"),
        ("broadening", "biên mở rộng trên", "biên mở rộng dưới"),
    ):
        if _trend_pair(ax, event=event, df=df, offset=offset, prefix=prefix, label_upper=upper, label_lower=lower):
            return
    if _horizontal_band(ax, df, event=event, top=_num(event.get("rectangle_resistance")), bottom=_num(event.get("rectangle_support")), top_label="kháng cự hộp", bottom_label="hỗ trợ hộp"):
        return
    neckline = _num(event.get("neckline_price"))
    if neckline is not None:
        ax.axhline(neckline, color="#245b5a", linestyle="-", linewidth=1.25, alpha=0.9, zorder=5)
        _annotate(ax, 0.5, neckline, "đường cổ / neckline", "#245b5a")
        _label_head_shoulders(ax, df, event, pattern_id) if "head_and_shoulders" in pattern_id else _label_extrema(ax, df, event, pattern_id)
        return
    if "cup_with_handle" in pattern_id:
        _label_cup_handle(ax, df, event, pattern_id)
        return
    _label_extrema(ax, df, event, pattern_id)


def render_canonical_example_chart(*, price_db: Path, event: Mapping[str, Any], pattern_id: str, out_path: Path, title: str) -> bool:
    symbol = str(event.get("symbol") or event.get("ticker") or "").strip()
    if not symbol:
        return False
    raw = _load_ohlcv(price_db, symbol)
    df, offset = _slice_window(raw, event)
    if df.empty:
        return False
    fs = _date(event.get("formation_start_date") or event.get("formation_start"))
    fe = _date(event.get("formation_end_date") or event.get("formation_end"))
    bd = _date(event.get("breakout_date"))
    i0, i1, ib = _nearest_idx(df, fs), _nearest_idx(df, fe), _nearest_idx(df, bd)
    direction = str(event.get("breakout_direction") or "").lower()
    fig, ax = plt.subplots(figsize=(10.4, 5.35), dpi=185)
    _draw_candles(ax, df)
    if i0 is not None and i1 is not None and i1 >= i0:
        ax.axvspan(i0 - 0.5, i1 + 0.5, color="#6baed6", alpha=0.16, zorder=0)
        ax.axvline(i0, color="#6baed6", linewidth=0.8, alpha=0.65)
        ax.axvline(i1, color="#6baed6", linewidth=0.8, alpha=0.65)
        ax.text(i0 + 0.2, float(df["high"].max()), "vùng hình thái", fontsize=7.5, color="#377aa3", va="top")
    _draw_geometry(ax, df, event, pattern_id, offset)
    if ib is not None:
        ax.axvline(ib, color="#7A5195", linewidth=1.25, alpha=0.95, zorder=6)
        ax.text(ib + 0.25, float(df["high"].max()), "phá vỡ lên" if direction == "up" else "phá vỡ xuống" if direction == "down" else "phá vỡ", fontsize=8, color="#7A5195", va="bottom", zorder=8)
    breakout_price, target_price = _num(event.get("breakout_price")), _num(event.get("target_price"))
    if breakout_price is not None:
        ax.axhline(breakout_price, color="#245b5a", linestyle="--", linewidth=0.95, alpha=0.85, zorder=4)
        _annotate(ax, 0.5, breakout_price, "giá phá vỡ", "#245b5a")
    if target_price is not None:
        ax.axhline(target_price, color="#e98b2a", linestyle="--", linewidth=0.95, alpha=0.9, zorder=4)
        _annotate(ax, 0.5, target_price, "mục tiêu", "#e98b2a")
    ax.set_title(title, fontsize=10.5, loc="left")
    ax.grid(True, alpha=0.14)
    y_values = [float(df["low"].min()), float(df["high"].max())] + [v for v in (breakout_price, target_price) if v is not None]
    y_min, y_max = min(y_values), max(y_values)
    pad = max(0.01, (y_max - y_min) * 0.10)
    ax.set_ylim(y_min - pad, y_max + pad)
    ax.set_xlim(-1, len(df))
    ticks = list(range(0, len(df), max(1, len(df) // 8)))
    ax.set_xticks(ticks)
    ax.set_xticklabels([pd.to_datetime(df.iloc[i]["date"]).strftime("%Y-%m-%d") for i in ticks], rotation=35, ha="right", fontsize=7.5)
    ax.tick_params(axis="y", labelsize=7.5)
    fig.subplots_adjust(left=0.07, right=0.985, top=0.90, bottom=0.18)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    return True


def build_canonical_example_charts(
    *,
    pattern_id: str,
    events: pd.DataFrame,
    existing_examples: Mapping[str, Any] | None,
    out_dir: Path,
    price_db: Path = DEFAULT_PRICE_DB,
    schematic: Path | None = None,
) -> tuple[dict[str, Path], dict[str, Mapping[str, Any]], dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    charts: dict[str, Path] = {}
    if schematic and schematic.exists():
        schematic_target = out_dir / schematic.name
        if schematic.resolve() != schematic_target.resolve():
            shutil.copy2(schematic, schematic_target)
        charts["schematic"] = schematic_target
    selected = _select_examples(events, existing_examples, pattern_id)
    title_map = {"textbook_success": "ví dụ đạt mục tiêu", "middle_case": "ví dụ trung vị", "failure": "ví dụ thất bại"}
    failures: list[dict[str, str]] = []
    for key in ("textbook_success", "middle_case", "failure"):
        event = selected.get(key)
        if not event:
            failures.append({"key": key, "reason": "missing_event"})
            continue
        symbol = str(event.get("symbol") or event.get("ticker") or "UNKNOWN")
        breakout_date = str(event.get("breakout_date") or "unknown")
        out_path = out_dir / f"{key}_{symbol}_{breakout_date}.png"
        title = f"{symbol} - {title_map[key]} ({breakout_date})"
        if render_canonical_example_chart(price_db=price_db, event=event, pattern_id=pattern_id, out_path=out_path, title=title):
            charts[key] = out_path
        else:
            failures.append({"key": key, "reason": "render_failed"})
    report = {"status": "PASS" if not failures else "WARN", "pattern_id": pattern_id, "chart_dir": str(out_dir), "rendered_keys": sorted(charts.keys()), "failures": failures}
    return charts, selected, report
