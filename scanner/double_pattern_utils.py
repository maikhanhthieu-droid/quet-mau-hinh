from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


def _extreme_width_bars(
    df: pd.DataFrame,
    *,
    idx: int,
    price: float,
    column: str,
    tol_pct: float,
    window: int,
    is_peak: bool,
) -> Optional[int]:
    if idx < 0 or idx >= len(df) or price <= 0:
        return None

    if is_peak:
        threshold = float(price) * (1.0 - float(tol_pct) / 100.0)
    else:
        threshold = float(price) * (1.0 + float(tol_pct) / 100.0)

    left = idx
    for k in range(1, int(window) + 1):
        j = idx - k
        if j < 0:
            break
        value = float(df.iloc[j][column])
        if (value >= threshold) if is_peak else (value <= threshold):
            left = j
        else:
            break

    right = idx
    for k in range(1, int(window) + 1):
        j = idx + k
        if j >= len(df):
            break
        value = float(df.iloc[j][column])
        if (value >= threshold) if is_peak else (value <= threshold):
            right = j
        else:
            break

    return int(right - left + 1)


def peak_width_bars(df: pd.DataFrame, peak_idx: int, peak_price: float, *, tol_pct: float = 2.0, window: int = 15) -> Optional[int]:
    return _extreme_width_bars(
        df,
        idx=int(peak_idx),
        price=float(peak_price),
        column="high",
        tol_pct=float(tol_pct),
        window=int(window),
        is_peak=True,
    )


def trough_width_bars(df: pd.DataFrame, trough_idx: int, trough_price: float, *, tol_pct: float = 2.0, window: int = 15) -> Optional[int]:
    return _extreme_width_bars(
        df,
        idx=int(trough_idx),
        price=float(trough_price),
        column="low",
        tol_pct=float(tol_pct),
        window=int(window),
        is_peak=False,
    )


def adam_eve_label(width: Optional[int], *, adam_max: int = 3, eve_min: int = 7) -> Optional[str]:
    if width is None:
        return None
    if int(width) <= int(adam_max):
        return "A"
    if int(width) >= int(eve_min):
        return "E"
    return None


def _extreme_reaction_pct(
    df: pd.DataFrame,
    *,
    idx: int,
    price: float,
    is_peak: bool,
    reaction_window: int = 4,
) -> Optional[float]:
    if idx < 0 or idx >= len(df) or price <= 0:
        return None

    left = df.iloc[max(0, idx - reaction_window) : idx]
    right = df.iloc[idx + 1 : min(len(df), idx + 1 + reaction_window)]
    if len(left) == 0 or len(right) == 0:
        return None

    if is_peak:
        left_ref = float(left["low"].min())
        right_ref = float(right["low"].min())
        left_move = (float(price) - left_ref) / float(price) * 100.0
        right_move = (float(price) - right_ref) / float(price) * 100.0
    else:
        left_ref = float(left["high"].max())
        right_ref = float(right["high"].max())
        left_move = (left_ref - float(price)) / float(price) * 100.0
        right_move = (right_ref - float(price)) / float(price) * 100.0

    return float(min(left_move, right_move))


