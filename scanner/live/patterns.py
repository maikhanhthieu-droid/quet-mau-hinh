"""Causal accumulation candidates for the nightly VN100 watchlist.

The detectors intentionally inspect only a suffix ending at the last complete
bar.  They do not call any research detector that evaluates future bars.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd


DETECTOR_VERSION = "vn100_accumulation_eod_v1"


class AccumulationCandidate(dict):
    """JSON-friendly candidate with an explicit immutable-style export hook."""

    def to_dict(self) -> dict[str, Any]:
        return dict(self)


@dataclass(frozen=True)
class AccumulationConfig:
    min_bars: int = 120
    min_average_value_vnd: float = 5_000_000_000.0
    max_distance_to_breakout_pct: float = 6.0


def _slope_pct(values: Iterable[float]) -> float:
    series = pd.Series(values, dtype="float64").dropna()
    if len(series) < 3 or float(series.mean()) <= 0:
        return 0.0
    x = np.arange(len(series), dtype=float)
    return float(np.polyfit(x, series.to_numpy(), 1)[0] / series.mean() * 100.0)


def _range_pct(frame: pd.DataFrame) -> float:
    low = float(frame["low"].min())
    high = float(frame["high"].max())
    return max(0.0, (high / low - 1.0) * 100.0) if low > 0 else 999.0


def _window_metrics(frame: pd.DataFrame) -> dict[str, float]:
    midpoint = max(1, len(frame) // 2)
    first = frame.iloc[:midpoint]
    second = frame.iloc[midpoint:]
    resistance = float(frame["high"].quantile(0.90))
    support = float(frame["low"].quantile(0.10))
    first_range = _range_pct(first)
    second_range = _range_pct(second)
    previous_volume = float(frame["volume"].iloc[:-5].tail(20).mean())
    recent_volume = float(frame["volume"].tail(5).mean())
    volume_ratio = recent_volume / previous_volume if previous_volume > 0 else 1.0
    near_resistance = frame["high"] >= resistance * 0.98
    return {
        "support": support,
        "resistance": resistance,
        "range_pct": _range_pct(frame),
        "first_range_pct": first_range,
        "second_range_pct": second_range,
        "contraction_ratio": second_range / first_range if first_range > 0 else 1.0,
        "volume_ratio": volume_ratio,
        "resistance_touches": float(near_resistance.sum()),
        "close_slope_pct_per_bar": _slope_pct(frame["close"]),
        "high_slope_pct_per_bar": _slope_pct(frame["high"]),
        "low_slope_pct_per_bar": _slope_pct(frame["low"]),
    }


def _status(distance: float) -> str:
    return "near_breakout" if distance <= 1.5 else "forming"


def _score(
    *,
    range_pct: float,
    distance: float,
    volume_ratio: float,
    contraction_ratio: float,
    touches: float,
    trend_pct: float,
) -> float:
    tightness = max(0.0, min(30.0, 30.0 * (1.0 - range_pct / 20.0)))
    proximity = max(0.0, min(25.0, 25.0 * (1.0 - distance / 8.0)))
    dry_up = max(0.0, min(20.0, 20.0 * (1.15 - volume_ratio)))
    contraction = max(0.0, min(15.0, 15.0 * (1.25 - contraction_ratio)))
    touch_quality = max(0.0, min(7.0, touches * 2.5))
    trend = max(0.0, min(3.0, trend_pct / 8.0))
    return round(max(0.0, min(100.0, tightness + proximity + dry_up + contraction + touch_quality + trend)), 2)


def _candidate(
    frame: pd.DataFrame,
    *,
    pattern_id: str,
    pattern_name: str,
    start_idx: int,
    metrics: dict[str, float],
    trend_pct: float,
    reasons: list[str],
) -> dict[str, Any] | None:
    close = float(frame["close"].iloc[-1])
    resistance = float(metrics["resistance"])
    if resistance <= 0 or close > resistance * 1.002:
        return None
    distance = max(0.0, (resistance - close) / resistance * 100.0)
    score = _score(
        range_pct=metrics["range_pct"],
        distance=distance,
        volume_ratio=metrics["volume_ratio"],
        contraction_ratio=metrics["contraction_ratio"],
        touches=metrics["resistance_touches"],
        trend_pct=trend_pct,
    )
    return AccumulationCandidate({
        "symbol": str(frame["symbol"].iloc[-1]).upper(),
        "pattern_id": pattern_id,
        "pattern_name_vi": pattern_name,
        "detector_version": DETECTOR_VERSION,
        "status": _status(distance),
        "as_of_date": pd.Timestamp(frame["time"].iloc[-1]).date().isoformat(),
        "formation_start": pd.Timestamp(frame["time"].iloc[start_idx]).date().isoformat(),
        "formation_end": pd.Timestamp(frame["time"].iloc[-1]).date().isoformat(),
        "close": round(close, 4),
        "support": round(float(metrics["support"]), 4),
        "resistance": round(resistance, 4),
        "distance_to_breakout_pct": round(distance, 3),
        "base_days": int(len(frame) - start_idx),
        "range_pct": round(float(metrics["range_pct"]), 3),
        "volume_ratio_5_20": round(float(metrics["volume_ratio"]), 3),
        "average_value_20_vnd": 0,
        "source": str(frame["source"].iloc[-1]).upper() if "source" in frame.columns else "unknown",
        "known_data_only": True,
        "setup_score": score,
        "reasons": reasons,
        "risk_note": "Ứng viên đang tích lũy; chưa phải tín hiệu mua và cần xác nhận breakout bằng dữ liệu mới.",
    })


def _base_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"symbol", "time", "open", "high", "low", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"OHLCV thiếu cột: {', '.join(sorted(missing))}")
    out = frame.copy()
    out["time"] = pd.to_datetime(out["time"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out = out.dropna(subset=list(required)).sort_values("time")
    return out.drop_duplicates(subset=["time"], keep="last").reset_index(drop=True)


def scan_symbol(
    frame: pd.DataFrame,
    config: AccumulationConfig | None = None,
    *,
    as_of: pd.Timestamp | str | None = None,
) -> list[dict[str, Any]]:
    """Return only causal forming/near-breakout candidates for one symbol."""

    config = config or AccumulationConfig()
    if as_of is not None and "time" in frame.columns:
        cutoff = pd.Timestamp(as_of)
        frame = frame.loc[pd.to_datetime(frame["time"], errors="coerce") <= cutoff].copy()
    frame = _base_frame(frame)
    if len(frame) < config.min_bars:
        return []
    # In Vietnam, vnstock prices are in thousand-VND units.  This is only used
    # for liquidity gating; displayed prices remain in provider units.
    average_value_vnd = float((frame["close"].tail(20) * frame["volume"].tail(20) * 1000.0).mean())
    if average_value_vnd < config.min_average_value_vnd:
        return []

    latest_close = float(frame["close"].iloc[-1])
    sma50 = float(frame["close"].tail(50).mean())
    if latest_close < sma50 * 0.90:
        return []
    trend_anchor = max(0, len(frame) - 80)
    trend_pct = (latest_close / float(frame["close"].iloc[trend_anchor]) - 1.0) * 100.0
    candidates: list[dict[str, Any]] = []

    for width in (15, 20, 30, 40, 50):
        if len(frame) < width + 10:
            continue
        window = frame.tail(width)
        metrics = _window_metrics(window)
        distance = max(0.0, (metrics["resistance"] - latest_close) / metrics["resistance"] * 100.0)
        if metrics["range_pct"] <= 16 and metrics["close_slope_pct_per_bar"] <= 0.30 and 0 <= distance <= config.max_distance_to_breakout_pct:
            reasons = [f"nền {width} phiên", f"biên độ {metrics['range_pct']:.1f}%"]
            if metrics["volume_ratio"] <= 1.0:
                reasons.append("khối lượng co lại")
            if metrics["resistance_touches"] >= 2:
                reasons.append("nhiều lần kiểm tra kháng cự")
            candidate = _candidate(frame, pattern_id="flat_base", pattern_name="Nền giá phẳng", start_idx=len(frame) - width, metrics=metrics, trend_pct=trend_pct, reasons=reasons)
            if candidate:
                candidate["average_value_20_vnd"] = round(average_value_vnd)
                candidates.append(candidate)
                break

    for width in (25, 35, 45):
        if len(frame) < width + 10:
            continue
        window = frame.tail(width)
        metrics = _window_metrics(window)
        distance = max(0.0, (metrics["resistance"] - latest_close) / metrics["resistance"] * 100.0)
        if metrics["high_slope_pct_per_bar"] <= 0.10 and metrics["low_slope_pct_per_bar"] >= 0.02 and metrics["contraction_ratio"] <= 1.05 and 0 <= distance <= config.max_distance_to_breakout_pct:
            candidate = _candidate(frame, pattern_id="ascending_triangle", pattern_name="Tam giác tăng", start_idx=len(frame) - width, metrics=metrics, trend_pct=trend_pct, reasons=[f"kháng cự phẳng {width} phiên", "đáy nâng dần", "biên độ thu hẹp"])
            if candidate:
                candidate["average_value_20_vnd"] = round(average_value_vnd)
                candidates.append(candidate)
                break

    for width in (25, 35, 45):
        if len(frame) < width + 10:
            continue
        window = frame.tail(width)
        metrics = _window_metrics(window)
        distance = max(0.0, (metrics["resistance"] - latest_close) / metrics["resistance"] * 100.0)
        if metrics["high_slope_pct_per_bar"] <= -0.02 and metrics["low_slope_pct_per_bar"] >= 0.02 and metrics["contraction_ratio"] <= 0.95 and 0 <= distance <= config.max_distance_to_breakout_pct:
            candidate = _candidate(frame, pattern_id="symmetrical_triangle", pattern_name="Tam giác cân", start_idx=len(frame) - width, metrics=metrics, trend_pct=trend_pct, reasons=[f"đỉnh thấp dần {width} phiên", "đáy cao dần", "biên độ thu hẹp"])
            if candidate:
                candidate["average_value_20_vnd"] = round(average_value_vnd)
                candidates.append(candidate)
                break

    for width in (8, 12, 15, 20):
        if len(frame) < width + 25:
            continue
        pole = frame.iloc[-width - 20 : -width]
        flag = frame.tail(width)
        pole_gain = (float(pole["close"].iloc[-1]) / float(pole["close"].iloc[0]) - 1.0) * 100.0
        metrics = _window_metrics(flag)
        distance = max(0.0, (metrics["resistance"] - latest_close) / metrics["resistance"] * 100.0)
        if pole_gain >= 8 and metrics["range_pct"] <= 18 and metrics["close_slope_pct_per_bar"] <= 0.20 and metrics["volume_ratio"] <= 1.20 and 0 <= distance <= config.max_distance_to_breakout_pct:
            candidate = _candidate(frame, pattern_id="bull_flag", pattern_name="Cờ tăng đang hình thành", start_idx=len(frame) - width, metrics=metrics, trend_pct=pole_gain, reasons=[f"cột cờ +{pole_gain:.1f}%", f"thân cờ {width} phiên", "khối lượng không tăng trong nhịp nghỉ"])
            if candidate:
                candidate["average_value_20_vnd"] = round(average_value_vnd)
                candidates.append(candidate)
                break

    if len(frame) >= 50:
        ranges = [_range_pct(frame.tail(width)) for width in (40, 20, 10)]
        window = frame.tail(40)
        metrics = _window_metrics(window)
        distance = max(0.0, (metrics["resistance"] - latest_close) / metrics["resistance"] * 100.0)
        if ranges[2] < ranges[1] < ranges[0] and metrics["volume_ratio"] <= 0.95 and 0 <= distance <= config.max_distance_to_breakout_pct:
            candidate = _candidate(frame, pattern_id="volatility_contraction", pattern_name="Co hẹp biến động (VCP)", start_idx=len(frame) - 40, metrics=metrics, trend_pct=trend_pct, reasons=["ba nhịp co hẹp liên tiếp", "khối lượng khô dần", "giá nằm dưới kháng cự gần"])
            if candidate:
                candidate["average_value_20_vnd"] = round(average_value_vnd)
                candidates.append(candidate)

    # Keep the best instance of each pattern and sort deterministically.  No
    # future-derived fields are added here.
    best: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        current = best.get(candidate["pattern_id"])
        if current is None or candidate["setup_score"] > current["setup_score"]:
            best[candidate["pattern_id"]] = candidate
    return sorted(best.values(), key=lambda row: (-float(row["setup_score"]), row["pattern_id"]))


def scan_many(frames: Iterable[pd.DataFrame], config: AccumulationConfig | None = None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for frame in frames:
        results.extend(scan_symbol(frame, config=config))
    return sorted(results, key=lambda row: (-float(row["setup_score"]), row["symbol"], row["pattern_id"]))
