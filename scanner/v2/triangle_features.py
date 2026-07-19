"""Source-grounded diagnostics shared by Triangle Family scanners."""

from __future__ import annotations

import math
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd


def _safe_float(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def line_value(*, idx0: int, price0: float, slope_per_bar: float, idx: int) -> float:
    return float(price0) + float(slope_per_bar) * (int(idx) - int(idx0))


def line_value_from_detection(row: Mapping[str, Any], *, side: str, idx: int) -> Optional[float]:
    try:
        return line_value(
            idx0=int(row[f"triangle_{side}_idx0"]),
            price0=float(row[f"triangle_{side}_price0"]),
            slope_per_bar=float(row[f"triangle_{side}_slope_per_bar"]),
            idx=int(idx),
        )
    except (KeyError, TypeError, ValueError):
        return None


def triangle_apex_metrics(
    *,
    upper_idx0: int,
    upper_price0: float,
    upper_slope_per_bar: float,
    lower_idx0: int,
    lower_price0: float,
    lower_slope_per_bar: float,
    formation_start_idx: int,
    breakout_idx: int,
) -> dict[str, Any]:
    upper_intercept = float(upper_price0) - float(upper_slope_per_bar) * int(upper_idx0)
    lower_intercept = float(lower_price0) - float(lower_slope_per_bar) * int(lower_idx0)
    slope_delta = float(upper_slope_per_bar) - float(lower_slope_per_bar)
    if abs(slope_delta) < 1e-12:
        return {"apex_idx": None, "apex_progress_pct": None, "bars_to_apex": None}
    apex = (lower_intercept - upper_intercept) / slope_delta
    if not math.isfinite(apex):
        return {"apex_idx": None, "apex_progress_pct": None, "bars_to_apex": None}
    progress = None
    if apex > int(formation_start_idx):
        progress = (int(breakout_idx) - int(formation_start_idx)) / max(apex - int(formation_start_idx), 1e-9) * 100.0
    return {
        "apex_idx": round(float(apex), 2),
        "apex_progress_pct": round(float(progress), 2) if progress is not None else None,
        "bars_to_apex": round(float(apex - int(breakout_idx)), 2),
    }


def triangle_crossing_metrics(
    df: pd.DataFrame,
    *,
    formation_start_idx: int,
    formation_end_idx: int,
    upper_idx0: int,
    upper_price0: float,
    upper_slope_per_bar: float,
    lower_idx0: int,
    lower_price0: float,
    lower_slope_per_bar: float,
    touch_tolerance_pct: float = 2.0,
) -> dict[str, Any]:
    start = int(formation_start_idx)
    end = int(formation_end_idx)
    if df.empty or end < start:
        return {
            "upper_touch_count": 0,
            "lower_touch_count": 0,
            "triangle_crossing_count": 0,
            "triangle_white_space_score": None,
        }
    side_values: list[int] = []
    normalized_positions: list[float] = []
    upper_touches = 0
    lower_touches = 0
    tol = max(float(touch_tolerance_pct), 0.0) / 100.0
    for idx in range(start, min(end + 1, len(df))):
        row = df.iloc[idx]
        upper = line_value(idx0=upper_idx0, price0=upper_price0, slope_per_bar=upper_slope_per_bar, idx=idx)
        lower = line_value(idx0=lower_idx0, price0=lower_price0, slope_per_bar=lower_slope_per_bar, idx=idx)
        if upper <= lower or upper <= 0 or lower <= 0:
            continue
        high = _safe_float(row.get("high"))
        low = _safe_float(row.get("low"))
        close = _safe_float(row.get("close"))
        if high is not None and high >= upper * (1.0 - tol):
            upper_touches += 1
        if low is not None and low <= lower * (1.0 + tol):
            lower_touches += 1
        if close is None:
            continue
        midpoint = (upper + lower) / 2.0
        side_values.append(1 if close >= midpoint else -1)
        normalized_positions.append(float(np.clip((close - lower) / max(upper - lower, 1e-9), 0.0, 1.0)))
    crossings = sum(1 for prev, cur in zip(side_values, side_values[1:]) if prev != cur)
    white_space_score = None
    if normalized_positions:
        white_space_score = (max(normalized_positions) - min(normalized_positions)) * 100.0
    return {
        "upper_touch_count": int(upper_touches),
        "lower_touch_count": int(lower_touches),
        "triangle_crossing_count": int(crossings),
        "triangle_white_space_score": round(float(white_space_score), 2) if white_space_score is not None else None,
    }


def volume_trend_metrics(df: pd.DataFrame, *, formation_start_idx: int, formation_end_idx: int) -> dict[str, Any]:
    if df.empty:
        return {"volume_trend_slope_pct_per_bar": None, "volume_trend_direction": "unknown"}
    vols = pd.to_numeric(df.iloc[int(formation_start_idx) : int(formation_end_idx) + 1].get("volume"), errors="coerce").dropna()
    if len(vols) < 3 or float(vols.median()) <= 0:
        return {"volume_trend_slope_pct_per_bar": None, "volume_trend_direction": "unknown"}
    x = np.arange(len(vols), dtype=float)
    slope = float(np.polyfit(x, vols.to_numpy(dtype=float), 1)[0])
    slope_pct = slope / float(vols.median()) * 100.0
    direction = "down" if slope_pct < -1.0 else ("up" if slope_pct > 1.0 else "flat")
    return {"volume_trend_slope_pct_per_bar": round(float(slope_pct), 4), "volume_trend_direction": direction}


def yearly_position_metric(df: pd.DataFrame, *, breakout_idx: int, breakout_price: float) -> dict[str, Any]:
    if df.empty or int(breakout_idx) < 0:
        return {"yearly_range_position_pct": None}
    yearly = df.iloc[max(0, int(breakout_idx) - 251) : int(breakout_idx) + 1]
    if yearly.empty:
        return {"yearly_range_position_pct": None}
    low = _safe_float(pd.to_numeric(yearly.get("low"), errors="coerce").min())
    high = _safe_float(pd.to_numeric(yearly.get("high"), errors="coerce").max())
    price = _safe_float(breakout_price)
    if low is None or high is None or price is None or high <= low:
        return {"yearly_range_position_pct": None}
    return {"yearly_range_position_pct": round(float((price - low) / (high - low) * 100.0), 2)}


def source_grounded_triangle_features(
    df: pd.DataFrame,
    *,
    formation_start_idx: int,
    formation_end_idx: int,
    breakout_idx: int,
    breakout_price: float,
    upper_idx0: int,
    upper_price0: float,
    upper_slope_per_bar: float,
    lower_idx0: int,
    lower_price0: float,
    lower_slope_per_bar: float,
) -> dict[str, Any]:
    features: dict[str, Any] = {}
    features.update(
        triangle_crossing_metrics(
            df,
            formation_start_idx=formation_start_idx,
            formation_end_idx=formation_end_idx,
            upper_idx0=upper_idx0,
            upper_price0=upper_price0,
            upper_slope_per_bar=upper_slope_per_bar,
            lower_idx0=lower_idx0,
            lower_price0=lower_price0,
            lower_slope_per_bar=lower_slope_per_bar,
        )
    )
    features.update(
        triangle_apex_metrics(
            upper_idx0=upper_idx0,
            upper_price0=upper_price0,
            upper_slope_per_bar=upper_slope_per_bar,
            lower_idx0=lower_idx0,
            lower_price0=lower_price0,
            lower_slope_per_bar=lower_slope_per_bar,
            formation_start_idx=formation_start_idx,
            breakout_idx=breakout_idx,
        )
    )
    features.update(volume_trend_metrics(df, formation_start_idx=formation_start_idx, formation_end_idx=formation_end_idx))
    features.update(yearly_position_metric(df, breakout_idx=breakout_idx, breakout_price=breakout_price))
    return features


def triangle_retest_metrics(
    future: pd.DataFrame,
    detection: Mapping[str, Any],
    *,
    tolerance_pct: float = 0.5,
    window_bars: int = 30,
) -> dict[str, Any]:
    if future.empty:
        return {
            "throwback_exact_30d": None,
            "days_to_throwback_exact": None,
            "throwback_to_breakout_30d": None,
            "days_to_throwback_to_breakout": None,
            "throwback_pullback_30d": None,
            "days_to_throwback_pullback": None,
        }
    direction = str(detection.get("breakout_direction") or "up")
    breakout_price = _safe_float(detection.get("breakout_price"))
    breakout_idx = int(detection.get("breakout_idx") or 0)
    if breakout_price is None or breakout_price <= 0:
        return {
            "throwback_exact_30d": None,
            "days_to_throwback_exact": None,
            "throwback_to_breakout_30d": None,
            "days_to_throwback_to_breakout": None,
            "throwback_pullback_30d": None,
            "days_to_throwback_pullback": None,
        }
    tol = max(float(tolerance_pct), 0.0) / 100.0
    window = future.head(int(window_bars)).copy()
    breakout_hit = False
    boundary_hit = False
    breakout_day: Optional[int] = None
    boundary_day: Optional[int] = None
    boundary_side = "upper" if direction == "up" else "lower"
    for offset, (_, row) in enumerate(window.iterrows(), start=1):
        high = _safe_float(row.get("high"))
        low = _safe_float(row.get("low"))
        absolute_idx = breakout_idx + offset
        boundary = line_value_from_detection(detection, side=boundary_side, idx=absolute_idx)
        if direction == "up":
            if not breakout_hit and low is not None and low <= breakout_price * (1.0 + tol):
                breakout_hit = True
                breakout_day = offset
            if boundary is not None and not boundary_hit and low is not None and low <= boundary * (1.0 + tol):
                boundary_hit = True
                boundary_day = offset
        else:
            if not breakout_hit and high is not None and high >= breakout_price * (1.0 - tol):
                breakout_hit = True
                breakout_day = offset
            if boundary is not None and not boundary_hit and high is not None and high >= boundary * (1.0 - tol):
                boundary_hit = True
                boundary_day = offset
    combined = bool(boundary_hit or breakout_hit)
    combined_day = min([day for day in [breakout_day, boundary_day] if day is not None], default=None)
    return {
        "throwback_exact_30d": bool(boundary_hit),
        "days_to_throwback_exact": int(boundary_day) if boundary_day is not None else None,
        "throwback_to_breakout_30d": bool(breakout_hit),
        "days_to_throwback_to_breakout": int(breakout_day) if breakout_day is not None else None,
        "throwback_pullback_30d": combined,
        "days_to_throwback_pullback": int(combined_day) if combined_day is not None else None,
    }