def _classify_extreme_shape(
    *,
    width: Optional[int],
    reaction_pct: Optional[float],
    adam_max: int,
    eve_min: int,
) -> Dict[str, Any]:
    evidence: List[str] = []
    if width is None:
        return {
            "label": None,
            "confidence": 0,
            "width_bars": None,
            "reaction_pct": reaction_pct,
            "sharpness_score": None,
            "evidence": ["missing_width"],
        }

    reaction = float(reaction_pct or 0.0)
    sharpness = float(reaction / max(1, int(width)))

    if int(width) <= int(adam_max):
        confidence = 88 if sharpness >= 0.9 else 74
        evidence.append(f"width<=adam_max({adam_max})")
        if sharpness >= 0.9:
            evidence.append("local_reaction_supports_sharp_spike")
        return {
            "label": "A",
            "confidence": int(confidence),
            "width_bars": int(width),
            "reaction_pct": round(reaction, 3),
            "sharpness_score": round(sharpness, 3),
            "evidence": evidence,
        }

    if int(width) >= int(eve_min):
        confidence = 86 if sharpness <= 0.65 else 72
        evidence.append(f"width>=eve_min({eve_min})")
        if sharpness <= 0.65:
            evidence.append("local_reaction_supports_rounded_shape")
        return {
            "label": "E",
            "confidence": int(confidence),
            "width_bars": int(width),
            "reaction_pct": round(reaction, 3),
            "sharpness_score": round(sharpness, 3),
            "evidence": evidence,
        }

    evidence.append("width_in_gap_between_adam_and_eve")

    # The original width-only split left a blind spot at 4-6 bars. Favor the side that is
    # structurally closest instead of forcing every gap-width extreme to stay unresolved.
    near_adam = int(width) <= int(adam_max) + 1
    near_eve = int(width) >= max(int(adam_max) + 2, int(eve_min) - 1)

    if near_adam and (sharpness >= 0.95 or reaction >= 3.5):
        evidence.append("gap_resolved_toward_adam_by_near_adam_width")
        return {
            "label": "A",
            "confidence": 64,
            "width_bars": int(width),
            "reaction_pct": round(reaction, 3),
            "sharpness_score": round(sharpness, 3),
            "evidence": evidence,
        }

    if near_eve and (sharpness <= 0.85 or reaction <= 4.2):
        evidence.append("gap_resolved_toward_eve_by_near_eve_width")
        return {
            "label": "E",
            "confidence": 64,
            "width_bars": int(width),
            "reaction_pct": round(reaction, 3),
            "sharpness_score": round(sharpness, 3),
            "evidence": evidence,
        }

    # Do not force the midpoint of the gap zone into Adam. Width=5 remains semantically
    # murky, but it can still behave like a rounded Eve when local reaction stays muted.
    if int(width) == int(adam_max) + 2 and sharpness <= 0.55 and reaction <= 2.8:
        evidence.append("mid_gap_resolved_toward_eve_by_extra_roundness")
        return {
            "label": "E",
            "confidence": 54,
            "width_bars": int(width),
            "reaction_pct": round(reaction, 3),
            "sharpness_score": round(sharpness, 3),
            "evidence": evidence,
        }

    # Keep the rest of the midpoint gap unresolved unless local reaction is unusually
    # decisive. This avoids reviving the old tendency to overproduce weak AA branches.
    if near_adam and (sharpness >= 1.15 or reaction >= 4.0):
        evidence.append("gap_resolved_toward_adam_by_local_reaction")
        return {
            "label": "A",
            "confidence": 58,
            "width_bars": int(width),
            "reaction_pct": round(reaction, 3),
            "sharpness_score": round(sharpness, 3),
            "evidence": evidence,
        }
    if near_eve and sharpness <= 0.70 and reaction <= 3.6:
        evidence.append("gap_resolved_toward_eve_by_local_reaction")
        return {
            "label": "E",
            "confidence": 58,
            "width_bars": int(width),
            "reaction_pct": round(reaction, 3),
            "sharpness_score": round(sharpness, 3),
            "evidence": evidence,
        }
    evidence.append("gap_not_resolved")
    return {
        "label": None,
        "confidence": 0,
        "width_bars": int(width),
        "reaction_pct": round(reaction, 3),
        "sharpness_score": round(sharpness, 3),
        "evidence": evidence,
    }


