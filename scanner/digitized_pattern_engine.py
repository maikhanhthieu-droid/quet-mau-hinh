"""
Digitized Pattern Engine
-----------------------
Loads pattern definitions from `extraction_phase_1/digitization/patterns_digitized/*_digitized.json`
and provides a set of scanners that can cover all digitized patterns.

Notes:
- The digitized specs directory is intentionally gitignored in the public repo because it may
  be derived from copyrighted sources. This module will gracefully degrade if specs are missing.
- Detection uses NO look-ahead beyond breakout confirmation. Post-breakout evaluation is handled
  separately in `post_breakout_analyzer.py`.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

try:
    # Package import (preferred)
    from .double_pattern_utils import (
        classify_double_bottom_variant,
        classify_double_top_variant,
        resolve_double_bottom_variant,
        resolve_double_top_variant,
    )
    from .pivot_detector import Pivot, PivotDetector, PivotType
except ImportError:  # pragma: no cover - support running as a script from scanner/
    from double_pattern_utils import (
        classify_double_bottom_variant,
        classify_double_top_variant,
        resolve_double_bottom_variant,
        resolve_double_top_variant,
    )
    from pivot_detector import Pivot, PivotDetector, PivotType


def _safe_float(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except Exception:
        return None
    if not np.isfinite(v):
        return None
    return v


def _pct_diff(a: float, b: float) -> float:
    denom = min(abs(a), abs(b))
    if denom <= 0:
        return float("inf")
    return abs(a - b) / denom * 100.0


def _slope_degrees(idx1: int, price1: float, idx2: int, price2: float) -> float:
    """
    Approximate slope in degrees using % change per bar.
    This isn't a charting angle; it's a stable numeric proxy that matches digitized thresholds reasonably.
    """
    bars = max(1, int(idx2) - int(idx1))
    if price1 == 0:
        return 0.0
    change_pct = (price2 - price1) / price1 * 100.0
    return float(np.degrees(np.arctan(change_pct / bars)))


@dataclass
class Trendline:
    idx0: int
    price0: float
    slope_per_bar: float

    def value_at(self, idx: int) -> float:
        return self.price0 + self.slope_per_bar * (idx - self.idx0)


class DigitizedPatternLibrary:
    def __init__(self, patterns_dir: Optional[str] = None):
        if patterns_dir is None:
            patterns_dir = os.path.join(
                os.path.dirname(__file__),
                "..",
                "extraction_phase_1",
                "digitization",
                "patterns_digitized",
            )
        self.patterns_dir = os.path.abspath(patterns_dir)

    def list_keys(self) -> List[str]:
        if not os.path.isdir(self.patterns_dir):
            return []
        keys: List[str] = []
        for name in os.listdir(self.patterns_dir):
            if not name.endswith("_digitized.json"):
                continue
            keys.append(name.replace("_digitized.json", ""))
        keys.sort()
        return keys

    def load(self, key: str) -> Dict[str, Any]:
        path = os.path.join(self.patterns_dir, f"{key}_digitized.json")
        with open(path, "r") as f:
            return json.load(f)


class BaseDigitizedScanner:
    def __init__(self, key: str, spec: Dict[str, Any]):
        self.key = key
        self.spec = spec
        self.pattern_type = str(spec.get("pattern_type") or "unknown")

        # Stable-ish hash for result traceability
        payload = json.dumps(
            {
                "key": self.key,
                "digitization_version": spec.get("digitization_version"),
                "pattern_type": self.pattern_type,
            },
            sort_keys=True,
            default=str,
        ).encode("utf-8")
        self.config_hash = hashlib.md5(payload).hexdigest()[:8]

    def scan(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError


class PivotSequenceScanner(BaseDigitizedScanner):
    """
    Generic pivot-sequence scanner:
    - Match required H/L sequence on pivots
    - Apply a pragmatic subset of digitized constraints
    - Find breakout based on computed boundaries
    """

    def __init__(self, key: str, spec: Dict[str, Any]):
        super().__init__(key, spec)
        self.ds = spec.get("detection_signature", {}) or {}
        self.geom = spec.get("geometry_constraints", {}) or {}
        self.prior = spec.get("prior_trend_requirements", {}) or {}
        self.breakout = spec.get("breakout_confirmation", {}) or {}

        seq = self.ds.get("pivot_sequence", []) or []
        self.pivot_tokens = [t for t in seq if t in ("H", "L")]
        self.pivot_order = str(self.ds.get("pivot_order") or "alternating")

    def _pick_pivots(self, pivots_filtered: List[Pivot], pivots_raw: List[Pivot]) -> List[Pivot]:
        if self.pivot_order in ("alternating", "sequential_trend_following", "alternating_required"):
            return pivots_filtered
        return pivots_raw or pivots_filtered

    def _validate_width_height(self, window: List[Pivot]) -> Tuple[bool, float, int]:
        start_idx = window[0].idx
        end_idx = window[-1].idx
        # KPI + spec use bar counts (inclusive).
        width_bars = (end_idx - start_idx) + 1

        wmin = self.geom.get("width_min_bars")
        wmax = self.geom.get("width_max_bars")
        if wmin is not None and width_bars < int(wmin):
            return False, 0.0, width_bars
        if wmax is not None and width_bars > int(wmax):
            return False, 0.0, width_bars

        highs = [p.price for p in window if p.type == PivotType.HIGH]
        lows = [p.price for p in window if p.type == PivotType.LOW]
        if not highs or not lows:
            return False, 0.0, width_bars

        upper = max(highs)
        lower = min(lows)
        mid = (upper + lower) / 2.0 if (upper + lower) != 0 else max(upper, 1e-9)
        height_pct = (upper - lower) / mid * 100.0

        hmin = self.geom.get("height_ratio_min")
        hmax = self.geom.get("height_ratio_max")
        if hmin is not None and height_pct < float(hmin):
            return False, height_pct, width_bars
        if hmax is not None and height_pct > float(hmax):
            return False, height_pct, width_bars

        return True, height_pct, width_bars

    def _check_prior_trend(self, df: pd.DataFrame, pattern_start_idx: int) -> Tuple[bool, Optional[str]]:
        direction = str(self.prior.get("direction") or "any").lower()
        min_bars = int(self.prior.get("min_period_bars") or 0)
        min_change = float(self.prior.get("min_change_pct") or 0.0)
        if min_bars <= 0 or min_change <= 0:
            return True, None
        if pattern_start_idx < min_bars:
            return False, None

        start = pattern_start_idx - min_bars
        end = pattern_start_idx
        p0 = _safe_float(df.iloc[start].get("close"))
        p1 = _safe_float(df.iloc[end].get("close"))
        if p0 is None or p1 is None or p0 <= 0:
            return False, None
        change_pct = (p1 - p0) / p0 * 100.0

        if direction == "up":
            return (change_pct >= min_change), "up"
        if direction == "down":
            return (change_pct <= -min_change), "down"
        # any: require at least some move for context
        return (abs(change_pct) >= min_change), ("up" if change_pct >= 0 else "down")

    def _near_equal(self, a: float, b: float, tol_pct: float) -> bool:
        return _pct_diff(a, b) <= tol_pct

    def _constraint_ok(self, constraint: str, pos: int, window: List[Pivot]) -> bool:
        # pos is 1-based
        cur = window[pos - 1]
        c = constraint

        tol = float(self.geom.get("near_equal_tolerance_pct") or 3.0)

        def _prev_same_type() -> Optional[Pivot]:
            for j in range(pos - 2, -1, -1):
                if window[j].type == cur.type:
                    return window[j]
            return None

        if c == "near_equal":
            ref = _prev_same_type() or window[0]
            return self._near_equal(cur.price, ref.price, tol)

        if c.startswith("near_equal_to_position_"):
            try:
                ref_pos = int(c.split("_")[-1])
            except Exception:
                return True
            if 1 <= ref_pos <= len(window):
                return self._near_equal(cur.price, window[ref_pos - 1].price, tol)
            return True

        if c in ("lower_than_previous", "lower_than_previous_low", "lower_than_previous_L"):
            prev = _prev_same_type()
            return True if prev is None else (cur.price < prev.price)

        if c in ("higher_than_previous", "higher_than_previous_high", "higher_than_previous_H"):
            prev = _prev_same_type()
            return True if prev is None else (cur.price > prev.price)

        if c == "lower_than_previous_high":
            prev = None
            for j in range(pos - 2, -1, -1):
                if window[j].type == PivotType.HIGH:
                    prev = window[j]
                    break
            return True if prev is None else (cur.price < prev.price)

        if c == "higher_than_previous_low":
            prev = None
            for j in range(pos - 2, -1, -1):
                if window[j].type == PivotType.LOW:
                    prev = window[j]
                    break
            return True if prev is None else (cur.price > prev.price)

        if c == "must_be_lowest":
            lows = [p.price for p in window if p.type == PivotType.LOW]
            return True if not lows else (cur.price <= min(lows))

        if c == "must_be_highest":
            highs = [p.price for p in window if p.type == PivotType.HIGH]
            return True if not highs else (cur.price >= max(highs))

        if c == "not_lowest":
            lows = [p.price for p in window if p.type == PivotType.LOW]
            return True if not lows else (cur.price > min(lows))

        if c == "not_highest":
            highs = [p.price for p in window if p.type == PivotType.HIGH]
            return True if not highs else (cur.price < max(highs))

        if c == "must_be_between":
            # For lows: must be below adjacent highs, for highs: above adjacent lows
            if pos <= 1 or pos >= len(window):
                return True
            left = window[pos - 2]
            right = window[pos]
            if cur.type == PivotType.LOW:
                return cur.price < left.price and cur.price < right.price
            if cur.type == PivotType.HIGH:
                return cur.price > left.price and cur.price > right.price
            return True

        # Cup-with-handle specific pragmatic constraints
        if c == "in_upper_third":
            # Assume cup bottom at pos2 and lip at pos3 (works for digitized spec order)
            if len(window) >= 4:
                cup_bottom = window[1].price
                cup_lip = window[2].price
                return cur.price >= cup_bottom + (cup_lip - cup_bottom) * (2.0 / 3.0)
            return True

        if c == "near_cup_lip":
            if len(window) >= 3:
                cup_lip = window[2].price
                return self._near_equal(cur.price, cup_lip, tol)
            return True

        if c == "shallow_decline":
            # Require last low not too deep vs handle resistance (position 5)
            if len(window) >= 6:
                handle_res = window[4].price
                if handle_res == 0:
                    return True
                drawdown = (handle_res - cur.price) / handle_res * 100.0
                return drawdown <= float(self.geom.get("depth_ratio_tolerance_pct") or 15.0)
            return True

        # Default: accept unknown constraints (we still want broad coverage)
        return True

    def _validate_mandatory(self, window: List[Pivot]) -> bool:
        mps = (self.ds.get("mandatory_pivots") or []) if isinstance(self.ds.get("mandatory_pivots"), list) else []
        for mp in mps:
            pos = mp.get("position")
            if not isinstance(pos, int):
                continue
            if not (1 <= pos <= len(window)):
                continue
            c = mp.get("constraint")
            if c:
                if not self._constraint_ok(str(c), pos, window):
                    return False
        return True

    def _build_boundaries(self, window: List[Pivot]) -> Tuple[Trendline, Trendline]:
        highs = [p for p in window if p.type == PivotType.HIGH]
        lows = [p for p in window if p.type == PivotType.LOW]

        # Upper boundary
        if len(highs) >= 2:
            p0, p1 = highs[0], highs[-1]
            slope = (p1.price - p0.price) / max(1, p1.idx - p0.idx)
            upper = Trendline(idx0=p0.idx, price0=p0.price, slope_per_bar=slope)
        else:
            p0 = highs[0]
            upper = Trendline(idx0=p0.idx, price0=p0.price, slope_per_bar=0.0)

        # Lower boundary
        if len(lows) >= 2:
            p0, p1 = lows[0], lows[-1]
            slope = (p1.price - p0.price) / max(1, p1.idx - p0.idx)
            lower = Trendline(idx0=p0.idx, price0=p0.price, slope_per_bar=slope)
        else:
            p0 = lows[0]
            lower = Trendline(idx0=p0.idx, price0=p0.price, slope_per_bar=0.0)

        return upper, lower

    def _breakout_directions(self, prior_dir: Optional[str]) -> List[str]:
        bd = str(self.breakout.get("breakout_direction") or "").lower()
        ptype = self.pattern_type.lower()

        # Prefer explicit reversal type
        if ptype == "reversal_bearish":
            return ["down"]
        if ptype == "reversal_bullish":
            return ["up"]

        if bd in ("up", "down"):
            return [bd]
        if bd in ("same_as_flagpole", "depends_on_prior_trend"):
            if prior_dir in ("up", "down"):
                return [prior_dir]
            return ["up", "down"]
        if bd in ("neutral", "both", "continuation_both"):
            return ["up", "down"]
        return ["up", "down"]

    def _find_breakout(
        self,
        df: pd.DataFrame,
        *,
        formation_end_idx: int,
        upper: Trendline,
        lower: Trendline,
        prior_dir: Optional[str],
    ) -> Tuple[Optional[int], Optional[str], Optional[float], bool]:
        thr_pct = float(self.breakout.get("breakout_threshold_pct") or 1.0) / 100.0
        vol_min = float(self.breakout.get("volume_multiplier_min") or 1.3)
        vol_required = bool(self.breakout.get("volume_required") is True)

        # Keep search bounded for performance; longer patterns can override in the future.
        search_bars = int(self.geom.get("breakout_search_bars") or 40)
        end = min(len(df), formation_end_idx + 1 + search_bars)

        for idx in range(formation_end_idx + 1, end):
            close = _safe_float(df.iloc[idx].get("close"))
            if close is None or close <= 0:
                continue

            up_level = upper.value_at(idx)
            dn_level = lower.value_at(idx)

            for d in self._breakout_directions(prior_dir):
                if d == "up":
                    if close > up_level * (1.0 + thr_pct):
                        vr = df.iloc[idx].get("volume_ratio", np.nan)
                        vol_ok = bool(pd.notna(vr) and np.isfinite(vr) and float(vr) >= vol_min)
                        if vol_required and not vol_ok:
                            continue
                        return idx, "up", close, vol_ok
                else:
                    if close < dn_level * (1.0 - thr_pct):
                        vr = df.iloc[idx].get("volume_ratio", np.nan)
                        vol_ok = bool(pd.notna(vr) and np.isfinite(vr) and float(vr) >= vol_min)
                        if vol_required and not vol_ok:
                            continue
                        return idx, "down", close, vol_ok

        return None, None, None, False

    def scan(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> List[Dict[str, Any]]:
        if not self.pivot_tokens:
            return []

        pivots = self._pick_pivots(pivots_filtered, pivots_raw)
        if len(pivots) < len(self.pivot_tokens):
            return []

        out: List[Dict[str, Any]] = []
        n = len(self.pivot_tokens)

        for i in range(len(pivots) - n + 1):
            window = pivots[i : i + n]

            # Type match (H/L)
            ok = True
            for tok, p in zip(self.pivot_tokens, window):
                if tok == "H" and p.type != PivotType.HIGH:
                    ok = False
                    break
                if tok == "L" and p.type != PivotType.LOW:
                    ok = False
                    break
            if not ok:
                continue

            # Width/height constraints
            ok, height_pct, width_bars = self._validate_width_height(window)
            if not ok:
                continue

            # Mandatory constraints
            if not self._validate_mandatory(window):
                continue

            # Prior trend
            prior_ok, prior_dir = self._check_prior_trend(df, window[0].idx)
            if not prior_ok:
                continue

            upper, lower = self._build_boundaries(window)
            breakout_idx, breakout_dir, breakout_price, vol_ok = self._find_breakout(
                df,
                formation_end_idx=window[-1].idx,
                upper=upper,
                lower=lower,
                prior_dir=prior_dir,
            )

            # For some high-frequency patterns, requiring breakout keeps result size sane.
            if self.key in ("pipe_bottoms",) and breakout_idx is None:
                continue

            # Pattern height for target: use boundary range at pattern start
            height_abs = max(0.0, upper.value_at(window[0].idx) - lower.value_at(window[0].idx))
            if height_abs <= 0:
                continue

            target = None
            stop = None
            if breakout_idx is not None and breakout_dir is not None and breakout_price is not None:
                if breakout_dir == "up":
                    target = breakout_price + height_abs
                    stop = lower.value_at(breakout_idx)
                else:
                    target = breakout_price - height_abs
                    stop = upper.value_at(breakout_idx)

            # Confidence: pragmatic scoring (hard constraints already passed)
            confidence = 70
            if vol_ok:
                confidence += 10
            if breakout_idx is not None:
                confidence += 10
            confidence = int(min(100, confidence))

            start_idx = window[0].idx
            end_idx = window[-1].idx
            pattern_id = f"{symbol}_{self.key}_{start_idx}_{end_idx}"

            out.append(
                {
                    "pattern_id": pattern_id,
                    "symbol": symbol,
                    "pattern_name": self.key,
                    "pattern_type": self.pattern_type,
                    "formation_start": str(df.iloc[start_idx]["date"].date()) if "date" in df.columns else str(start_idx),
                    "formation_end": str(df.iloc[end_idx]["date"].date()) if "date" in df.columns else str(end_idx),
                    "breakout_date": str(df.iloc[breakout_idx]["date"].date()) if breakout_idx is not None and "date" in df.columns else None,
                    "breakout_idx": int(breakout_idx) if breakout_idx is not None else None,
                    "breakout_direction": breakout_dir,
                    "breakout_price": breakout_price,
                    "target_price": target,
                    "stop_loss_price": stop,
                    "confidence_score": confidence,
                    "volume_confirmed": bool(vol_ok),
                    "pattern_height_pct": round(height_pct, 2),
                    "pattern_width_bars": int(width_bars),
                    "touch_count": int(len(window)),
                    "pivot_indices": [int(p.idx) for p in window],
                    "config_hash": self.config_hash,
                    "created_at": datetime.now().isoformat(),
                }
            )

        return out


class _DoublePatternFamilyScanner(PivotSequenceScanner):
    """
    Dedicated family scanner for double bottoms/tops.

    The digitized spec for these patterns is structurally simple (3 pivots), but the generic
    pivot-sequence scanner ignores several family-level semantics that matter for Bulkowski-style
    fidelity: extreme spacing, neckline depth, near-horizontal extremes, and variant metadata.
    This wrapper keeps the generic breakout/prior-trend machinery, then post-filters candidates
    with family-specific checks and attaches variant evidence without letting the variant decide
    family validity.
    """

    def __init__(self, key: str, spec: Dict[str, Any], *, is_top: bool):
        super().__init__(key, spec)
        self.is_top = bool(is_top)
        geom = self.geom if isinstance(self.geom, dict) else {}

        ratio_cfg_key = "top_price_ratio" if self.is_top else "bottom_price_ratio"
        depth_cfg_key = "trough_depth_pct" if self.is_top else "peak_height_pct"
        spacing_cfg_key = "time_between_tops" if self.is_top else "time_between_bottoms"
        slope_cfg_key = "tops_max_slope_degrees" if self.is_top else "bottoms_max_slope_degrees"

        ratio_cfg = geom.get(ratio_cfg_key, {}) or {}
        depth_cfg = geom.get(depth_cfg_key, {}) or {}
        spacing_cfg = geom.get(spacing_cfg_key, {}) or {}
        slope_cfg = geom.get("slope_constraints", {}) or {}

        self.extreme_ratio_min = float(ratio_cfg.get("min") or 0.97)
        self.extreme_ratio_max = float(ratio_cfg.get("max") or 1.03)
        self.middle_depth_min_pct = float(depth_cfg.get("min") or 5.0)
        self.middle_depth_max_pct = float(depth_cfg.get("max") or 25.0)
        self.extreme_spacing_min_bars = int(spacing_cfg.get("min_bars") or 7)
        self.extreme_spacing_max_bars = int(spacing_cfg.get("max_bars") or 90)
        self.extreme_spacing_optimal_bars = int(spacing_cfg.get("optimal_bars") or 28)
        self.extreme_slope_max_deg = abs(float(slope_cfg.get(slope_cfg_key) or 0.5))
        # Flat, step-like microstructure can make rounded double patterns look plausible in
        # digitized pivots while being unusable for research or strategy. Keep this gate narrow:
        # it should only remove pathological sequences, not normal low-volatility consolidations.
        self.micro_max_same_close_ratio = 0.70
        self.micro_max_zero_range_ratio = 0.75
        self.micro_min_unique_close_ratio = 0.20
        # The post-phase-3 audit showed that the AA branches still carry a specific residue:
        # bottoms are hurt by flat, illiquid repeated-print sequences, while tops are hurt by
        # shallow twin peaks that are not quite near-equal / near-horizontal enough. Keep these
        # gates AA-only so they do not suppress already-sparse Eve-side variants.
        self.aa_bottom_same_close_ratio_min = 0.46
        self.aa_bottom_zero_range_ratio_min = 0.65
        self.aa_bottom_unique_close_ratio_max = 0.24
        self.aa_top_diff_pct_min = 0.20
        self.aa_top_slope_deg_min = 0.15
        self.aa_top_shallow_depth_pct_max = 15.0

        variant_cfg = spec.get("variant_handling", {}) or {}
        self.variant_adam_max = 3
        self.variant_eve_min = 7
        for item in variant_cfg.get("variants", []) or []:
            if not isinstance(item, dict):
                continue
            rules = item.get("detection_rules", {}) or {}
            name = str(item.get("name") or "").upper()
            width = rules.get("peak_width_bars")
            if width is None:
                width = rules.get("trough_width_bars")
            try:
                width_int = int(width) if width is not None else None
            except Exception:
                width_int = None
            if width_int is None or width_int <= 0:
                continue
            if name == "AA":
                self.variant_adam_max = min(self.variant_adam_max, width_int)
            elif name == "EE":
                self.variant_eve_min = max(self.variant_eve_min, width_int)

    def _family_metrics(self, df: pd.DataFrame, pivot_indices: Sequence[Any]) -> Optional[Dict[str, Any]]:
        if len(pivot_indices) < 3:
            return None

        try:
            first_idx = int(pivot_indices[0])
            middle_idx = int(pivot_indices[1])
            second_idx = int(pivot_indices[2])
        except Exception:
            return None

        if not (0 <= first_idx < middle_idx < second_idx < len(df)):
            return None

        first_col = "high" if self.is_top else "low"
        middle_col = "low" if self.is_top else "high"
        second_col = first_col

        first_price = _safe_float(df.iloc[first_idx].get(first_col))
        middle_price = _safe_float(df.iloc[middle_idx].get(middle_col))
        second_price = _safe_float(df.iloc[second_idx].get(second_col))
        if first_price is None or middle_price is None or second_price is None:
            return None
        if first_price <= 0 or second_price <= 0 or middle_price <= 0:
            return None

        avg_extreme = (first_price + second_price) / 2.0
        if avg_extreme <= 0:
            return None

        if self.is_top:
            middle_depth_pct = (avg_extreme - middle_price) / avg_extreme * 100.0
            middle_between_extremes = middle_price < min(first_price, second_price)
        else:
            middle_depth_pct = (middle_price - avg_extreme) / avg_extreme * 100.0
            middle_between_extremes = middle_price > max(first_price, second_price)

        spacing_bars = int(second_idx - first_idx + 1)
        slope_deg = abs(_slope_degrees(first_idx, first_price, second_idx, second_price))
        seg = df.iloc[first_idx : second_idx + 1].copy()
        same_close_ratio = None
        unique_close_ratio = None
        zero_range_ratio = None
        if not seg.empty:
            close = pd.to_numeric(seg.get("close"), errors="coerce")
            high = pd.to_numeric(seg.get("high"), errors="coerce")
            low = pd.to_numeric(seg.get("low"), errors="coerce")
            if close.notna().any():
                same_close_ratio = float((close.diff().abs().fillna(0.0) <= 1e-12).mean())
                unique_close_ratio = float(close.nunique(dropna=True) / max(1, len(close)))
            if high.notna().any() and low.notna().any():
                zero_range_ratio = float(((high - low).abs() <= 1e-12).mean())

        return {
            "first_idx": int(first_idx),
            "middle_idx": int(middle_idx),
            "second_idx": int(second_idx),
            "first_price": float(first_price),
            "middle_price": float(middle_price),
            "second_price": float(second_price),
            "extreme_price_ratio": round(float(second_price / first_price), 4),
            "extreme_price_diff_pct": round(float(_pct_diff(first_price, second_price)), 3),
            "middle_depth_pct": round(float(middle_depth_pct), 3),
            "extreme_spacing_bars": int(spacing_bars),
            "extreme_slope_deg": round(float(slope_deg), 3),
            "middle_between_extremes": bool(middle_between_extremes),
            "same_close_ratio": round(float(same_close_ratio), 3) if same_close_ratio is not None else None,
            "unique_close_ratio": round(float(unique_close_ratio), 3) if unique_close_ratio is not None else None,
            "zero_range_ratio": round(float(zero_range_ratio), 3) if zero_range_ratio is not None else None,
        }

    def _family_metrics_ok(self, metrics: Dict[str, Any]) -> bool:
        if not metrics.get("middle_between_extremes"):
            return False

        try:
            ratio = float(metrics["extreme_price_ratio"])
            depth_pct = float(metrics["middle_depth_pct"])
            spacing_bars = int(metrics["extreme_spacing_bars"])
            slope_deg = float(metrics["extreme_slope_deg"])
        except Exception:
            return False

        if ratio < self.extreme_ratio_min or ratio > self.extreme_ratio_max:
            return False
        if depth_pct < self.middle_depth_min_pct or depth_pct > self.middle_depth_max_pct:
            return False
        if spacing_bars < self.extreme_spacing_min_bars or spacing_bars > self.extreme_spacing_max_bars:
            return False
        if slope_deg > self.extreme_slope_max_deg:
            return False
        same_close_ratio = _safe_float(metrics.get("same_close_ratio"))
        unique_close_ratio = _safe_float(metrics.get("unique_close_ratio"))
        zero_range_ratio = _safe_float(metrics.get("zero_range_ratio"))
        if zero_range_ratio is not None and zero_range_ratio >= self.micro_max_zero_range_ratio:
            return False
        if (
            same_close_ratio is not None
            and unique_close_ratio is not None
            and same_close_ratio >= self.micro_max_same_close_ratio
            and unique_close_ratio <= self.micro_min_unique_close_ratio
        ):
            return False
        return True

    def _resolve_variant(self, df: pd.DataFrame, metrics: Dict[str, Any]) -> Dict[str, Any]:
        kwargs = {
            "first_idx": int(metrics["first_idx"]),
            "second_idx": int(metrics["second_idx"]),
            "adam_max": int(self.variant_adam_max),
            "eve_min": int(self.variant_eve_min),
        }
        if self.is_top:
            return resolve_double_top_variant(df, **kwargs)
        return resolve_double_bottom_variant(df, **kwargs)

    def _score_family_confidence(
        self,
        base_confidence: Any,
        metrics: Dict[str, Any],
        variant_result: Dict[str, Any],
    ) -> int:
        try:
            confidence = int(base_confidence)
        except Exception:
            confidence = 70

        diff_pct = float(metrics.get("extreme_price_diff_pct") or 0.0)
        spacing_bars = int(metrics.get("extreme_spacing_bars") or 0)
        depth_pct = float(metrics.get("middle_depth_pct") or 0.0)

        if diff_pct <= float(self.geom.get("near_equal_tolerance_pct") or 1.5):
            confidence += 5
        elif diff_pct <= float(self.geom.get("symmetry_tolerance_pct") or 3.0):
            confidence += 2

        if spacing_bars > 0:
            optimal_gap = abs(spacing_bars - int(self.extreme_spacing_optimal_bars))
            if optimal_gap <= 7:
                confidence += 2

        if self.middle_depth_min_pct <= depth_pct <= self.middle_depth_max_pct:
            confidence += 2

        variant_confidence = int(variant_result.get("variant_confidence") or 0)
        if variant_confidence >= 80:
            confidence += 3
        elif variant_confidence >= 58:
            confidence += 1

        return max(0, min(100, int(confidence)))

    def _variant_metrics_ok(
        self,
        metrics: Dict[str, Any],
        variant_result: Dict[str, Any],
    ) -> bool:
        variant_code = str(variant_result.get("variant_code") or "")
        if variant_code != "AA":
            return True

        same_close_ratio = _safe_float(metrics.get("same_close_ratio")) or 0.0
        unique_close_ratio = _safe_float(metrics.get("unique_close_ratio")) or 1.0
        zero_range_ratio = _safe_float(metrics.get("zero_range_ratio")) or 0.0
        extreme_price_diff_pct = _safe_float(metrics.get("extreme_price_diff_pct")) or 0.0
        extreme_slope_deg = _safe_float(metrics.get("extreme_slope_deg")) or 0.0
        middle_depth_pct = _safe_float(metrics.get("middle_depth_pct")) or 0.0

        if not self.is_top:
            aa_bottom_flat_micro = (
                same_close_ratio >= self.aa_bottom_same_close_ratio_min
                and (
                    zero_range_ratio >= self.aa_bottom_zero_range_ratio_min
                    or unique_close_ratio <= self.aa_bottom_unique_close_ratio_max
                )
            )
            return not aa_bottom_flat_micro

        aa_top_shallow_uneven = (
            extreme_price_diff_pct >= self.aa_top_diff_pct_min
            and extreme_slope_deg >= self.aa_top_slope_deg_min
            and middle_depth_pct <= self.aa_top_shallow_depth_pct_max
        )
        return not aa_top_shallow_uneven

    def scan(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> List[Dict[str, Any]]:
        base_rows = super().scan(symbol=symbol, df=df, pivots_filtered=pivots_filtered, pivots_raw=pivots_raw)
        out: List[Dict[str, Any]] = []

        for row in base_rows:
            metrics = self._family_metrics(df, row.get("pivot_indices") or [])
            if not metrics or not self._family_metrics_ok(metrics):
                continue

            variant_result = self._resolve_variant(df, metrics)
            if not self._variant_metrics_ok(metrics, variant_result):
                continue
            first_extreme = variant_result.get("first_extreme") or {}
            second_extreme = variant_result.get("second_extreme") or {}

            enriched = dict(row)
            enriched["base_pattern_name"] = self.key
            enriched["variant_code"] = variant_result.get("variant_code")
            enriched["variant_confidence"] = int(variant_result.get("variant_confidence") or 0)
            enriched["variant_evidence_json"] = json.dumps(
                variant_result.get("evidence") or {},
                sort_keys=True,
                ensure_ascii=False,
            )
            enriched["first_extreme_width_bars"] = first_extreme.get("width_bars")
            enriched["second_extreme_width_bars"] = second_extreme.get("width_bars")
            enriched["family_metrics_json"] = json.dumps(metrics, sort_keys=True, ensure_ascii=False)
            enriched["confidence_score"] = self._score_family_confidence(
                row.get("confidence_score"),
                metrics,
                variant_result,
            )
            out.append(enriched)

        return out


class DoubleBottomFamilyScanner(_DoublePatternFamilyScanner):
    def __init__(self, key: str, spec: Dict[str, Any]):
        super().__init__(key, spec, is_top=False)


class DoubleTopFamilyScanner(_DoublePatternFamilyScanner):
    def __init__(self, key: str, spec: Dict[str, Any]):
        super().__init__(key, spec, is_top=True)


class _HeadShouldersFamilyScanner(PivotSequenceScanner):
    """
    Dedicated family scanner for head-and-shoulders top/bottom.

    The generic 5-pivot sequence catches the broad shape, but it does not enforce the
    most important family semantics from the Bulkowski-derived spec: shoulder symmetry,
    head prominence, neckline slope, and a defensible separation between standard and
    complex variants. This wrapper tightens family validity first, then classifies
    standard vs complex from surrounding pivots.
    """

    def __init__(self, key: str, spec: Dict[str, Any], *, is_top: bool):
        super().__init__(key, spec)
        self.is_top = bool(is_top)
        geom = self.geom if isinstance(self.geom, dict) else {}

        self.standard_width_max = int(geom.get("width_max_bars") or 270)
        self.family_width_max = int(self.standard_width_max)
        variant_cfg = spec.get("variant_handling", {}) or {}
        for item in variant_cfg.get("variants", []) or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("name") or "").lower() != "complex":
                continue
            override = (item.get("parameter_overrides") or {}).get("width_max_bars")
            try:
                self.family_width_max = max(self.family_width_max, int(override))
            except Exception:
                pass
        self.geom["width_max_bars"] = int(self.family_width_max)

        shoulder_ratio_cfg = geom.get("shoulder_head_ratio", {}) or {}
        slope_cfg = geom.get("slope_constraints", {}) or {}
        prominence_key = "head_above_shoulders_pct" if self.is_top else "head_below_shoulders_pct"
        prominence_cfg = geom.get(prominence_key, {}) or {}

        self.shoulder_tol_pct = float(geom.get("symmetry_tolerance_pct") or 5.0)
        self.neckline_tol_pct = max(float(geom.get("near_equal_tolerance_pct") or 2.0), 3.0)
        self.neckline_max_slope_deg = abs(float(slope_cfg.get("neckline_max_slope_degrees") or 1.6))
        self.head_prominence_min_pct = float(prominence_cfg.get("min") or 2.0)
        self.height_min_pct = float(geom.get("height_ratio_min") or 10.0)
        self.height_max_pct = float(geom.get("height_ratio_max") or 40.0)
        self.shoulder_ratio_min = float(shoulder_ratio_cfg.get("min") or 0.85)
        self.shoulder_ratio_max = float(shoulder_ratio_cfg.get("max") or 1.05)
        self.side_span_ratio_max = 2.5
        self.extra_shoulder_spacing_bars = 5
        self.bottom_min_shoulder_clearance_pct = 8.0
        self.bottom_micro_max_zero_range_ratio = 0.84
        self.bottom_micro_same_close_ratio_max = 0.75
        self.bottom_micro_unique_close_ratio_min = 0.18
        self.bottom_relaxed_neckline_max_deg = 3.0
        self.bottom_relaxed_neckline_diff_pct = 4.0
        self.bottom_relaxed_shoulder_diff_pct = min(self.shoulder_tol_pct, 2.5)
        self.bottom_relaxed_span_ratio_max = 1.6

    def _family_metrics(self, df: pd.DataFrame, pivot_indices: Sequence[Any]) -> Optional[Dict[str, Any]]:
        if len(pivot_indices) < 5:
            return None
        try:
            ls_idx, nl1_idx, head_idx, nl2_idx, rs_idx = [int(x) for x in pivot_indices[:5]]
        except Exception:
            return None
        if not (0 <= ls_idx < nl1_idx < head_idx < nl2_idx < rs_idx < len(df)):
            return None

        extreme_col = "high" if self.is_top else "low"
        neck_col = "low" if self.is_top else "high"

        ls_price = _safe_float(df.iloc[ls_idx].get(extreme_col))
        head_price = _safe_float(df.iloc[head_idx].get(extreme_col))
        rs_price = _safe_float(df.iloc[rs_idx].get(extreme_col))
        nl1_price = _safe_float(df.iloc[nl1_idx].get(neck_col))
        nl2_price = _safe_float(df.iloc[nl2_idx].get(neck_col))
        if None in (ls_price, head_price, rs_price, nl1_price, nl2_price):
            return None
        if min(float(ls_price), float(head_price), float(rs_price), float(nl1_price), float(nl2_price)) <= 0:
            return None

        shoulder_level = (float(ls_price) + float(rs_price)) / 2.0
        neckline_level = (float(nl1_price) + float(nl2_price)) / 2.0
        if shoulder_level <= 0 or neckline_level <= 0:
            return None

        if self.is_top:
            head_prominence_pct = (float(head_price) - shoulder_level) / shoulder_level * 100.0
            shoulder_clearance_pct = (shoulder_level - neckline_level) / shoulder_level * 100.0
        else:
            head_prominence_pct = (shoulder_level - float(head_price)) / shoulder_level * 100.0
            shoulder_clearance_pct = (neckline_level - shoulder_level) / neckline_level * 100.0 if neckline_level > 0 else 0.0

        height_pct = abs(float(head_price) - neckline_level) / ((float(head_price) + neckline_level) / 2.0) * 100.0
        left_span = int(head_idx - ls_idx + 1)
        right_span = int(rs_idx - head_idx + 1)
        span_ratio = float(max(left_span, right_span) / max(1, min(left_span, right_span)))
        shoulder_ratio = float(rs_price / ls_price) if float(ls_price) > 0 else None
        formation = df.iloc[ls_idx : rs_idx + 1]
        close_series = formation["close"].astype(float)
        same_close_ratio = float((close_series.diff().abs() < 1e-12).mean()) if not close_series.empty else 0.0
        unique_close_ratio = float(close_series.nunique() / max(1, len(close_series))) if not close_series.empty else 0.0
        zero_range_ratio = (
            float((((formation["high"].astype(float) - formation["low"].astype(float)).abs()) < 1e-12).mean())
            if not formation.empty
            else 0.0
        )

        return {
            "ls_idx": int(ls_idx),
            "nl1_idx": int(nl1_idx),
            "head_idx": int(head_idx),
            "nl2_idx": int(nl2_idx),
            "rs_idx": int(rs_idx),
            "ls_price": float(ls_price),
            "head_price": float(head_price),
            "rs_price": float(rs_price),
            "nl1_price": float(nl1_price),
            "nl2_price": float(nl2_price),
            "shoulder_level": round(float(shoulder_level), 6),
            "neckline_level": round(float(neckline_level), 6),
            "shoulder_diff_pct": round(float(_pct_diff(float(ls_price), float(rs_price))), 3),
            "shoulder_ratio": round(float(shoulder_ratio), 4) if shoulder_ratio is not None else None,
            "head_prominence_pct": round(float(head_prominence_pct), 3),
            "shoulder_clearance_pct": round(float(shoulder_clearance_pct), 3),
            "height_pct": round(float(height_pct), 3),
            "neckline_diff_pct": round(float(_pct_diff(float(nl1_price), float(nl2_price))), 3),
            "neckline_slope_deg": round(float(abs(_slope_degrees(nl1_idx, float(nl1_price), nl2_idx, float(nl2_price)))), 3),
            "left_span_bars": int(left_span),
            "right_span_bars": int(right_span),
            "side_span_ratio": round(float(span_ratio), 3),
            "same_close_ratio": round(float(same_close_ratio), 3),
            "unique_close_ratio": round(float(unique_close_ratio), 3),
            "zero_range_ratio": round(float(zero_range_ratio), 3),
        }

    def _family_metrics_ok(self, metrics: Dict[str, Any]) -> bool:
        return len(self._family_gate_failures(metrics)) == 0

    def _family_gate_failures(self, metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        failures: List[Dict[str, Any]] = []
        try:
            shoulder_diff_pct = float(metrics["shoulder_diff_pct"])
            shoulder_ratio = float(metrics["shoulder_ratio"])
            head_prominence_pct = float(metrics["head_prominence_pct"])
            shoulder_clearance_pct = float(metrics["shoulder_clearance_pct"])
            height_pct = float(metrics["height_pct"])
            neckline_slope_deg = float(metrics["neckline_slope_deg"])
            neckline_diff_pct = float(metrics.get("neckline_diff_pct") or 0.0)
            span_ratio = float(metrics["side_span_ratio"])
        except Exception:
            return [{"rule": "invalid_metrics"}]

        if shoulder_diff_pct > self.shoulder_tol_pct:
            failures.append(
                {
                    "rule": "shoulder_diff_pct",
                    "actual": round(shoulder_diff_pct, 3),
                    "limit": round(float(self.shoulder_tol_pct), 3),
                    "margin": round(shoulder_diff_pct - float(self.shoulder_tol_pct), 3),
                }
            )
        if shoulder_ratio < self.shoulder_ratio_min or shoulder_ratio > self.shoulder_ratio_max:
            # The digitized ratio bounds are broader than symmetry_tolerance, but still reject
            # extreme asymmetric shoulders.
            if shoulder_ratio < self.shoulder_ratio_min:
                failures.append(
                    {
                        "rule": "shoulder_ratio_min",
                        "actual": round(shoulder_ratio, 4),
                        "limit": round(float(self.shoulder_ratio_min), 4),
                        "margin": round(float(self.shoulder_ratio_min) - shoulder_ratio, 4),
                    }
                )
            else:
                failures.append(
                    {
                        "rule": "shoulder_ratio_max",
                        "actual": round(shoulder_ratio, 4),
                        "limit": round(float(self.shoulder_ratio_max), 4),
                        "margin": round(shoulder_ratio - float(self.shoulder_ratio_max), 4),
                    }
                )
        if head_prominence_pct < self.head_prominence_min_pct:
            failures.append(
                {
                    "rule": "head_prominence_pct",
                    "actual": round(head_prominence_pct, 3),
                    "limit": round(float(self.head_prominence_min_pct), 3),
                    "margin": round(float(self.head_prominence_min_pct) - head_prominence_pct, 3),
                }
            )
        if shoulder_clearance_pct <= 0:
            failures.append(
                {
                    "rule": "shoulder_clearance_nonpositive",
                    "actual": round(shoulder_clearance_pct, 3),
                    "limit": 0.0,
                    "margin": round(0.0 - shoulder_clearance_pct, 3),
                }
            )
        if height_pct < self.height_min_pct or height_pct > self.height_max_pct:
            if height_pct < self.height_min_pct:
                failures.append(
                    {
                        "rule": "height_pct_min",
                        "actual": round(height_pct, 3),
                        "limit": round(float(self.height_min_pct), 3),
                        "margin": round(float(self.height_min_pct) - height_pct, 3),
                    }
                )
            else:
                failures.append(
                    {
                        "rule": "height_pct_max",
                        "actual": round(height_pct, 3),
                        "limit": round(float(self.height_max_pct), 3),
                        "margin": round(height_pct - float(self.height_max_pct), 3),
                    }
                )
        relaxed_bottom_neckline = (
            (not self.is_top)
            and neckline_slope_deg <= self.bottom_relaxed_neckline_max_deg
            and neckline_diff_pct <= self.bottom_relaxed_neckline_diff_pct
            and shoulder_diff_pct <= self.bottom_relaxed_shoulder_diff_pct
            and span_ratio <= self.bottom_relaxed_span_ratio_max
            and shoulder_clearance_pct >= self.bottom_min_shoulder_clearance_pct
        )
        if neckline_slope_deg > self.neckline_max_slope_deg and not relaxed_bottom_neckline:
            failures.append(
                {
                    "rule": "neckline_slope_deg",
                    "actual": round(neckline_slope_deg, 3),
                    "limit": round(float(self.neckline_max_slope_deg), 3),
                    "margin": round(neckline_slope_deg - float(self.neckline_max_slope_deg), 3),
                }
            )
        if span_ratio > self.side_span_ratio_max:
            failures.append(
                {
                    "rule": "side_span_ratio",
                    "actual": round(span_ratio, 3),
                    "limit": round(float(self.side_span_ratio_max), 3),
                    "margin": round(span_ratio - float(self.side_span_ratio_max), 3),
                }
            )
        if not self.is_top:
            same_close_ratio = float(metrics.get("same_close_ratio") or 0.0)
            unique_close_ratio = float(metrics.get("unique_close_ratio") or 0.0)
            zero_range_ratio = float(metrics.get("zero_range_ratio") or 0.0)
            if shoulder_clearance_pct < self.bottom_min_shoulder_clearance_pct:
                failures.append(
                    {
                        "rule": "bottom_shoulder_clearance_pct",
                        "actual": round(shoulder_clearance_pct, 3),
                        "limit": round(float(self.bottom_min_shoulder_clearance_pct), 3),
                        "margin": round(float(self.bottom_min_shoulder_clearance_pct) - shoulder_clearance_pct, 3),
                    }
                )
            if zero_range_ratio >= self.bottom_micro_max_zero_range_ratio:
                failures.append(
                    {
                        "rule": "bottom_zero_range_ratio",
                        "actual": round(zero_range_ratio, 3),
                        "limit": round(float(self.bottom_micro_max_zero_range_ratio), 3),
                        "margin": round(zero_range_ratio - float(self.bottom_micro_max_zero_range_ratio), 3),
                    }
                )
            if (
                same_close_ratio >= self.bottom_micro_same_close_ratio_max
                and unique_close_ratio <= self.bottom_micro_unique_close_ratio_min
            ):
                failures.append(
                    {
                        "rule": "bottom_flat_microstructure",
                        "same_close_ratio": round(same_close_ratio, 3),
                        "same_close_limit": round(float(self.bottom_micro_same_close_ratio_max), 3),
                        "unique_close_ratio": round(unique_close_ratio, 3),
                        "unique_close_limit": round(float(self.bottom_micro_unique_close_ratio_min), 3),
                    }
                )
        return failures

    def _dedupe_extra_pivots(self, pivots: List[Pivot], *, head_idx: int) -> Dict[str, List[Pivot]]:
        left: List[Pivot] = []
        right: List[Pivot] = []
        last_left = None
        last_right = None
        for p in sorted(pivots, key=lambda x: int(x.idx)):
            idx = int(p.idx)
            if idx < head_idx:
                if last_left is None or idx - last_left >= self.extra_shoulder_spacing_bars:
                    left.append(p)
                    last_left = idx
            elif idx > head_idx:
                if last_right is None or idx - last_right >= self.extra_shoulder_spacing_bars:
                    right.append(p)
                    last_right = idx
        return {"left": left, "right": right}

    def _has_local_neckline_retrace(
        self,
        candidate: Pivot,
        *,
        source: Sequence[Pivot],
        neckline_level: float,
        ls_idx: int,
        rs_idx: int,
    ) -> bool:
        neck_type = PivotType.LOW if self.is_top else PivotType.HIGH
        idx = int(candidate.idx)
        prev_neck: Optional[Pivot] = None
        next_neck: Optional[Pivot] = None

        for p in sorted(source, key=lambda x: int(x.idx)):
            p_idx = int(p.idx)
            if p_idx <= ls_idx or p_idx >= rs_idx or p_idx == idx or p.type != neck_type:
                continue
            if p_idx < idx:
                prev_neck = p
                continue
            next_neck = p
            break

        tol_pct = max(self.neckline_tol_pct, 4.0)
        for neck in (prev_neck, next_neck):
            if neck is None:
                continue
            if _pct_diff(float(neck.price), float(neckline_level)) <= tol_pct:
                return True
        return False

    def _classify_variant(
        self,
        *,
        row: Dict[str, Any],
        metrics: Dict[str, Any],
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> Dict[str, Any]:
        shoulder_level = float(metrics["shoulder_level"])
        neckline_level = float(metrics["neckline_level"])
        head_price = float(metrics["head_price"])
        ls_idx = int(metrics["ls_idx"])
        head_idx = int(metrics["head_idx"])
        rs_idx = int(metrics["rs_idx"])

        target_type = PivotType.HIGH if self.is_top else PivotType.LOW
        tol = max(self.shoulder_tol_pct, self.neckline_tol_pct)
        known = {ls_idx, head_idx, rs_idx}
        source = pivots_raw or pivots_filtered

        candidate_extras: List[Pivot] = []
        for p in source:
            idx = int(p.idx)
            if p.type != target_type or idx <= ls_idx or idx >= rs_idx or idx in known:
                continue
            if min(abs(idx - ls_idx), abs(idx - head_idx), abs(idx - rs_idx)) < self.extra_shoulder_spacing_bars:
                continue
            price = float(p.price)
            if _pct_diff(price, shoulder_level) > tol:
                continue
            if self.is_top:
                if price >= head_price * (1.0 - max(0.01, self.head_prominence_min_pct / 200.0)):
                    continue
                if price <= neckline_level:
                    continue
            else:
                if price <= head_price * (1.0 + max(0.01, self.head_prominence_min_pct / 200.0)):
                    continue
                if price >= neckline_level:
                    continue
            candidate_extras.append(p)

        candidate_deduped = self._dedupe_extra_pivots(candidate_extras, head_idx=head_idx)
        deduped = {
            "left": [
                p
                for p in candidate_deduped["left"]
                if self._has_local_neckline_retrace(
                    p,
                    source=source,
                    neckline_level=neckline_level,
                    ls_idx=ls_idx,
                    rs_idx=rs_idx,
                )
            ],
            "right": [
                p
                for p in candidate_deduped["right"]
                if self._has_local_neckline_retrace(
                    p,
                    source=source,
                    neckline_level=neckline_level,
                    ls_idx=ls_idx,
                    rs_idx=rs_idx,
                )
            ],
        }
        left_count = len(deduped["left"])
        right_count = len(deduped["right"])
        extra_count = left_count + right_count

        evidence: Dict[str, Any] = {
            "candidate_shoulders_left": len(candidate_deduped["left"]),
            "candidate_shoulders_right": len(candidate_deduped["right"]),
            "candidate_shoulders_total": len(candidate_deduped["left"]) + len(candidate_deduped["right"]),
            "extra_shoulders_left": left_count,
            "extra_shoulders_right": right_count,
            "extra_shoulders_total": extra_count,
            "width_exceeds_standard_max": bool(int(row.get("pattern_width_bars") or 0) > int(self.standard_width_max)),
        }

        if extra_count >= 2 or (left_count >= 1 and right_count >= 1):
            return {"variant_code": "complex", "variant_confidence": 88, "evidence": evidence}
        if extra_count == 1:
            return {"variant_code": "complex", "variant_confidence": 76, "evidence": evidence}
        if bool(evidence["width_exceeds_standard_max"]):
            return {"variant_code": "complex", "variant_confidence": 58, "evidence": evidence}
        return {"variant_code": "standard", "variant_confidence": 82, "evidence": evidence}

    def _score_family_confidence(
        self,
        base_confidence: Any,
        metrics: Dict[str, Any],
        variant_result: Dict[str, Any],
    ) -> int:
        try:
            confidence = int(base_confidence)
        except Exception:
            confidence = 70

        if float(metrics.get("shoulder_diff_pct") or 999.0) <= (self.shoulder_tol_pct / 2.0):
            confidence += 4
        if float(metrics.get("head_prominence_pct") or 0.0) >= (self.head_prominence_min_pct + 1.5):
            confidence += 3
        if float(metrics.get("neckline_slope_deg") or 999.0) <= (self.neckline_max_slope_deg / 2.0):
            confidence += 3
        if float(metrics.get("side_span_ratio") or 999.0) <= 1.6:
            confidence += 2

        variant_confidence = int(variant_result.get("variant_confidence") or 0)
        if variant_confidence >= 80:
            confidence += 2

        return max(0, min(100, int(confidence)))

    def scan(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> List[Dict[str, Any]]:
        base_rows = super().scan(symbol=symbol, df=df, pivots_filtered=pivots_filtered, pivots_raw=pivots_raw)
        out: List[Dict[str, Any]] = []
        for row in base_rows:
            if row.get("breakout_idx") is None or _safe_float(row.get("breakout_price")) is None:
                continue
            metrics = self._family_metrics(df, row.get("pivot_indices") or [])
            if not metrics or not self._family_metrics_ok(metrics):
                continue

            variant_result = self._classify_variant(
                row=row,
                metrics=metrics,
                pivots_filtered=pivots_filtered,
                pivots_raw=pivots_raw,
            )
            enriched = dict(row)
            enriched["base_pattern_name"] = self.key
            enriched["variant_code"] = variant_result.get("variant_code")
            enriched["variant_confidence"] = int(variant_result.get("variant_confidence") or 0)
            enriched["variant_evidence_json"] = json.dumps(
                variant_result.get("evidence") or {},
                sort_keys=True,
                ensure_ascii=False,
            )
            enriched["family_metrics_json"] = json.dumps(metrics, sort_keys=True, ensure_ascii=False)
            enriched["confidence_score"] = self._score_family_confidence(
                row.get("confidence_score"),
                metrics,
                variant_result,
            )
            out.append(enriched)
        return out


class HeadShouldersTopFamilyScanner(_HeadShouldersFamilyScanner):
    def __init__(self, key: str, spec: Dict[str, Any]):
        super().__init__(key, spec, is_top=True)


class HeadShouldersBottomFamilyScanner(_HeadShouldersFamilyScanner):
    def __init__(self, key: str, spec: Dict[str, Any]):
        super().__init__(key, spec, is_top=False)

    def _classify_variant(
        self,
        *,
        row: Dict[str, Any],
        metrics: Dict[str, Any],
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> Dict[str, Any]:
        result = super()._classify_variant(
            row=row,
            metrics=metrics,
            pivots_filtered=pivots_filtered,
            pivots_raw=pivots_raw,
        )
        if str(result.get("variant_code") or "") != "complex":
            return result

        evidence = dict(result.get("evidence") or {})
        extra_total = int(evidence.get("extra_shoulders_total") or 0)
        width_exceeds = bool(evidence.get("width_exceeds_standard_max"))
        if extra_total == 1 and not width_exceeds:
            evidence["single_extra_demoted_to_standard"] = True
            return {
                "variant_code": "standard",
                "variant_confidence": 68,
                "evidence": evidence,
            }
        return result


class TriangleFamilyScanner(BaseDigitizedScanner):
    """
    Dedicated family scanner for triangles.

    The old shared-spec splitter only looked at relative highs/lows on a single 5-pivot
    sequence. That was too permissive: channels, flat compressions, and post-apex ranges
    were frequently labeled as triangles. This family scanner matches both boundary-start
    sequences, then enforces slope + convergence semantics before assigning the Bulkowski
    chapter variants.
    """

    def __init__(self, key: str, spec: Dict[str, Any]):
        super().__init__(key, spec)
        self.geom = spec.get("geometry_constraints", {}) or {}
        self.variant_cfg = spec.get("variant_handling", {}) or {}

        self.flat_deg_max = 3.0
        self.rising_deg_min = 3.0
        self.falling_deg_max = -4.0
        self.progress_min_pct = 30.0
        self.progress_max_pct = 95.0
        self.compression_min_ratio = 0.05
        self.compression_max_ratio = 0.85
        self.boundary_fit_error_max_pct = 30.0
        self.ascending_upper_deg_max = 1.0
        self.ascending_lower_deg_min = 7.0
        self.ascending_progress_min_pct = 55.0
        self.ascending_compression_max_ratio = 0.45

        high_first = copy.deepcopy(spec)
        high_first.setdefault("detection_signature", {})
        high_first["detection_signature"]["pivot_sequence"] = ["H", "L", "H", "L", "H"]
        high_first["detection_signature"]["mandatory_pivots"] = []

        low_first = copy.deepcopy(spec)
        low_first.setdefault("detection_signature", {})
        low_first["detection_signature"]["pivot_sequence"] = ["L", "H", "L", "H", "L"]
        low_first["detection_signature"]["mandatory_pivots"] = []

        self._high_first = PivotSequenceScanner("__triangles_high_first", high_first)
        self._low_first = PivotSequenceScanner("__triangles_low_first", low_first)

    def _collect_points(
        self,
        df: pd.DataFrame,
        pivots: List[int],
        tokens: List[str],
    ) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
        highs: List[Tuple[int, float]] = []
        lows: List[Tuple[int, float]] = []
        for idx, token in zip(pivots, tokens):
            if idx < 0 or idx >= len(df):
                return [], []
            if token == "H":
                highs.append((idx, float(df.iloc[idx]["high"])))
            elif token == "L":
                lows.append((idx, float(df.iloc[idx]["low"])))
        return highs, lows

    def _build_line(self, points: List[Tuple[int, float]]) -> Optional[Trendline]:
        if len(points) < 2:
            return None
        idx0, price0 = points[0]
        idx1, price1 = points[-1]
        bars = max(1, idx1 - idx0)
        return Trendline(
            idx0=idx0,
            price0=float(price0),
            slope_per_bar=(float(price1) - float(price0)) / bars,
        )

    def _fit_error_pct(
        self,
        *,
        line: Trendline,
        points: List[Tuple[int, float]],
        start_gap: float,
    ) -> Optional[float]:
        if len(points) <= 2 or start_gap <= 0:
            return None
        errs = [
            abs(float(price) - line.value_at(int(idx))) / start_gap * 100.0
            for idx, price in points[1:-1]
        ]
        return max(errs) if errs else None

    def _family_metrics(
        self,
        df: pd.DataFrame,
        pivots: List[Any],
        *,
        sequence_tag: str,
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(pivots, (list, tuple)) or len(pivots) < 5:
            return None
        try:
            idxs = [int(x) for x in pivots[:5]]
        except Exception:
            return None
        if any(i < 0 or i >= len(df) for i in idxs):
            return None

        tokens = list(sequence_tag)
        highs, lows = self._collect_points(df, idxs, tokens)
        if len(highs) < 2 or len(lows) < 2:
            return None

        upper = self._build_line(highs)
        lower = self._build_line(lows)
        if upper is None or lower is None:
            return None

        start_idx = int(idxs[0])
        end_idx = int(idxs[-1])
        mid_idx = int(idxs[len(idxs) // 2])
        start_gap = float(upper.value_at(start_idx) - lower.value_at(start_idx))
        mid_gap = float(upper.value_at(mid_idx) - lower.value_at(mid_idx))
        end_gap = float(upper.value_at(end_idx) - lower.value_at(end_idx))
        compression_ratio = (end_gap / start_gap) if start_gap > 0 else None

        upper_fit_error_pct = self._fit_error_pct(line=upper, points=highs, start_gap=start_gap)
        lower_fit_error_pct = self._fit_error_pct(line=lower, points=lows, start_gap=start_gap)
        boundary_fit_error_pct = max(
            [x for x in (upper_fit_error_pct, lower_fit_error_pct) if x is not None],
            default=None,
        )

        apex_idx = None
        apex_progress_pct = None
        bars_to_apex = None
        slope_delta = float(upper.slope_per_bar - lower.slope_per_bar)
        if abs(slope_delta) > 1e-9:
            apex = upper.idx0 + (lower.value_at(upper.idx0) - upper.price0) / slope_delta
            if np.isfinite(apex):
                apex_idx = float(apex)
                if apex > start_idx:
                    apex_progress_pct = (end_idx - start_idx) / max(1e-9, apex - start_idx) * 100.0
                if apex > end_idx:
                    bars_to_apex = float(apex - end_idx)

        return {
            "sequence_tag": sequence_tag,
            "start_idx": start_idx,
            "end_idx": end_idx,
            "high_touch_count": len(highs),
            "low_touch_count": len(lows),
            "upper_slope_deg": float(_slope_degrees(highs[0][0], highs[0][1], highs[-1][0], highs[-1][1])),
            "lower_slope_deg": float(_slope_degrees(lows[0][0], lows[0][1], lows[-1][0], lows[-1][1])),
            "upper_slope_per_bar": float(upper.slope_per_bar),
            "lower_slope_per_bar": float(lower.slope_per_bar),
            "start_gap": start_gap,
            "mid_gap": mid_gap,
            "end_gap": end_gap,
            "compression_ratio": compression_ratio,
            "gap_reduction_pct": ((1.0 - compression_ratio) * 100.0) if compression_ratio is not None else None,
            "upper_fit_error_pct": upper_fit_error_pct,
            "lower_fit_error_pct": lower_fit_error_pct,
            "boundary_fit_error_pct": boundary_fit_error_pct,
            "apex_idx": apex_idx,
            "apex_progress_pct": apex_progress_pct,
            "bars_to_apex": bars_to_apex,
            "breakout_direction": None,
        }

    def _family_metrics_ok(self, metrics: Dict[str, Any]) -> bool:
        start_gap = float(metrics.get("start_gap") or 0.0)
        mid_gap = float(metrics.get("mid_gap") or 0.0)
        end_gap = float(metrics.get("end_gap") or 0.0)
        compression_ratio = _safe_float(metrics.get("compression_ratio"))
        progress = _safe_float(metrics.get("apex_progress_pct"))
        fit_error = _safe_float(metrics.get("boundary_fit_error_pct"))
        upper_slope = _safe_float(metrics.get("upper_slope_per_bar"))
        lower_slope = _safe_float(metrics.get("lower_slope_per_bar"))

        if start_gap <= 0 or mid_gap <= 0 or end_gap <= 0:
            return False
        if compression_ratio is None or compression_ratio < self.compression_min_ratio or compression_ratio > self.compression_max_ratio:
            return False
        if progress is None or progress < self.progress_min_pct or progress > self.progress_max_pct:
            return False
        if fit_error is not None and fit_error > self.boundary_fit_error_max_pct:
            return False
        if upper_slope is None or lower_slope is None or upper_slope >= lower_slope:
            return False
        return True

    def _resolve_variant(self, metrics: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        upper_deg = float(metrics.get("upper_slope_deg") or 0.0)
        lower_deg = float(metrics.get("lower_slope_deg") or 0.0)
        progress = float(metrics.get("apex_progress_pct") or 0.0)
        compression_ratio = float(metrics.get("compression_ratio") or 0.0)
        evidence = {
            "upper_slope_deg": round(upper_deg, 2),
            "lower_slope_deg": round(lower_deg, 2),
            "compression_ratio": round(compression_ratio, 3),
            "apex_progress_pct": round(progress, 1),
            "boundary_fit_error_pct": round(float(metrics.get("boundary_fit_error_pct") or 0.0), 2),
            "sequence_tag": metrics.get("sequence_tag"),
        }

        if abs(upper_deg) <= self.flat_deg_max and lower_deg >= self.rising_deg_min:
            if upper_deg > self.ascending_upper_deg_max:
                return None
            if lower_deg < self.ascending_lower_deg_min:
                return None
            if progress < self.ascending_progress_min_pct:
                return None
            if compression_ratio > self.ascending_compression_max_ratio:
                return None
            conf = 76
            if abs(upper_deg) <= 1.5 and lower_deg >= 5.0:
                conf += 8
            if 45.0 <= progress <= 80.0:
                conf += 4
            if compression_ratio <= 0.50:
                conf += 2
            return {
                "variant_code": "ascending",
                "variant_confidence": min(100, conf),
                "pattern_type": "continuation_bullish",
                "evidence": evidence,
            }

        if upper_deg <= self.falling_deg_max and abs(lower_deg) <= self.flat_deg_max:
            conf = 76
            if upper_deg <= -7.0 and abs(lower_deg) <= 1.5:
                conf += 8
            if 45.0 <= progress <= 80.0:
                conf += 4
            if compression_ratio <= 0.50:
                conf += 2
            return {
                "variant_code": "descending",
                "variant_confidence": min(100, conf),
                "pattern_type": "continuation_bearish",
                "evidence": evidence,
            }

        if upper_deg <= self.falling_deg_max and lower_deg >= self.rising_deg_min:
            conf = 74
            if upper_deg <= -6.0 and lower_deg >= 5.0:
                conf += 8
            if 50.0 <= progress <= 85.0:
                conf += 4
            if compression_ratio <= 0.45:
                conf += 2
            return {
                "variant_code": "symmetrical",
                "variant_confidence": min(100, conf),
                "pattern_type": "continuation_neutral",
                "evidence": evidence,
            }

        return None

    def _score_family_confidence(
        self,
        base_confidence: Any,
        metrics: Dict[str, Any],
        variant_result: Dict[str, Any],
    ) -> int:
        try:
            confidence = int(base_confidence)
        except Exception:
            confidence = 70

        fit_error = float(metrics.get("boundary_fit_error_pct") or 999.0)
        progress = float(metrics.get("apex_progress_pct") or 0.0)
        compression_ratio = float(metrics.get("compression_ratio") or 9.0)

        if fit_error <= 10.0:
            confidence += 4
        elif fit_error <= 20.0:
            confidence += 2

        if 50.0 <= progress <= 75.0:
            confidence += 3
        elif self.progress_min_pct <= progress <= 90.0:
            confidence += 1

        if compression_ratio <= 0.35:
            confidence += 3
        elif compression_ratio <= 0.55:
            confidence += 1

        variant_confidence = int(variant_result.get("variant_confidence") or 0)
        if variant_confidence >= 84:
            confidence += 3
        elif variant_confidence >= 76:
            confidence += 1

        return max(0, min(100, confidence))

    def scan(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> List[Dict[str, Any]]:
        tagged_rows: List[Tuple[Dict[str, Any], str]] = []
        for scanner, sequence_tag in (
            (self._high_first, "HLHLH"),
            (self._low_first, "LHLHL"),
        ):
            for row in scanner.scan(symbol=symbol, df=df, pivots_filtered=pivots_filtered, pivots_raw=pivots_raw):
                tagged_rows.append((dict(row), sequence_tag))

        deduped: Dict[Tuple[int, ...], Dict[str, Any]] = {}
        out: List[Dict[str, Any]] = []
        for row, sequence_tag in tagged_rows:
            pivots = row.get("pivot_indices") or []
            key = tuple(int(x) for x in pivots[:5]) if isinstance(pivots, (list, tuple)) else ()
            if not key:
                continue

            metrics = self._family_metrics(df, list(key), sequence_tag=sequence_tag)
            if not metrics:
                continue
            metrics["breakout_direction"] = row.get("breakout_direction")
            if not self._family_metrics_ok(metrics):
                continue

            variant_result = self._resolve_variant(metrics)
            if not variant_result:
                continue

            enriched = dict(row)
            enriched["pattern_name"] = self.key
            enriched["pattern_id"] = f"{symbol}_{self.key}_{key[0]}_{key[-1]}"
            enriched["pattern_type"] = variant_result.get("pattern_type") or self.pattern_type
            enriched["base_pattern_name"] = self.key
            enriched["variant_code"] = variant_result.get("variant_code")
            enriched["variant_confidence"] = int(variant_result.get("variant_confidence") or 0)
            enriched["variant_evidence_json"] = json.dumps(
                variant_result.get("evidence") or {},
                sort_keys=True,
                ensure_ascii=False,
            )
            enriched["family_metrics_json"] = json.dumps(metrics, sort_keys=True, ensure_ascii=False)
            enriched["confidence_score"] = self._score_family_confidence(
                row.get("confidence_score"),
                metrics,
                variant_result,
            )

            prev = deduped.get(key)
            if prev is None or int(enriched.get("confidence_score") or 0) > int(prev.get("confidence_score") or 0):
                deduped[key] = enriched

        out.extend(deduped.values())
        return out


class BroadeningWedgeFamilyScanner(PivotSequenceScanner):
    """
    Dedicated family scanner for broadening wedges.

    The old chapter splitter reused a generic 6-pivot detector and only checked
    the sign of the first/last boundary slopes. That admitted broad channels and
    loose megaphones with poor boundary discipline. This wrapper keeps the same
    base sequence, then requires coherent same-direction diverging boundaries
    before assigning ascending vs descending chapters.
    """

    def __init__(self, key: str, spec: Dict[str, Any]):
        super().__init__(key, spec)
        self.divergence_min_ratio = 1.10
        self.fit_error_max_pct = 26.0
        self.min_abs_slope_deg = 0.4
        self.min_slope_gap_deg = 1.0
        self.max_width_bars = min(int(self.geom.get("width_max_bars") or 180), 165)

    def _family_metrics(self, df: pd.DataFrame, pivots: Sequence[Any]) -> Optional[Dict[str, Any]]:
        if len(pivots) < 6:
            return None
        try:
            idxs = [int(x) for x in pivots[:6]]
        except Exception:
            return None
        if any(i < 0 or i >= len(df) for i in idxs):
            return None
        hs = [idxs[i] for i in (0, 2, 4)]
        ls = [idxs[i] for i in (1, 3, 5)]
        if not (hs[0] < ls[0] < hs[1] < ls[1] < hs[2] < ls[2]):
            return None

        highs = [(idx, float(df.iloc[idx]["high"])) for idx in hs]
        lows = [(idx, float(df.iloc[idx]["low"])) for idx in ls]
        upper = Trendline(
            idx0=highs[0][0],
            price0=highs[0][1],
            slope_per_bar=(highs[-1][1] - highs[0][1]) / max(1, highs[-1][0] - highs[0][0]),
        )
        lower = Trendline(
            idx0=lows[0][0],
            price0=lows[0][1],
            slope_per_bar=(lows[-1][1] - lows[0][1]) / max(1, lows[-1][0] - lows[0][0]),
        )

        start_idx = idxs[0]
        end_idx = idxs[-1]
        start_gap = upper.value_at(start_idx) - lower.value_at(start_idx)
        mid_idx = idxs[2]
        mid_gap = upper.value_at(mid_idx) - lower.value_at(mid_idx)
        end_gap = upper.value_at(end_idx) - lower.value_at(end_idx)
        if start_gap <= 0 or mid_gap <= 0 or end_gap <= 0:
            return None

        def _fit_error(line: Trendline, points: List[Tuple[int, float]]) -> Optional[float]:
            errs = [
                abs(price - line.value_at(idx)) / start_gap * 100.0
                for idx, price in points[1:-1]
            ]
            return max(errs) if errs else None

        upper_fit = _fit_error(upper, highs)
        lower_fit = _fit_error(lower, lows)
        boundary_fit = max([x for x in (upper_fit, lower_fit) if x is not None], default=None)
        width_bars = end_idx - start_idx + 1
        divergence_ratio = end_gap / start_gap
        slope_gap_deg = abs(
            _slope_degrees(highs[0][0], highs[0][1], highs[-1][0], highs[-1][1])
            - _slope_degrees(lows[0][0], lows[0][1], lows[-1][0], lows[-1][1])
        )

        return {
            "start_idx": int(start_idx),
            "end_idx": int(end_idx),
            "width_bars": int(width_bars),
            "upper_slope_deg": float(_slope_degrees(highs[0][0], highs[0][1], highs[-1][0], highs[-1][1])),
            "lower_slope_deg": float(_slope_degrees(lows[0][0], lows[0][1], lows[-1][0], lows[-1][1])),
            "upper_slope_per_bar": float(upper.slope_per_bar),
            "lower_slope_per_bar": float(lower.slope_per_bar),
            "start_gap": float(start_gap),
            "mid_gap": float(mid_gap),
            "end_gap": float(end_gap),
            "divergence_ratio": float(divergence_ratio),
            "gap_growth_pct": float((divergence_ratio - 1.0) * 100.0),
            "upper_fit_error_pct": upper_fit,
            "lower_fit_error_pct": lower_fit,
            "boundary_fit_error_pct": boundary_fit,
            "slope_gap_deg": float(slope_gap_deg),
        }

    def _family_metrics_ok(self, metrics: Dict[str, Any]) -> bool:
        upper_deg = float(metrics.get("upper_slope_deg") or 0.0)
        lower_deg = float(metrics.get("lower_slope_deg") or 0.0)
        divergence_ratio = float(metrics.get("divergence_ratio") or 0.0)
        fit_error = _safe_float(metrics.get("boundary_fit_error_pct"))
        width_bars = int(metrics.get("width_bars") or 0)
        slope_gap_deg = float(metrics.get("slope_gap_deg") or 0.0)

        if width_bars <= 0 or width_bars > self.max_width_bars:
            return False
        if divergence_ratio < self.divergence_min_ratio:
            return False
        if fit_error is not None and fit_error > self.fit_error_max_pct:
            return False
        if abs(upper_deg) < self.min_abs_slope_deg or abs(lower_deg) < self.min_abs_slope_deg:
            return False
        if slope_gap_deg < self.min_slope_gap_deg:
            return False
        return True

    def _resolve_variant(self, metrics: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        upper_deg = float(metrics.get("upper_slope_deg") or 0.0)
        lower_deg = float(metrics.get("lower_slope_deg") or 0.0)
        divergence_ratio = float(metrics.get("divergence_ratio") or 0.0)
        evidence = {
            "upper_slope_deg": round(upper_deg, 2),
            "lower_slope_deg": round(lower_deg, 2),
            "divergence_ratio": round(divergence_ratio, 3),
            "boundary_fit_error_pct": round(float(metrics.get("boundary_fit_error_pct") or 0.0), 2),
            "slope_gap_deg": round(float(metrics.get("slope_gap_deg") or 0.0), 2),
        }

        if upper_deg > 0.0 and lower_deg > 0.0 and upper_deg > lower_deg + 0.4:
            conf = 76
            if divergence_ratio >= 1.20:
                conf += 4
            if upper_deg >= 3.5 and lower_deg >= 1.0:
                conf += 4
            return {
                "variant_code": "ascending",
                "variant_confidence": min(100, conf),
                "pattern_type": "continuation_bullish",
                "evidence": evidence,
            }

        if upper_deg < 0.0 and lower_deg < 0.0 and lower_deg < upper_deg - 0.4:
            conf = 76
            if divergence_ratio >= 1.20:
                conf += 4
            if upper_deg <= -1.0 and lower_deg <= -3.5:
                conf += 4
            return {
                "variant_code": "descending",
                "variant_confidence": min(100, conf),
                "pattern_type": "continuation_bearish",
                "evidence": evidence,
            }
        return None

    def _score_family_confidence(self, base_confidence: Any, metrics: Dict[str, Any], variant_result: Dict[str, Any]) -> int:
        try:
            confidence = int(base_confidence)
        except Exception:
            confidence = 70
        divergence_ratio = float(metrics.get("divergence_ratio") or 0.0)
        fit_error = float(metrics.get("boundary_fit_error_pct") or 999.0)
        if divergence_ratio >= 1.20:
            confidence += 4
        elif divergence_ratio >= 1.14:
            confidence += 2
        if fit_error <= 12.0:
            confidence += 4
        elif fit_error <= 20.0:
            confidence += 2
        if int(variant_result.get("variant_confidence") or 0) >= 84:
            confidence += 2
        return max(0, min(100, confidence))

    def scan(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> List[Dict[str, Any]]:
        base_rows = super().scan(symbol=symbol, df=df, pivots_filtered=pivots_filtered, pivots_raw=pivots_raw)
        out: List[Dict[str, Any]] = []
        for row in base_rows:
            if row.get("breakout_idx") is None or _safe_float(row.get("breakout_price")) is None:
                continue
            metrics = self._family_metrics(df, row.get("pivot_indices") or [])
            if not metrics or not self._family_metrics_ok(metrics):
                continue
            variant = self._resolve_variant(metrics)
            if not variant:
                continue
            enriched = dict(row)
            enriched["pattern_name"] = self.key
            enriched["base_pattern_name"] = self.key
            enriched["variant_code"] = variant.get("variant_code")
            enriched["variant_confidence"] = int(variant.get("variant_confidence") or 0)
            enriched["variant_evidence_json"] = json.dumps(variant.get("evidence") or {}, sort_keys=True, ensure_ascii=False)
            enriched["family_metrics_json"] = json.dumps(metrics, sort_keys=True, ensure_ascii=False)
            enriched["pattern_type"] = variant.get("pattern_type") or self.pattern_type
            enriched["confidence_score"] = self._score_family_confidence(
                row.get("confidence_score"),
                metrics,
                variant,
            )
            out.append(enriched)
        return out


class HornFamilyScanner(BaseDigitizedScanner):
    """
    Dedicated family scanner for horn bottoms/tops.

    The legacy mapping only split the shared detector by breakout direction. Horns
    are much stricter than that: they are short, sharp, symmetric spike reversals.
    This scanner evaluates both mirrored 3-pivot sequences and keeps only the fast,
    V-shaped structures that match the family semantics.
    """

    def __init__(self, key: str, spec: Dict[str, Any]):
        super().__init__(key, spec)
        self.geom = spec.get("geometry_constraints", {}) or {}
        self.prior = spec.get("prior_trend_requirements", {}) or {}

        hlh = copy.deepcopy(spec)
        hlh.setdefault("detection_signature", {})
        hlh["detection_signature"]["pivot_sequence"] = ["H", "L", "H"]
        hlh["detection_signature"]["mandatory_pivots"] = []
        hlh["pattern_type"] = "reversal_bearish"

        lhl = copy.deepcopy(spec)
        lhl.setdefault("detection_signature", {})
        lhl["detection_signature"]["pivot_sequence"] = ["L", "H", "L"]
        lhl["detection_signature"]["mandatory_pivots"] = []
        lhl["pattern_type"] = "reversal_bullish"

        self._top = PivotSequenceScanner("__horns_hlh", hlh)
        self._bottom = PivotSequenceScanner("__horns_lhl", lhl)

        self.width_max_bars = min(int(self.geom.get("width_max_bars") or 20), 18)
        self.leg_span_max_bars = 6
        self.extreme_similarity_min = float((self.geom.get("horn_peak_similarity_pct") or {}).get("min") or 0.92)
        self.extreme_similarity_max = float((self.geom.get("horn_peak_similarity_pct") or {}).get("max") or 1.08)
        self.depth_min_pct = max(4.0, float(self.geom.get("height_ratio_min") or 3.0))
        self.depth_max_pct = min(18.0, float(self.geom.get("height_ratio_max") or 15.0) + 3.0)
        self.approach_angle_min_deg = 18.0
        self.directional_ratio_min = 0.55
        self.min_prior_bars = int(self.prior.get("min_period_bars") or 10)
        self.min_prior_change_pct = float(self.prior.get("min_change_pct") or 5.0)

    def _direction_ratio(self, df: pd.DataFrame, *, start_idx: int, end_idx: int, positive: bool) -> Optional[float]:
        if end_idx <= start_idx:
            return None
        closes = pd.to_numeric(df.iloc[start_idx : end_idx + 1]["close"], errors="coerce").dropna().to_numpy()
        if len(closes) < 2:
            return None
        diffs = np.diff(closes)
        if len(diffs) == 0:
            return None
        return float(np.mean(diffs > 0)) if positive else float(np.mean(diffs < 0))

    def _prior_change_pct(self, df: pd.DataFrame, start_idx: int) -> Optional[float]:
        if start_idx < self.min_prior_bars:
            return None
        p0 = _safe_float(df.iloc[start_idx - self.min_prior_bars].get("close"))
        p1 = _safe_float(df.iloc[start_idx].get("close"))
        if p0 is None or p1 is None or p0 <= 0:
            return None
        return (p1 - p0) / p0 * 100.0

    def _family_metrics(self, df: pd.DataFrame, pivots: Sequence[Any], *, sequence_tag: str) -> Optional[Dict[str, Any]]:
        if len(pivots) < 3:
            return None
        try:
            i0, i1, i2 = [int(x) for x in pivots[:3]]
        except Exception:
            return None
        if not (0 <= i0 < i1 < i2 < len(df)):
            return None

        if sequence_tag == "HLH":
            p0 = float(df.iloc[i0]["high"])
            pm = float(df.iloc[i1]["low"])
            p2 = float(df.iloc[i2]["high"])
            left_positive = False
            right_positive = True
        else:
            p0 = float(df.iloc[i0]["low"])
            pm = float(df.iloc[i1]["high"])
            p2 = float(df.iloc[i2]["low"])
            left_positive = True
            right_positive = False

        if min(abs(p0), abs(pm), abs(p2)) <= 0:
            return None

        avg_extreme = (p0 + p2) / 2.0
        similarity_ratio = p2 / p0 if p0 != 0 else None
        if sequence_tag == "HLH":
            middle_depth_pct = (avg_extreme - pm) / avg_extreme * 100.0
        else:
            middle_depth_pct = (pm - avg_extreme) / avg_extreme * 100.0

        width_bars = i2 - i0 + 1
        left_span = i1 - i0
        right_span = i2 - i1
        prior_change_pct = self._prior_change_pct(df, i0)

        return {
            "sequence_tag": sequence_tag,
            "width_bars": int(width_bars),
            "left_span_bars": int(left_span),
            "right_span_bars": int(right_span),
            "similarity_ratio": float(similarity_ratio) if similarity_ratio is not None else None,
            "extreme_diff_pct": float(_pct_diff(p0, p2)),
            "middle_depth_pct": float(middle_depth_pct),
            "left_leg_deg": float(_slope_degrees(i0, p0, i1, pm)),
            "right_leg_deg": float(_slope_degrees(i1, pm, i2, p2)),
            "left_direction_ratio": self._direction_ratio(df, start_idx=i0, end_idx=i1, positive=left_positive),
            "right_direction_ratio": self._direction_ratio(df, start_idx=i1, end_idx=i2, positive=right_positive),
            "prior_change_pct": prior_change_pct,
        }

    def _family_metrics_ok(self, metrics: Dict[str, Any]) -> bool:
        width_bars = int(metrics.get("width_bars") or 0)
        left_span = int(metrics.get("left_span_bars") or 0)
        right_span = int(metrics.get("right_span_bars") or 0)
        sim = _safe_float(metrics.get("similarity_ratio"))
        depth_pct = float(metrics.get("middle_depth_pct") or 0.0)
        left_deg = abs(float(metrics.get("left_leg_deg") or 0.0))
        right_deg = abs(float(metrics.get("right_leg_deg") or 0.0))
        left_ratio = _safe_float(metrics.get("left_direction_ratio"))
        right_ratio = _safe_float(metrics.get("right_direction_ratio"))
        seq = str(metrics.get("sequence_tag") or "")
        prior_change_pct = _safe_float(metrics.get("prior_change_pct"))

        if width_bars <= 0 or width_bars > self.width_max_bars:
            return False
        if left_span <= 0 or right_span <= 0 or left_span > self.leg_span_max_bars or right_span > self.leg_span_max_bars:
            return False
        if sim is None or sim < self.extreme_similarity_min or sim > self.extreme_similarity_max:
            return False
        if depth_pct < self.depth_min_pct or depth_pct > self.depth_max_pct:
            return False
        if left_deg < self.approach_angle_min_deg or right_deg < self.approach_angle_min_deg:
            return False
        if left_ratio is not None and left_ratio < self.directional_ratio_min:
            return False
        if right_ratio is not None and right_ratio < self.directional_ratio_min:
            return False
        if prior_change_pct is None:
            return False
        if seq == "HLH" and prior_change_pct < self.min_prior_change_pct:
            return False
        if seq == "LHL" and prior_change_pct > -self.min_prior_change_pct:
            return False
        return True

    def _resolve_variant(self, metrics: Dict[str, Any], *, breakout_direction: Optional[str]) -> Optional[Dict[str, Any]]:
        seq = str(metrics.get("sequence_tag") or "")
        bo = str(breakout_direction or "")
        evidence = {
            "sequence_tag": seq,
            "middle_depth_pct": round(float(metrics.get("middle_depth_pct") or 0.0), 2),
            "extreme_diff_pct": round(float(metrics.get("extreme_diff_pct") or 0.0), 2),
            "left_leg_deg": round(float(metrics.get("left_leg_deg") or 0.0), 2),
            "right_leg_deg": round(float(metrics.get("right_leg_deg") or 0.0), 2),
            "prior_change_pct": round(float(metrics.get("prior_change_pct") or 0.0), 2),
        }

        if seq == "HLH" and bo == "down":
            return {"variant_code": "horn_top", "variant_confidence": 82, "pattern_type": "reversal_bearish", "evidence": evidence}
        if seq == "LHL" and bo == "up":
            return {"variant_code": "horn_bottom", "variant_confidence": 82, "pattern_type": "reversal_bullish", "evidence": evidence}
        return None

    def _score_family_confidence(self, base_confidence: Any, metrics: Dict[str, Any], variant_result: Dict[str, Any]) -> int:
        try:
            confidence = int(base_confidence)
        except Exception:
            confidence = 70
        if float(metrics.get("extreme_diff_pct") or 999.0) <= 3.0:
            confidence += 4
        if abs(float(metrics.get("left_leg_deg") or 0.0)) >= 30.0:
            confidence += 2
        if abs(float(metrics.get("right_leg_deg") or 0.0)) >= 30.0:
            confidence += 2
        return max(0, min(100, confidence))

    def scan(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> List[Dict[str, Any]]:
        tagged_rows: List[Tuple[Dict[str, Any], str]] = []
        for scanner, sequence_tag in ((self._top, "HLH"), (self._bottom, "LHL")):
            for row in scanner.scan(symbol=symbol, df=df, pivots_filtered=pivots_filtered, pivots_raw=pivots_raw):
                tagged_rows.append((dict(row), sequence_tag))

        out: List[Dict[str, Any]] = []
        for row, sequence_tag in tagged_rows:
            if row.get("breakout_idx") is None or _safe_float(row.get("breakout_price")) is None:
                continue
            metrics = self._family_metrics(df, row.get("pivot_indices") or [], sequence_tag=sequence_tag)
            if not metrics or not self._family_metrics_ok(metrics):
                continue
            variant = self._resolve_variant(metrics, breakout_direction=row.get("breakout_direction"))
            if not variant:
                continue
            enriched = dict(row)
            enriched["pattern_name"] = self.key
            enriched["base_pattern_name"] = self.key
            enriched["variant_code"] = variant.get("variant_code")
            enriched["variant_confidence"] = int(variant.get("variant_confidence") or 0)
            enriched["variant_evidence_json"] = json.dumps(variant.get("evidence") or {}, sort_keys=True, ensure_ascii=False)
            enriched["family_metrics_json"] = json.dumps(metrics, sort_keys=True, ensure_ascii=False)
            enriched["pattern_type"] = variant.get("pattern_type") or self.pattern_type
            enriched["confidence_score"] = self._score_family_confidence(
                row.get("confidence_score"),
                metrics,
                variant,
            )
            out.append(enriched)
        return out


class ScallopFamilyScanner(BaseDigitizedScanner):
    """
    Dedicated family scanner for scallops.

    The legacy chapter splitter treated every scallop as the same 3-pivot `L-H-L`
    structure and only flipped the chapter label by comparing start/end lows plus
    breakout direction. That misses the core ontology from the source material:
    some chapters are `L-H-L`, others are their mirrored `H-L-H` form, and all of
    them need a curved/asymmetric profile rather than an arbitrary three-pivot swing.
    """

    def __init__(self, key: str, spec: Dict[str, Any]):
        super().__init__(key, spec)
        self.geom = spec.get("geometry_constraints", {}) or {}

        lhl = copy.deepcopy(spec)
        lhl.setdefault("detection_signature", {})
        lhl["detection_signature"]["pivot_sequence"] = ["L", "H", "L"]
        lhl["detection_signature"]["mandatory_pivots"] = []

        hlh = copy.deepcopy(spec)
        hlh.setdefault("detection_signature", {})
        hlh["detection_signature"]["pivot_sequence"] = ["H", "L", "H"]
        hlh["detection_signature"]["mandatory_pivots"] = []

        self._lhl = PivotSequenceScanner("__scallops_lhl", lhl)
        self._hlh = PivotSequenceScanner("__scallops_hlh", hlh)

        self.min_left_share_pct = 45.0
        self.max_left_share_pct = 90.0
        self.min_excursion_pct = 14.0
        self.min_leg_bars = 4
        self.min_left_leg_deg = 2.0
        self.min_right_leg_deg = 2.0
        self.min_directional_ratio = 0.40
        self.min_overall_shift_pct = 1.5
        self.descending_min_shift_pct = 4.0
        self.descending_min_left_leg_abs_deg = 18.0
        self.descending_min_right_leg_deg = 22.0
        self.descending_directional_ratio_min = 0.46
        self.descending_min_excursion_pct = 60.0
        self.ascending_inverted_min_shift_pct = 4.0
        self.ascending_inverted_min_left_leg_abs_deg = 18.0
        self.ascending_inverted_min_right_leg_deg = 34.0
        self.ascending_inverted_max_left_share_pct = 72.0
        self.ascending_inverted_min_excursion_pct = 75.0
        self.ascending_inverted_directional_ratio_min = 0.48
        self.ascending_inverted_strong_shift_pct = 5.0
        self.ascending_inverted_review_max_left_share_pct = 68.0
        self.ascending_inverted_review_min_left_leg_abs_deg = 20.0
        self.ascending_inverted_review_min_right_directional_ratio = 0.50

    def _segment_direction_ratio(
        self,
        df: pd.DataFrame,
        *,
        start_idx: int,
        end_idx: int,
        positive: bool,
    ) -> Optional[float]:
        if end_idx <= start_idx:
            return None
        closes = pd.to_numeric(df.iloc[start_idx : end_idx + 1]["close"], errors="coerce").dropna().to_numpy()
        if len(closes) < 2:
            return None
        diffs = np.diff(closes)
        if len(diffs) == 0:
            return None
        if positive:
            return float(np.mean(diffs > 0))
        return float(np.mean(diffs < 0))

    def _family_metrics(
        self,
        df: pd.DataFrame,
        pivots: List[Any],
        *,
        sequence_tag: str,
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(pivots, (list, tuple)) or len(pivots) < 3:
            return None
        try:
            i0, i1, i2 = [int(x) for x in pivots[:3]]
        except Exception:
            return None
        if any(i < 0 or i >= len(df) for i in (i0, i1, i2)):
            return None

        if sequence_tag == "LHL":
            p0 = float(df.iloc[i0]["low"])
            pm = float(df.iloc[i1]["high"])
            p2 = float(df.iloc[i2]["low"])
            left_positive = True
            right_positive = False
        else:
            p0 = float(df.iloc[i0]["high"])
            pm = float(df.iloc[i1]["low"])
            p2 = float(df.iloc[i2]["high"])
            left_positive = False
            right_positive = True

        total_span = i2 - i0
        if total_span <= 0:
            return None
        left_span = i1 - i0
        right_span = i2 - i1
        if left_span <= 0 or right_span <= 0:
            return None

        line_mid = p0 + (p2 - p0) * ((i1 - i0) / total_span)
        span_height = max(abs(pm - p0), abs(pm - p2), 1e-9)
        excursion_pct = abs(pm - line_mid) / span_height * 100.0
        overall_shift_pct = ((p2 - p0) / max(abs(p0), 1e-9)) * 100.0

        left_ratio = self._segment_direction_ratio(df, start_idx=i0, end_idx=i1, positive=left_positive)
        right_ratio = self._segment_direction_ratio(df, start_idx=i1, end_idx=i2, positive=right_positive)

        return {
            "sequence_tag": sequence_tag,
            "start_idx": i0,
            "mid_idx": i1,
            "end_idx": i2,
            "start_anchor_price": p0,
            "mid_anchor_price": pm,
            "end_anchor_price": p2,
            "left_span_bars": left_span,
            "right_span_bars": right_span,
            "left_share_pct": left_span / total_span * 100.0,
            "overall_shift_pct": overall_shift_pct,
            "left_leg_deg": float(_slope_degrees(i0, p0, i1, pm)),
            "right_leg_deg": float(_slope_degrees(i1, pm, i2, p2)),
            "arc_excursion_pct": excursion_pct,
            "left_directional_ratio": left_ratio,
            "right_directional_ratio": right_ratio,
        }

    def _family_metrics_ok(self, metrics: Dict[str, Any]) -> bool:
        left_span = int(metrics.get("left_span_bars") or 0)
        right_span = int(metrics.get("right_span_bars") or 0)
        left_share = float(metrics.get("left_share_pct") or 0.0)
        excursion = float(metrics.get("arc_excursion_pct") or 0.0)
        left_deg = float(metrics.get("left_leg_deg") or 0.0)
        right_deg = float(metrics.get("right_leg_deg") or 0.0)
        left_ratio = _safe_float(metrics.get("left_directional_ratio"))
        right_ratio = _safe_float(metrics.get("right_directional_ratio"))
        seq = str(metrics.get("sequence_tag") or "")
        start_price = float(metrics.get("start_anchor_price") or 0.0)
        mid_price = float(metrics.get("mid_anchor_price") or 0.0)
        end_price = float(metrics.get("end_anchor_price") or 0.0)

        if left_span < self.min_leg_bars or right_span < self.min_leg_bars:
            return False
        if left_share < self.min_left_share_pct or left_share > self.max_left_share_pct:
            return False
        if excursion < self.min_excursion_pct:
            return False
        if left_ratio is not None and left_ratio < self.min_directional_ratio:
            return False
        if right_ratio is not None and right_ratio < self.min_directional_ratio:
            return False

        if seq == "LHL":
            if left_deg < self.min_left_leg_deg or right_deg > -self.min_right_leg_deg:
                return False
            if mid_price <= max(start_price, end_price):
                return False
        elif seq == "HLH":
            if left_deg > -self.min_left_leg_deg or right_deg < self.min_right_leg_deg:
                return False
            if mid_price >= min(start_price, end_price):
                return False
        else:
            return False

        return True

    def _resolve_variant(self, metrics: Dict[str, Any], *, breakout_direction: Optional[str]) -> Optional[Dict[str, Any]]:
        seq = str(metrics.get("sequence_tag") or "")
        bo = str(breakout_direction or "")
        overall_shift = float(metrics.get("overall_shift_pct") or 0.0)
        left_share = float(metrics.get("left_share_pct") or 0.0)
        excursion = float(metrics.get("arc_excursion_pct") or 0.0)
        left_deg = float(metrics.get("left_leg_deg") or 0.0)
        right_deg = float(metrics.get("right_leg_deg") or 0.0)
        left_ratio = _safe_float(metrics.get("left_directional_ratio"))
        right_ratio = _safe_float(metrics.get("right_directional_ratio"))
        evidence = {
            "sequence_tag": seq,
            "overall_shift_pct": round(overall_shift, 2),
            "left_share_pct": round(left_share, 1),
            "left_leg_deg": round(left_deg, 2),
            "right_leg_deg": round(right_deg, 2),
            "arc_excursion_pct": round(excursion, 2),
            "left_directional_ratio": round(float(left_ratio), 3) if left_ratio is not None else None,
            "right_directional_ratio": round(float(right_ratio), 3) if right_ratio is not None else None,
        }

        def _conf(base: int) -> int:
            bonus = 0
            if 55.0 <= left_share <= 82.0:
                bonus += 4
            if excursion >= 24.0:
                bonus += 4
            if abs(overall_shift) >= 4.0:
                bonus += 3
            return min(100, base + bonus)

        if seq == "LHL" and bo == "up":
            if overall_shift >= self.min_overall_shift_pct:
                return {
                    "variant_code": "scallops_ascending",
                    "variant_confidence": _conf(78),
                    "pattern_type": "reversal_bullish",
                    "evidence": evidence,
                }
            if overall_shift <= -self.min_overall_shift_pct:
                return {
                    "variant_code": "scallops_descending_inverted",
                    "variant_confidence": _conf(74),
                    "pattern_type": "reversal_bullish",
                    "evidence": evidence,
                }

        if seq == "HLH" and bo == "down":
            if overall_shift <= -self.min_overall_shift_pct:
                if overall_shift > -self.descending_min_shift_pct:
                    return None
                if excursion < self.descending_min_excursion_pct:
                    return None
                if abs(left_deg) < self.descending_min_left_leg_abs_deg or right_deg < self.descending_min_right_leg_deg:
                    return None
                if left_ratio is not None and left_ratio < self.descending_directional_ratio_min:
                    return None
                if right_ratio is not None and right_ratio < self.descending_directional_ratio_min:
                    return None
                return {
                    "variant_code": "scallops_descending",
                    "variant_confidence": _conf(78),
                    "pattern_type": "reversal_bearish",
                    "evidence": evidence,
                }
            if overall_shift >= self.min_overall_shift_pct:
                if overall_shift < self.ascending_inverted_strong_shift_pct:
                    return None
                if abs(left_deg) < self.ascending_inverted_min_left_leg_abs_deg:
                    return None
                if right_deg < self.ascending_inverted_min_right_leg_deg:
                    return None
                if left_share > self.ascending_inverted_max_left_share_pct:
                    return None
                if excursion < self.ascending_inverted_min_excursion_pct:
                    return None
                if left_ratio is not None and left_ratio < self.ascending_inverted_directional_ratio_min:
                    return None
                if right_ratio is not None and right_ratio < self.ascending_inverted_directional_ratio_min:
                    return None
                return {
                    "variant_code": "scallops_ascending_inverted",
                    "variant_confidence": _conf(74),
                    "pattern_type": "reversal_bearish",
                    "evidence": evidence,
                }

        return None

    def _score_family_confidence(
        self,
        base_confidence: Any,
        metrics: Dict[str, Any],
        variant_result: Dict[str, Any],
    ) -> int:
        try:
            confidence = int(base_confidence)
        except Exception:
            confidence = 70

        left_share = float(metrics.get("left_share_pct") or 0.0)
        excursion = float(metrics.get("arc_excursion_pct") or 0.0)
        if 55.0 <= left_share <= 80.0:
            confidence += 3
        elif left_share >= 50.0:
            confidence += 1
        if excursion >= 24.0:
            confidence += 4
        elif excursion >= 18.0:
            confidence += 2

        variant_confidence = int(variant_result.get("variant_confidence") or 0)
        if variant_confidence >= 84:
            confidence += 3
        elif variant_confidence >= 76:
            confidence += 1

        return max(0, min(100, confidence))

    def _variant_metrics_ok(
        self,
        metrics: Dict[str, Any],
        variant_result: Dict[str, Any],
    ) -> bool:
        if str(variant_result.get("variant_code") or "") != "scallops_ascending_inverted":
            return True

        left_share = float(metrics.get("left_share_pct") or 0.0)
        overall_shift = float(metrics.get("overall_shift_pct") or 0.0)
        left_deg = abs(float(metrics.get("left_leg_deg") or 0.0))
        right_ratio = _safe_float(metrics.get("right_directional_ratio")) or 0.0

        return (
            left_share <= self.ascending_inverted_review_max_left_share_pct
            and overall_shift >= self.ascending_inverted_strong_shift_pct
            and left_deg >= self.ascending_inverted_review_min_left_leg_abs_deg
            and right_ratio >= self.ascending_inverted_review_min_right_directional_ratio
        )

    def scan(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> List[Dict[str, Any]]:
        tagged_rows: List[Tuple[Dict[str, Any], str]] = []
        for scanner, sequence_tag in ((self._lhl, "LHL"), (self._hlh, "HLH")):
            for row in scanner.scan(symbol=symbol, df=df, pivots_filtered=pivots_filtered, pivots_raw=pivots_raw):
                tagged_rows.append((dict(row), sequence_tag))

        deduped: Dict[Tuple[int, ...], Dict[str, Any]] = {}
        for row, sequence_tag in tagged_rows:
            pivots = row.get("pivot_indices") or []
            key = tuple(int(x) for x in pivots[:3]) if isinstance(pivots, (list, tuple)) else ()
            if not key:
                continue

            metrics = self._family_metrics(df, list(key), sequence_tag=sequence_tag)
            if not metrics or not self._family_metrics_ok(metrics):
                continue

            variant_result = self._resolve_variant(metrics, breakout_direction=row.get("breakout_direction"))
            if not variant_result:
                continue
            if not self._variant_metrics_ok(metrics, variant_result):
                continue

            enriched = dict(row)
            enriched["pattern_name"] = self.key
            enriched["pattern_id"] = f"{symbol}_{self.key}_{key[0]}_{key[-1]}"
            enriched["pattern_type"] = variant_result.get("pattern_type") or self.pattern_type
            enriched["base_pattern_name"] = self.key
            enriched["variant_code"] = variant_result.get("variant_code")
            enriched["variant_confidence"] = int(variant_result.get("variant_confidence") or 0)
            enriched["variant_evidence_json"] = json.dumps(
                variant_result.get("evidence") or {},
                sort_keys=True,
                ensure_ascii=False,
            )
            enriched["family_metrics_json"] = json.dumps(metrics, sort_keys=True, ensure_ascii=False)
            enriched["confidence_score"] = self._score_family_confidence(
                row.get("confidence_score"),
                metrics,
                variant_result,
            )

            prev = deduped.get(key)
            if prev is None or int(enriched.get("confidence_score") or 0) > int(prev.get("confidence_score") or 0):
                deduped[key] = enriched

        return list(deduped.values())


class RoundingBottomsTopsScanner(BaseDigitizedScanner):
    """
    The digitized spec contains both rounding bottoms and rounding tops in one file.
    Mandatory pivots are annotated with `variant` ("bottom"/"top"), but the generic
    PivotSequenceScanner does not interpret that field. This wrapper instantiates
    two PivotSequenceScanners (bottom + top) using filtered mandatory pivots and
    an inverted pivot sequence for the top variant.
    """

    def __init__(self, key: str, spec: Dict[str, Any]):
        super().__init__(key, spec)
        self.geom = spec.get("geometry_constraints", {}) or {}

        ds = spec.get("detection_signature", {}) or {}
        base_seq = (ds.get("pivot_sequence") or []) if isinstance(ds.get("pivot_sequence"), list) else []
        base_mps = (ds.get("mandatory_pivots") or []) if isinstance(ds.get("mandatory_pivots"), list) else []

        def _invert_seq(seq: List[Any]) -> List[Any]:
            out: List[Any] = []
            for t in seq:
                if t == "H":
                    out.append("L")
                elif t == "L":
                    out.append("H")
                else:
                    out.append(t)
            return out

        bottom_spec = copy.deepcopy(spec)
        bottom_spec["pattern_type"] = "reversal_bullish"
        bottom_spec.setdefault("detection_signature", {})
        bottom_spec["detection_signature"]["pivot_sequence"] = list(base_seq)
        bottom_spec["detection_signature"]["mandatory_pivots"] = [
            mp for mp in base_mps if not isinstance(mp, dict) or (mp.get("variant") in (None, "", "bottom"))
        ]
        self._bottom = PivotSequenceScanner(key, bottom_spec)

        top_spec = copy.deepcopy(spec)
        top_spec["pattern_type"] = "reversal_bearish"
        top_spec.setdefault("detection_signature", {})
        top_spec["detection_signature"]["pivot_sequence"] = _invert_seq(list(base_seq))
        top_spec["detection_signature"]["mandatory_pivots"] = [
            mp for mp in base_mps if not isinstance(mp, dict) or (mp.get("variant") in (None, "", "top"))
        ]
        self._top = PivotSequenceScanner("__rounding_top", top_spec)

        self.width_max_bars = min(int(self.geom.get("width_max_bars") or 180), 170)
        curvature = self.geom.get("curvature_measurement", {}) or {}
        # The digitized fit error is idealized; allow a pragmatic ceiling for real OHLCV.
        self.fit_error_max_pct = max(14.0, float(curvature.get("max_fit_error_pct") or 2.0) * 12.0)
        self.directional_ratio_min = 0.52
        self.symmetry_ratio_max = 2.1
        self.center_pos_min_pct = 28.0
        self.center_pos_max_pct = 72.0
        self.center_clearance_min_pct = 3.0
        self.top_width_max_bars = 80
        self.top_fit_error_max_pct = min(self.fit_error_max_pct, 19.0)
        self.top_directional_ratio_min = 0.55
        self.top_center_clearance_min_pct = 4.5
        self.top_trend_progress_abs_max_pct = 12.0

    def _direction_ratio(self, df: pd.DataFrame, *, start_idx: int, end_idx: int, positive: bool) -> Optional[float]:
        if end_idx <= start_idx:
            return None
        closes = pd.to_numeric(df.iloc[start_idx : end_idx + 1]["close"], errors="coerce").dropna().to_numpy()
        if len(closes) < 2:
            return None
        diffs = np.diff(closes)
        if len(diffs) == 0:
            return None
        return float(np.mean(diffs > 0)) if positive else float(np.mean(diffs < 0))

    def _quadratic_fit_error_pct(self, df: pd.DataFrame, start_idx: int, end_idx: int) -> Optional[float]:
        if end_idx <= start_idx:
            return None
        closes = pd.to_numeric(df.iloc[start_idx : end_idx + 1]["close"], errors="coerce").dropna().to_numpy(dtype=float, copy=False)
        if len(closes) < 7:
            return None
        price_range = float(np.nanmax(closes) - np.nanmin(closes))
        if not np.isfinite(price_range) or price_range <= 0:
            return None
        x = np.linspace(-1.0, 1.0, len(closes))
        try:
            coeff = np.polyfit(x, closes, 2)
        except Exception:
            return None
        fit = np.polyval(coeff, x)
        rmse = float(np.sqrt(np.nanmean((closes - fit) ** 2)))
        return rmse / price_range * 100.0

    def _family_metrics(self, df: pd.DataFrame, pivots: Sequence[Any], *, variant_tag: str) -> Optional[Dict[str, Any]]:
        if len(pivots) < 6:
            return None
        try:
            i0, i1, i2, i3, i4, i5 = [int(x) for x in pivots[:6]]
        except Exception:
            return None
        if not (0 <= i0 < i1 < i2 < i3 < i4 < i5 < len(df)):
            return None

        start_idx = i0
        end_idx = i5
        width_bars = end_idx - start_idx + 1
        center_idx = i2
        center_pos_pct = (center_idx - start_idx) / max(1, end_idx - start_idx) * 100.0
        left_span = i2 - i0
        right_span = i5 - i2
        span_balance_ratio = max(left_span, right_span) / max(1, min(left_span, right_span))
        fit_error_pct = self._quadratic_fit_error_pct(df, start_idx, end_idx)

        if variant_tag == "bottom":
            left_edge = float(df.iloc[i0]["low"])
            center_extreme = float(df.iloc[i2]["low"])
            right_edge = float(df.iloc[i4]["low"])
            mid1 = float(df.iloc[i1]["high"])
            mid2 = float(df.iloc[i3]["high"])
            last_mid = float(df.iloc[i5]["high"])
            center_clearance_pct = ((0.5 * (left_edge + right_edge)) - center_extreme) / max(1e-9, 0.5 * (left_edge + right_edge)) * 100.0
            monotonic_left = self._direction_ratio(df, start_idx=i0, end_idx=i2, positive=False)
            monotonic_right = self._direction_ratio(df, start_idx=i2, end_idx=i5, positive=True)
            trend_progress_pct = (last_mid - mid1) / max(1e-9, mid1) * 100.0
            expected_sign = 1.0
        else:
            left_edge = float(df.iloc[i0]["high"])
            center_extreme = float(df.iloc[i2]["high"])
            right_edge = float(df.iloc[i4]["high"])
            mid1 = float(df.iloc[i1]["low"])
            mid2 = float(df.iloc[i3]["low"])
            last_mid = float(df.iloc[i5]["low"])
            center_clearance_pct = (center_extreme - (0.5 * (left_edge + right_edge))) / max(1e-9, 0.5 * (left_edge + right_edge)) * 100.0
            monotonic_left = self._direction_ratio(df, start_idx=i0, end_idx=i2, positive=True)
            monotonic_right = self._direction_ratio(df, start_idx=i2, end_idx=i5, positive=False)
            trend_progress_pct = (mid1 - last_mid) / max(1e-9, mid1) * 100.0
            expected_sign = -1.0

        x = np.array([0.0, 0.5, 1.0])
        y = np.array([left_edge, center_extreme, right_edge])
        try:
            coeff = np.polyfit(x, y, 2)
            curvature_coeff = float(coeff[0])
        except Exception:
            curvature_coeff = 0.0

        return {
            "variant_tag": variant_tag,
            "width_bars": int(width_bars),
            "center_pos_pct": float(center_pos_pct),
            "span_balance_ratio": float(span_balance_ratio),
            "center_clearance_pct": float(center_clearance_pct),
            "fit_error_pct": fit_error_pct,
            "monotonic_left_ratio": monotonic_left,
            "monotonic_right_ratio": monotonic_right,
            "trend_progress_pct": float(trend_progress_pct),
            "mid_progress_pct": float(_pct_diff(mid1, mid2)),
            "curvature_coeff": float(curvature_coeff),
            "expected_curvature_sign": float(expected_sign),
        }

    def _family_metrics_ok(self, metrics: Dict[str, Any]) -> bool:
        width_bars = int(metrics.get("width_bars") or 0)
        center_pos_pct = float(metrics.get("center_pos_pct") or 0.0)
        span_balance_ratio = float(metrics.get("span_balance_ratio") or 999.0)
        center_clearance_pct = float(metrics.get("center_clearance_pct") or 0.0)
        fit_error_pct = _safe_float(metrics.get("fit_error_pct"))
        monotonic_left = _safe_float(metrics.get("monotonic_left_ratio"))
        monotonic_right = _safe_float(metrics.get("monotonic_right_ratio"))
        curvature_coeff = float(metrics.get("curvature_coeff") or 0.0)
        expected_sign = float(metrics.get("expected_curvature_sign") or 0.0)

        if width_bars <= 0 or width_bars > self.width_max_bars:
            return False
        if center_pos_pct < self.center_pos_min_pct or center_pos_pct > self.center_pos_max_pct:
            return False
        if span_balance_ratio > self.symmetry_ratio_max:
            return False
        if center_clearance_pct < self.center_clearance_min_pct:
            return False
        if fit_error_pct is not None and fit_error_pct > self.fit_error_max_pct:
            return False
        if monotonic_left is not None and monotonic_left < self.directional_ratio_min:
            return False
        if monotonic_right is not None and monotonic_right < self.directional_ratio_min:
            return False
        if expected_sign > 0 and curvature_coeff <= 0:
            return False
        if expected_sign < 0 and curvature_coeff >= 0:
            return False
        if str(metrics.get("variant_tag") or "") == "top":
            if width_bars > self.top_width_max_bars:
                return False
            if fit_error_pct is not None and fit_error_pct > self.top_fit_error_max_pct:
                return False
            if center_clearance_pct < self.top_center_clearance_min_pct:
                return False
            if monotonic_left is not None and monotonic_left < self.top_directional_ratio_min:
                return False
            if monotonic_right is not None and monotonic_right < self.top_directional_ratio_min:
                return False
            if abs(float(metrics.get("trend_progress_pct") or 0.0)) > self.top_trend_progress_abs_max_pct:
                return False
        return True

    def _resolve_variant(self, metrics: Dict[str, Any], *, breakout_direction: Optional[str]) -> Optional[Dict[str, Any]]:
        tag = str(metrics.get("variant_tag") or "")
        bo = str(breakout_direction or "")
        evidence = {
            "center_pos_pct": round(float(metrics.get("center_pos_pct") or 0.0), 2),
            "center_clearance_pct": round(float(metrics.get("center_clearance_pct") or 0.0), 2),
            "fit_error_pct": round(float(metrics.get("fit_error_pct") or 0.0), 2),
            "span_balance_ratio": round(float(metrics.get("span_balance_ratio") or 0.0), 2),
            "trend_progress_pct": round(float(metrics.get("trend_progress_pct") or 0.0), 2),
        }
        if tag == "bottom" and bo == "up":
            return {
                "variant_code": "rounding_bottom",
                "variant_confidence": 82,
                "pattern_type": "reversal_bullish",
                "evidence": evidence,
            }
        if tag == "top" and bo == "down":
            return {
                "variant_code": "rounding_top",
                "variant_confidence": 82,
                "pattern_type": "reversal_bearish",
                "evidence": evidence,
            }
        return None

    def _score_family_confidence(self, base_confidence: Any, metrics: Dict[str, Any], variant_result: Dict[str, Any]) -> int:
        try:
            confidence = int(base_confidence)
        except Exception:
            confidence = 70
        fit_error = float(metrics.get("fit_error_pct") or 999.0)
        if fit_error <= 10.0:
            confidence += 5
        elif fit_error <= 18.0:
            confidence += 3
        if float(metrics.get("span_balance_ratio") or 999.0) <= 1.4:
            confidence += 2
        if float(metrics.get("center_clearance_pct") or 0.0) >= 7.0:
            confidence += 3
        return max(0, min(100, confidence))

    def scan(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []

        for base_row, tag in [*( (r, "bottom") for r in self._bottom.scan(symbol=symbol, df=df, pivots_filtered=pivots_filtered, pivots_raw=pivots_raw) ), *( (r, "top") for r in self._top.scan(symbol=symbol, df=df, pivots_filtered=pivots_filtered, pivots_raw=pivots_raw) )]:
            row = dict(base_row)
            if row.get("breakout_idx") is None or _safe_float(row.get("breakout_price")) is None:
                continue
            metrics = self._family_metrics(df, row.get("pivot_indices") or [], variant_tag=tag)
            if not metrics or not self._family_metrics_ok(metrics):
                continue
            variant = self._resolve_variant(metrics, breakout_direction=row.get("breakout_direction"))
            if not variant:
                continue
            row["pattern_id"] = f"{row['pattern_id']}_{tag}"
            row["pattern_name"] = self.key
            row["base_pattern_name"] = self.key
            row["variant_code"] = variant.get("variant_code")
            row["variant_confidence"] = int(variant.get("variant_confidence") or 0)
            row["variant_evidence_json"] = json.dumps(variant.get("evidence") or {}, sort_keys=True, ensure_ascii=False)
            row["family_metrics_json"] = json.dumps(metrics, sort_keys=True, ensure_ascii=False)
            row["pattern_type"] = variant.get("pattern_type") or row.get("pattern_type") or self.pattern_type
            row["confidence_score"] = self._score_family_confidence(row.get("confidence_score"), metrics, variant)
            out.append(row)

        return out


class CupWithHandleScanner(BaseDigitizedScanner):
    """
    Cup-with-handle is fundamentally a curved formation; a strict 6-pivot template is brittle.
    This scanner uses a pragmatic approach:
    - Identify candidate cup rims (two highs) separated by the cup width
    - Find the cup bottom between rims
    - Verify depth + handle constraints from digitized spec
    - Confirm breakout above handle resistance with optional volume requirement

    The goal is coverage on real-world OHLCV while staying anchored to digitized constraints.
    """

    def __init__(self, key: str, spec: Dict[str, Any]):
        super().__init__(key, spec)
        self.geom = spec.get("geometry_constraints", {}) or {}
        self.prior = spec.get("prior_trend_requirements", {}) or {}
        self.bo = spec.get("breakout_confirmation", {}) or {}

        self.width_min = int(self.geom.get("width_min_bars") or 84)
        self.width_max = int(self.geom.get("width_max_bars") or 504)
        self.width_hard_max = min(self.width_max, int(self.geom.get("width_hard_cap_bars") or 220))
        self.depth_min = float(self.geom.get("height_ratio_min") or 15.0)
        self.depth_max = float(self.geom.get("height_ratio_max") or 33.0)
        self.bottom_pos_min_pct = float(self.geom.get("bottom_position_min_pct") or 28.0)
        self.bottom_pos_max_pct = float(self.geom.get("bottom_position_max_pct") or 72.0)
        self.roundness_band_pct = float(self.geom.get("roundness_band_pct") or 35.0)
        self.roundness_min_bars = int(self.geom.get("roundness_min_bars") or 5)

        handle = self.geom.get("handle_constraints", {}) or {}
        self.handle_min_bars = 5
        self.handle_max_bars = 20
        self.handle_pos_min_pct = float(handle.get("handle_position_min_pct") or 67.0)
        self.handle_min_decline_pct = float(handle.get("handle_min_decline_pct") or 2.0)
        self.handle_max_decline_pct = float(handle.get("handle_max_decline_pct") or 12.0)
        self.handle_width_max_pct = float(handle.get("handle_width_max_pct_of_cup") or 35.0)
        self.handle_slope_max_pct = float(handle.get("handle_slope_max_pct") or 3.0)
        self.handle_retrace_max_pct = float(handle.get("handle_retrace_max_pct_of_cup") or 45.0)

        # Rims "near equal" is very strict in some digitizations; treat the digitized tolerance
        # as "ideal" and apply a looser hard cap for coverage. Confidence scoring rewards tight rims.
        self.rim_tol_ideal = float(self.geom.get("near_equal_tolerance_pct") or 2.0)
        self.rim_tol_hard = max(self.rim_tol_ideal, 10.0)

        self.breakout_thr = float(self.bo.get("breakout_threshold_pct") or 1.0) / 100.0
        self.confirm_bars = int(self.bo.get("confirmation_bars") or 1)
        self.close_beyond = bool(self.bo.get("close_beyond_required") if self.bo.get("close_beyond_required") is not None else True)
        self.vol_required = bool(self.bo.get("volume_required") or False)
        self.vol_mult_min = float(self.bo.get("volume_multiplier_min") or 1.3)

        # Bound breakout search to keep scans fast.
        self.breakout_search_bars = min(int(self.geom.get("breakout_search_bars") or 12), 15)
        self.breakout_lag_max_bars = int(self.geom.get("breakout_lag_max_bars") or 8)

    def _prior_trend_ok(self, df: pd.DataFrame, start_idx: int) -> bool:
        direction = str(self.prior.get("direction") or "up").lower()
        min_bars = int(self.prior.get("min_period_bars") or 0)
        min_change = float(self.prior.get("min_change_pct") or 0.0)
        if min_bars <= 0 or min_change <= 0:
            return True
        if start_idx < min_bars:
            return False
        p0 = _safe_float(df.iloc[start_idx - min_bars].get("close"))
        p1 = _safe_float(df.iloc[start_idx].get("close"))
        if p0 is None or p1 is None or p0 <= 0:
            return False
        change_pct = (p1 - p0) / p0 * 100.0
        if direction == "up":
            return change_pct >= min_change
        if direction == "down":
            return change_pct <= -min_change
        return abs(change_pct) >= min_change

    def _breakout_ok(self, df: pd.DataFrame, idx0: int, level: float) -> Tuple[Optional[int], Optional[float], bool]:
        """
        Find breakout above `level` starting at idx0. Returns (breakout_idx, breakout_price, vol_ok).
        """
        end = min(len(df), idx0 + self.breakout_search_bars)
        thr = level * (1.0 + self.breakout_thr)
        for i in range(idx0, end):
            close = _safe_float(df.iloc[i].get("close"))
            if close is None:
                continue
            if close <= thr:
                continue

            # Confirmation bars: require consecutive closes beyond threshold.
            if self.confirm_bars > 1:
                j_end = min(len(df), i + self.confirm_bars)
                all_ok = True
                for j in range(i, j_end):
                    c = _safe_float(df.iloc[j].get("close"))
                    if c is None or c <= thr:
                        all_ok = False
                        break
                if not all_ok:
                    continue

            vr = df.iloc[i].get("volume_ratio", np.nan)
            vol_ok = bool(pd.notna(vr) and np.isfinite(vr) and float(vr) >= self.vol_mult_min)
            if self.vol_required and not vol_ok:
                continue
            return i, close, vol_ok

        return None, None, False

    def scan(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> List[Dict[str, Any]]:
        pivots = pivots_filtered
        highs = [p for p in pivots if p.type == PivotType.HIGH]
        if len(highs) < 2:
            return []

        out: List[Dict[str, Any]] = []

        for i in range(len(highs) - 1):
            left = highs[i]
            # width_min is a bar-count (inclusive)
            if int(left.idx) + int(self.width_min) - 1 >= len(df):
                continue
            if not self._prior_trend_ok(df, int(left.idx)):
                continue

            for j in range(i + 1, len(highs)):
                right = highs[j]
                width_bars = int(right.idx) - int(left.idx) + 1
                if width_bars < self.width_min:
                    continue
                if width_bars > self.width_hard_max:
                    break

                # Rim similarity (hard cap for coverage; scoring uses ideal tolerance).
                rim_diff = _pct_diff(float(left.price), float(right.price))
                if rim_diff > self.rim_tol_hard:
                    continue

                seg = df.iloc[int(left.idx) : int(right.idx) + 1]
                if len(seg) < 3:
                    continue
                bottom_low = _safe_float(seg["low"].min())
                if bottom_low is None or bottom_low <= 0:
                    continue

                # Depth % (cup depth vs average rim)
                rim_avg = (float(left.price) + float(right.price)) / 2.0
                if rim_avg <= 0:
                    continue
                depth_pct = (rim_avg - bottom_low) / rim_avg * 100.0
                if depth_pct < self.depth_min or depth_pct > self.depth_max:
                    continue
                depth_abs = max(0.0, rim_avg - bottom_low)
                if depth_abs <= 0:
                    continue

                bottom_idx = int(left.idx) + int(np.argmin(seg["low"].to_numpy()))
                left_span_bars = bottom_idx - int(left.idx)
                right_span_bars = int(right.idx) - bottom_idx
                if left_span_bars <= 0 or right_span_bars <= 0:
                    continue
                bottom_pos_pct = left_span_bars / max(1, width_bars - 1) * 100.0
                if bottom_pos_pct < self.bottom_pos_min_pct or bottom_pos_pct > self.bottom_pos_max_pct:
                    continue

                roundness_band = bottom_low + depth_abs * (self.roundness_band_pct / 100.0)
                near_bottom_bars = int((seg["low"] <= roundness_band).sum())
                min_roundness_bars = max(3, min(self.roundness_min_bars, width_bars // 8))
                if near_bottom_bars < min_roundness_bars:
                    continue

                # Handle search window
                handle_start = int(right.idx) + 1
                if handle_start + self.handle_min_bars >= len(df):
                    continue
                handle_end_max = min(len(df) - 1, handle_start + self.handle_max_bars - 1)

                for handle_end in range(handle_start + self.handle_min_bars - 1, handle_end_max + 1):
                    # Enforce width constraints on the *full* formation (cup + handle).
                    # We persist `pattern_width_bars` as left-rim -> handle_end inclusive.
                    total_width_bars = int(handle_end) - int(left.idx) + 1
                    if total_width_bars > self.width_hard_max:
                        break
                    hseg = df.iloc[handle_start : handle_end + 1]
                    if len(hseg) == 0:
                        continue
                    handle_width_bars = len(hseg)
                    if handle_width_bars > max(self.handle_min_bars, int(round(width_bars * self.handle_width_max_pct / 100.0))):
                        continue
                    handle_low = _safe_float(hseg["low"].min())
                    if handle_low is None:
                        continue
                    handle_decline = (rim_avg - handle_low) / rim_avg * 100.0
                    if handle_decline < self.handle_min_decline_pct or handle_decline > self.handle_max_decline_pct:
                        continue
                    if depth_pct > 0 and (handle_decline / depth_pct * 100.0) > self.handle_retrace_max_pct:
                        continue

                    # Handle must be in upper third of cup depth (position % from bottom -> rim).
                    denom = rim_avg - bottom_low
                    if denom <= 0:
                        continue
                    handle_pos_pct = (handle_low - bottom_low) / denom * 100.0
                    if handle_pos_pct < self.handle_pos_min_pct:
                        continue

                    handle_start_close = _safe_float(hseg.iloc[0].get("close"))
                    handle_end_close = _safe_float(hseg.iloc[-1].get("close"))
                    if handle_start_close is None or handle_end_close is None:
                        continue
                    handle_slope_pct = (handle_end_close - handle_start_close) / rim_avg * 100.0
                    if handle_slope_pct > self.handle_slope_max_pct:
                        continue

                    handle_res = _safe_float(hseg["high"].max())
                    if handle_res is None or handle_res <= 0:
                        continue
                    if _pct_diff(handle_res, rim_avg) > self.rim_tol_hard:
                        continue

                    breakout_idx, breakout_price, vol_ok = self._breakout_ok(df, handle_end + 1, handle_res)
                    if breakout_idx is None or breakout_price is None:
                        continue
                    breakout_lag_bars = int(breakout_idx) - int(handle_end)
                    if breakout_lag_bars < 1 or breakout_lag_bars > self.breakout_lag_max_bars:
                        continue

                    # Target/stop (pragmatic): depth in absolute price units.
                    target = breakout_price + depth_abs
                    stop = float(handle_low)

                    variant_code = "standard"
                    if depth_pct < 20.0:
                        variant_code = "shallow_cup"
                    elif depth_pct > 30.0:
                        variant_code = "deep_cup"

                    family_metrics = {
                        "cup_width_bars": int(width_bars),
                        "handle_width_bars": int(handle_width_bars),
                        "bottom_pos_pct": round(float(bottom_pos_pct), 2),
                        "near_bottom_bars": int(near_bottom_bars),
                        "rim_diff_pct": round(float(rim_diff), 2),
                        "handle_decline_pct": round(float(handle_decline), 2),
                        "handle_pos_pct": round(float(handle_pos_pct), 2),
                        "handle_slope_pct": round(float(handle_slope_pct), 2),
                        "breakout_lag_bars": int(breakout_lag_bars),
                    }
                    variant_evidence = {
                        "depth_pct": round(float(depth_pct), 2),
                        "variant_code": variant_code,
                    }

                    confidence = 60
                    if rim_diff <= self.rim_tol_ideal:
                        confidence += 10
                    elif rim_diff <= 5.0:
                        confidence += 5
                    if abs(bottom_pos_pct - 50.0) <= 10.0:
                        confidence += 5
                    if near_bottom_bars >= max(self.roundness_min_bars, 5):
                        confidence += 5
                    if vol_ok:
                        confidence += 10
                    confidence += 10  # breakout found
                    confidence = int(min(100, confidence))

                    # Use positional indices (pivot engine works on iloc positions).
                    handle_low_idx = int(handle_start) + int(np.argmin(hseg["low"].to_numpy()))

                    pattern_id = f"{symbol}_{self.key}_{int(left.idx)}_{int(handle_end)}"
                    out.append(
                        {
                            "pattern_id": pattern_id,
                            "symbol": symbol,
                            "pattern_name": self.key,
                            "pattern_type": self.pattern_type,
                            "formation_start": str(df.iloc[int(left.idx)]["date"].date()) if "date" in df.columns else str(int(left.idx)),
                            "formation_end": str(df.iloc[int(handle_end)]["date"].date()) if "date" in df.columns else str(int(handle_end)),
                            "breakout_date": str(df.iloc[int(breakout_idx)]["date"].date()) if "date" in df.columns else None,
                            "breakout_idx": int(breakout_idx),
                            "breakout_direction": "up",
                            "breakout_price": float(breakout_price),
                            "target_price": float(target),
                            "stop_loss_price": float(stop),
                            "confidence_score": confidence,
                            "volume_confirmed": bool(vol_ok),
                            "pattern_height_pct": round(float(depth_pct), 2),
                            "pattern_width_bars": (int(handle_end) - int(left.idx)) + 1,
                            "touch_count": 6,
                            "pivot_indices": [int(left.idx), bottom_idx, int(right.idx), handle_low_idx, int(handle_end)],
                            "base_pattern_name": "cup_with_handle",
                            "variant_code": variant_code,
                            "variant_confidence": confidence,
                            "variant_evidence_json": json.dumps(variant_evidence, ensure_ascii=False, sort_keys=True),
                            "family_metrics_json": json.dumps(family_metrics, ensure_ascii=False, sort_keys=True),
                            "config_hash": self.config_hash,
                            "created_at": datetime.now().isoformat(),
                        }
                    )
                    break  # stop at first valid handle+breakout for this rim pair

        return out


def _invert_ohlcv_prices(df: pd.DataFrame) -> Tuple[pd.DataFrame, float]:
    """
    Invert OHLC prices around a constant to mirror bullish/bearish formations.

    Returns (inverted_df, a) where inverted_price = a - price.
    """
    if df.empty:
        return df.copy(), 0.0
    hi = pd.to_numeric(df["high"], errors="coerce")
    lo = pd.to_numeric(df["low"], errors="coerce")
    if hi.dropna().empty or lo.dropna().empty:
        return df.copy(), 0.0
    a = float(hi.max()) + float(lo.min())

    inv = df.copy()
    inv_open = a - pd.to_numeric(inv["open"], errors="coerce")
    inv_close = a - pd.to_numeric(inv["close"], errors="coerce")
    inv_high_raw = a - pd.to_numeric(inv["low"], errors="coerce")
    inv_low_raw = a - pd.to_numeric(inv["high"], errors="coerce")
    inv["open"] = inv_open
    inv["close"] = inv_close
    inv["high"] = np.maximum(inv_high_raw, inv_low_raw)
    inv["low"] = np.minimum(inv_high_raw, inv_low_raw)
    return inv, a


def _invert_pivots(pivots: List[Pivot], a: float) -> List[Pivot]:
    out: List[Pivot] = []
    for p in pivots:
        if p.type == PivotType.HIGH:
            t = PivotType.LOW
        elif p.type == PivotType.LOW:
            t = PivotType.HIGH
        else:
            t = p.type
        try:
            price = float(a) - float(p.price)
        except Exception:
            continue
        out.append(
            Pivot(
                idx=int(p.idx),
                date=p.date,
                price=price,
                type=t,
                strength=int(getattr(p, "strength", 0) or 0),
                classification=str(getattr(p, "classification", "") or ""),
            )
        )
    return out


class InvertedCupWithHandleScanner(CupWithHandleScanner):
    """
    Detects Bulkowski's "Cup with Handle, Inverted" by mirroring price series and pivots,
    then re-using the bullish cup-with-handle logic.

    Output is mapped back into the original (non-inverted) price space:
      - breakout_direction is 'down'
      - breakout/target/stop prices use the original df
    """

    def scan(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> List[Dict[str, Any]]:
        inv_df, a = _invert_ohlcv_prices(df)
        inv_pf = _invert_pivots(pivots_filtered, a)
        inv_pr = _invert_pivots(pivots_raw, a)

        rows = super().scan(symbol=symbol, df=inv_df, pivots_filtered=inv_pf, pivots_raw=inv_pr)
        out: List[Dict[str, Any]] = []

        for r in rows:
            piv = r.get("pivot_indices") or []
            if not isinstance(piv, (list, tuple)) or len(piv) < 5:
                continue
            try:
                left_idx = int(piv[0])
                right_idx = int(piv[2])
                handle_end_idx = int(piv[4])
            except Exception:
                continue
            if not (0 <= left_idx < len(df) and 0 <= right_idx < len(df) and 0 <= handle_end_idx < len(df)):
                continue

            # Inverted cup rims correspond to *lows* in the original df.
            rim1 = _safe_float(df.iloc[left_idx].get("low"))
            rim2 = _safe_float(df.iloc[right_idx].get("low"))
            if rim1 is None or rim2 is None or rim1 <= 0 or rim2 <= 0:
                continue
            rim_avg = (float(rim1) + float(rim2)) / 2.0

            seg = df.iloc[min(left_idx, right_idx) : max(left_idx, right_idx) + 1]
            if len(seg) == 0:
                continue
            cup_top = _safe_float(seg["high"].max())
            if cup_top is None or cup_top <= 0:
                continue

            depth_abs = float(cup_top) - float(rim_avg)
            if depth_abs <= 0:
                continue

            breakout_idx = r.get("breakout_idx")
            try:
                bi = int(breakout_idx) if breakout_idx is not None else None
            except Exception:
                bi = None
            if bi is None or not (0 <= bi < len(df)):
                continue

            breakout_price = _safe_float(df.iloc[bi].get("close"))
            if breakout_price is None or breakout_price <= 0:
                continue

            # Stop = handle high (original). Handle starts after right rim.
            hs = min(len(df), max(right_idx + 1, 0))
            he = min(len(df) - 1, max(handle_end_idx, hs))
            hseg = df.iloc[hs : he + 1] if hs <= he else df.iloc[handle_end_idx : handle_end_idx + 1]
            handle_high = _safe_float(hseg["high"].max()) if len(hseg) else None
            if handle_high is None or handle_high <= 0:
                continue

            family_metrics = {}
            if r.get("family_metrics_json"):
                try:
                    family_metrics = json.loads(str(r.get("family_metrics_json") or ""))
                except Exception:
                    family_metrics = {}

            handle_rebound_pct = (float(handle_high) - float(rim_avg)) / float(rim_avg) * 100.0 if float(rim_avg) > 0 else 0.0
            handle_ceiling_pct = (float(handle_high) - float(rim_avg)) / float(depth_abs) * 100.0 if float(depth_abs) > 0 else 0.0
            mirrored_handle_slope_pct = _safe_float(family_metrics.get("handle_slope_pct"))
            breakout_lag_bars = int(family_metrics.get("breakout_lag_bars") or 0)
            rim_diff_pct = _safe_float(family_metrics.get("rim_diff_pct"))

            # The mirrored bullish scan still lets in a few bearish cups whose handles do not
            # drift upward or whose downside breakout comes too late. Re-check those semantics
            # in original price space before keeping the formation.
            if mirrored_handle_slope_pct is None or mirrored_handle_slope_pct > 0.75:
                continue
            if breakout_lag_bars <= 0 or breakout_lag_bars > 5:
                continue
            if rim_diff_pct is not None and rim_diff_pct > max(self.rim_tol_ideal + 3.0, 6.0):
                continue
            if handle_rebound_pct < 2.5 or handle_rebound_pct > 8.5:
                continue
            if handle_ceiling_pct > 32.0:
                continue

            row = dict(r)
            row["pattern_type"] = "continuation_bearish"
            row["breakout_direction"] = "down"
            row["breakout_price"] = float(breakout_price)
            row["target_price"] = float(breakout_price) - float(depth_abs)
            row["stop_loss_price"] = float(handle_high)
            family_metrics.update(
                {
                    "orig_handle_rebound_pct": round(float(handle_rebound_pct), 2),
                    "orig_handle_ceiling_pct": round(float(handle_ceiling_pct), 2),
                    "orig_handle_high": round(float(handle_high), 6),
                }
            )
            row["family_metrics_json"] = json.dumps(family_metrics, ensure_ascii=False, sort_keys=True)
            out.append(row)

        return out


class InsideDayScanner(BaseDigitizedScanner):
    def scan(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> List[Dict[str, Any]]:
        # Keep result size sane: only emit inside-day when a breakout happens within max_return_days.
        bo = self.spec.get("breakout_confirmation", {}) or {}
        thr_pct = float(bo.get("breakout_threshold_pct") or 0.5) / 100.0
        max_return = int(bo.get("max_return_days") or 2)

        geom = self.spec.get("geometry_constraints", {}) or {}
        hmin = geom.get("height_ratio_min")
        hmax = geom.get("height_ratio_max")

        out: List[Dict[str, Any]] = []
        for i in range(1, len(df)):
            y = df.iloc[i - 1]
            t = df.iloc[i]
            if t["high"] < y["high"] and t["low"] > y["low"]:
                inside_high = float(t["high"])
                inside_low = float(t["low"])
                if inside_high <= inside_low:
                    continue
                height_abs = inside_high - inside_low
                ref = (inside_high + inside_low) / 2.0
                if ref <= 0:
                    continue
                height_pct = height_abs / ref * 100.0
                if hmin is not None and height_pct < float(hmin):
                    continue
                if hmax is not None and height_pct > float(hmax):
                    continue

                breakout_idx = None
                breakout_dir = None
                breakout_price = None
                for j in range(i + 1, min(len(df), i + 1 + max_return)):
                    close = _safe_float(df.iloc[j].get("close"))
                    if close is None:
                        continue
                    if close > inside_high * (1.0 + thr_pct):
                        breakout_idx = j
                        breakout_dir = "up"
                        breakout_price = close
                        break
                    if close < inside_low * (1.0 - thr_pct):
                        breakout_idx = j
                        breakout_dir = "down"
                        breakout_price = close
                        break

                if breakout_idx is None:
                    continue

                pattern_id = f"{symbol}_{self.key}_{i-1}_{i}"
                target = breakout_price + height_abs if breakout_dir == "up" else breakout_price - height_abs
                stop = inside_low if breakout_dir == "up" else inside_high

                out.append(
                    {
                        "pattern_id": pattern_id,
                        "symbol": symbol,
                        "pattern_name": self.key,
                        "pattern_type": self.pattern_type,
                        "formation_start": str(y["date"].date()) if "date" in df.columns else str(i - 1),
                        "formation_end": str(t["date"].date()) if "date" in df.columns else str(i),
                        "breakout_date": str(df.iloc[breakout_idx]["date"].date()) if "date" in df.columns else None,
                        "breakout_idx": int(breakout_idx),
                        "breakout_direction": breakout_dir,
                        "breakout_price": breakout_price,
                        "target_price": target,
                        "stop_loss_price": stop,
                        "confidence_score": 70,
                        "volume_confirmed": False,
                        "pattern_height_pct": round(height_pct, 2),
                        "pattern_width_bars": 2,
                        "touch_count": 2,
                        "pivot_indices": [int(i - 1), int(i)],
                        "config_hash": self.config_hash,
                        "created_at": datetime.now().isoformat(),
                    }
                )

        return out


class MeasuredMoveScanner(BaseDigitizedScanner):
    """
    Dedicated family scanner for measured moves.

    The previous chapter mapping reused the raw digitized scanner and split only by
    breakout direction. That anchored detections too late and mixed together several
    unrelated seven-pivot windows. This family scanner models the textbook structure:
    phase 1 impulse, phase 2 correction, then a continuation breakout that projects
    another phase 1 distance.
    """

    def __init__(self, key: str, spec: Dict[str, Any]):
        super().__init__(key, spec)
        self.geom = spec.get("geometry_constraints", {}) or {}
        self.bo = spec.get("breakout_confirmation", {}) or {}
        slope = self.geom.get("slope_constraints", {}) or {}
        phase13 = self.geom.get("phase1_phase3_ratio", {}) or {}
        retrace = self.geom.get("phase2_retracement_ratio", {}) or {}
        duration = self.geom.get("phase2_duration_ratio", {}) or {}

        self.width_min_bars = int(self.geom.get("width_min_bars") or 21)
        self.width_max_bars = min(int(self.geom.get("width_max_bars") or 126), 140)
        self.phase1_slope_min_deg = float(slope.get("phase1_slope_min_degrees") or 15.0)
        self.phase1_slope_max_deg = float(slope.get("phase1_slope_max_degrees") or 75.0)
        self.phase2_slope_max_deg = float(slope.get("phase2_slope_max_degrees") or 30.0)
        self.phase1_phase3_ratio_min = float(phase13.get("min") or 0.85)
        self.phase1_phase3_ratio_max = float(phase13.get("max") or 1.15)
        self.phase2_retracement_min = float(retrace.get("min") or 0.33)
        self.phase2_retracement_max = float(retrace.get("max") or 0.67)
        self.phase2_duration_min = float(duration.get("min") or 0.30)
        self.phase2_duration_max = float(duration.get("max") or 0.80)
        self.breakout_thr = float(self.bo.get("breakout_threshold_pct") or 1.0) / 100.0
        self.confirm_bars = int(self.bo.get("confirmation_bars") or 2)
        self.breakout_search_bars = 42
        self.vol_required = bool(self.bo.get("volume_required") or False)
        self.vol_mult_min = float(self.bo.get("volume_multiplier_min") or 1.2)

    def _breakout_ok(
        self,
        df: pd.DataFrame,
        *,
        start_idx: int,
        ref_level: float,
        direction: str,
    ) -> tuple[Optional[int], Optional[float], bool]:
        if ref_level <= 0:
            return None, None, False
        for i in range(start_idx, min(len(df), start_idx + self.breakout_search_bars)):
            close = _safe_float(df.iloc[i].get("close"))
            if close is None:
                continue
            if direction == "up":
                ok = close > ref_level * (1.0 + self.breakout_thr)
            else:
                ok = close < ref_level * (1.0 - self.breakout_thr)
            if not ok:
                continue
            if self.confirm_bars > 1:
                all_ok = True
                for j in range(i, min(len(df), i + self.confirm_bars)):
                    c = _safe_float(df.iloc[j].get("close"))
                    if c is None:
                        all_ok = False
                        break
                    if direction == "up" and not (c > ref_level * (1.0 + self.breakout_thr)):
                        all_ok = False
                        break
                    if direction == "down" and not (c < ref_level * (1.0 - self.breakout_thr)):
                        all_ok = False
                        break
                if not all_ok:
                    continue
            vr = df.iloc[i].get("volume_ratio", np.nan)
            vol_ok = bool(pd.notna(vr) and np.isfinite(vr) and float(vr) >= self.vol_mult_min)
            if self.vol_required and not vol_ok:
                continue
            return int(i), float(close), vol_ok
        return None, None, False

    def _candidate(self, df: pd.DataFrame, pivots: Sequence[Pivot]) -> Optional[Dict[str, Any]]:
        if len(pivots) != 3:
            return None
        idxs = [int(p.idx) for p in pivots]
        if not (idxs[0] < idxs[1] < idxs[2]):
            return None
        width_bars = idxs[2] - idxs[0] + 1
        if width_bars < self.width_min_bars or width_bars > self.width_max_bars:
            return None

        kinds = [p.type for p in pivots]
        if kinds == [PivotType.LOW, PivotType.HIGH, PivotType.LOW]:
            direction = "up"
            phase1_start = float(df.iloc[idxs[0]]["low"])
            phase1_end = float(df.iloc[idxs[1]]["high"])
            phase2_end = float(df.iloc[idxs[2]]["low"])
            pattern_type = "continuation_bullish"
            variant_code = "measured_move_up"
            breakout_ref = phase1_end
            stop_loss_price = phase2_end
        elif kinds == [PivotType.HIGH, PivotType.LOW, PivotType.HIGH]:
            direction = "down"
            phase1_start = float(df.iloc[idxs[0]]["high"])
            phase1_end = float(df.iloc[idxs[1]]["low"])
            phase2_end = float(df.iloc[idxs[2]]["high"])
            pattern_type = "continuation_bearish"
            variant_code = "measured_move_down"
            breakout_ref = phase1_end
            stop_loss_price = phase2_end
        else:
            return None

        phase1_abs = abs(phase1_end - phase1_start)
        if phase1_abs <= 0 or phase1_start <= 0 or phase1_end <= 0 or phase2_end <= 0:
            return None

        if direction == "up":
            retracement_abs = phase1_end - phase2_end
            if retracement_abs <= 0:
                return None
            phase2_slope_deg = abs(_slope_degrees(idxs[1], phase1_end, idxs[2], phase2_end))
        else:
            retracement_abs = phase2_end - phase1_end
            if retracement_abs <= 0:
                return None
            phase2_slope_deg = abs(_slope_degrees(idxs[1], phase1_end, idxs[2], phase2_end))

        retracement_ratio = retracement_abs / phase1_abs
        if retracement_ratio < self.phase2_retracement_min or retracement_ratio > self.phase2_retracement_max:
            return None

        phase1_bars = idxs[1] - idxs[0]
        phase2_bars = idxs[2] - idxs[1]
        if phase1_bars <= 0 or phase2_bars <= 0:
            return None
        phase2_duration_ratio = phase2_bars / phase1_bars
        if phase2_duration_ratio < self.phase2_duration_min or phase2_duration_ratio > self.phase2_duration_max:
            return None

        phase1_slope_deg = abs(_slope_degrees(idxs[0], phase1_start, idxs[1], phase1_end))
        if phase1_slope_deg < self.phase1_slope_min_deg or phase1_slope_deg > self.phase1_slope_max_deg:
            return None
        if phase2_slope_deg > self.phase2_slope_max_deg:
            return None

        breakout_idx, breakout_price, vol_ok = self._breakout_ok(
            df,
            start_idx=idxs[2] + 1,
            ref_level=breakout_ref,
            direction=direction,
        )
        if breakout_idx is None or breakout_price is None:
            return None

        breakout_progress_ratio = abs(breakout_price - phase2_end) / phase1_abs if phase1_abs > 0 else None
        if breakout_progress_ratio is None:
            return None

        target_price = phase2_end + phase1_abs if direction == "up" else phase2_end - phase1_abs

        confidence = 76
        if 0.42 <= retracement_ratio <= 0.58:
            confidence += 5
        if phase2_duration_ratio <= 0.60:
            confidence += 3
        if breakout_progress_ratio <= 0.35:
            confidence += 3
        if vol_ok:
            confidence += 3
        confidence = max(0, min(100, confidence))

        family_metrics = {
            "phase1_move_pct": abs((phase1_end - phase1_start) / phase1_start) * 100.0,
            "phase1_bars": int(phase1_bars),
            "phase1_slope_deg": float(phase1_slope_deg),
            "phase2_bars": int(phase2_bars),
            "phase2_slope_deg": float(phase2_slope_deg),
            "phase2_retracement_ratio": float(retracement_ratio),
            "phase2_retracement_pct": float(retracement_ratio * 100.0),
            "phase2_duration_ratio": float(phase2_duration_ratio),
            "projected_phase3_ratio": 1.0,
            "breakout_progress_ratio": float(breakout_progress_ratio),
            "breakout_lag_bars": int(breakout_idx - idxs[2]),
        }

        return {
            "pattern_id": f"{variant_code}_{idxs[0]}_{idxs[2]}",
            "pattern_type": pattern_type,
            "breakout_direction": direction,
            "breakout_idx": int(breakout_idx),
            "breakout_price": float(breakout_price),
            "target_price": float(target_price),
            "stop_loss_price": float(stop_loss_price),
            "confidence_score": int(confidence),
            "volume_confirmed": bool(vol_ok),
            "pattern_height_pct": round(float(abs((target_price - phase2_end) / max(1e-9, phase2_end)) * 100.0), 2),
            "pattern_width_bars": int(width_bars),
            "touch_count": 3,
            "pivot_indices": idxs,
            "variant_code": variant_code,
            "variant_confidence": int(confidence),
            "variant_evidence_json": json.dumps(
                {
                    "phase2_retracement_ratio": round(float(retracement_ratio), 3),
                    "phase2_duration_ratio": round(float(phase2_duration_ratio), 3),
                    "projected_phase3_ratio": 1.0,
                    "breakout_progress_ratio": round(float(breakout_progress_ratio), 3),
                    "phase1_slope_deg": round(float(phase1_slope_deg), 2),
                },
                sort_keys=True,
                ensure_ascii=False,
            ),
            "family_metrics_json": json.dumps(family_metrics, sort_keys=True, ensure_ascii=False),
        }

    def scan(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> List[Dict[str, Any]]:
        pivots = pivots_filtered or pivots_raw
        if len(pivots) < 3:
            return []

        out: List[Dict[str, Any]] = []
        seen: set[tuple[int, int, str]] = set()
        for i in range(len(pivots) - 2):
            window = pivots[i : i + 3]
            candidate = self._candidate(df, window)
            if not candidate:
                continue
            start_idx = int(candidate["pivot_indices"][0])
            end_idx = int(candidate["pivot_indices"][-1])
            breakout_idx = int(candidate["breakout_idx"])
            sig = (start_idx, end_idx, str(candidate["variant_code"]))
            if sig in seen:
                continue
            seen.add(sig)
            out.append(
                {
                    "pattern_id": f"{symbol}_{self.key}_{candidate['pattern_id']}",
                    "symbol": symbol,
                    "pattern_name": self.key,
                    "base_pattern_name": self.key,
                    "pattern_type": candidate["pattern_type"],
                    "formation_start": str(df.iloc[start_idx]["date"].date()) if "date" in df.columns else str(start_idx),
                    "formation_end": str(df.iloc[end_idx]["date"].date()) if "date" in df.columns else str(end_idx),
                    "breakout_date": str(df.iloc[breakout_idx]["date"].date()) if "date" in df.columns else None,
                    "breakout_idx": breakout_idx,
                    "breakout_direction": candidate["breakout_direction"],
                    "breakout_price": candidate["breakout_price"],
                    "target_price": candidate["target_price"],
                    "stop_loss_price": candidate["stop_loss_price"],
                    "confidence_score": candidate["confidence_score"],
                    "volume_confirmed": candidate["volume_confirmed"],
                    "variant_code": candidate["variant_code"],
                    "variant_confidence": candidate["variant_confidence"],
                    "variant_evidence_json": candidate["variant_evidence_json"],
                    "family_metrics_json": candidate["family_metrics_json"],
                    "pattern_height_pct": candidate["pattern_height_pct"],
                    "pattern_width_bars": candidate["pattern_width_bars"],
                    "touch_count": candidate["touch_count"],
                    "pivot_indices": candidate["pivot_indices"],
                    "config_hash": self.config_hash,
                    "created_at": datetime.now().isoformat(),
                }
            )
        return out


class GapScanner(BaseDigitizedScanner):
    def __init__(self, key: str, spec: Dict[str, Any]):
        super().__init__(key, spec)
        self.geom = spec.get("geometry_constraints", {}) or {}
        self.breakout = spec.get("breakout_confirmation", {}) or {}
        self.prior = spec.get("prior_trend_requirements", {}) or {}

        gap_cfg = self.geom.get("gap_constraints") or {}
        if not isinstance(gap_cfg, dict):
            gap_cfg = {}

        self.min_gap = float(gap_cfg.get("min_gap_size_pct") or 0.1) / 100.0
        max_gap_pct = gap_cfg.get("max_gap_size_pct")
        self.max_gap = float(max_gap_pct) / 100.0 if max_gap_pct is not None else None
        self.hmin = self.geom.get("height_ratio_min")
        self.hmax = self.geom.get("height_ratio_max")
        self.breakout_thr = float(self.breakout.get("breakout_threshold_pct") or 0.1) / 100.0
        self.fill_horizon = int(self.breakout.get("max_return_days") or 3)
        self.min_prior_bars = max(3, int(self.prior.get("min_period_bars") or 5))
        self.min_prior_change = float(self.prior.get("min_change_pct") or 3.0)
        self.min_volume_ratio = float(self.breakout.get("volume_multiplier_min") or 1.1)

    def _gap_candidate(self, df: pd.DataFrame, i: int) -> Optional[Dict[str, Any]]:
        if i <= 0 or i >= len(df):
            return None
        prev = df.iloc[i - 1]
        cur = df.iloc[i]

        prev_high = _safe_float(prev.get("high"))
        prev_low = _safe_float(prev.get("low"))
        cur_high = _safe_float(cur.get("high"))
        cur_low = _safe_float(cur.get("low"))
        cur_close = _safe_float(cur.get("close"))
        if None in (prev_high, prev_low, cur_high, cur_low, cur_close):
            return None

        direction: Optional[str] = None
        lower_edge: Optional[float] = None
        upper_edge: Optional[float] = None

        if float(cur_low) > float(prev_high) * (1.0 + self.min_gap):
            direction = "up"
            lower_edge = float(prev_high)
            upper_edge = float(cur_low)
        elif float(cur_high) < float(prev_low) * (1.0 - self.min_gap):
            direction = "down"
            lower_edge = float(cur_high)
            upper_edge = float(prev_low)
        else:
            return None

        height_abs = float(upper_edge - lower_edge)
        if height_abs <= 0:
            return None
        ref = (float(upper_edge) + float(lower_edge)) / 2.0
        if ref <= 0:
            return None
        gap_pct = height_abs / ref
        if self.max_gap is not None and gap_pct > self.max_gap:
            return None
        gap_pct_100 = gap_pct * 100.0
        if self.hmin is not None and gap_pct_100 < float(self.hmin):
            return None
        if self.hmax is not None and gap_pct_100 > float(self.hmax):
            return None

        return {
            "direction": direction,
            "gap_lower_edge": float(lower_edge),
            "gap_upper_edge": float(upper_edge),
            "gap_abs": float(height_abs),
            "gap_pct": float(gap_pct_100),
            "breakout_price": float(cur_close),
        }

    def _prior_change_pct(self, df: pd.DataFrame, end_idx: int, bars: int) -> Optional[float]:
        if end_idx <= 0 or bars <= 0:
            return None
        start_idx = end_idx - bars
        if start_idx < 0:
            return None
        p0 = _safe_float(df.iloc[start_idx].get("close"))
        p1 = _safe_float(df.iloc[end_idx].get("close"))
        if p0 is None or p1 is None or p0 <= 0:
            return None
        return (float(p1) - float(p0)) / float(p0) * 100.0

    def _recent_range_pct(self, df: pd.DataFrame, end_idx: int, bars: int) -> Optional[float]:
        start_idx = max(0, end_idx - bars + 1)
        window = df.iloc[start_idx : end_idx + 1]
        if len(window) < max(3, bars // 2):
            return None
        high = _safe_float(window["high"].max())
        low = _safe_float(window["low"].min())
        if high is None or low is None or high <= 0 or high <= low:
            return None
        ref = (float(high) + float(low)) / 2.0
        if ref <= 0:
            return None
        return (float(high) - float(low)) / ref * 100.0

    def _directional_ratio(self, df: pd.DataFrame, end_idx: int, bars: int, *, direction: str) -> Optional[float]:
        start_idx = end_idx - bars + 1
        if start_idx <= 0:
            return None
        closes = df.iloc[start_idx - 1 : end_idx + 1]["close"].to_numpy(dtype=float, copy=False)
        if closes.size < 3 or not np.isfinite(closes).all():
            return None
        diffs = np.diff(closes)
        if diffs.size == 0:
            return None
        if direction == "up":
            return float(np.mean(diffs > 0))
        return float(np.mean(diffs < 0))

    def _classify_gap_variant(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        direction = str(metrics.get("direction") or "up")
        gap_pct = _safe_float(metrics.get("gap_pct")) or 0.0
        vol_ratio = _safe_float(metrics.get("volume_ratio")) or 0.0
        prior10 = _safe_float(metrics.get("prior_change_10_pct"))
        prior20 = _safe_float(metrics.get("prior_change_20_pct"))
        recent_range = _safe_float(metrics.get("recent_range_10_pct"))
        dir_ratio = _safe_float(metrics.get("directional_ratio_10"))

        trend_dir = "flat"
        trend_strength = 0.0
        for change in (prior20, prior10):
            if change is None:
                continue
            if abs(change) >= self.min_prior_change:
                trend_dir = "up" if change > 0 else "down"
                trend_strength = abs(change)
                break

        consolidation = (
            recent_range is not None
            and recent_range <= max(6.0, gap_pct * 2.8)
            and (prior10 is None or abs(prior10) <= 4.5)
        )
        established_trend = trend_dir == direction and trend_strength >= 5.0
        extended_trend = trend_dir == direction and (
            trend_strength >= 12.0
            or (
                trend_strength >= 8.0
                and dir_ratio is not None
                and dir_ratio >= 0.70
                and gap_pct >= 0.7
            )
        )

        if consolidation and gap_pct >= 0.6 and vol_ratio >= 1.25:
            subtype = "breakaway_gap"
            base_conf = 88
            evidence = ["prior_consolidation", "volume_support", "large_gap"]
        elif extended_trend and gap_pct >= 0.8 and vol_ratio >= 1.4:
            subtype = "exhaustion_gap"
            base_conf = 78
            evidence = ["extended_trend", "high_volume", "trend_stretch"]
        elif established_trend and gap_pct >= 0.35:
            subtype = "continuation_gap"
            base_conf = 82
            evidence = ["established_trend", "gap_in_trend_direction"]
        else:
            subtype = "common_gap"
            base_conf = 60
            evidence = ["weak_context_or_small_gap"]

        confidence = base_conf
        if gap_pct >= 1.2:
            confidence += 4
        if vol_ratio >= 2.0:
            confidence += 4
        if subtype == "common_gap" and gap_pct <= 0.35:
            confidence -= 5
        if subtype == "common_gap" and vol_ratio < 1.0:
            confidence -= 3
        confidence = int(max(45, min(98, confidence)))

        return {
            "variant_code": f"{subtype}_{direction}",
            "variant_confidence": confidence,
            "evidence": evidence,
            "subtype": subtype,
        }

    def scan(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for i in range(1, len(df)):
            candidate = self._gap_candidate(df, i)
            if not candidate:
                continue

            direction = str(candidate["direction"])
            prior_change_5 = self._prior_change_pct(df, i - 1, 5)
            prior_change_10 = self._prior_change_pct(df, i - 1, 10)
            prior_change_20 = self._prior_change_pct(df, i - 1, 20)
            recent_range_10 = self._recent_range_pct(df, i - 1, 10)
            directional_ratio = self._directional_ratio(df, i - 1, 10, direction=direction)
            volume_ratio = _safe_float(df.iloc[i].get("volume_ratio")) or 0.0

            metrics = {
                "direction": direction,
                "gap_pct": candidate["gap_pct"],
                "prior_change_5_pct": prior_change_5,
                "prior_change_10_pct": prior_change_10,
                "prior_change_20_pct": prior_change_20,
                "recent_range_10_pct": recent_range_10,
                "directional_ratio_10": directional_ratio,
                "volume_ratio": volume_ratio,
            }
            variant = self._classify_gap_variant(metrics)
            subtype = str(variant["subtype"])
            confidence = int(variant["variant_confidence"])

            target_price = (
                float(candidate["breakout_price"]) + float(candidate["gap_abs"])
                if direction == "up"
                else float(candidate["breakout_price"]) - float(candidate["gap_abs"])
            )
            stop_loss_price = float(candidate["gap_lower_edge"]) if direction == "up" else float(candidate["gap_upper_edge"])

            family_metrics = {
                "gap_pct": float(candidate["gap_pct"]),
                "gap_abs": float(candidate["gap_abs"]),
                "gap_lower_edge": float(candidate["gap_lower_edge"]),
                "gap_upper_edge": float(candidate["gap_upper_edge"]),
                "prior_change_5_pct": prior_change_5,
                "prior_change_10_pct": prior_change_10,
                "prior_change_20_pct": prior_change_20,
                "recent_range_10_pct": recent_range_10,
                "directional_ratio_10": directional_ratio,
                "volume_ratio": volume_ratio,
                "subtype": subtype,
                "fill_horizon_bars": int(self.fill_horizon),
            }

            out.append(
                {
                    "pattern_id": f"{symbol}_{self.key}_{i}_{direction}",
                    "symbol": symbol,
                    "pattern_name": self.key,
                    "base_pattern_name": self.key,
                    "pattern_type": self.pattern_type,
                    "formation_start": str(df.iloc[i]["date"].date()) if "date" in df.columns else str(i),
                    "formation_end": str(df.iloc[i]["date"].date()) if "date" in df.columns else str(i),
                    "breakout_date": str(df.iloc[i]["date"].date()) if "date" in df.columns else None,
                    "breakout_idx": int(i),
                    "breakout_direction": direction,
                    "breakout_price": float(candidate["breakout_price"]),
                    "target_price": float(target_price),
                    "stop_loss_price": float(stop_loss_price),
                    "confidence_score": confidence,
                    "volume_confirmed": bool(volume_ratio >= self.min_volume_ratio),
                    "pattern_height_pct": round(float(candidate["gap_pct"]), 3),
                    "pattern_width_bars": 1,
                    "touch_count": 1,
                    "pivot_indices": [int(i - 1), int(i)],
                    "variant_code": variant["variant_code"],
                    "variant_confidence": confidence,
                    "variant_evidence_json": json.dumps(
                        {
                            "subtype": subtype,
                            "volume_ratio": round(float(volume_ratio), 3),
                            "prior_change_10_pct": None if prior_change_10 is None else round(float(prior_change_10), 3),
                            "prior_change_20_pct": None if prior_change_20 is None else round(float(prior_change_20), 3),
                        },
                        sort_keys=True,
                        ensure_ascii=False,
                    ),
                    "family_metrics_json": json.dumps(family_metrics, sort_keys=True, ensure_ascii=False),
                    "config_hash": self.config_hash,
                    "created_at": datetime.now().isoformat(),
                }
            )

        return out


class DeadCatBounceScanner(BaseDigitizedScanner):
    """
    Bulkowski Part Two (Event Patterns): Dead-Cat Bounce (DCB).

    Detection is OHLCV-only and avoids look-ahead beyond the "breakout" anchor:
      - Identify a sharp event decline (15%+ from pre-event high to event low within <= 8 bars)
      - Identify a bounce of 15% to 35% from the event low, peaking 5 to 25 bars after the event low
      - Breakout/anchor is the bounce peak day, expecting a post-bounce decline (measured by evaluator)
    """

    def __init__(self, key: str, spec: Dict[str, Any]):
        super().__init__(key, spec)
        s = spec.get("event_constraints", {}) or {}
        self.event_decline_min_pct = float(s.get("event_decline_min_pct") or 15.0)
        self.event_decline_max_bars = int(s.get("event_decline_max_bars") or 8)
        self.bounce_min_pct = float(s.get("bounce_min_pct") or 15.0)
        self.bounce_max_pct = float(s.get("bounce_max_pct") or 35.0)
        self.bounce_min_bars = int(s.get("bounce_min_bars") or 5)
        self.bounce_max_bars = int(s.get("bounce_max_bars") or 25)
        self.gap_preferred = bool(s.get("gap_preferred") if s.get("gap_preferred") is not None else True)

        v = spec.get("volume_constraints", {}) or {}
        self.vol_ratio_preferred = float(v.get("event_volume_ratio_preferred") or 2.0)

    @staticmethod
    def _gap_down(df: pd.DataFrame, i: int) -> bool:
        if i <= 0 or i >= len(df):
            return False
        try:
            return float(df.iloc[i]["high"]) < float(df.iloc[i - 1]["low"])
        except Exception:
            return False

    def scan(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if len(df) < 50:
            return out

        seen: set[tuple[int, int]] = set()
        n = len(df)

        for event_start in range(1, n - 2):
            pre_high = _safe_float(df.iloc[event_start - 1].get("high"))
            if pre_high is None or pre_high <= 0:
                continue

            # Event decline window (<= 8 bars, inclusive).
            end = min(n - 1, event_start + max(1, self.event_decline_max_bars))
            seg = df.iloc[event_start : end + 1]
            if seg.empty:
                continue

            event_low = _safe_float(seg["low"].min())
            if event_low is None or event_low <= 0:
                continue
            try:
                low_vals = seg["low"].to_numpy(dtype=float, copy=False)
                if low_vals.size == 0 or not np.isfinite(low_vals).any():
                    continue
                event_low_rel = int(np.nanargmin(low_vals))
                event_low_idx = int(event_start + event_low_rel)
            except Exception:
                continue

            event_decline_pct = (float(pre_high) - float(event_low)) / float(pre_high) * 100.0
            if event_decline_pct < float(self.event_decline_min_pct):
                continue

            # Bounce peak must occur 5..25 bars after the event low.
            b0 = event_low_idx + int(self.bounce_min_bars)
            b1 = event_low_idx + int(self.bounce_max_bars)
            if b0 >= n:
                continue
            b1 = min(n - 1, b1)
            bseg = df.iloc[b0 : b1 + 1]
            if bseg.empty:
                continue
            bounce_high = _safe_float(bseg["high"].max())
            if bounce_high is None or bounce_high <= 0:
                continue
            try:
                high_vals = bseg["high"].to_numpy(dtype=float, copy=False)
                if high_vals.size == 0 or not np.isfinite(high_vals).any():
                    continue
                bounce_high_rel = int(np.nanargmax(high_vals))
                bounce_high_idx = int(b0 + bounce_high_rel)
            except Exception:
                continue

            bounce_pct = (float(bounce_high) - float(event_low)) / float(event_low) * 100.0
            if bounce_pct < float(self.bounce_min_pct) or bounce_pct > float(self.bounce_max_pct):
                continue

            sig = (int(event_low_idx), int(bounce_high_idx))
            if sig in seen:
                continue
            seen.add(sig)

            # Anchor = bounce peak close (expecting subsequent decline).
            breakout_idx = int(bounce_high_idx)
            breakout_price = _safe_float(df.iloc[breakout_idx].get("close"))
            if breakout_price is None or breakout_price <= 0:
                continue

            gap = self._gap_down(df, int(event_start))
            confidence = 65
            if gap:
                confidence += 10
            if float(event_decline_pct) >= 25.0:
                confidence += 5
            if float(bounce_pct) >= 25.0:
                confidence += 5

            vr = df.iloc[int(event_start)].get("volume_ratio", np.nan)
            if pd.notna(vr) and np.isfinite(vr) and float(vr) >= float(self.vol_ratio_preferred):
                confidence += 10
            confidence = int(min(100, confidence))

            pattern_id = f"{symbol}_{self.key}_{int(event_start)}_{int(bounce_high_idx)}"
            width_bars = int(bounce_high_idx - event_start + 1)

            out.append(
                {
                    "pattern_id": pattern_id,
                    "symbol": symbol,
                    "pattern_name": self.key,
                    "pattern_type": self.pattern_type,
                    "formation_start": str(df.iloc[int(event_start)]["date"].date()) if "date" in df.columns else str(int(event_start)),
                    "formation_end": str(df.iloc[int(bounce_high_idx)]["date"].date()) if "date" in df.columns else str(int(bounce_high_idx)),
                    "breakout_date": str(df.iloc[int(breakout_idx)]["date"].date()) if "date" in df.columns else None,
                    "breakout_idx": int(breakout_idx),
                    "breakout_direction": "down",
                    "breakout_price": float(breakout_price),
                    "target_price": None,
                    "stop_loss_price": None,
                    "confidence_score": confidence,
                    "volume_confirmed": bool(gap) if self.gap_preferred else False,
                    # Store event-decline magnitude as pattern height (event KPI).
                    "pattern_height_pct": round(float(event_decline_pct), 2),
                    "pattern_width_bars": int(width_bars),
                    "touch_count": 4,
                    # Indices: pre-event high, event start, event low, bounce peak.
                    "pivot_indices": [int(event_start - 1), int(event_start), int(event_low_idx), int(bounce_high_idx)],
                    "config_hash": self.config_hash,
                    "created_at": datetime.now().isoformat(),
                }
            )

        return out


class DeadCatBounceInvertedScanner(BaseDigitizedScanner):
    """
    Bulkowski Part Two (Event Patterns): Inverted Dead-Cat Bounce (iDCB).

    OHLCV-only, causal detection at day 2 (Bulkowski-style: selling on day 2):
      - Day 1: large 1-day upward move (>= 5% close-to-close by default)
      - Day 2: higher high and higher low than day 1 (a final push)
      - Anchor/breakout is day 2 close, expecting a giveback (measured by evaluator)
    """

    def __init__(self, key: str, spec: Dict[str, Any]):
        super().__init__(key, spec)
        s = spec.get("event_constraints", {}) or {}
        self.up_move_min_pct = float(s.get("up_move_min_pct") or 5.0)
        self.gap_preferred = bool(s.get("gap_preferred") if s.get("gap_preferred") is not None else True)

        v = spec.get("volume_constraints", {}) or {}
        self.vol_ratio_preferred = float(v.get("event_volume_ratio_preferred") or 2.0)

    @staticmethod
    def _gap_up(df: pd.DataFrame, i: int) -> bool:
        if i <= 0 or i >= len(df):
            return False
        try:
            return float(df.iloc[i]["low"]) > float(df.iloc[i - 1]["high"])
        except Exception:
            return False

    def scan(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if len(df) < 10:
            return out

        n = len(df)
        for day1 in range(1, n - 1):
            ref_close = _safe_float(df.iloc[day1 - 1].get("close"))
            c1 = _safe_float(df.iloc[day1].get("close"))
            if ref_close is None or c1 is None or ref_close <= 0:
                continue
            move_pct = (float(c1) - float(ref_close)) / float(ref_close) * 100.0
            if move_pct < float(self.up_move_min_pct):
                continue

            day2 = day1 + 1
            try:
                h1 = float(df.iloc[day1]["high"])
                l1 = float(df.iloc[day1]["low"])
                h2 = float(df.iloc[day2]["high"])
                l2 = float(df.iloc[day2]["low"])
            except Exception:
                continue

            # Bulkowski-style day 2 push: higher high and higher low.
            if not (h2 > h1 and l2 > l1):
                continue

            breakout_idx = int(day2)
            breakout_price = _safe_float(df.iloc[breakout_idx].get("close"))
            if breakout_price is None or breakout_price <= 0:
                continue

            gap = self._gap_up(df, int(day1))
            confidence = 60
            if gap:
                confidence += 10
            if float(move_pct) >= 10.0:
                confidence += 10
            vr = df.iloc[int(day1)].get("volume_ratio", np.nan)
            if pd.notna(vr) and np.isfinite(vr) and float(vr) >= float(self.vol_ratio_preferred):
                confidence += 10
            confidence = int(min(100, confidence))

            pattern_id = f"{symbol}_{self.key}_{int(day1)}_{int(day2)}"
            out.append(
                {
                    "pattern_id": pattern_id,
                    "symbol": symbol,
                    "pattern_name": self.key,
                    "pattern_type": self.pattern_type,
                    "formation_start": str(df.iloc[int(day1 - 1)]["date"].date()) if "date" in df.columns else str(int(day1 - 1)),
                    "formation_end": str(df.iloc[int(day2)]["date"].date()) if "date" in df.columns else str(int(day2)),
                    "breakout_date": str(df.iloc[int(breakout_idx)]["date"].date()) if "date" in df.columns else None,
                    "breakout_idx": int(breakout_idx),
                    "breakout_direction": "down",
                    "breakout_price": float(breakout_price),
                    "target_price": None,
                    "stop_loss_price": None,
                    "confidence_score": confidence,
                    "volume_confirmed": bool(gap) if self.gap_preferred else False,
                    "pattern_height_pct": round(float(move_pct), 2),
                    "pattern_width_bars": 3,
                    "touch_count": 3,
                    "pivot_indices": [int(day1 - 1), int(day1), int(day2)],
                    "config_hash": self.config_hash,
                    "created_at": datetime.now().isoformat(),
                }
            )

        return out


class IslandScanner(BaseDigitizedScanner):
    def __init__(self, key: str, spec: Dict[str, Any]):
        super().__init__(key, spec)
        self.geom = spec.get("geometry_constraints", {}) or {}
        self.breakout = spec.get("breakout_confirmation", {}) or {}
        self.prior = spec.get("prior_trend_requirements", {}) or {}
        gap_cfg = self.geom.get("gap_constraints") or {}
        if not isinstance(gap_cfg, dict):
            gap_cfg = {}
        island_dur = self.geom.get("island_duration") or {}
        if not isinstance(island_dur, dict):
            island_dur = {}
        duration = self.spec.get("duration_constraints", {}) or {}

        self.min_gap_pct = float(gap_cfg.get("min_gap_size_pct") or 0.5) / 100.0
        max_gap_pct = gap_cfg.get("max_gap_size_pct")
        self.max_gap_pct = float(max_gap_pct) / 100.0 if max_gap_pct is not None else None
        self.min_gap_similarity_ratio = float(gap_cfg.get("gap_similarity_pct") or 50.0) / 100.0
        price_sep = self.geom.get("price_separation") or {}
        if not isinstance(price_sep, dict):
            price_sep = {}
        self.min_separation_pct = float(price_sep.get("min_separation_pct") or 0.5) / 100.0
        self.min_island_bars = max(3, int(duration.get("min_bars") or island_dur.get("min_bars") or 3))
        self.max_island_bars = int(island_dur.get("max_bars") or self.geom.get("width_max_bars") or duration.get("max_bars") or 20)
        self.width_min_bars = int(self.geom.get("width_min_bars") or self.min_island_bars)
        self.width_max_bars = int(self.geom.get("width_max_bars") or self.max_island_bars)
        self.hmin = self.geom.get("height_ratio_min")
        self.hmax = self.geom.get("height_ratio_max")
        self.min_prior_bars = max(3, int(self.prior.get("min_period_bars") or 5))
        self.min_prior_change = float(self.prior.get("min_change_pct") or 3.0)
        self.min_volume_ratio = float(self.breakout.get("volume_multiplier_min") or 1.1)

    def _gap_up(self, df: pd.DataFrame, i: int) -> Optional[Dict[str, float]]:
        if i <= 0 or i >= len(df):
            return None
        prev_high = _safe_float(df.iloc[i - 1].get("high"))
        cur_low = _safe_float(df.iloc[i].get("low"))
        if prev_high is None or cur_low is None:
            return None
        if float(cur_low) <= float(prev_high) * (1.0 + self.min_gap_pct):
            return None
        ref = (float(prev_high) + float(cur_low)) / 2.0
        if ref <= 0:
            return None
        gap_pct = (float(cur_low) - float(prev_high)) / ref
        if gap_pct <= 0:
            return None
        if self.max_gap_pct is not None and gap_pct > self.max_gap_pct:
            return None
        return {
            "gap_pct": float(gap_pct),
            "mainland_edge": float(prev_high),
            "island_edge": float(cur_low),
        }

    def _gap_down(self, df: pd.DataFrame, i: int) -> Optional[Dict[str, float]]:
        if i <= 0 or i >= len(df):
            return None
        prev_low = _safe_float(df.iloc[i - 1].get("low"))
        cur_high = _safe_float(df.iloc[i].get("high"))
        if prev_low is None or cur_high is None:
            return None
        if float(cur_high) >= float(prev_low) * (1.0 - self.min_gap_pct):
            return None
        ref = (float(prev_low) + float(cur_high)) / 2.0
        if ref <= 0:
            return None
        gap_pct = (float(prev_low) - float(cur_high)) / ref
        if gap_pct <= 0:
            return None
        if self.max_gap_pct is not None and gap_pct > self.max_gap_pct:
            return None
        return {
            "gap_pct": float(gap_pct),
            "mainland_edge": float(prev_low),
            "island_edge": float(cur_high),
        }

    def _prior_trend_ok(self, df: pd.DataFrame, start_idx: int, *, direction: str) -> tuple[bool, Optional[float]]:
        ref_idx = start_idx - 1
        if ref_idx < self.min_prior_bars:
            return False, None
        start_ref = ref_idx - self.min_prior_bars
        p0 = _safe_float(df.iloc[start_ref].get("close"))
        p1 = _safe_float(df.iloc[ref_idx].get("close"))
        if p0 is None or p1 is None or p0 <= 0:
            return False, None
        change_pct = (float(p1) - float(p0)) / float(p0) * 100.0
        if direction == "up":
            return change_pct >= self.min_prior_change, float(change_pct)
        return change_pct <= -self.min_prior_change, float(change_pct)

    def _build_candidate(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        entry_idx: int,
        exit_idx: int,
        direction: str,
    ) -> Optional[Dict[str, Any]]:
        width_bars = int(exit_idx - entry_idx + 1)
        if width_bars < self.min_island_bars or width_bars > self.max_island_bars:
            return None
        if width_bars < self.width_min_bars or width_bars > self.width_max_bars:
            return None
        if exit_idx - entry_idx < 2:
            return None

        if direction == "down":
            first_gap = self._gap_up(df, entry_idx)
            second_gap = self._gap_down(df, exit_idx)
            prior_ok, prior_change = self._prior_trend_ok(df, entry_idx, direction="up")
        else:
            first_gap = self._gap_down(df, entry_idx)
            second_gap = self._gap_up(df, exit_idx)
            prior_ok, prior_change = self._prior_trend_ok(df, entry_idx, direction="down")
        if not prior_ok or not first_gap or not second_gap:
            return None

        gap_similarity = min(float(first_gap["gap_pct"]), float(second_gap["gap_pct"])) / max(float(first_gap["gap_pct"]), float(second_gap["gap_pct"]))
        if gap_similarity < self.min_gap_similarity_ratio:
            return None

        island_window = df.iloc[entry_idx:exit_idx]
        if len(island_window) < 1:
            return None
        island_high = _safe_float(island_window["high"].max())
        island_low = _safe_float(island_window["low"].min())
        if island_high is None or island_low is None or island_high <= island_low:
            return None

        if direction == "down":
            mainland_boundary = float(first_gap["mainland_edge"])
            if not bool((island_window["low"] > mainland_boundary * (1.0 + self.min_separation_pct)).all()):
                return None
            separation_pct = (float(island_low) - mainland_boundary) / mainland_boundary * 100.0 if mainland_boundary > 0 else None
            stop_loss_price = float(island_high)
            pattern_type = "reversal_bearish"
            variant_code = "island_top"
        else:
            mainland_boundary = float(first_gap["mainland_edge"])
            if not bool((island_window["high"] < mainland_boundary * (1.0 - self.min_separation_pct)).all()):
                return None
            separation_pct = (mainland_boundary - float(island_high)) / mainland_boundary * 100.0 if mainland_boundary > 0 else None
            stop_loss_price = float(island_low)
            pattern_type = "reversal_bullish"
            variant_code = "island_bottom"

        breakout_price = _safe_float(df.iloc[exit_idx].get("close"))
        if breakout_price is None or breakout_price <= 0:
            return None

        height_abs = float(island_high - island_low)
        ref = (float(island_high) + float(island_low)) / 2.0
        if ref <= 0:
            return None
        height_pct = height_abs / ref * 100.0
        if self.hmin is not None and height_pct < float(self.hmin):
            return None
        if self.hmax is not None and height_pct > float(self.hmax):
            return None

        target_price = float(breakout_price) - height_abs if direction == "down" else float(breakout_price) + height_abs
        entry_volume = _safe_float(df.iloc[entry_idx].get("volume_ratio")) or 0.0
        exit_volume = _safe_float(df.iloc[exit_idx].get("volume_ratio")) or 0.0
        volume_confirmed = max(entry_volume, exit_volume) >= self.min_volume_ratio

        confidence = 74
        if width_bars <= 6:
            confidence += 4
        if gap_similarity >= 0.70:
            confidence += 5
        if separation_pct is not None and separation_pct >= 1.0:
            confidence += 4
        if volume_confirmed:
            confidence += 3
        confidence = int(max(55, min(96, confidence)))

        family_metrics = {
            "first_gap_pct": float(first_gap["gap_pct"] * 100.0),
            "second_gap_pct": float(second_gap["gap_pct"] * 100.0),
            "gap_similarity_ratio": float(gap_similarity),
            "prior_change_pct": prior_change,
            "separation_pct": separation_pct,
            "island_range_pct": float(height_pct),
            "entry_volume_ratio": float(entry_volume),
            "exit_volume_ratio": float(exit_volume),
            "width_bars": int(width_bars),
        }

        return {
            "pattern_id": f"{symbol}_{self.key}_{entry_idx}_{exit_idx}_{variant_code}",
            "symbol": symbol,
            "pattern_name": self.key,
            "base_pattern_name": self.key,
            "pattern_type": pattern_type,
            "formation_start": str(df.iloc[entry_idx]["date"].date()) if "date" in df.columns else str(entry_idx),
            "formation_end": str(df.iloc[exit_idx]["date"].date()) if "date" in df.columns else str(exit_idx),
            "breakout_date": str(df.iloc[exit_idx]["date"].date()) if "date" in df.columns else None,
            "breakout_idx": int(exit_idx),
            "breakout_direction": direction,
            "breakout_price": float(breakout_price),
            "target_price": float(target_price),
            "stop_loss_price": float(stop_loss_price),
            "confidence_score": confidence,
            "volume_confirmed": bool(volume_confirmed),
            "pattern_height_pct": round(float(height_pct), 2),
            "pattern_width_bars": int(width_bars),
            "touch_count": 2,
            "pivot_indices": [int(entry_idx), int(exit_idx)],
            "variant_code": variant_code,
            "variant_confidence": confidence,
            "variant_evidence_json": json.dumps(
                {
                    "gap_similarity_ratio": round(float(gap_similarity), 3),
                    "prior_change_pct": None if prior_change is None else round(float(prior_change), 3),
                    "separation_pct": None if separation_pct is None else round(float(separation_pct), 3),
                },
                sort_keys=True,
                ensure_ascii=False,
            ),
            "family_metrics_json": json.dumps(family_metrics, sort_keys=True, ensure_ascii=False),
            "config_hash": self.config_hash,
            "created_at": datetime.now().isoformat(),
        }

    def scan(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []

        i = 1
        while i < len(df):
            if self._gap_up(df, i):
                j_end = min(len(df), i + self.max_island_bars)
                j = i + 1
                while j < j_end:
                    if self._gap_down(df, j):
                        row = self._build_candidate(symbol=symbol, df=df, entry_idx=i, exit_idx=j, direction="down")
                        if row is not None:
                            out.append(row)
                        i = j  # skip ahead
                        break
                    j += 1
                i += 1
                continue

            if self._gap_down(df, i):
                j_end = min(len(df), i + self.max_island_bars)
                j = i + 1
                while j < j_end:
                    if self._gap_up(df, j):
                        row = self._build_candidate(symbol=symbol, df=df, entry_idx=i, exit_idx=j, direction="up")
                        if row is not None:
                            out.append(row)
                        i = j
                        break
                    j += 1
                i += 1
                continue

            i += 1

        return out


class ThreeMethodsScanner(BaseDigitizedScanner):
    def scan(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> List[Dict[str, Any]]:
        geom = self.spec.get("geometry_constraints", {}) or {}
        first_req = geom.get("first_bar_requirements", {}) or {}
        last_req = geom.get("last_bar_requirements", {}) or {}
        middle_req = geom.get("middle_bars_requirements", {}) or {}

        min_body_atr = float(first_req.get("min_body_size_atr") or 1.5)
        min_last_body_atr = float(last_req.get("min_body_size_atr") or 1.5)

        out: List[Dict[str, Any]] = []
        if "atr" not in df.columns:
            return out

        # KPI sanity: enforce digitized height constraints using a symmetric % definition.
        hmin = geom.get("height_ratio_min")
        hmax = geom.get("height_ratio_max")

        for i in range(4, len(df)):
            w = df.iloc[i - 4 : i + 1].copy()
            if len(w) != 5:
                continue

            atr = _safe_float(w.iloc[0].get("atr")) or _safe_float(w.iloc[-1].get("atr"))
            if atr is None or atr <= 0:
                continue

            o1, c1 = float(w.iloc[0]["open"]), float(w.iloc[0]["close"])
            o5, c5 = float(w.iloc[-1]["open"]), float(w.iloc[-1]["close"])
            body1 = abs(c1 - o1)
            body5 = abs(c5 - o5)

            # Middle 3 bars small and inside first bar's range
            first_high = float(w.iloc[0]["high"])
            first_low = float(w.iloc[0]["low"])
            inside_ok = True
            for k in range(1, 4):
                bk = w.iloc[k]
                if float(bk["high"]) > first_high or float(bk["low"]) < first_low:
                    inside_ok = False
                    break
                if abs(float(bk["close"]) - float(bk["open"])) > body1 * (float(middle_req.get("max_body_size_pct") or 50) / 100.0):
                    inside_ok = False
                    break
            if not inside_ok:
                continue

            # Rising methods: long white, 3 small, long white closing above first close
            is_bull = (c1 > o1) and (c5 > o5) and (body1 >= min_body_atr * atr) and (body5 >= min_last_body_atr * atr) and (c5 > c1)
            # Falling methods: long black, 3 small, long black closing below first close
            is_bear = (c1 < o1) and (c5 < o5) and (body1 >= min_body_atr * atr) and (body5 >= min_last_body_atr * atr) and (c5 < c1)

            if not (is_bull or is_bear):
                continue

            breakout_dir = "up" if is_bull else "down"
            breakout_idx = i
            breakout_price = float(df.iloc[breakout_idx]["close"])

            pattern_id = f"{symbol}_{self.key}_{i-4}_{i}"
            height_abs = first_high - first_low
            if height_abs <= 0:
                continue
            ref = (first_high + first_low) / 2.0
            if ref <= 0:
                continue
            height_pct = height_abs / ref * 100.0
            if hmin is not None and height_pct < float(hmin):
                continue
            if hmax is not None and height_pct > float(hmax):
                continue
            target = breakout_price + height_abs if breakout_dir == "up" else breakout_price - height_abs
            stop = first_low if breakout_dir == "up" else first_high

            out.append(
                {
                    "pattern_id": pattern_id,
                    "symbol": symbol,
                    "pattern_name": self.key,
                    "pattern_type": self.pattern_type,
                    "formation_start": str(df.iloc[i - 4]["date"].date()) if "date" in df.columns else str(i - 4),
                    "formation_end": str(df.iloc[i]["date"].date()) if "date" in df.columns else str(i),
                    "breakout_date": str(df.iloc[breakout_idx]["date"].date()) if "date" in df.columns else None,
                    "breakout_idx": int(breakout_idx),
                    "breakout_direction": breakout_dir,
                    "breakout_price": breakout_price,
                    "target_price": target,
                    "stop_loss_price": stop,
                    "confidence_score": 80,
                    "volume_confirmed": False,
                    "pattern_height_pct": round(height_pct, 2),
                    "pattern_width_bars": 5,
                    "touch_count": 5,
                    "pivot_indices": [int(i - 4), int(i - 3), int(i - 2), int(i - 1), int(i)],
                    "config_hash": self.config_hash,
                    "created_at": datetime.now().isoformat(),
                }
            )

        return out


class TripleBottomsTopsScanner(BaseDigitizedScanner):
    """
    `triple_bottoms_tops` is the only digitized spec that nests 2 sub-specs under
    detection_signature.{triple_bottom,triple_top}. We support both sequences here.
    """

    def __init__(self, key: str, spec: Dict[str, Any]):
        super().__init__(key, spec)
        ds = spec.get("detection_signature", {}) or {}
        bo = spec.get("breakout_confirmation", {}) or {}
        self.geom = spec.get("geometry_constraints", {}) or {}

        self._bottom: Optional[PivotSequenceScanner] = None
        self._top: Optional[PivotSequenceScanner] = None

        tb = ds.get("triple_bottom")
        if isinstance(tb, dict):
            bottom_spec = copy.deepcopy(spec)
            bottom_spec["detection_signature"] = tb
            bottom_spec["pattern_type"] = "reversal_bullish"
            if isinstance(bo.get("triple_bottom"), dict):
                bottom_spec["breakout_confirmation"] = bo.get("triple_bottom")
            self._bottom = PivotSequenceScanner("__triple_bottom", bottom_spec)

        tt = ds.get("triple_top")
        if isinstance(tt, dict):
            top_spec = copy.deepcopy(spec)
            top_spec["detection_signature"] = tt
            top_spec["pattern_type"] = "reversal_bearish"
            if isinstance(bo.get("triple_top"), dict):
                top_spec["breakout_confirmation"] = bo.get("triple_top")
            self._top = PivotSequenceScanner("__triple_top", top_spec)

        triple_ratio = self.geom.get("triple_price_ratio", {}) or {}
        depth = self.geom.get("peak_trough_depth_pct", {}) or {}
        slope = self.geom.get("slope_constraints", {}) or {}
        self.width_max_bars = min(int(self.geom.get("width_max_bars") or 270), 240)
        self.extreme_ratio_min = float(triple_ratio.get("min") or 0.96)
        self.extreme_ratio_max = float(triple_ratio.get("max") or 1.04)
        self.depth_min_pct = float(depth.get("min") or 5.0)
        self.depth_max_pct = float(depth.get("max") or 25.0)
        self.boundary_slope_max_deg = max(2.0, float(slope.get("boundary_max_slope_degrees") or 1.0) + 1.5)
        self.span_balance_max_ratio = 2.75
        self.pullback_similarity_max_ratio = 1.18

    def _family_metrics(self, df: pd.DataFrame, pivots: Sequence[Any], *, variant_tag: str) -> Optional[Dict[str, Any]]:
        if len(pivots) < 5:
            return None
        try:
            i0, i1, i2, i3, i4 = [int(x) for x in pivots[:5]]
        except Exception:
            return None
        if not (0 <= i0 < i1 < i2 < i3 < i4 < len(df)):
            return None

        width_bars = i4 - i0 + 1
        left_span = i2 - i0
        right_span = i4 - i2
        span_balance_ratio = max(left_span, right_span) / max(1, min(left_span, right_span))

        if variant_tag == "bottom":
            extremes = [float(df.iloc[i0]["low"]), float(df.iloc[i2]["low"]), float(df.iloc[i4]["low"])]
            pullbacks = [float(df.iloc[i1]["high"]), float(df.iloc[i3]["high"])]
        else:
            extremes = [float(df.iloc[i0]["high"]), float(df.iloc[i2]["high"]), float(df.iloc[i4]["high"])]
            pullbacks = [float(df.iloc[i1]["low"]), float(df.iloc[i3]["low"])]

        if min(abs(x) for x in extremes + pullbacks) <= 0:
            return None

        extreme_ratio = max(extremes) / min(extremes)
        pullback_ratio = max(pullbacks) / min(pullbacks)
        avg_extreme = float(np.mean(extremes))
        avg_pullback = float(np.mean(pullbacks))
        if variant_tag == "bottom":
            depth_pct = (avg_pullback - avg_extreme) / avg_pullback * 100.0
            boundary_slope_deg = abs(_slope_degrees(i0, extremes[0], i4, extremes[2]))
        else:
            depth_pct = (avg_extreme - avg_pullback) / avg_extreme * 100.0
            boundary_slope_deg = abs(_slope_degrees(i0, extremes[0], i4, extremes[2]))

        return {
            "variant_tag": variant_tag,
            "width_bars": int(width_bars),
            "left_span_bars": int(left_span),
            "right_span_bars": int(right_span),
            "span_balance_ratio": float(span_balance_ratio),
            "extreme_ratio": float(extreme_ratio),
            "extreme_diff_pct": float(_pct_diff(extremes[0], extremes[2])),
            "pullback_ratio": float(pullback_ratio),
            "pullback_diff_pct": float(_pct_diff(pullbacks[0], pullbacks[1])),
            "depth_pct": float(depth_pct),
            "boundary_slope_deg": float(boundary_slope_deg),
        }

    def _family_metrics_ok(self, metrics: Dict[str, Any]) -> bool:
        width_bars = int(metrics.get("width_bars") or 0)
        span_balance_ratio = float(metrics.get("span_balance_ratio") or 999.0)
        extreme_ratio = float(metrics.get("extreme_ratio") or 0.0)
        pullback_ratio = float(metrics.get("pullback_ratio") or 999.0)
        depth_pct = float(metrics.get("depth_pct") or 0.0)
        boundary_slope_deg = float(metrics.get("boundary_slope_deg") or 999.0)

        if width_bars <= 0 or width_bars > self.width_max_bars:
            return False
        if span_balance_ratio > self.span_balance_max_ratio:
            return False
        if extreme_ratio < self.extreme_ratio_min or extreme_ratio > self.extreme_ratio_max:
            return False
        if pullback_ratio > self.pullback_similarity_max_ratio:
            return False
        if depth_pct < self.depth_min_pct or depth_pct > self.depth_max_pct:
            return False
        if boundary_slope_deg > self.boundary_slope_max_deg:
            return False
        return True

    def _resolve_variant(self, metrics: Dict[str, Any], *, breakout_direction: Optional[str]) -> Optional[Dict[str, Any]]:
        tag = str(metrics.get("variant_tag") or "")
        bo = str(breakout_direction or "")
        evidence = {
            "extreme_diff_pct": round(float(metrics.get("extreme_diff_pct") or 0.0), 2),
            "pullback_diff_pct": round(float(metrics.get("pullback_diff_pct") or 0.0), 2),
            "depth_pct": round(float(metrics.get("depth_pct") or 0.0), 2),
            "boundary_slope_deg": round(float(metrics.get("boundary_slope_deg") or 0.0), 2),
        }
        if tag == "bottom" and bo == "up":
            return {
                "variant_code": "triple_bottom",
                "variant_confidence": 82,
                "pattern_type": "reversal_bullish",
                "evidence": evidence,
            }
        if tag == "top" and bo == "down":
            return {
                "variant_code": "triple_top",
                "variant_confidence": 82,
                "pattern_type": "reversal_bearish",
                "evidence": evidence,
            }
        return None

    def _score_family_confidence(self, base_confidence: Any, metrics: Dict[str, Any], variant_result: Dict[str, Any]) -> int:
        try:
            confidence = int(base_confidence)
        except Exception:
            confidence = 70
        if float(metrics.get("extreme_diff_pct") or 999.0) <= 2.0:
            confidence += 4
        if float(metrics.get("pullback_diff_pct") or 999.0) <= 4.0:
            confidence += 3
        if float(metrics.get("boundary_slope_deg") or 999.0) <= 1.25:
            confidence += 3
        return max(0, min(100, confidence))

    def scan(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        tagged_rows: List[Tuple[Dict[str, Any], str]] = []
        if self._bottom is not None:
            tagged_rows.extend(
                (dict(r), "bottom")
                for r in self._bottom.scan(
                    symbol=symbol,
                    df=df,
                    pivots_filtered=pivots_filtered,
                    pivots_raw=pivots_raw,
                )
            )
        if self._top is not None:
            tagged_rows.extend(
                (dict(r), "top")
                for r in self._top.scan(
                    symbol=symbol,
                    df=df,
                    pivots_filtered=pivots_filtered,
                    pivots_raw=pivots_raw,
                )
            )

        for row, tag in tagged_rows:
            if row.get("breakout_idx") is None or _safe_float(row.get("breakout_price")) is None:
                continue
            metrics = self._family_metrics(df, row.get("pivot_indices") or [], variant_tag=tag)
            if not metrics or not self._family_metrics_ok(metrics):
                continue
            variant = self._resolve_variant(metrics, breakout_direction=row.get("breakout_direction"))
            if not variant:
                continue
            row["pattern_name"] = self.key
            row["base_pattern_name"] = self.key
            row["variant_code"] = variant.get("variant_code")
            row["variant_confidence"] = int(variant.get("variant_confidence") or 0)
            row["variant_evidence_json"] = json.dumps(variant.get("evidence") or {}, sort_keys=True, ensure_ascii=False)
            row["family_metrics_json"] = json.dumps(metrics, sort_keys=True, ensure_ascii=False)
            row["pattern_type"] = variant.get("pattern_type") or row.get("pattern_type") or self.pattern_type
            row["confidence_score"] = self._score_family_confidence(row.get("confidence_score"), metrics, variant)
            out.append(row)
        return out


class PipeBottomScanner(BaseDigitizedScanner):
    """
    Pipe bottoms have pivot_sequence ["L","L"] so the generic pivot-sequence implementation
    (which expects both highs and lows) cannot compute height/boundaries. This scanner:
    - finds 2 near-equal lows separated by a few bars
    - validates "vertical-ish" legs into/out of each low (pragmatic)
    - confirms breakout above the interim high after the 2nd low
    """

    def __init__(self, key: str, spec: Dict[str, Any]):
        super().__init__(key, spec)
        self.ds = spec.get("detection_signature", {}) or {}
        self.geom = spec.get("geometry_constraints", {}) or {}
        self.prior = spec.get("prior_trend_requirements", {}) or {}
        self.bo = spec.get("breakout_confirmation", {}) or {}

        self.width_min = int(self.geom.get("width_min_bars") or 0)
        self.width_max = int(self.geom.get("width_max_bars") or 10_000)

        sep = self.geom.get("parallel_separation_bars", {}) or {}
        self.sep_min = int(sep.get("min") or 0)
        self.sep_max = int(sep.get("max") or self.width_max)

        sim = self.geom.get("pipe_bottom_similarity_pct", {}) or {}
        self.sim_min = float(sim.get("min") or 0.97)
        self.sim_max = float(sim.get("max") or 1.03)

        vdr = self.geom.get("vertical_drop_ratio", {}) or {}
        self.drop_min = float(vdr.get("min") or 0.0)
        self.drop_max = float(vdr.get("max") or 1e9)

        slope = self.geom.get("slope_constraints", {}) or {}
        self.angle_min = float(slope.get("pipe_vertical_angle_min_degrees") or 0.0)
        self.angle_max = float(slope.get("pipe_vertical_angle_max_degrees") or 90.0)

        self.height_min = float(self.geom.get("height_ratio_min") or 0.0)
        self.height_max = float(self.geom.get("height_ratio_max") or 1e9)

        self.breakout_thr = float(self.bo.get("breakout_threshold_pct") or 1.0) / 100.0
        self.confirm_bars = int(self.bo.get("confirmation_bars") or 1)
        self.close_beyond = bool(self.bo.get("close_beyond_required") if self.bo.get("close_beyond_required") is not None else True)
        self.vol_required = bool(self.bo.get("volume_required") or False)
        self.vol_mult_min = float(self.bo.get("volume_multiplier_min") or 1.3)
        self.breakout_lag_max_bars = min(int(self.geom.get("breakout_lag_max_bars") or 12), 15)
        self.leg_balance_max_ratio = 2.25
        self.angle_gap_max_deg = 28.0

        # Pragmatic local windows for "vertical" leg checks
        self._leg_window_pre = 3
        self._leg_window_post = 3

    def _check_prior_trend(self, df: pd.DataFrame, pattern_start_idx: int) -> bool:
        direction = str(self.prior.get("direction") or "any").lower()
        min_bars = int(self.prior.get("min_period_bars") or 0)
        min_change = float(self.prior.get("min_change_pct") or 0.0)
        if min_bars <= 0 or min_change <= 0:
            return True
        if pattern_start_idx < min_bars:
            return False

        start = pattern_start_idx - min_bars
        end = pattern_start_idx
        p0 = _safe_float(df.iloc[start].get("close"))
        p1 = _safe_float(df.iloc[end].get("close"))
        if p0 is None or p1 is None or p0 <= 0:
            return False
        change_pct = (p1 - p0) / p0 * 100.0

        if direction == "down":
            return change_pct <= -min_change
        if direction == "up":
            return change_pct >= min_change
        return abs(change_pct) >= min_change

    def _leg_ok(self, df: pd.DataFrame, low_idx: int, low_price: float) -> bool:
        if low_idx <= 0 or low_idx >= len(df):
            return False

        pre0 = max(0, low_idx - self._leg_window_pre)
        pre = df.iloc[pre0:low_idx]
        if len(pre) == 0:
            return False
        pre_high = float(pre["high"].max())
        if not np.isfinite(pre_high) or pre_high <= 0:
            return False
        drop_pct = (pre_high - low_price) / pre_high * 100.0
        if not (self.drop_min <= drop_pct <= self.drop_max):
            return False

        # Angle proxy (steeper = closer to vertical). Compute indices in *positional* space.
        try:
            pre_high_vals = pre["high"].to_numpy(dtype=float, copy=False)
            if pre_high_vals.size == 0 or not np.isfinite(pre_high_vals).any():
                return False
            pre_high_rel = int(np.nanargmax(pre_high_vals))
            pre_high_idx = int(pre0 + pre_high_rel)
        except Exception:
            return False
        angle = abs(_slope_degrees(pre_high_idx, pre_high, low_idx, low_price))
        if not (self.angle_min <= angle <= self.angle_max):
            return False

        post1 = min(len(df), low_idx + 1 + self._leg_window_post)
        post = df.iloc[low_idx + 1 : post1]
        if len(post) == 0:
            return False
        post_high = float(post["high"].max())
        if low_price <= 0:
            return False
        rise_pct = (post_high - low_price) / low_price * 100.0
        if rise_pct < self.drop_min:
            return False

        return True

    def _find_breakout(
        self,
        df: pd.DataFrame,
        *,
        start_idx: int,
        level: float,
        direction: str = "up",
        max_lookahead: int = 30,
    ) -> Tuple[Optional[int], Optional[float], bool]:
        thr = level * (1.0 + self.breakout_thr) if direction == "up" else level * (1.0 - self.breakout_thr)

        for i in range(start_idx, min(len(df), start_idx + max_lookahead)):
            close = _safe_float(df.iloc[i].get("close"))
            if close is None:
                continue
            ok = close > thr if direction == "up" else close < thr
            if not ok:
                continue

            # Confirmation bars: require consecutive closes beyond threshold.
            if self.confirm_bars > 1:
                j_end = min(len(df), i + self.confirm_bars)
                all_ok = True
                for j in range(i, j_end):
                    c = _safe_float(df.iloc[j].get("close"))
                    if c is None:
                        all_ok = False
                        break
                    if direction == "up" and not (c > thr):
                        all_ok = False
                        break
                    if direction == "down" and not (c < thr):
                        all_ok = False
                        break
                if not all_ok:
                    continue

            vr = df.iloc[i].get("volume_ratio", np.nan)
            vol_ok = bool(pd.notna(vr) and np.isfinite(vr) and float(vr) >= self.vol_mult_min)
            if self.vol_required and not vol_ok:
                continue
            return i, close, vol_ok

        return None, None, False

    def scan(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> List[Dict[str, Any]]:
        def _leg_snapshot(low_idx: int, low_price: float) -> Optional[Dict[str, float]]:
            pre0 = max(0, low_idx - self._leg_window_pre)
            pre = df.iloc[pre0:low_idx]
            post1 = min(len(df), low_idx + 1 + self._leg_window_post)
            post = df.iloc[low_idx + 1 : post1]
            if len(pre) == 0 or len(post) == 0:
                return None
            pre_high = _safe_float(pre["high"].max())
            post_high = _safe_float(post["high"].max())
            if pre_high is None or post_high is None or pre_high <= 0 or low_price <= 0:
                return None
            try:
                pre_high_vals = pre["high"].to_numpy(dtype=float, copy=False)
                pre_high_rel = int(np.nanargmax(pre_high_vals))
                pre_high_idx = int(pre0 + pre_high_rel)
            except Exception:
                return None
            drop_pct = (pre_high - low_price) / pre_high * 100.0
            rebound_pct = (post_high - low_price) / low_price * 100.0
            angle_deg = abs(_slope_degrees(pre_high_idx, pre_high, low_idx, low_price))
            return {
                "drop_pct": float(drop_pct),
                "rebound_pct": float(rebound_pct),
                "angle_deg": float(angle_deg),
            }

        pivots = pivots_raw or pivots_filtered
        lows = [p for p in pivots if p.type == PivotType.LOW]
        if len(lows) < 2:
            return []

        out: List[Dict[str, Any]] = []

        for i in range(len(lows) - 1):
            l1 = lows[i]
            for j in range(i + 1, len(lows)):
                l2 = lows[j]
                sep = int(l2.idx) - int(l1.idx)
                width_bars = sep + 1
                if width_bars < self.width_min:
                    continue
                if width_bars > self.width_max:
                    break
                if sep < self.sep_min or sep > self.sep_max:
                    continue

                if l1.price <= 0 or l2.price <= 0:
                    continue
                ratio = float(l2.price) / float(l1.price)
                if not (self.sim_min <= ratio <= self.sim_max):
                    continue

                if not self._check_prior_trend(df, int(l1.idx)):
                    continue

                if not self._leg_ok(df, int(l1.idx), float(l1.price)):
                    continue
                if not self._leg_ok(df, int(l2.idx), float(l2.price)):
                    continue
                left_leg = _leg_snapshot(int(l1.idx), float(l1.price))
                right_leg = _leg_snapshot(int(l2.idx), float(l2.price))
                if left_leg is None or right_leg is None:
                    continue

                # Interim high between the two lows acts as breakout level.
                interim = df.iloc[int(l1.idx) : int(l2.idx) + 1]
                if len(interim) == 0:
                    continue
                interim_high = _safe_float(interim["high"].max())
                if interim_high is None or interim_high <= 0:
                    continue
                try:
                    interim_high_vals = interim["high"].to_numpy(dtype=float, copy=False)
                    if interim_high_vals.size == 0 or not np.isfinite(interim_high_vals).any():
                        continue
                    interim_high_rel = int(np.nanargmax(interim_high_vals))
                    interim_high_idx = int(int(l1.idx) + interim_high_rel)
                except Exception:
                    continue

                avg_low = (float(l1.price) + float(l2.price)) / 2.0
                height_abs = interim_high - avg_low
                if height_abs <= 0:
                    continue

                height_drop_pct = height_abs / interim_high * 100.0
                if not (self.height_min <= height_drop_pct <= self.height_max):
                    continue

                breakout_idx, breakout_price, vol_ok = self._find_breakout(
                    df,
                    start_idx=int(l2.idx) + 1,
                    level=float(interim_high),
                    direction="up",
                    max_lookahead=30,
                )
                if breakout_idx is None or breakout_price is None:
                    continue
                breakout_lag_bars = int(breakout_idx) - int(l2.idx)
                if breakout_lag_bars > self.breakout_lag_max_bars:
                    continue
                drop_min = min(float(left_leg["drop_pct"]), float(right_leg["drop_pct"]))
                drop_max = max(float(left_leg["drop_pct"]), float(right_leg["drop_pct"]))
                rebound_min = min(float(left_leg["rebound_pct"]), float(right_leg["rebound_pct"]))
                rebound_max = max(float(left_leg["rebound_pct"]), float(right_leg["rebound_pct"]))
                if drop_min <= 0 or rebound_min <= 0:
                    continue
                drop_balance = drop_max / drop_min
                rebound_balance = rebound_max / rebound_min
                if drop_balance > self.leg_balance_max_ratio or rebound_balance > self.leg_balance_max_ratio:
                    continue
                if abs(float(left_leg["angle_deg"]) - float(right_leg["angle_deg"])) > self.angle_gap_max_deg:
                    continue

                target = breakout_price + height_abs
                stop = avg_low

                confidence = 75
                if vol_ok:
                    confidence += 10
                if drop_balance <= 1.35:
                    confidence += 4
                if rebound_balance <= 1.35:
                    confidence += 3
                confidence = int(min(100, confidence))
                family_metrics = {
                    "width_bars": int(width_bars),
                    "separation_bars": int(sep),
                    "similarity_ratio": float(ratio),
                    "height_drop_pct": float(height_drop_pct),
                    "left_drop_pct": float(left_leg["drop_pct"]),
                    "right_drop_pct": float(right_leg["drop_pct"]),
                    "left_rebound_pct": float(left_leg["rebound_pct"]),
                    "right_rebound_pct": float(right_leg["rebound_pct"]),
                    "left_angle_deg": float(left_leg["angle_deg"]),
                    "right_angle_deg": float(right_leg["angle_deg"]),
                    "breakout_lag_bars": int(breakout_lag_bars),
                    "drop_balance_ratio": float(drop_balance),
                    "rebound_balance_ratio": float(rebound_balance),
                }

                pattern_id = f"{symbol}_{self.key}_{int(l1.idx)}_{int(l2.idx)}"

                out.append(
                    {
                        "pattern_id": pattern_id,
                        "symbol": symbol,
                        "pattern_name": self.key,
                        "pattern_type": self.pattern_type,
                        "formation_start": str(df.iloc[int(l1.idx)]["date"].date()) if "date" in df.columns else str(int(l1.idx)),
                        "formation_end": str(df.iloc[int(l2.idx)]["date"].date()) if "date" in df.columns else str(int(l2.idx)),
                        "breakout_date": str(df.iloc[int(breakout_idx)]["date"].date()) if "date" in df.columns else None,
                        "breakout_idx": int(breakout_idx),
                        "breakout_direction": "up",
                        "breakout_price": float(breakout_price),
                        "target_price": float(target),
                        "stop_loss_price": float(stop),
                        "confidence_score": confidence,
                        "volume_confirmed": bool(vol_ok),
                        "base_pattern_name": self.key,
                        "variant_code": "pipe_bottom",
                        "variant_confidence": confidence,
                        "variant_evidence_json": json.dumps(
                            {
                                "similarity_ratio": round(float(ratio), 4),
                                "height_drop_pct": round(float(height_drop_pct), 2),
                                "breakout_lag_bars": int(breakout_lag_bars),
                            },
                            sort_keys=True,
                            ensure_ascii=False,
                        ),
                        "family_metrics_json": json.dumps(family_metrics, sort_keys=True, ensure_ascii=False),
                        "pattern_height_pct": round(height_drop_pct, 2),
                        "pattern_width_bars": int(width_bars),
                        "touch_count": 2,
                        "pivot_indices": [int(l1.idx), int(interim_high_idx), int(l2.idx)],
                        "config_hash": self.config_hash,
                        "created_at": datetime.now().isoformat(),
                    }
                )

        return out


class PipeTopScanner(BaseDigitizedScanner):
    """
    Pipe tops are the bearish mirror of pipe bottoms. This scanner:
    - finds 2 near-equal highs separated by a few bars
    - validates "vertical-ish" legs into/out of each high (pragmatic)
    - confirms breakout below the interim low after the 2nd high
    """

    def __init__(self, key: str, spec: Dict[str, Any]):
        super().__init__(key, spec)
        self.ds = spec.get("detection_signature", {}) or {}
        self.geom = spec.get("geometry_constraints", {}) or {}
        self.prior = spec.get("prior_trend_requirements", {}) or {}
        self.bo = spec.get("breakout_confirmation", {}) or {}

        self.width_min = int(self.geom.get("width_min_bars") or 0)
        self.width_max = int(self.geom.get("width_max_bars") or 10_000)

        sep = self.geom.get("parallel_separation_bars", {}) or {}
        self.sep_min = int(sep.get("min") or 0)
        self.sep_max = int(sep.get("max") or self.width_max)

        sim = self.geom.get("pipe_bottom_similarity_pct", {}) or {}
        self.sim_min = float(sim.get("min") or 0.97)
        self.sim_max = float(sim.get("max") or 1.03)

        vdr = self.geom.get("vertical_drop_ratio", {}) or {}
        self.rise_min = float(vdr.get("min") or 0.0)
        self.rise_max = float(vdr.get("max") or 1e9)

        slope = self.geom.get("slope_constraints", {}) or {}
        self.angle_min = float(slope.get("pipe_vertical_angle_min_degrees") or 0.0)
        self.angle_max = float(slope.get("pipe_vertical_angle_max_degrees") or 90.0)

        self.height_min = float(self.geom.get("height_ratio_min") or 0.0)
        self.height_max = float(self.geom.get("height_ratio_max") or 1e9)

        self.breakout_thr = float(self.bo.get("breakout_threshold_pct") or 1.0) / 100.0
        self.confirm_bars = int(self.bo.get("confirmation_bars") or 1)
        self.vol_required = bool(self.bo.get("volume_required") or False)
        self.vol_mult_min = float(self.bo.get("volume_multiplier_min") or 1.3)
        self.breakout_lag_max_bars = min(int(self.geom.get("breakout_lag_max_bars") or 12), 15)
        self.leg_balance_max_ratio = 2.25
        self.angle_gap_max_deg = 28.0

        self._leg_window_pre = 3
        self._leg_window_post = 3

    def _check_prior_trend(self, df: pd.DataFrame, pattern_start_idx: int) -> bool:
        direction = str(self.prior.get("direction") or "any").lower()
        min_bars = int(self.prior.get("min_period_bars") or 0)
        min_change = float(self.prior.get("min_change_pct") or 0.0)
        if min_bars <= 0 or min_change <= 0:
            return True
        if pattern_start_idx < min_bars:
            return False

        start = pattern_start_idx - min_bars
        end = pattern_start_idx
        p0 = _safe_float(df.iloc[start].get("close"))
        p1 = _safe_float(df.iloc[end].get("close"))
        if p0 is None or p1 is None or p0 <= 0:
            return False
        change_pct = (p1 - p0) / p0 * 100.0

        if direction == "up":
            return change_pct >= min_change
        if direction == "down":
            return change_pct <= -min_change
        return abs(change_pct) >= min_change

    def _leg_ok(self, df: pd.DataFrame, high_idx: int, high_price: float) -> bool:
        if high_idx <= 0 or high_idx >= len(df):
            return False
        if high_price <= 0:
            return False

        pre0 = max(0, high_idx - self._leg_window_pre)
        pre = df.iloc[pre0:high_idx]
        if len(pre) == 0:
            return False
        pre_low = _safe_float(pre["low"].min())
        if pre_low is None or pre_low <= 0:
            return False
        rise_pct = (high_price - pre_low) / pre_low * 100.0
        if not (self.rise_min <= rise_pct <= self.rise_max):
            return False

        try:
            pre_low_vals = pre["low"].to_numpy(dtype=float, copy=False)
            if pre_low_vals.size == 0 or not np.isfinite(pre_low_vals).any():
                return False
            pre_low_rel = int(np.nanargmin(pre_low_vals))
            pre_low_idx = int(pre0 + pre_low_rel)
        except Exception:
            return False
        angle = abs(_slope_degrees(pre_low_idx, float(pre_low), high_idx, float(high_price)))
        if not (self.angle_min <= angle <= self.angle_max):
            return False

        post1 = min(len(df), high_idx + 1 + self._leg_window_post)
        post = df.iloc[high_idx + 1 : post1]
        if len(post) == 0:
            return False
        post_low = _safe_float(post["low"].min())
        if post_low is None or post_low <= 0:
            return False
        drop_pct = (high_price - post_low) / high_price * 100.0
        if drop_pct < self.rise_min:
            return False
        return True

    def _find_breakout(
        self,
        df: pd.DataFrame,
        *,
        start_idx: int,
        level: float,
        direction: str = "down",
        max_lookahead: int = 30,
    ) -> Tuple[Optional[int], Optional[float], bool]:
        thr = level * (1.0 - self.breakout_thr) if direction == "down" else level * (1.0 + self.breakout_thr)

        for i in range(start_idx, min(len(df), start_idx + max_lookahead)):
            close = _safe_float(df.iloc[i].get("close"))
            if close is None:
                continue
            ok = close < thr if direction == "down" else close > thr
            if not ok:
                continue

            if self.confirm_bars > 1:
                j_end = min(len(df), i + self.confirm_bars)
                all_ok = True
                for j in range(i, j_end):
                    c = _safe_float(df.iloc[j].get("close"))
                    if c is None:
                        all_ok = False
                        break
                    if direction == "down" and not (c < thr):
                        all_ok = False
                        break
                    if direction == "up" and not (c > thr):
                        all_ok = False
                        break
                if not all_ok:
                    continue

            vr = df.iloc[i].get("volume_ratio", np.nan)
            vol_ok = bool(pd.notna(vr) and np.isfinite(vr) and float(vr) >= self.vol_mult_min)
            if self.vol_required and not vol_ok:
                continue
            return i, close, vol_ok

        return None, None, False

    def scan(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> List[Dict[str, Any]]:
        def _leg_snapshot(high_idx: int, high_price: float) -> Optional[Dict[str, float]]:
            pre0 = max(0, high_idx - self._leg_window_pre)
            pre = df.iloc[pre0:high_idx]
            post1 = min(len(df), high_idx + 1 + self._leg_window_post)
            post = df.iloc[high_idx + 1 : post1]
            if len(pre) == 0 or len(post) == 0:
                return None
            pre_low = _safe_float(pre["low"].min())
            post_low = _safe_float(post["low"].min())
            if pre_low is None or post_low is None or pre_low <= 0 or post_low <= 0 or high_price <= 0:
                return None
            try:
                pre_low_vals = pre["low"].to_numpy(dtype=float, copy=False)
                pre_low_rel = int(np.nanargmin(pre_low_vals))
                pre_low_idx = int(pre0 + pre_low_rel)
            except Exception:
                return None
            rise_pct = (high_price - pre_low) / pre_low * 100.0
            drop_pct = (high_price - post_low) / high_price * 100.0
            angle_deg = abs(_slope_degrees(pre_low_idx, pre_low, high_idx, high_price))
            return {
                "rise_pct": float(rise_pct),
                "drop_pct": float(drop_pct),
                "angle_deg": float(angle_deg),
            }

        pivots = pivots_raw or pivots_filtered
        highs = [p for p in pivots if p.type == PivotType.HIGH]
        if len(highs) < 2:
            return []

        out: List[Dict[str, Any]] = []
        for i in range(len(highs) - 1):
            h1 = highs[i]
            for j in range(i + 1, len(highs)):
                h2 = highs[j]
                sep = int(h2.idx) - int(h1.idx)
                width_bars = sep + 1
                if width_bars < self.width_min:
                    continue
                if width_bars > self.width_max:
                    break
                if sep < self.sep_min or sep > self.sep_max:
                    continue

                if h1.price <= 0 or h2.price <= 0:
                    continue
                ratio = float(h2.price) / float(h1.price)
                if not (self.sim_min <= ratio <= self.sim_max):
                    continue

                if not self._check_prior_trend(df, int(h1.idx)):
                    continue

                if not self._leg_ok(df, int(h1.idx), float(h1.price)):
                    continue
                if not self._leg_ok(df, int(h2.idx), float(h2.price)):
                    continue
                left_leg = _leg_snapshot(int(h1.idx), float(h1.price))
                right_leg = _leg_snapshot(int(h2.idx), float(h2.price))
                if left_leg is None or right_leg is None:
                    continue

                interim = df.iloc[int(h1.idx) : int(h2.idx) + 1]
                if len(interim) == 0:
                    continue
                interim_low = _safe_float(interim["low"].min())
                if interim_low is None or interim_low <= 0:
                    continue
                try:
                    interim_low_vals = interim["low"].to_numpy(dtype=float, copy=False)
                    if interim_low_vals.size == 0 or not np.isfinite(interim_low_vals).any():
                        continue
                    interim_low_rel = int(np.nanargmin(interim_low_vals))
                    interim_low_idx = int(int(h1.idx) + interim_low_rel)
                except Exception:
                    continue

                avg_high = (float(h1.price) + float(h2.price)) / 2.0
                height_abs = avg_high - float(interim_low)
                if height_abs <= 0:
                    continue
                mid = (avg_high + float(interim_low)) / 2.0
                height_pct = (height_abs / mid * 100.0) if mid > 0 else None
                if height_pct is None or not np.isfinite(height_pct) or height_pct <= 0:
                    continue
                if not (self.height_min <= float(height_pct) <= self.height_max):
                    continue

                breakout_idx, breakout_price, vol_ok = self._find_breakout(
                    df,
                    start_idx=int(h2.idx) + 1,
                    level=float(interim_low),
                    direction="down",
                    max_lookahead=30,
                )
                if breakout_idx is None or breakout_price is None:
                    continue
                breakout_lag_bars = int(breakout_idx) - int(h2.idx)
                if breakout_lag_bars > self.breakout_lag_max_bars:
                    continue
                rise_min = min(float(left_leg["rise_pct"]), float(right_leg["rise_pct"]))
                rise_max = max(float(left_leg["rise_pct"]), float(right_leg["rise_pct"]))
                drop_min = min(float(left_leg["drop_pct"]), float(right_leg["drop_pct"]))
                drop_max = max(float(left_leg["drop_pct"]), float(right_leg["drop_pct"]))
                if rise_min <= 0 or drop_min <= 0:
                    continue
                rise_balance = rise_max / rise_min
                drop_balance = drop_max / drop_min
                if rise_balance > self.leg_balance_max_ratio or drop_balance > self.leg_balance_max_ratio:
                    continue
                if abs(float(left_leg["angle_deg"]) - float(right_leg["angle_deg"])) > self.angle_gap_max_deg:
                    continue

                target = float(breakout_price) - float(height_abs)
                stop = float(avg_high)

                confidence = 75
                if vol_ok:
                    confidence += 10
                if rise_balance <= 1.35:
                    confidence += 4
                if drop_balance <= 1.35:
                    confidence += 3
                confidence = int(min(100, confidence))
                family_metrics = {
                    "width_bars": int(width_bars),
                    "separation_bars": int(sep),
                    "similarity_ratio": float(ratio),
                    "height_rise_pct": float(height_pct),
                    "left_rise_pct": float(left_leg["rise_pct"]),
                    "right_rise_pct": float(right_leg["rise_pct"]),
                    "left_drop_pct": float(left_leg["drop_pct"]),
                    "right_drop_pct": float(right_leg["drop_pct"]),
                    "left_angle_deg": float(left_leg["angle_deg"]),
                    "right_angle_deg": float(right_leg["angle_deg"]),
                    "breakout_lag_bars": int(breakout_lag_bars),
                    "rise_balance_ratio": float(rise_balance),
                    "drop_balance_ratio": float(drop_balance),
                }

                pattern_id = f"{symbol}_{self.key}_{int(h1.idx)}_{int(h2.idx)}"
                out.append(
                    {
                        "pattern_id": pattern_id,
                        "symbol": symbol,
                        "pattern_name": self.key,
                        "pattern_type": self.pattern_type,
                        "formation_start": str(df.iloc[int(h1.idx)]["date"].date()) if "date" in df.columns else str(int(h1.idx)),
                        "formation_end": str(df.iloc[int(h2.idx)]["date"].date()) if "date" in df.columns else str(int(h2.idx)),
                        "breakout_date": str(df.iloc[int(breakout_idx)]["date"].date()) if "date" in df.columns else None,
                        "breakout_idx": int(breakout_idx),
                        "breakout_direction": "down",
                        "breakout_price": float(breakout_price),
                        "target_price": float(target),
                        "stop_loss_price": float(stop),
                        "confidence_score": confidence,
                        "volume_confirmed": bool(vol_ok),
                        "base_pattern_name": self.key,
                        "variant_code": "pipe_top",
                        "variant_confidence": confidence,
                        "variant_evidence_json": json.dumps(
                            {
                                "similarity_ratio": round(float(ratio), 4),
                                "height_rise_pct": round(float(height_pct), 2),
                                "breakout_lag_bars": int(breakout_lag_bars),
                            },
                            sort_keys=True,
                            ensure_ascii=False,
                        ),
                        "family_metrics_json": json.dumps(family_metrics, sort_keys=True, ensure_ascii=False),
                        "pattern_height_pct": round(float(height_pct), 2),
                        "pattern_width_bars": int(width_bars),
                        "touch_count": 2,
                        "pivot_indices": [int(h1.idx), int(interim_low_idx), int(h2.idx)],
                        "config_hash": self.config_hash,
                        "created_at": datetime.now().isoformat(),
                    }
                )

        return out


class FlagFamilyScanner(BaseDigitizedScanner):
    """
    Dedicated family scanner for flags.

    The generic pivot scanner ignores the `flagpole` token from the digitized spec,
    so the old implementation mostly detected short channels with breakouts. This
    family scanner reinstates the core semantics:
    - a strong prior pole
    - a short parallel consolidation channel
    - breakout in the same direction as the pole
    """

    def __init__(self, key: str, spec: Dict[str, Any]):
        super().__init__(key, spec)
        self.geom = spec.get("geometry_constraints", {}) or {}
        self.prior = spec.get("prior_trend_requirements", {}) or {}
        self.bo = spec.get("breakout_confirmation", {}) or {}

        self.width_min_bars = int(self.geom.get("width_min_bars") or 5)
        self.width_max_bars = min(int(self.geom.get("width_max_bars") or 25), 26)
        slope_cfg = self.geom.get("slope_constraints", {}) or {}
        bull_slope = slope_cfg.get("bull_flag", {}) or {}
        bear_slope = slope_cfg.get("bear_flag", {}) or {}
        self.parallel_tol_deg = max(
            float(bull_slope.get("parallel_tolerance_degrees") or 3.0),
            float(bear_slope.get("parallel_tolerance_degrees") or 3.0),
        )
        self.bull_avg_slope_min = -10.0
        self.bull_avg_slope_max = 3.0
        self.bear_avg_slope_min = -3.0
        self.bear_avg_slope_max = 10.0
        self.height_min_pct = float(self.geom.get("height_ratio_min") or 3.0)
        self.height_max_pct = float(self.geom.get("height_ratio_max") or 15.0)
        self.pole_lookback_bars = 40
        self.pole_min_change_pct = max(8.0, float(self.prior.get("min_change_pct") or 10.0))
        self.pole_min_slope_deg = max(8.0, float(self.prior.get("trend_slope_min_degrees") or 30.0) * 0.45)
        self.flag_to_pole_max_pct = 55.0
        self.breakout_search_bars = 12
        self.breakout_thr = float(self.bo.get("breakout_threshold_pct") or 0.75) / 100.0
        self.confirm_bars = int(self.bo.get("confirmation_bars") or 1)
        self.vol_required = bool(self.bo.get("volume_required") or False)
        self.vol_mult_min = float(self.bo.get("volume_multiplier_min") or 1.2)

    def _prior_pole(self, df: pd.DataFrame, *, start_idx: int, direction: str, anchor_price: float) -> Optional[Dict[str, float]]:
        lb = max(0, start_idx - self.pole_lookback_bars)
        window = df.iloc[lb : start_idx + 1]
        if len(window) < 4 or anchor_price <= 0:
            return None

        if direction == "up":
            pole_price = _safe_float(window["low"].min())
            if pole_price is None or pole_price <= 0:
                return None
            try:
                vals = window["low"].to_numpy(dtype=float, copy=False)
                pole_rel = int(np.nanargmin(vals))
            except Exception:
                return None
            pole_idx = int(lb + pole_rel)
            move_pct = (anchor_price - pole_price) / pole_price * 100.0
            slope_deg = _slope_degrees(pole_idx, pole_price, start_idx, anchor_price)
        else:
            pole_price = _safe_float(window["high"].max())
            if pole_price is None or pole_price <= 0:
                return None
            try:
                vals = window["high"].to_numpy(dtype=float, copy=False)
                pole_rel = int(np.nanargmax(vals))
            except Exception:
                return None
            pole_idx = int(lb + pole_rel)
            move_pct = (pole_price - anchor_price) / pole_price * 100.0
            slope_deg = abs(_slope_degrees(pole_idx, pole_price, start_idx, anchor_price))

        pole_bars = start_idx - pole_idx + 1
        if pole_bars <= 1 or pole_bars > self.pole_lookback_bars:
            return None
        if move_pct < self.pole_min_change_pct or slope_deg < self.pole_min_slope_deg:
            return None
        return {
            "pole_idx": float(pole_idx),
            "pole_price": float(pole_price),
            "pole_move_pct": float(move_pct),
            "pole_slope_deg": float(slope_deg),
            "pole_bars": float(pole_bars),
        }

    def _breakout_ok(self, df: pd.DataFrame, *, start_idx: int, line: Trendline, direction: str) -> Tuple[Optional[int], Optional[float], bool]:
        for i in range(start_idx, min(len(df), start_idx + self.breakout_search_bars)):
            close = _safe_float(df.iloc[i].get("close"))
            boundary = line.value_at(i)
            if close is None or boundary <= 0:
                continue
            thr = boundary * (1.0 + self.breakout_thr) if direction == "up" else boundary * (1.0 - self.breakout_thr)
            if direction == "up":
                ok = close > thr
            else:
                ok = close < thr
            if not ok:
                continue

            if self.confirm_bars > 1:
                j_end = min(len(df), i + self.confirm_bars)
                all_ok = True
                for j in range(i, j_end):
                    c = _safe_float(df.iloc[j].get("close"))
                    b = line.value_at(j)
                    if c is None or b <= 0:
                        all_ok = False
                        break
                    tt = b * (1.0 + self.breakout_thr) if direction == "up" else b * (1.0 - self.breakout_thr)
                    if direction == "up" and not (c > tt):
                        all_ok = False
                        break
                    if direction == "down" and not (c < tt):
                        all_ok = False
                        break
                if not all_ok:
                    continue

            vr = df.iloc[i].get("volume_ratio", np.nan)
            vol_ok = bool(pd.notna(vr) and np.isfinite(vr) and float(vr) >= self.vol_mult_min)
            if self.vol_required and not vol_ok:
                continue
            return i, close, vol_ok
        return None, None, False

    def _candidate(self, df: pd.DataFrame, pivots: Sequence[Pivot]) -> Optional[Dict[str, Any]]:
        if len(pivots) != 4:
            return None
        idxs = [int(p.idx) for p in pivots]
        if not (idxs[0] < idxs[1] < idxs[2] < idxs[3]):
            return None
        width_bars = idxs[-1] - idxs[0] + 1
        if width_bars < self.width_min_bars or width_bars > self.width_max_bars:
            return None

        kinds = [p.type for p in pivots]
        if kinds == [PivotType.HIGH, PivotType.LOW, PivotType.HIGH, PivotType.LOW]:
            direction = "up"
            upper_points = [(idxs[0], float(df.iloc[idxs[0]]["high"])), (idxs[2], float(df.iloc[idxs[2]]["high"]))]
            lower_points = [(idxs[1], float(df.iloc[idxs[1]]["low"])), (idxs[3], float(df.iloc[idxs[3]]["low"]))]
            anchor_price = upper_points[0][1]
            pattern_type = "continuation_bullish"
            variant_code = "bull_flag"
        elif kinds == [PivotType.LOW, PivotType.HIGH, PivotType.LOW, PivotType.HIGH]:
            direction = "down"
            upper_points = [(idxs[1], float(df.iloc[idxs[1]]["high"])), (idxs[3], float(df.iloc[idxs[3]]["high"]))]
            lower_points = [(idxs[0], float(df.iloc[idxs[0]]["low"])), (idxs[2], float(df.iloc[idxs[2]]["low"]))]
            anchor_price = lower_points[0][1]
            pattern_type = "continuation_bearish"
            variant_code = "bear_flag"
        else:
            return None

        upper = Trendline(
            idx0=upper_points[0][0],
            price0=upper_points[0][1],
            slope_per_bar=(upper_points[1][1] - upper_points[0][1]) / max(1, upper_points[1][0] - upper_points[0][0]),
        )
        lower = Trendline(
            idx0=lower_points[0][0],
            price0=lower_points[0][1],
            slope_per_bar=(lower_points[1][1] - lower_points[0][1]) / max(1, lower_points[1][0] - lower_points[0][0]),
        )
        upper_deg = _slope_degrees(upper_points[0][0], upper_points[0][1], upper_points[1][0], upper_points[1][1])
        lower_deg = _slope_degrees(lower_points[0][0], lower_points[0][1], lower_points[1][0], lower_points[1][1])
        slope_gap_deg = abs(upper_deg - lower_deg)
        if slope_gap_deg > self.parallel_tol_deg + 1.0:
            return None

        avg_slope_deg = (upper_deg + lower_deg) / 2.0
        if direction == "up":
            if avg_slope_deg < self.bull_avg_slope_min or avg_slope_deg > self.bull_avg_slope_max:
                return None
        else:
            if avg_slope_deg < self.bear_avg_slope_min or avg_slope_deg > self.bear_avg_slope_max:
                return None

        mid_idx = (idxs[1] + idxs[2]) // 2
        gap_mid = upper.value_at(mid_idx) - lower.value_at(mid_idx)
        if gap_mid <= 0:
            return None
        mid_ref = (upper.value_at(mid_idx) + lower.value_at(mid_idx)) / 2.0
        if mid_ref <= 0:
            return None
        flag_height_pct = gap_mid / mid_ref * 100.0
        if flag_height_pct < self.height_min_pct or flag_height_pct > self.height_max_pct:
            return None

        pole = self._prior_pole(df, start_idx=idxs[0], direction=direction, anchor_price=anchor_price)
        if not pole:
            return None
        if pole["pole_move_pct"] <= 0:
            return None
        flag_to_pole_pct = flag_height_pct / pole["pole_move_pct"] * 100.0
        if flag_to_pole_pct > self.flag_to_pole_max_pct:
            return None

        breakout_line = upper if direction == "up" else lower
        breakout_idx, breakout_price, vol_ok = self._breakout_ok(df, start_idx=idxs[-1] + 1, line=breakout_line, direction=direction)
        if breakout_idx is None or breakout_price is None:
            return None

        pole_height_abs = abs(anchor_price - float(pole["pole_price"]))
        target_price = float(breakout_price) + pole_height_abs if direction == "up" else float(breakout_price) - pole_height_abs
        stop_loss_price = float(lower.value_at(int(breakout_idx))) if direction == "up" else float(upper.value_at(int(breakout_idx)))

        confidence = 78
        if pole["pole_move_pct"] >= 14.0:
            confidence += 4
        if slope_gap_deg <= 1.8:
            confidence += 4
        if flag_to_pole_pct <= 35.0:
            confidence += 4
        if vol_ok:
            confidence += 4
        confidence = max(0, min(100, confidence))

        family_metrics = {
            "width_bars": int(width_bars),
            "upper_slope_deg": float(upper_deg),
            "lower_slope_deg": float(lower_deg),
            "avg_slope_deg": float(avg_slope_deg),
            "slope_gap_deg": float(slope_gap_deg),
            "flag_height_pct": float(flag_height_pct),
            "flag_to_pole_pct": float(flag_to_pole_pct),
            "pole_move_pct": float(pole["pole_move_pct"]),
            "pole_slope_deg": float(pole["pole_slope_deg"]),
            "pole_bars": int(pole["pole_bars"]),
            "breakout_lag_bars": int(int(breakout_idx) - idxs[-1]),
        }

        return {
            "pattern_id": f"{variant_code}_{idxs[0]}_{idxs[-1]}",
            "pattern_type": pattern_type,
            "breakout_direction": direction,
            "breakout_idx": int(breakout_idx),
            "breakout_price": float(breakout_price),
            "target_price": float(target_price),
            "stop_loss_price": float(stop_loss_price),
            "confidence_score": int(confidence),
            "volume_confirmed": bool(vol_ok),
            "pattern_height_pct": round(float(flag_height_pct), 2),
            "pattern_width_bars": int(width_bars),
            "touch_count": 4,
            "pivot_indices": idxs,
            "variant_code": variant_code,
            "variant_confidence": int(confidence),
            "variant_evidence_json": json.dumps(
                {
                    "pole_move_pct": round(float(pole["pole_move_pct"]), 2),
                    "flag_to_pole_pct": round(float(flag_to_pole_pct), 2),
                    "avg_slope_deg": round(float(avg_slope_deg), 2),
                },
                sort_keys=True,
                ensure_ascii=False,
            ),
            "family_metrics_json": json.dumps(family_metrics, sort_keys=True, ensure_ascii=False),
        }

    def scan(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> List[Dict[str, Any]]:
        pivots = pivots_filtered or pivots_raw
        if len(pivots) < 4:
            return []

        out: List[Dict[str, Any]] = []
        for i in range(len(pivots) - 3):
            window = pivots[i : i + 4]
            candidate = self._candidate(df, window)
            if not candidate:
                continue
            start_idx = int(candidate["pivot_indices"][0])
            end_idx = int(candidate["pivot_indices"][-1])
            breakout_idx = int(candidate["breakout_idx"])
            out.append(
                {
                    "pattern_id": f"{symbol}_{self.key}_{candidate['pattern_id']}",
                    "symbol": symbol,
                    "pattern_name": self.key,
                    "base_pattern_name": self.key,
                    "pattern_type": candidate["pattern_type"],
                    "formation_start": str(df.iloc[start_idx]["date"].date()) if "date" in df.columns else str(start_idx),
                    "formation_end": str(df.iloc[end_idx]["date"].date()) if "date" in df.columns else str(end_idx),
                    "breakout_date": str(df.iloc[breakout_idx]["date"].date()) if "date" in df.columns else None,
                    "breakout_idx": breakout_idx,
                    "breakout_direction": candidate["breakout_direction"],
                    "breakout_price": candidate["breakout_price"],
                    "target_price": candidate["target_price"],
                    "stop_loss_price": candidate["stop_loss_price"],
                    "confidence_score": candidate["confidence_score"],
                    "volume_confirmed": candidate["volume_confirmed"],
                    "variant_code": candidate["variant_code"],
                    "variant_confidence": candidate["variant_confidence"],
                    "variant_evidence_json": candidate["variant_evidence_json"],
                    "family_metrics_json": candidate["family_metrics_json"],
                    "pattern_height_pct": candidate["pattern_height_pct"],
                    "pattern_width_bars": candidate["pattern_width_bars"],
                    "touch_count": candidate["touch_count"],
                    "pivot_indices": candidate["pivot_indices"],
                    "config_hash": self.config_hash,
                    "created_at": datetime.now().isoformat(),
                }
            )
        return out


class SpikeScanner(BaseDigitizedScanner):
    def scan(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> List[Dict[str, Any]]:
        geom = self.spec.get("geometry_constraints", {}) or {}
        mag = geom.get("spike_magnitude", {}) or {}
        min_range_pct = float(mag.get("min_range_pct") or 3.0) / 100.0
        hmin = geom.get("height_ratio_min")
        hmax = geom.get("height_ratio_max")

        out: List[Dict[str, Any]] = []
        for i in range(1, len(df)):
            prev = df.iloc[i - 1]
            cur = df.iloc[i]
            if float(prev["close"]) <= 0:
                continue
            rng = float(cur["high"] - cur["low"])
            rng_pct = rng / float(prev["close"])
            if rng_pct < min_range_pct:
                continue
            height_pct = rng_pct * 100.0
            if hmin is not None and height_pct < float(hmin):
                continue
            if hmax is not None and height_pct > float(hmax):
                continue

            # Treat spike day as breakout; direction based on close-open
            breakout_dir = "up" if float(cur["close"]) >= float(cur["open"]) else "down"
            breakout_price = float(cur["close"])
            breakout_idx = i

            pattern_id = f"{symbol}_{self.key}_{i}_{i}"
            out.append(
                {
                    "pattern_id": pattern_id,
                    "symbol": symbol,
                    "pattern_name": self.key,
                    "pattern_type": self.pattern_type,
                    "formation_start": str(cur["date"].date()) if "date" in df.columns else str(i),
                    "formation_end": str(cur["date"].date()) if "date" in df.columns else str(i),
                    "breakout_date": str(cur["date"].date()) if "date" in df.columns else None,
                    "breakout_idx": int(breakout_idx),
                    "breakout_direction": breakout_dir,
                    "breakout_price": breakout_price,
                    "target_price": breakout_price + rng if breakout_dir == "up" else breakout_price - rng,
                    "stop_loss_price": float(cur["low"]) if breakout_dir == "up" else float(cur["high"]),
                    "confidence_score": 70,
                    "volume_confirmed": False,
                    "pattern_height_pct": round(height_pct, 2),
                    "pattern_width_bars": 1,
                    "touch_count": 1,
                    "pivot_indices": [int(i)],
                    "config_hash": self.config_hash,
                    "created_at": datetime.now().isoformat(),
                }
            )

        return out


def build_digitized_scanners(
    library: DigitizedPatternLibrary,
) -> Dict[str, BaseDigitizedScanner]:
    scanners: Dict[str, BaseDigitizedScanner] = {}
    for key in library.list_keys():
        spec = library.load(key)
        ds = spec.get("detection_signature", {}) or {}

        if key == "rounding_bottoms_tops":
            scanners[key] = RoundingBottomsTopsScanner(key, spec)
            continue
        if key == "horn_bottoms_tops":
            scanners[key] = HornFamilyScanner(key, spec)
            continue
        if key == "cup_with_handle":
            scanners[key] = CupWithHandleScanner(key, spec)
            continue

        if key == "triple_bottoms_tops":
            scanners[key] = TripleBottomsTopsScanner(key, spec)
            continue
        if key == "head_and_shoulders_top":
            scanners[key] = HeadShouldersTopFamilyScanner(key, spec)
            continue
        if key == "head_and_shoulders_bottom":
            scanners[key] = HeadShouldersBottomFamilyScanner(key, spec)
            continue
        if key == "double_bottoms":
            scanners[key] = DoubleBottomFamilyScanner(key, spec)
            continue
        if key == "double_tops":
            scanners[key] = DoubleTopFamilyScanner(key, spec)
            continue
        if key == "pipe_bottoms":
            scanners[key] = PipeBottomScanner(key, spec)
            continue
        if key == "flags":
            scanners[key] = FlagFamilyScanner(key, spec)
            continue

        if key == "inside_day":
            scanners[key] = InsideDayScanner(key, spec)
            continue
        if key == "gaps":
            scanners[key] = GapScanner(key, spec)
            continue
        if key == "islands":
            scanners[key] = IslandScanner(key, spec)
            continue
        if key == "rising_falling_three_methods":
            scanners[key] = ThreeMethodsScanner(key, spec)
            continue
        if key == "spike_formation":
            scanners[key] = SpikeScanner(key, spec)
            continue

        # Default pivot-based implementation
        scanners[key] = PivotSequenceScanner(key, spec)

    return scanners


class _CachedScanner:
    def __init__(self, scanner: Any):
        self._scanner = scanner
        self._last_key: Optional[Tuple[str, int]] = None
        self._last_rows: Optional[List[Dict[str, Any]]] = None

    def scan(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> List[Dict[str, Any]]:
        ck = (str(symbol), int(id(df)))
        if self._last_key == ck and self._last_rows is not None:
            return self._last_rows
        rows = self._scanner.scan(symbol=symbol, df=df, pivots_filtered=pivots_filtered, pivots_raw=pivots_raw)
        # Cache the original list; downstream wrappers must not mutate it.
        self._last_key = ck
        self._last_rows = list(rows)
        return self._last_rows


class _DerivedScanner:
    def __init__(
        self,
        key: str,
        base: Any,
        *,
        keep_if: Any,
        transform: Optional[Any] = None,
    ):
        self.key = key
        self._base = base
        self._keep_if = keep_if
        self._transform = transform

    def scan(
        self,
        *,
        symbol: str,
        df: pd.DataFrame,
        pivots_filtered: List[Pivot],
        pivots_raw: List[Pivot],
    ) -> List[Dict[str, Any]]:
        base_rows = self._base.scan(symbol=symbol, df=df, pivots_filtered=pivots_filtered, pivots_raw=pivots_raw)
        out: List[Dict[str, Any]] = []
        for r in base_rows:
            try:
                ok = bool(self._keep_if(r, df, pivots_filtered, pivots_raw))
            except Exception:
                ok = False
            if not ok:
                continue
            row = dict(r)
            row["pattern_name"] = self.key
            # Ensure uniqueness across derived patterns.
            row["pattern_id"] = f"{symbol}_{self.key}_{row.get('pattern_id')}"
            if self._transform is not None:
                try:
                    row = self._transform(row, df, pivots_filtered, pivots_raw) or row
                except Exception:
                    pass
            out.append(row)
        return out


def build_bulkowski_53_scanners(library: DigitizedPatternLibrary) -> Dict[str, Any]:
    """
    Build a scanner set aligned to Bulkowski Part One (53 chart-pattern chapters).

    Notes:
    - Uses local digitized specs when available, but does not require one spec file per chapter.
    - Some chapters are implemented as derived sub-views of a base detector (cached per symbol).
    - Event patterns (Part Two) are intentionally excluded here.
    """

    digitized = build_digitized_scanners(library)
    out: Dict[str, Any] = {}

    def _get(key: str) -> Optional[Any]:
        return digitized.get(key)

    def _pct(a: float, b: float) -> float:
        if b == 0:
            return float("inf")
        return abs(a - b) / abs(b) * 100.0

    # Chapter 1 + 4
    if _get("broadening_bottoms"):
        out["broadening_bottoms"] = _get("broadening_bottoms")
    if _get("broadening_tops"):
        out["broadening_tops"] = _get("broadening_tops")

    # Chapter 2 + 3: built-in right-angled broadening formations
    right_asc_spec = library.load("broadening_formations_right_angled_ascending") if "broadening_formations_right_angled_ascending" in library.list_keys() else None
    if not isinstance(right_asc_spec, dict):
        right_asc_spec = {
            "pattern_name": "Broadening Formations, Right-Angled and Ascending",
            "pattern_type": "continuation_both",
            "digitization_version": "builtin_bulkowski_53_v1",
            "detection_signature": {
                "pivot_sequence": ["L", "H", "L", "H", "L", "H"],
                "pivot_order": "alternating",
                "mandatory_pivots": [
                    {"position": 3, "type": "L", "constraint": "near_equal"},
                    {"position": 5, "type": "L", "constraint": "near_equal"},
                    {"position": 4, "type": "H", "constraint": "higher_than_previous"},
                    {"position": 6, "type": "H", "constraint": "higher_than_previous"},
                ],
            },
            "geometry_constraints": {
                "width_min_bars": 21,
                "width_max_bars": 210,
                "height_ratio_min": 6.0,
                "height_ratio_max": 80.0,
                "near_equal_tolerance_pct": 2.0,
                "breakout_search_bars": 60,
            },
            "prior_trend_requirements": {"direction": "any", "min_period_bars": 21, "min_change_pct": 10.0},
            "breakout_confirmation": {"breakout_direction": "both", "breakout_threshold_pct": 1.0, "confirmation_bars": 1, "close_beyond_required": True},
        }

    right_desc_spec = library.load("broadening_formations_right_angled_descending") if "broadening_formations_right_angled_descending" in library.list_keys() else None
    if not isinstance(right_desc_spec, dict):
        right_desc_spec = {
            "pattern_name": "Broadening Formations, Right-Angled and Descending",
            "pattern_type": "continuation_both",
            "digitization_version": "builtin_bulkowski_53_v1",
            "detection_signature": {
                "pivot_sequence": ["H", "L", "H", "L", "H", "L"],
                "pivot_order": "alternating",
                "mandatory_pivots": [
                    {"position": 3, "type": "H", "constraint": "near_equal"},
                    {"position": 5, "type": "H", "constraint": "near_equal"},
                    {"position": 4, "type": "L", "constraint": "lower_than_previous"},
                    {"position": 6, "type": "L", "constraint": "lower_than_previous"},
                ],
            },
            "geometry_constraints": {
                "width_min_bars": 21,
                "width_max_bars": 210,
                "height_ratio_min": 6.0,
                "height_ratio_max": 80.0,
                "near_equal_tolerance_pct": 2.0,
                "breakout_search_bars": 60,
            },
            "prior_trend_requirements": {"direction": "any", "min_period_bars": 21, "min_change_pct": 10.0},
            "breakout_confirmation": {"breakout_direction": "both", "breakout_threshold_pct": 1.0, "confirmation_bars": 1, "close_beyond_required": True},
        }
    out["broadening_formations_right_angled_ascending"] = PivotSequenceScanner("broadening_formations_right_angled_ascending", right_asc_spec)
    out["broadening_formations_right_angled_descending"] = PivotSequenceScanner("broadening_formations_right_angled_descending", right_desc_spec)

    # Chapter 5 + 6: built-in broadening wedges (diverging wedge boundaries)
    bw_spec = library.load("broadening_wedges") if "broadening_wedges" in library.list_keys() else None
    if not isinstance(bw_spec, dict):
        bw_spec = {
            "pattern_name": "Broadening Wedges, Ascending/Descending",
            "pattern_type": "continuation_both",
            "digitization_version": "builtin_bulkowski_53_v1",
            "detection_signature": {
                "pivot_sequence": ["H", "L", "H", "L", "H", "L"],
                "pivot_order": "alternating",
                "mandatory_pivots": [],
            },
            "geometry_constraints": {
                "width_min_bars": 21,
                "width_max_bars": 180,
                "height_ratio_min": 6.0,
                "height_ratio_max": 80.0,
                "near_equal_tolerance_pct": 2.0,
                "breakout_search_bars": 60,
            },
            "prior_trend_requirements": {"direction": "any", "min_period_bars": 21, "min_change_pct": 10.0},
            "breakout_confirmation": {"breakout_direction": "both", "breakout_threshold_pct": 1.0, "confirmation_bars": 1, "close_beyond_required": True},
        }
    bw_base = _CachedScanner(BroadeningWedgeFamilyScanner("broadening_wedges", bw_spec))
    out["broadening_wedges_ascending"] = _DerivedScanner(
        "broadening_wedges_ascending",
        bw_base,
        keep_if=lambda r, *_: str(r.get("variant_code") or "") == "ascending",
    )
    out["broadening_wedges_descending"] = _DerivedScanner(
        "broadening_wedges_descending",
        bw_base,
        keep_if=lambda r, *_: str(r.get("variant_code") or "") == "descending",
    )

    # Chapter 7 + 8: bump-and-run reversal bottom/top
    barr = library.load("bump_and_run_reversal") if "bump_and_run_reversal" in library.list_keys() else None
    if isinstance(barr, dict):
        out["bump_and_run_reversal_tops"] = PivotSequenceScanner("bump_and_run_reversal_tops", barr)

        barr_b = copy.deepcopy(barr)
        barr_b["pattern_type"] = "reversal_bullish"
        barr_b.setdefault("prior_trend_requirements", {})
        barr_b["prior_trend_requirements"]["direction"] = "down"
        barr_b.setdefault("breakout_confirmation", {})
        barr_b["breakout_confirmation"]["breakout_direction"] = "up"
        ds = barr_b.get("detection_signature", {}) or {}
        seq = (ds.get("pivot_sequence") or []) if isinstance(ds.get("pivot_sequence"), list) else []
        inv = []
        for t in seq:
            if t == "H":
                inv.append("L")
            elif t == "L":
                inv.append("H")
            else:
                inv.append(t)
        barr_b.setdefault("detection_signature", {})
        barr_b["detection_signature"]["pivot_sequence"] = inv
        out["bump_and_run_reversal_bottoms"] = PivotSequenceScanner("bump_and_run_reversal_bottoms", barr_b)

    # Chapter 9 + 10: cup with handle (+ inverted)
    cwh = library.load("cup_with_handle") if "cup_with_handle" in library.list_keys() else None
    if isinstance(cwh, dict):
        out["cup_with_handle"] = CupWithHandleScanner("cup_with_handle", cwh)
        out["cup_with_handle_inverted"] = InvertedCupWithHandleScanner("cup_with_handle_inverted", cwh)

    # Chapter 11 + 12: diamonds
    db = library.load("diamond_bottom") if "diamond_bottom" in library.list_keys() else None
    if isinstance(db, dict):
        out["diamond_bottoms"] = PivotSequenceScanner("diamond_bottoms", db)
    dt = library.load("diamond_top") if "diamond_top" in library.list_keys() else None
    if isinstance(dt, dict):
        out["diamond_tops"] = PivotSequenceScanner("diamond_tops", dt)

    # Chapter 13-20: double bottoms/tops by Adam/Eve variant
    if _get("double_bottoms"):
        base = _CachedScanner(_get("double_bottoms"))

        def _db_variant(r: Dict[str, Any], df: pd.DataFrame) -> Optional[str]:
            code = r.get("variant_code")
            if isinstance(code, str) and code:
                return code
            piv = r.get("pivot_indices") or []
            if not isinstance(piv, (list, tuple)) or len(piv) < 3:
                return None
            try:
                b1, b2 = int(piv[0]), int(piv[2])
            except Exception:
                return None
            variant, _, _ = classify_double_bottom_variant(df, first_idx=b1, second_idx=b2)
            return variant

        out["double_bottoms_adam_adam"] = _DerivedScanner("double_bottoms_adam_adam", base, keep_if=lambda r, df, *_: _db_variant(r, df) == "AA")
        out["double_bottoms_adam_eve"] = _DerivedScanner("double_bottoms_adam_eve", base, keep_if=lambda r, df, *_: _db_variant(r, df) == "AE")
        out["double_bottoms_eve_adam"] = _DerivedScanner("double_bottoms_eve_adam", base, keep_if=lambda r, df, *_: _db_variant(r, df) == "EA")
        out["double_bottoms_eve_eve"] = _DerivedScanner("double_bottoms_eve_eve", base, keep_if=lambda r, df, *_: _db_variant(r, df) == "EE")

    if _get("double_tops"):
        base = _CachedScanner(_get("double_tops"))

        def _dt_variant(r: Dict[str, Any], df: pd.DataFrame) -> Optional[str]:
            code = r.get("variant_code")
            if isinstance(code, str) and code:
                return code
            piv = r.get("pivot_indices") or []
            if not isinstance(piv, (list, tuple)) or len(piv) < 3:
                return None
            try:
                p1i, p2i = int(piv[0]), int(piv[2])
            except Exception:
                return None
            variant, _, _ = classify_double_top_variant(df, first_idx=p1i, second_idx=p2i)
            return variant

        out["double_tops_adam_adam"] = _DerivedScanner("double_tops_adam_adam", base, keep_if=lambda r, df, *_: _dt_variant(r, df) == "AA")
        out["double_tops_adam_eve"] = _DerivedScanner("double_tops_adam_eve", base, keep_if=lambda r, df, *_: _dt_variant(r, df) == "AE")
        out["double_tops_eve_adam"] = _DerivedScanner("double_tops_eve_adam", base, keep_if=lambda r, df, *_: _dt_variant(r, df) == "EA")
        out["double_tops_eve_eve"] = _DerivedScanner("double_tops_eve_eve", base, keep_if=lambda r, df, *_: _dt_variant(r, df) == "EE")

    # Chapter 21-22: flags (+ high & tight)
    if _get("flags"):
        base = _CachedScanner(_get("flags"))

        def _is_high_tight(r: Dict[str, Any], df: pd.DataFrame, *_: Any) -> bool:
            if str(r.get("breakout_direction") or "") != "up":
                return False
            piv = r.get("pivot_indices") or []
            if not isinstance(piv, (list, tuple)) or not piv:
                return False
            try:
                start = int(min(int(x) for x in piv if x is not None))
                end = int(max(int(x) for x in piv if x is not None))
            except Exception:
                return False
            if start < 0 or end >= len(df):
                return False

            form = df.iloc[start : end + 1]
            if len(form) == 0:
                return False
            form_high = float(form["high"].max())
            form_low = float(form["low"].min())
            if form_high <= 0:
                return False

            # Look back up to 60 bars for pole start (pragmatic).
            lb = max(0, start - 60)
            pre = df.iloc[lb : start + 1]
            if len(pre) == 0:
                return False
            pole_low = float(pre["low"].min())
            try:
                pole_low_vals = pre["low"].to_numpy(dtype=float, copy=False)
                if pole_low_vals.size == 0 or not np.isfinite(pole_low_vals).any():
                    return False
                pole_low_rel = int(np.nanargmin(pole_low_vals))
                pole_low_idx = int(lb + pole_low_rel)
            except Exception:
                return False
            if pole_low <= 0:
                return False
            pole_gain = (form_high - pole_low) / pole_low * 100.0
            pole_dur = int(start - pole_low_idx + 1)
            if pole_gain < 100.0 or pole_dur > 60:
                return False

            dd = (form_high - form_low) / form_high * 100.0
            return dd <= 20.0

        out["flags_high_tight"] = _DerivedScanner("flags_high_tight", base, keep_if=_is_high_tight)
        out["flags"] = _DerivedScanner("flags", base, keep_if=lambda r, df, *_: not _is_high_tight(r, df))

    # Chapter 23: gaps
    if _get("gaps"):
        out["gaps"] = _get("gaps")

    # Chapter 24-27: head & shoulders (standard vs complex)
    if _get("head_and_shoulders_bottom"):
        base = _CachedScanner(_get("head_and_shoulders_bottom"))
        hs_spec = library.load("head_and_shoulders_bottom") if "head_and_shoulders_bottom" in library.list_keys() else {}
        standard_width_max = int((hs_spec.get("geometry_constraints", {}) or {}).get("width_max_bars") or 270)

        def _hsb_complex(r: Dict[str, Any], df: pd.DataFrame, _pf: List[Pivot], pr: List[Pivot]) -> bool:
            variant = str(r.get("variant_code") or "")
            if variant:
                return variant == "complex"
            piv = r.get("pivot_indices") or []
            if not isinstance(piv, (list, tuple)) or len(piv) < 5:
                return False
            try:
                l1, l2, l3 = int(piv[0]), int(piv[2]), int(piv[4])
            except Exception:
                return False
            if not (0 <= l1 < len(df) and 0 <= l2 < len(df) and 0 <= l3 < len(df)):
                return False
            shoulder_level = (float(df.iloc[l1]["low"]) + float(df.iloc[l3]["low"])) / 2.0
            head = float(df.iloc[l2]["low"])
            if shoulder_level <= 0:
                return False

            if int(r.get("pattern_width_bars") or 0) > standard_width_max:
                return True

            tol = float((hs_spec.get("geometry_constraints", {}) or {}).get("near_equal_tolerance_pct") or 3.0)
            lows = [p for p in (pr or _pf) if p.type == PivotType.LOW and l1 <= int(p.idx) <= l3]
            count = 0
            for p in lows:
                if int(p.idx) in (l1, l2, l3):
                    continue
                if float(p.price) <= head * 1.02:
                    continue
                if _pct(float(p.price), shoulder_level) <= tol:
                    count += 1
            return count >= 1

        out["head_and_shoulders_bottoms_complex"] = _DerivedScanner("head_and_shoulders_bottoms_complex", base, keep_if=_hsb_complex)
        out["head_and_shoulders_bottoms"] = _DerivedScanner(
            "head_and_shoulders_bottoms",
            base,
            keep_if=lambda r, df, pf, pr: (int(r.get("pattern_width_bars") or 0) <= standard_width_max) and (not _hsb_complex(r, df, pf, pr)),
        )

    if _get("head_and_shoulders_top"):
        base = _CachedScanner(_get("head_and_shoulders_top"))
        hs_spec = library.load("head_and_shoulders_top") if "head_and_shoulders_top" in library.list_keys() else {}
        standard_width_max = int((hs_spec.get("geometry_constraints", {}) or {}).get("width_max_bars") or 270)

        def _hst_complex(r: Dict[str, Any], df: pd.DataFrame, _pf: List[Pivot], pr: List[Pivot]) -> bool:
            variant = str(r.get("variant_code") or "")
            if variant:
                return variant == "complex"
            piv = r.get("pivot_indices") or []
            if not isinstance(piv, (list, tuple)) or len(piv) < 5:
                return False
            try:
                h1, h2, h3 = int(piv[0]), int(piv[2]), int(piv[4])
            except Exception:
                return False
            if not (0 <= h1 < len(df) and 0 <= h2 < len(df) and 0 <= h3 < len(df)):
                return False
            shoulder_level = (float(df.iloc[h1]["high"]) + float(df.iloc[h3]["high"])) / 2.0
            head = float(df.iloc[h2]["high"])
            if shoulder_level <= 0:
                return False

            if int(r.get("pattern_width_bars") or 0) > standard_width_max:
                return True

            tol = float((hs_spec.get("geometry_constraints", {}) or {}).get("near_equal_tolerance_pct") or 3.0)
            highs = [p for p in (pr or _pf) if p.type == PivotType.HIGH and h1 <= int(p.idx) <= h3]
            count = 0
            for p in highs:
                if int(p.idx) in (h1, h2, h3):
                    continue
                if float(p.price) >= head * 0.98:
                    continue
                if _pct(float(p.price), shoulder_level) <= tol:
                    count += 1
            return count >= 1

        out["head_and_shoulders_tops_complex"] = _DerivedScanner("head_and_shoulders_tops_complex", base, keep_if=_hst_complex)
        out["head_and_shoulders_tops"] = _DerivedScanner(
            "head_and_shoulders_tops",
            base,
            keep_if=lambda r, df, pf, pr: (int(r.get("pattern_width_bars") or 0) <= standard_width_max) and (not _hst_complex(r, df, pf, pr)),
        )

    # Chapter 28-29: horns
    if _get("horn_bottoms_tops"):
        base = _CachedScanner(_get("horn_bottoms_tops"))
        out["horn_bottoms"] = _DerivedScanner("horn_bottoms", base, keep_if=lambda r, *_: str(r.get("variant_code") or "") == "horn_bottom")
        out["horn_tops"] = _DerivedScanner("horn_tops", base, keep_if=lambda r, *_: str(r.get("variant_code") or "") == "horn_top")

    # Chapter 30-31: islands (regular vs long)
    islands_spec = library.load("islands") if "islands" in library.list_keys() else None
    if isinstance(islands_spec, dict):
        spec_long = copy.deepcopy(islands_spec)
        spec_long.setdefault("geometry_constraints", {})
        spec_long["geometry_constraints"]["width_max_bars"] = 40
        spec_long.setdefault("duration_constraints", {})
        spec_long["duration_constraints"]["max_bars"] = 42
        isl_base = _CachedScanner(IslandScanner("__islands_base", spec_long))

        def _is_long_island(r: Dict[str, Any], *_: Any) -> bool:
            try:
                return int(r.get("pattern_width_bars") or 0) > 10
            except Exception:
                return False

        out["islands_long"] = _DerivedScanner("islands_long", isl_base, keep_if=_is_long_island)
        out["island_reversals"] = _DerivedScanner("island_reversals", isl_base, keep_if=lambda r, *_: not _is_long_island(r))

    # Chapter 32-33: measured moves
    if _get("measured_move_down_up"):
        mm_spec = library.load("measured_move_down_up")
        mm_base = _CachedScanner(MeasuredMoveScanner("measured_move_down_up", mm_spec))
        out["measured_move_down"] = _DerivedScanner("measured_move_down", mm_base, keep_if=lambda r, *_: str(r.get("variant_code") or "") == "measured_move_down")
        out["measured_move_up"] = _DerivedScanner("measured_move_up", mm_base, keep_if=lambda r, *_: str(r.get("variant_code") or "") == "measured_move_up")

    # Chapter 34: pennants
    if _get("pennants"):
        out["pennants"] = _get("pennants")

    # Chapter 35-36: pipes
    pb = library.load("pipe_bottoms") if "pipe_bottoms" in library.list_keys() else None
    if isinstance(pb, dict):
        out["pipe_bottoms"] = PipeBottomScanner("pipe_bottoms", pb)
        pt = copy.deepcopy(pb)
        pt["pattern_type"] = "reversal_bearish"
        pt.setdefault("prior_trend_requirements", {})
        pt["prior_trend_requirements"]["direction"] = "up"
        pt.setdefault("breakout_confirmation", {})
        pt["breakout_confirmation"]["breakout_direction"] = "down"
        out["pipe_tops"] = PipeTopScanner("pipe_tops", pt)

    # Chapter 37-38: rectangles
    if _get("rectangle_bottoms_tops"):
        base = _CachedScanner(_get("rectangle_bottoms_tops"))
        out["rectangle_bottoms"] = _DerivedScanner("rectangle_bottoms", base, keep_if=lambda r, *_: str(r.get("breakout_direction") or "") == "up")
        out["rectangle_tops"] = _DerivedScanner("rectangle_tops", base, keep_if=lambda r, *_: str(r.get("breakout_direction") or "") == "down")

    # Chapter 39-40: rounding bottoms/tops
    if _get("rounding_bottoms_tops"):
        base = _CachedScanner(_get("rounding_bottoms_tops"))
        out["rounding_bottoms"] = _DerivedScanner("rounding_bottoms", base, keep_if=lambda r, *_: str(r.get("variant_code") or "") == "rounding_bottom")
        out["rounding_tops"] = _DerivedScanner("rounding_tops", base, keep_if=lambda r, *_: str(r.get("variant_code") or "") == "rounding_top")

    # Chapter 41-44: scallops (ascending/descending + inverted)
    if _get("scallop_ascending_descending"):
        spec = library.load("scallop_ascending_descending") if "scallop_ascending_descending" in library.list_keys() else {}
        base = _CachedScanner(ScallopFamilyScanner("scallops", spec if isinstance(spec, dict) else {}))
        out["scallops_ascending"] = _DerivedScanner(
            "scallops_ascending",
            base,
            keep_if=lambda r, *_: str(r.get("variant_code") or "") == "scallops_ascending",
        )
        out["scallops_ascending_inverted"] = _DerivedScanner(
            "scallops_ascending_inverted",
            base,
            keep_if=lambda r, *_: str(r.get("variant_code") or "") == "scallops_ascending_inverted",
        )
        out["scallops_descending"] = _DerivedScanner(
            "scallops_descending",
            base,
            keep_if=lambda r, *_: str(r.get("variant_code") or "") == "scallops_descending",
        )
        out["scallops_descending_inverted"] = _DerivedScanner(
            "scallops_descending_inverted",
            base,
            keep_if=lambda r, *_: str(r.get("variant_code") or "") == "scallops_descending_inverted",
        )

    # Chapter 45-46: three falling peaks / three rising valleys
    tfp_spec = library.load("three_falling_peaks") if "three_falling_peaks" in library.list_keys() else None
    if not isinstance(tfp_spec, dict):
        tfp_spec = {
            "pattern_name": "Three Falling Peaks",
            "pattern_type": "reversal_bearish",
            "digitization_version": "builtin_bulkowski_53_v1",
            "detection_signature": {
                "pivot_sequence": ["H", "L", "H", "L", "H"],
                "pivot_order": "alternating",
                "mandatory_pivots": [
                    {"position": 3, "type": "H", "constraint": "lower_than_previous"},
                    {"position": 5, "type": "H", "constraint": "lower_than_previous"},
                ],
            },
            "geometry_constraints": {"width_min_bars": 42, "width_max_bars": 270, "height_ratio_min": 6.0, "height_ratio_max": 80.0, "near_equal_tolerance_pct": 3.0},
            "prior_trend_requirements": {"direction": "up", "min_period_bars": 21, "min_change_pct": 10.0},
            "breakout_confirmation": {"breakout_direction": "down", "breakout_threshold_pct": 1.0, "confirmation_bars": 1, "close_beyond_required": True},
        }

    trv_spec = library.load("three_rising_valleys") if "three_rising_valleys" in library.list_keys() else None
    if not isinstance(trv_spec, dict):
        trv_spec = {
            "pattern_name": "Three Rising Valleys",
            "pattern_type": "reversal_bullish",
            "digitization_version": "builtin_bulkowski_53_v1",
            "detection_signature": {
                "pivot_sequence": ["L", "H", "L", "H", "L"],
                "pivot_order": "alternating",
                "mandatory_pivots": [
                    {"position": 3, "type": "L", "constraint": "higher_than_previous"},
                    {"position": 5, "type": "L", "constraint": "higher_than_previous"},
                ],
            },
            "geometry_constraints": {"width_min_bars": 42, "width_max_bars": 270, "height_ratio_min": 6.0, "height_ratio_max": 80.0, "near_equal_tolerance_pct": 3.0},
            "prior_trend_requirements": {"direction": "down", "min_period_bars": 21, "min_change_pct": 10.0},
            "breakout_confirmation": {"breakout_direction": "up", "breakout_threshold_pct": 1.0, "confirmation_bars": 1, "close_beyond_required": True},
        }
    out["three_falling_peaks"] = PivotSequenceScanner("three_falling_peaks", tfp_spec)
    out["three_rising_valleys"] = PivotSequenceScanner("three_rising_valleys", trv_spec)

    # Chapter 47-49: triangles (ascending/descending/symmetrical)
    tri_spec = library.load("triangles") if "triangles" in library.list_keys() else None
    if isinstance(tri_spec, dict):
        base = _CachedScanner(TriangleFamilyScanner("triangles", tri_spec))
        out["triangles_ascending"] = _DerivedScanner(
            "triangles_ascending",
            base,
            keep_if=lambda r, *_: str(r.get("variant_code") or "") == "ascending",
        )
        out["triangles_descending"] = _DerivedScanner(
            "triangles_descending",
            base,
            keep_if=lambda r, *_: str(r.get("variant_code") or "") == "descending",
        )
        out["triangles_symmetrical"] = _DerivedScanner(
            "triangles_symmetrical",
            base,
            keep_if=lambda r, *_: str(r.get("variant_code") or "") == "symmetrical",
        )

    # Chapter 50-51: triple bottoms/tops
    tbt = library.load("triple_bottoms_tops") if "triple_bottoms_tops" in library.list_keys() else None
    if isinstance(tbt, dict):
        base = _CachedScanner(TripleBottomsTopsScanner("triple_bottoms_tops", tbt))
        out["triple_bottoms"] = _DerivedScanner("triple_bottoms", base, keep_if=lambda r, *_: str(r.get("variant_code") or "") == "triple_bottom")
        out["triple_tops"] = _DerivedScanner("triple_tops", base, keep_if=lambda r, *_: str(r.get("variant_code") or "") == "triple_top")

    # Chapter 52-53: wedges (falling/rising)
    wedge_spec = library.load("wedges_ascending_descending") if "wedges_ascending_descending" in library.list_keys() else None
    if isinstance(wedge_spec, dict):
        w_any = copy.deepcopy(wedge_spec)
        w_any.setdefault("detection_signature", {})
        w_any["detection_signature"]["mandatory_pivots"] = []
        base = _CachedScanner(PivotSequenceScanner("__wedges_base", w_any))

        def _w_slopes(r: Dict[str, Any], df: pd.DataFrame) -> Optional[Tuple[float, float]]:
            piv = r.get("pivot_indices") or []
            if not isinstance(piv, (list, tuple)) or len(piv) < 6:
                return None
            try:
                idxs = [int(x) for x in piv[:6]]
            except Exception:
                return None
            hs = [idxs[i] for i in (0, 2, 4)]
            ls = [idxs[i] for i in (1, 3, 5)]
            if any(i < 0 or i >= len(df) for i in hs + ls):
                return None
            up0, up1 = hs[0], hs[-1]
            lo0, lo1 = ls[0], ls[-1]
            up_deg = _slope_degrees(up0, float(df.iloc[up0]["high"]), up1, float(df.iloc[up1]["high"]))
            lo_deg = _slope_degrees(lo0, float(df.iloc[lo0]["low"]), lo1, float(df.iloc[lo1]["low"]))
            return up_deg, lo_deg

        def _keep_w_falling(r: Dict[str, Any], df: pd.DataFrame, *_: Any) -> bool:
            s = _w_slopes(r, df)
            if s is None:
                return False
            up_deg, lo_deg = s
            return up_deg < -0.2 and lo_deg < -0.2 and str(r.get("breakout_direction") or "") == "up"

        def _keep_w_rising(r: Dict[str, Any], df: pd.DataFrame, *_: Any) -> bool:
            s = _w_slopes(r, df)
            if s is None:
                return False
            up_deg, lo_deg = s
            return up_deg > 0.2 and lo_deg > 0.2 and str(r.get("breakout_direction") or "") == "down"

        def _set_type(ptype: str):
            def _t(row: Dict[str, Any], *_: Any) -> Dict[str, Any]:
                row["pattern_type"] = ptype
                return row

            return _t

        out["wedges_falling"] = _DerivedScanner("wedges_falling", base, keep_if=_keep_w_falling, transform=_set_type("reversal_bullish"))
        out["wedges_rising"] = _DerivedScanner("wedges_rising", base, keep_if=_keep_w_rising, transform=_set_type("reversal_bearish"))

    # Return stable ordering for CLI/help usage.
    ordered_keys = [
        "broadening_bottoms",
        "broadening_formations_right_angled_ascending",
        "broadening_formations_right_angled_descending",
        "broadening_tops",
        "broadening_wedges_ascending",
        "broadening_wedges_descending",
        "bump_and_run_reversal_bottoms",
        "bump_and_run_reversal_tops",
        "cup_with_handle",
        "cup_with_handle_inverted",
        "diamond_bottoms",
        "diamond_tops",
        "double_bottoms_adam_adam",
        "double_bottoms_adam_eve",
        "double_bottoms_eve_adam",
        "double_bottoms_eve_eve",
        "double_tops_adam_adam",
        "double_tops_adam_eve",
        "double_tops_eve_adam",
        "double_tops_eve_eve",
        "flags",
        "flags_high_tight",
        "gaps",
        "head_and_shoulders_bottoms",
        "head_and_shoulders_bottoms_complex",
        "head_and_shoulders_tops",
        "head_and_shoulders_tops_complex",
        "horn_bottoms",
        "horn_tops",
        "island_reversals",
        "islands_long",
        "measured_move_down",
        "measured_move_up",
        "pennants",
        "pipe_bottoms",
        "pipe_tops",
        "rectangle_bottoms",
        "rectangle_tops",
        "rounding_bottoms",
        "rounding_tops",
        "scallops_ascending",
        "scallops_ascending_inverted",
        "scallops_descending",
        "scallops_descending_inverted",
        "three_falling_peaks",
        "three_rising_valleys",
        "triangles_ascending",
        "triangles_descending",
        "triangles_symmetrical",
        "triple_bottoms",
        "triple_tops",
        "wedges_falling",
        "wedges_rising",
    ]
    return {k: out[k] for k in ordered_keys if k in out}


def build_event_ohlcv_scanners() -> Dict[str, Any]:
    """
    Build a minimal OHLCV-only event-pattern scanner set.

    This intentionally includes only the event patterns that can be defined
    from price/volume alone (no external event database required).
    """

    dcb_spec = {
        "pattern_name": "Dead-Cat Bounce",
        "pattern_type": "event_bearish",
        "digitization_version": "builtin_event_ohlcv_v1",
        "event_constraints": {
            # Bulkowski: min event decline used in study (15%), usually higher; up to ~8 sessions.
            "event_decline_min_pct": 15.0,
            "event_decline_max_bars": 8,
            # Bulkowski: bounce recovery typically 15% to 35%, peaking 5 to 25 days.
            "bounce_min_pct": 15.0,
            "bounce_max_pct": 35.0,
            "bounce_min_bars": 5,
            "bounce_max_bars": 25,
            "gap_preferred": True,
        },
        "volume_constraints": {"event_volume_ratio_preferred": 2.0},
    }
    idcb_spec = {
        "pattern_name": "Dead-Cat Bounce, Inverted",
        "pattern_type": "event_bearish",
        "digitization_version": "builtin_event_ohlcv_v1",
        "event_constraints": {
            # Bulkowski: large 1-day upward move (>= 5% in the book's frequency distributions).
            "up_move_min_pct": 5.0,
            "gap_preferred": True,
        },
        "volume_constraints": {"event_volume_ratio_preferred": 2.0},
    }

    return {
        "dead_cat_bounce": DeadCatBounceScanner("dead_cat_bounce", dcb_spec),
        "dead_cat_bounce_inverted": DeadCatBounceInvertedScanner("dead_cat_bounce_inverted", idcb_spec),
    }


def build_bulkowski_55_ohlcv_scanners(library: DigitizedPatternLibrary) -> Dict[str, Any]:
    """
    Bulkowski Part One (53 chart patterns) + OHLCV-only event exceptions:
      - Dead-Cat Bounce
      - Dead-Cat Bounce, Inverted
    """

    out: Dict[str, Any] = {}
    out.update(build_bulkowski_53_scanners(library))
    out.update(build_event_ohlcv_scanners())
    return out


def build_bulkowski_53_strict_scanners(library: DigitizedPatternLibrary) -> Dict[str, Any]:
    """
    Strict-ish subset of Bulkowski Part One (53 chart-pattern chapters).

    Definition:
      - Keep only patterns that map to an existing digitized spec key (via `spec_key` mapping).
      - Exclude built-in proxy patterns that do not have a digitized spec anchor (e.g., some
        broadening sub-types and a few standalone proxy chapters).

    This is useful when you want research runs whose pattern definitions are tightly tied to
    the digitized spec library, while still keeping the Bulkowski chapter/variant keys.
    """

    full = build_bulkowski_53_scanners(library)
    try:
        from .pattern_set_metadata import BULKOWSKI_53_META  # type: ignore
    except Exception:  # pragma: no cover
        from pattern_set_metadata import BULKOWSKI_53_META  # type: ignore

    strict: Dict[str, Any] = {}
    for k, scanner in full.items():
        meta = BULKOWSKI_53_META.get(str(k), {})
        if meta.get("spec_key"):
            strict[str(k)] = scanner
    return strict


def build_bulkowski_strict_ohlcv_scanners(library: DigitizedPatternLibrary) -> Dict[str, Any]:
    """
    Spec-anchored Bulkowski chart patterns + OHLCV-only event exceptions.

    Currently:
      bulkowski_53_strict (53) + event_ohlcv (2) = 55 patterns
    """

    out: Dict[str, Any] = {}
    out.update(build_bulkowski_53_strict_scanners(library))
    out.update(build_event_ohlcv_scanners())
    return out


def build_bulkowski_49_strict_ohlcv_scanners(library: DigitizedPatternLibrary) -> Dict[str, Any]:
    """
    Deprecated alias for `build_bulkowski_strict_ohlcv_scanners`.

    Kept for backward compatibility with older runs/scripts.
    """

    return build_bulkowski_strict_ohlcv_scanners(library)