def _resolve_double_variant(
    df: pd.DataFrame,
    *,
    first_idx: int,
    second_idx: int,
    is_peak: bool,
    adam_max: int = 3,
    eve_min: int = 7,
    tol_pct: float = 2.0,
    window: int = 15,
    reaction_window: int = 4,
) -> Dict[str, Any]:
    if not (0 <= int(first_idx) < len(df) and 0 <= int(second_idx) < len(df)):
        return {
            "variant_code": None,
            "variant_confidence": 0,
            "first_extreme": None,
            "second_extreme": None,
            "evidence": {"error": "index_out_of_range"},
        }

    if is_peak:
        first_price = float(df.iloc[int(first_idx)]["high"])
        second_price = float(df.iloc[int(second_idx)]["high"])
        width_fn = peak_width_bars
    else:
        first_price = float(df.iloc[int(first_idx)]["low"])
        second_price = float(df.iloc[int(second_idx)]["low"])
        width_fn = trough_width_bars

    w1 = width_fn(df, int(first_idx), first_price, tol_pct=float(tol_pct), window=int(window))
    w2 = width_fn(df, int(second_idx), second_price, tol_pct=float(tol_pct), window=int(window))
    r1 = _extreme_reaction_pct(df, idx=int(first_idx), price=float(first_price), is_peak=is_peak, reaction_window=int(reaction_window))
    r2 = _extreme_reaction_pct(df, idx=int(second_idx), price=float(second_price), is_peak=is_peak, reaction_window=int(reaction_window))

    e1 = _classify_extreme_shape(width=w1, reaction_pct=r1, adam_max=int(adam_max), eve_min=int(eve_min))
    e2 = _classify_extreme_shape(width=w2, reaction_pct=r2, adam_max=int(adam_max), eve_min=int(eve_min))
    label1 = e1.get("label")
    label2 = e2.get("label")
    code = f"{label1}{label2}" if (label1 and label2) else None
    confidence = int(min(int(e1.get("confidence") or 0), int(e2.get("confidence") or 0))) if code else 0

    return {
        "variant_code": code,
        "variant_confidence": confidence,
        "first_extreme": e1,
        "second_extreme": e2,
        "evidence": {
            "method": "width_plus_local_reaction",
            "adam_max_width_bars": int(adam_max),
            "eve_min_width_bars": int(eve_min),
            "first_extreme": e1,
            "second_extreme": e2,
        },
    }


def resolve_double_bottom_variant(
    df: pd.DataFrame,
    *,
    first_idx: int,
    second_idx: int,
    adam_max: int = 3,
    eve_min: int = 7,
    tol_pct: float = 2.0,
    window: int = 15,
    reaction_window: int = 4,
) -> Dict[str, Any]:
    return _resolve_double_variant(
        df,
        first_idx=int(first_idx),
        second_idx=int(second_idx),
        is_peak=False,
        adam_max=int(adam_max),
        eve_min=int(eve_min),
        tol_pct=float(tol_pct),
        window=int(window),
        reaction_window=int(reaction_window),
    )


def resolve_double_top_variant(
    df: pd.DataFrame,
    *,
    first_idx: int,
    second_idx: int,
    adam_max: int = 3,
    eve_min: int = 7,
    tol_pct: float = 2.0,
    window: int = 15,
    reaction_window: int = 4,
) -> Dict[str, Any]:
    return _resolve_double_variant(
        df,
        first_idx=int(first_idx),
        second_idx=int(second_idx),
        is_peak=True,
        adam_max=int(adam_max),
        eve_min=int(eve_min),
        tol_pct=float(tol_pct),
        window=int(window),
        reaction_window=int(reaction_window),
    )


def classify_double_bottom_variant(
    df: pd.DataFrame,
    *,
    first_idx: int,
    second_idx: int,
    adam_max: int = 3,
    eve_min: int = 7,
    tol_pct: float = 2.0,
    window: int = 15,
) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    result = resolve_double_bottom_variant(
        df,
        first_idx=int(first_idx),
        second_idx=int(second_idx),
        adam_max=int(adam_max),
        eve_min=int(eve_min),
        tol_pct=float(tol_pct),
        window=int(window),
    )
    first = result.get("first_extreme") or {}
    second = result.get("second_extreme") or {}
    return (
        result.get("variant_code"),
        first.get("width_bars"),
        second.get("width_bars"),
    )


def classify_double_top_variant(
    df: pd.DataFrame,
    *,
    first_idx: int,
    second_idx: int,
    adam_max: int = 3,
    eve_min: int = 7,
    tol_pct: float = 2.0,
    window: int = 15,
) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    result = resolve_double_top_variant(
        df,
        first_idx=int(first_idx),
        second_idx=int(second_idx),
        adam_max=int(adam_max),
        eve_min=int(eve_min),
        tol_pct=float(tol_pct),
        window=int(window),
    )
    first = result.get("first_extreme") or {}
    second = result.get("second_extreme") or {}
    return (
        result.get("variant_code"),
        first.get("width_bars"),
        second.get("width_bars"),
    )
