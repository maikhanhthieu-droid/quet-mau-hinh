"""
Post-Breakout Evaluator
========================

EVALUATION LAYER ONLY - Uses look-ahead data (252 bars) for statistics.
Should NOT be used during detection/scanning phase.

This module evaluates detected patterns AFTER formation to compute:
- Failure rates (2 definitions per Bulkowski)
- Ultimate price and time-to-ultimate
- Throwback/pullback rates
- Target achievement

ARCHITECTURE:
┌─────────────────┐     ┌──────────────────────┐
│  Detection      │     │  Evaluation          │
│  (no lookahead) │ ──► │  (lookahead 252 bars)│
│  - Pivot detect │     │  - Failure rate      │
│  - Pattern form │     │  - Ultimate price    │
│  - Breakout     │     │  - Throwback rate    │
│    confirm only │     │  - Target achieved   │
└─────────────────┘     └──────────────────────┘

DEFINITIONS (per digitized specs):
----------------------------------
1. FAILURE RATE - Two definitions:
   a) Bust Failure: Price reverses X% against breakout direction
      - For bearish: price rises X% from breakout price
      - For bullish: price falls X% from breakout price
      - Thresholds: 5%, 10% (standard)

   b) Invalidation Failure: Price returns across pattern boundary
      - For bearish: price rises above trough/neckline
      - For bullish: price falls below peak/neckline

2. ULTIMATE PRICE:
   - Ultimate Low (bearish): Lowest price within window before:
     a) 20% reversal upward, OR
     b) New pattern forms, OR
     c) End of window (252 bars)
   - Ultimate High (bullish): Highest price within window before same stops

3. THROWBACK/PULLBACK:
   - Throwback (bearish): Price returns to breakout price level
   - Pullback (bullish): Price returns to breakout price level
   - Tolerance: within X% of breakout price (default 1%)

4. TARGET ACHIEVEMENT:
   - Price reaches target_price (measured from pattern height)
   - Can be measured as: intraday touch OR closing price
   - time_to_target: calendar days from breakout to target hit
"""

from dataclasses import dataclass, asdict, field
from datetime import datetime, date, timedelta
import os
from typing import List, Optional, Dict, Any, Tuple
from enum import Enum
import pandas as pd
import numpy as np
import json

try:
    from .double_pattern_utils import resolve_double_bottom_variant, resolve_double_top_variant  # type: ignore
except ImportError:  # pragma: no cover
    from double_pattern_utils import resolve_double_bottom_variant, resolve_double_top_variant  # type: ignore


def _safe_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except Exception:
        return None
    return f if np.isfinite(f) else None


class FailureType(Enum):
    """Types of pattern failure"""
    NONE = "none"
    BUST_5PCT = "bust_5pct"      # Price reversed 5% against breakout
    BUST_10PCT = "bust_10pct"    # Price reversed 10% against breakout
    BOUNDARY = "boundary"        # Price crossed pattern boundary


class TargetMethod(Enum):
    """Methods for measuring target achievement"""
    INTRADAY = "intraday"  # Any touch of target level
    CLOSE = "close"        # Closing price at/above target


@dataclass
class PostBreakoutResult:
    """
    Evaluation results for a single pattern.

    All metrics use LOOK-AHEAD data and should NOT be used for detection.
    """
    # Identity
    pattern_id: str
    symbol: str
    pattern_name: str

    # Breakout info (from detection)
    breakout_date: Optional[str]
    breakout_price: Optional[float]
    breakout_direction: Optional[str]  # 'up' or 'down'
    target_price: Optional[float]
    stop_loss_price: Optional[float]

    # === FAILURE METRICS ===
    # Definition 1: Bust failure (price reversal from breakout)
    bust_failure_5pct: Optional[bool]   # Reversed >= 5% from breakout
    bust_failure_10pct: Optional[bool]  # Reversed >= 10% from breakout
    bust_failure_date: Optional[str]    # Date of first bust failure
    bust_failure_pct: Optional[float]   # Actual % reversal

    # Definition 2: Boundary invalidation
    boundary_invalidated: Optional[bool]  # Price crossed boundary
    boundary_invalidation_date: Optional[str]

    # === ULTIMATE PRICE METRICS ===
    ultimate_price: Optional[float]      # Ultimate low (bearish) or high (bullish)
    ultimate_date: Optional[str]
    days_to_ultimate: Optional[int]
    ultimate_stop_reason: Optional[str]  # '20pct_reversal', 'new_pattern', 'end_of_window'

    # === THROWBACK/PULLBACK METRICS ===
    throwback_pullback_occurred: Optional[bool]
    throwback_pullback_date: Optional[str]
    days_to_throwback_pullback: Optional[int]
    # Which level was retested
    retested_breakout_level: Optional[bool]    # Retested breakout price
    retested_boundary_level: Optional[bool]    # Retested pattern boundary

    # === TARGET METRICS ===
    target_achieved_intraday: Optional[bool]   # Target touched (intraday)
    target_achieved_close: Optional[bool]      # Target closed at/above
    target_achievement_date: Optional[str]
    days_to_target: Optional[int]

    # === EXCURSION METRICS ===
    max_favorable_excursion_pct: Optional[float]  # Max % in expected direction
    max_adverse_excursion_pct: Optional[float]    # Max % against expected

    # === VARIANT METRICS (Double patterns) ===
    variant: Optional[str] = None  # 'AA', 'AE', 'EA', 'EE' (Adam/Eve)
    variant_confidence: Optional[int] = None
    peak1_width_bars: Optional[int] = None
    peak2_width_bars: Optional[int] = None

    # Analysis metadata
    evaluation_window_bars: int = 252
    evaluation_date: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvaluationConfig:
    """Configuration for post-breakout evaluation"""
    # Window settings
    lookahead_bars: int = 252  # ~1 year of trading days

    # Ultimate price stop rules
    reversal_threshold_pct: float = 20.0  # 20% reversal stops ultimate search

    # Failure thresholds
    bust_failure_thresholds: Tuple[float, ...] = (5.0, 10.0)  # Standard thresholds

    # Throwback/Pullback settings
    throwback_window_days: int = 30  # Calendar days after breakout to count retests
    throwback_tolerance_pct: float = 1.0  # Within 1% of breakout = retest

    # Boundary invalidation gating (to reduce "any-time" false invalidations)
    invalidation_return_threshold_pct: float = 3.0
    invalidation_within_bars: int = 10

    # Variant classification (double tops) - Adam/Eve by peak width
    variant_peak_width_tolerance_pct: float = 2.0
    variant_peak_width_window_bars: int = 15
    variant_adam_max_peak_width_bars: int = 3
    variant_eve_min_peak_width_bars: int = 7

    # Target settings
    target_method: TargetMethod = TargetMethod.INTRADAY


class PostBreakoutEvaluator:
    """
    Evaluates pattern performance AFTER breakout using look-ahead data.

    IMPORTANT: This evaluator uses future data and should ONLY be used
    for statistical analysis, NOT for real-time detection.
    """

    def __init__(self, config: Optional[EvaluationConfig] = None):
        self.config = config or EvaluationConfig()
        self._digitized_spec_cache: Dict[str, Optional[Dict[str, Any]]] = {}

    def evaluate(self,
                 detection: Any,
                 df_full: pd.DataFrame,
                 pattern_boundary_price: Optional[float] = None,
                 pattern_height: Optional[float] = None) -> PostBreakoutResult:
        """
        Evaluate a pattern detection using look-ahead data.

        Args:
            detection: PatternDetection object from scanner
            df_full: Full OHLCV DataFrame (must extend beyond breakout)
            pattern_boundary_price: Trough price (bearish) or Peak price (bullish)
            pattern_height: Pattern height for calculations

        Returns:
            PostBreakoutResult with all evaluation metrics
        """
        # Find breakout index
        breakout_idx = self._find_breakout_index(detection, df_full)

        if breakout_idx is None or breakout_idx >= len(df_full) - 1:
            return self._empty_result(detection)

        breakout_date = self._to_date(getattr(detection, "breakout_date", None))
        if breakout_date is None and "date" in df_full.columns:
            try:
                breakout_date = self._to_date(df_full.iloc[breakout_idx]["date"])
            except Exception:
                breakout_date = None

        # Get evaluation window
        # IMPORTANT: post-breakout metrics must use bars AFTER the breakout bar,
        # otherwise throwback/pullback and bust can be trivially triggered on the breakout bar itself.
        start_idx = breakout_idx + 1
        lookahead_bars = self._pattern_lookahead_bars(str(getattr(detection, "pattern_name", "") or ""))
        window_end = min(start_idx + lookahead_bars, len(df_full))
        future_df = df_full.iloc[start_idx:window_end].copy()

        if len(future_df) < 2:
            return self._empty_result(detection)

        breakout_price = detection.breakout_price or df_full.iloc[breakout_idx]['close']
        try:
            breakout_price = float(breakout_price)
        except Exception:
            return self._empty_result(detection)
        if not np.isfinite(breakout_price) or breakout_price <= 0:
            return self._empty_result(detection)

        direction = detection.breakout_direction or self._infer_direction(detection)

        # Infer boundary/height when not supplied by the caller.
        if pattern_boundary_price is None:
            pattern_boundary_price = self._infer_boundary_price(detection, df_full)
        breakout_level, opposite_level = self._infer_breakout_and_opposite_levels(detection, df_full, breakout_idx, breakout_price, direction)
        opposite_boundary_price = opposite_level
        if pattern_height is None:
            pattern_height = self._infer_pattern_height(detection, breakout_price)

        variant, variant_confidence, peak1_w, peak2_w = self._classify_double_pattern_variant(detection, df_full)

        # Evaluate based on breakout direction
        if direction == 'down' or detection.pattern_type == 'reversal_bearish':
            res = self._evaluate_bearish(
                detection, future_df, breakout_idx, breakout_price,
                breakout_level, opposite_boundary_price, pattern_height, breakout_date
            )
        else:
            res = self._evaluate_bullish(
                detection, future_df, breakout_idx, breakout_price,
                breakout_level, opposite_boundary_price, pattern_height, breakout_date
            )

        res.variant = variant
        res.variant_confidence = variant_confidence
        res.peak1_width_bars = peak1_w
        res.peak2_width_bars = peak2_w
        res.evaluation_window_bars = int(len(future_df))
        return res

    def _evaluate_bearish(self,
                          detection: Any,
                          future_df: pd.DataFrame,
                          breakout_idx: int,
                          breakout_price: float,
                          breakout_level: Optional[float],
                          opposite_boundary_price: Optional[float],
                          pattern_height: Optional[float],
                          breakout_date: Optional[date]) -> PostBreakoutResult:
        """Evaluate bearish pattern (expected downward move)"""

        # === BUSTED PATTERN (Bulkowski-style) ===
        # "Busted" = moved less than X% in breakout direction, then reversed by >= X%.
        cumulative_close_high = future_df["close"].expanding().max()
        adverse_pct_series = (cumulative_close_high - breakout_price) / breakout_price * 100
        max_adverse_pct = float(adverse_pct_series.max()) if len(adverse_pct_series) else 0.0

        max_favorable_pct_close = (breakout_price - float(future_df["close"].min())) / breakout_price * 100
        if not np.isfinite(max_favorable_pct_close):
            max_favorable_pct_close = 0.0
        max_favorable_pct_close = max(0.0, float(max_favorable_pct_close))

        t1 = float(self.config.bust_failure_thresholds[0]) if self.config.bust_failure_thresholds else 5.0
        t2 = float(self.config.bust_failure_thresholds[1]) if len(self.config.bust_failure_thresholds) > 1 else 10.0

        bust_5pct = bool((max_favorable_pct_close < t1) and (max_adverse_pct >= t1))
        bust_10pct = bool((max_favorable_pct_close < t2) and (max_adverse_pct >= t2))

        bust_failure_date = None
        bust_failure_pct = None
        bust_thr = None
        if bust_5pct:
            bust_thr = t1
        elif bust_10pct:
            bust_thr = t2

        if bust_thr is not None:
            bust_mask = adverse_pct_series >= bust_thr
            if bool(bust_mask.any()) and "date" in future_df.columns:
                first_bust_idx = int(bust_mask[bust_mask].index[0])
                bust_dt = self._to_date(future_df.loc[first_bust_idx, "date"])
                bust_failure_date = str(bust_dt) if bust_dt is not None else None
            bust_failure_pct = round(max_adverse_pct, 2) if np.isfinite(max_adverse_pct) else None

        # Definition 2: Boundary invalidation
        boundary_invalidated = None
        boundary_invalidation_date = None
        if opposite_boundary_price is not None:
            try:
                bp = float(opposite_boundary_price)
            except Exception:
                bp = None
            if bp is None or not np.isfinite(bp) or bp <= 0:
                bp = None
            if bp is None:
                pass
            else:
                thr = bp * (1.0 + self.config.invalidation_return_threshold_pct / 100.0)
                boundary_mask = future_df["close"] >= thr
                boundary_invalidated = bool(boundary_mask.any())
                if boundary_invalidated:
                    first_invalid_idx = boundary_mask[boundary_mask].index[0]
                    inv_dt = self._to_date(future_df.loc[first_invalid_idx, "date"]) if "date" in future_df.columns else None
                    boundary_invalidation_date = str(inv_dt) if inv_dt is not None else None

        # === ULTIMATE LOW ===
        ultimate_price, ultimate_date, days_to_ultimate, stop_reason = \
            self._find_ultimate_bearish(future_df, breakout_price, breakout_date)

        # === THROWBACK ===
        # Retest of breakout level within 30 days, then resumes decline (Bulkowski-style).
        throwback_occurred = None
        throwback_date = None
        days_to_throwback = None
        retested_breakout = None
        retested_boundary = None

        tolerance = self.config.throwback_tolerance_pct / 100
        throw_level = breakout_level if breakout_level is not None else breakout_price

        window_df = future_df
        if breakout_date is not None and "date" in future_df.columns:
            cutoff = breakout_date + timedelta(days=int(self.config.throwback_window_days))
            window_df = future_df[future_df["date"].dt.date <= cutoff]
            if window_df.empty:
                window_df = future_df.iloc[:0]

        breakout_retest_mask = (
            window_df["high"] >= breakout_price * (1 - tolerance) if not window_df.empty else None
        )
        boundary_retest_mask = (
            window_df["high"] >= throw_level * (1 - tolerance) if not window_df.empty else None
        )

        throwback_occurred = bool(boundary_retest_mask.any()) if boundary_retest_mask is not None else False

        if throwback_occurred:
            first_throwback_idx = boundary_retest_mask[boundary_retest_mask].index[0]
            tb_dt = self._to_date(window_df.loc[first_throwback_idx, "date"]) if "date" in window_df.columns else None
            throwback_date = str(tb_dt) if tb_dt is not None else None
            days_to_throwback = self._days_between(breakout_date, tb_dt)
            retested_breakout = bool(breakout_retest_mask.any()) if breakout_retest_mask is not None else None
            retested_boundary = True

            # Resume check: after the retest, price should make a new low vs the lows before retest.
            try:
                pos = int(future_df.index.get_loc(first_throwback_idx))
            except Exception:
                pos = None
            if pos is not None:
                pre_low = _safe_float(future_df.iloc[: pos + 1]["low"].min())
                post_low = _safe_float(future_df.iloc[pos + 1 :]["low"].min()) if pos + 1 < len(future_df) else None
                if pre_low is not None and post_low is not None:
                    if not (post_low < pre_low):
                        throwback_occurred = False
                        throwback_date = None
                        days_to_throwback = None

        # Also check boundary retest
        if not throwback_occurred:
            retested_breakout = bool(breakout_retest_mask.any()) if breakout_retest_mask is not None else None
            retested_boundary = bool(boundary_retest_mask.any()) if boundary_retest_mask is not None else None

        # === TARGET ACHIEVEMENT ===
        target_achieved_intraday = None
        target_achieved_close = None
        target_date = None
        days_to_target = None

        if detection.target_price is not None:
            # Intraday: any touch
            intraday_mask = future_df["low"] <= detection.target_price
            target_achieved_intraday = bool(intraday_mask.any())
            if target_achieved_intraday:
                first_target_idx = intraday_mask[intraday_mask].index[0]
                t_dt = self._to_date(future_df.loc[first_target_idx, "date"]) if "date" in future_df.columns else None
                target_date = str(t_dt) if t_dt is not None else None
                days_to_target = self._days_between(breakout_date, t_dt)

            # Close: closing price at or below target
            close_mask = future_df["close"] <= detection.target_price
            target_achieved_close = bool(close_mask.any())

        # === EXCURSION ===
        max_favorable_pct = None
        if ultimate_price is not None and breakout_price > 0:
            max_favorable_pct = (breakout_price - float(ultimate_price)) / breakout_price * 100
            if not np.isfinite(max_favorable_pct):
                max_favorable_pct = None
            elif max_favorable_pct < 0:
                max_favorable_pct = 0.0

        max_adverse_pct_exc = None
        if breakout_price > 0:
            try:
                adverse_high = float(future_df["high"].max())
            except Exception:
                adverse_high = None
            if adverse_high is not None and np.isfinite(adverse_high):
                max_adverse_pct_exc = (adverse_high - breakout_price) / breakout_price * 100
                if not np.isfinite(max_adverse_pct_exc):
                    max_adverse_pct_exc = None
                elif max_adverse_pct_exc < 0:
                    max_adverse_pct_exc = 0.0

        return PostBreakoutResult(
            pattern_id=detection.pattern_id,
            symbol=detection.symbol,
            pattern_name=detection.pattern_name,
            breakout_date=detection.breakout_date,
            breakout_price=breakout_price,
            breakout_direction='down',
            target_price=detection.target_price,
            stop_loss_price=detection.stop_loss_price,
            # Failures
            bust_failure_5pct=bust_5pct,
            bust_failure_10pct=bust_10pct,
            bust_failure_date=bust_failure_date,
            bust_failure_pct=bust_failure_pct,
            boundary_invalidated=boundary_invalidated,
            boundary_invalidation_date=boundary_invalidation_date,
            # Ultimate
            ultimate_price=ultimate_price,
            ultimate_date=ultimate_date,
            days_to_ultimate=days_to_ultimate,
            ultimate_stop_reason=stop_reason,
            # Throwback
            throwback_pullback_occurred=throwback_occurred,
            throwback_pullback_date=throwback_date,
            days_to_throwback_pullback=days_to_throwback,
            retested_breakout_level=retested_breakout,
            retested_boundary_level=retested_boundary,
            # Target
            target_achieved_intraday=target_achieved_intraday,
            target_achieved_close=target_achieved_close,
            target_achievement_date=target_date,
            days_to_target=days_to_target,
            # Excursion
            max_favorable_excursion_pct=round(float(max_favorable_pct), 2) if max_favorable_pct is not None else None,
            max_adverse_excursion_pct=round(float(max_adverse_pct_exc), 2) if max_adverse_pct_exc is not None else None,
            evaluation_window_bars=int(len(future_df)),
        )

    def _evaluate_bullish(self,
                          detection: Any,
                          future_df: pd.DataFrame,
                          breakout_idx: int,
                          breakout_price: float,
                          breakout_level: Optional[float],
                          opposite_boundary_price: Optional[float],
                          pattern_height: Optional[float],
                          breakout_date: Optional[date]) -> PostBreakoutResult:
        """Evaluate bullish pattern (expected upward move)"""

        # === BUSTED PATTERN (Bulkowski-style) ===
        cumulative_close_low = future_df["close"].expanding().min()
        adverse_pct_series = (breakout_price - cumulative_close_low) / breakout_price * 100
        max_adverse_pct = float(adverse_pct_series.max()) if len(adverse_pct_series) else 0.0

        max_favorable_pct_close = (float(future_df["close"].max()) - breakout_price) / breakout_price * 100
        if not np.isfinite(max_favorable_pct_close):
            max_favorable_pct_close = 0.0
        max_favorable_pct_close = max(0.0, float(max_favorable_pct_close))

        t1 = float(self.config.bust_failure_thresholds[0]) if self.config.bust_failure_thresholds else 5.0
        t2 = float(self.config.bust_failure_thresholds[1]) if len(self.config.bust_failure_thresholds) > 1 else 10.0

        bust_5pct = bool((max_favorable_pct_close < t1) and (max_adverse_pct >= t1))
        bust_10pct = bool((max_favorable_pct_close < t2) and (max_adverse_pct >= t2))

        bust_failure_date = None
        bust_failure_pct = None
        bust_thr = None
        if bust_5pct:
            bust_thr = t1
        elif bust_10pct:
            bust_thr = t2
        if bust_thr is not None:
            bust_mask = adverse_pct_series >= bust_thr
            if bool(bust_mask.any()) and "date" in future_df.columns:
                first_bust_idx = int(bust_mask[bust_mask].index[0])
                bust_dt = self._to_date(future_df.loc[first_bust_idx, "date"])
                bust_failure_date = str(bust_dt) if bust_dt is not None else None
            bust_failure_pct = round(max_adverse_pct, 2) if np.isfinite(max_adverse_pct) else None

        # Definition 2: Boundary invalidation
        boundary_invalidated = None
        boundary_invalidation_date = None
        if opposite_boundary_price is not None:
            try:
                bp = float(opposite_boundary_price)
            except Exception:
                bp = None
            if bp is None or not np.isfinite(bp) or bp <= 0:
                bp = None
            if bp is None:
                pass
            else:
                thr = bp * (1.0 - self.config.invalidation_return_threshold_pct / 100.0)
                # For bullish: invalidation when close returns below boundary by a threshold.
                boundary_mask = future_df["close"] <= thr
                boundary_invalidated = bool(boundary_mask.any())
                if boundary_invalidated:
                    first_invalid_idx = boundary_mask[boundary_mask].index[0]
                    inv_dt = self._to_date(future_df.loc[first_invalid_idx, "date"]) if "date" in future_df.columns else None
                    boundary_invalidation_date = str(inv_dt) if inv_dt is not None else None

        # === ULTIMATE HIGH ===
        ultimate_price, ultimate_date, days_to_ultimate, stop_reason = \
            self._find_ultimate_bullish(future_df, breakout_price, breakout_date)

        # === PULLBACK ===
        # Retest of breakout level within 30 days, then resumes rise (Bulkowski-style).
        tolerance = self.config.throwback_tolerance_pct / 100
        pull_level = breakout_level if breakout_level is not None else breakout_price

        window_df = future_df
        if breakout_date is not None and "date" in future_df.columns:
            cutoff = breakout_date + timedelta(days=int(self.config.throwback_window_days))
            window_df = future_df[future_df["date"].dt.date <= cutoff]
            if window_df.empty:
                window_df = future_df.iloc[:0]

        breakout_retest_mask = window_df["low"] <= breakout_price * (1 + tolerance) if not window_df.empty else None
        boundary_retest_mask = window_df["low"] <= pull_level * (1 + tolerance) if not window_df.empty else None
        pullback_mask = boundary_retest_mask
        pullback_occurred = bool(pullback_mask.any()) if pullback_mask is not None else False

        pullback_date = None
        days_to_pullback = None
        retested_breakout = None
        retested_boundary = None

        if pullback_occurred:
            first_pullback_idx = pullback_mask[pullback_mask].index[0]
            pb_dt = self._to_date(window_df.loc[first_pullback_idx, "date"]) if "date" in window_df.columns else None
            pullback_date = str(pb_dt) if pb_dt is not None else None
            days_to_pullback = self._days_between(breakout_date, pb_dt)
            retested_breakout = bool(breakout_retest_mask.any()) if breakout_retest_mask is not None else None
            retested_boundary = True

            # Resume check: after the retest, price should make a new high vs the highs before retest.
            try:
                pos = int(future_df.index.get_loc(first_pullback_idx))
            except Exception:
                pos = None
            if pos is not None:
                pre_high = _safe_float(future_df.iloc[: pos + 1]["high"].max())
                post_high = _safe_float(future_df.iloc[pos + 1 :]["high"].max()) if pos + 1 < len(future_df) else None
                if pre_high is not None and post_high is not None:
                    if not (post_high > pre_high):
                        pullback_occurred = False
                        pullback_date = None
                        days_to_pullback = None

        if not pullback_occurred:
            retested_breakout = bool(breakout_retest_mask.any()) if breakout_retest_mask is not None else None
            retested_boundary = bool(boundary_retest_mask.any()) if boundary_retest_mask is not None else None

        # === TARGET ACHIEVEMENT ===
        target_achieved_intraday = None
        target_achieved_close = None
        target_date = None
        days_to_target = None

        if detection.target_price is not None:
            intraday_mask = future_df['high'] >= detection.target_price
            target_achieved_intraday = bool(intraday_mask.any())
            if target_achieved_intraday:
                first_target_idx = intraday_mask[intraday_mask].index[0]
                t_dt = self._to_date(future_df.loc[first_target_idx, "date"]) if "date" in future_df.columns else None
                target_date = str(t_dt) if t_dt is not None else None
                days_to_target = self._days_between(breakout_date, t_dt)

            close_mask = future_df['close'] >= detection.target_price
            target_achieved_close = bool(close_mask.any())

        # === EXCURSION ===
        max_favorable_pct = None
        if ultimate_price is not None and breakout_price > 0:
            max_favorable_pct = (float(ultimate_price) - breakout_price) / breakout_price * 100
            if not np.isfinite(max_favorable_pct):
                max_favorable_pct = None
            elif max_favorable_pct < 0:
                max_favorable_pct = 0.0

        max_adverse_pct_exc = None
        if breakout_price > 0:
            try:
                adverse_low = float(future_df["low"].min())
            except Exception:
                adverse_low = None
            if adverse_low is not None and np.isfinite(adverse_low):
                max_adverse_pct_exc = (breakout_price - adverse_low) / breakout_price * 100
                if not np.isfinite(max_adverse_pct_exc):
                    max_adverse_pct_exc = None
                elif max_adverse_pct_exc < 0:
                    max_adverse_pct_exc = 0.0

        return PostBreakoutResult(
            pattern_id=detection.pattern_id,
            symbol=detection.symbol,
            pattern_name=detection.pattern_name,
            breakout_date=detection.breakout_date,
            breakout_price=breakout_price,
            breakout_direction='up',
            target_price=detection.target_price,
            stop_loss_price=detection.stop_loss_price,
            bust_failure_5pct=bust_5pct,
            bust_failure_10pct=bust_10pct,
            bust_failure_date=bust_failure_date,
            bust_failure_pct=bust_failure_pct,
            boundary_invalidated=boundary_invalidated,
            boundary_invalidation_date=boundary_invalidation_date,
            ultimate_price=ultimate_price,
            ultimate_date=ultimate_date,
            days_to_ultimate=days_to_ultimate,
            ultimate_stop_reason=stop_reason,
            throwback_pullback_occurred=pullback_occurred,
            throwback_pullback_date=pullback_date,
            days_to_throwback_pullback=days_to_pullback,
            retested_breakout_level=retested_breakout,
            retested_boundary_level=retested_boundary,
            target_achieved_intraday=target_achieved_intraday,
            target_achieved_close=target_achieved_close,
            target_achievement_date=target_date,
            days_to_target=days_to_target,
            max_favorable_excursion_pct=round(float(max_favorable_pct), 2) if max_favorable_pct is not None else None,
            max_adverse_excursion_pct=round(float(max_adverse_pct_exc), 2) if max_adverse_pct_exc is not None else None,
            evaluation_window_bars=int(len(future_df)),
        )

    def _find_ultimate_bearish(
        self,
        future_df: pd.DataFrame,
        breakout_price: float,
        breakout_date: Optional[date],
    ) -> Tuple[Optional[float], Optional[str], Optional[int], Optional[str]]:
        """
        Find ultimate low for bearish pattern.

        Stops when:
        1. 20% reversal upward from lowest point
        2. End of window (252 bars)
        """
        if len(future_df) == 0:
            return None, None, None, None

        running_low = float('inf')
        running_low_idx = None

        for i, (idx, row) in enumerate(future_df.iterrows()):
            low = row['low']

            if low < running_low:
                running_low = low
                running_low_idx = idx

            # Check for 20% reversal
            if running_low < breakout_price:
                reversal_pct = (row['high'] - running_low) / running_low * 100
                if reversal_pct >= self.config.reversal_threshold_pct:
                    # Stopped by reversal
                    ult_dt = self._to_date(future_df.loc[running_low_idx, "date"]) if "date" in future_df.columns else None
                    ultimate_date = str(ult_dt) if ult_dt is not None else None
                    days = self._days_between(breakout_date, ult_dt)
                    return running_low, ultimate_date, days, '20pct_reversal'

        # End of window
        if running_low_idx is not None:
            ult_dt = self._to_date(future_df.loc[running_low_idx, "date"]) if "date" in future_df.columns else None
            ultimate_date = str(ult_dt) if ult_dt is not None else None
            days = self._days_between(breakout_date, ult_dt)
            return running_low, ultimate_date, days, 'end_of_window'

        return None, None, None, None

    def _find_ultimate_bullish(
        self,
        future_df: pd.DataFrame,
        breakout_price: float,
        breakout_date: Optional[date],
    ) -> Tuple[Optional[float], Optional[str], Optional[int], Optional[str]]:
        """
        Find ultimate high for bullish pattern.

        Stops when:
        1. 20% reversal downward from highest point
        2. End of window (252 bars)
        """
        if len(future_df) == 0:
            return None, None, None, None

        running_high = 0
        running_high_idx = None

        for i, (idx, row) in enumerate(future_df.iterrows()):
            high = row['high']

            if high > running_high:
                running_high = high
                running_high_idx = idx

            # Check for 20% reversal
            if running_high > breakout_price:
                reversal_pct = (running_high - row['low']) / running_high * 100
                if reversal_pct >= self.config.reversal_threshold_pct:
                    ult_dt = self._to_date(future_df.loc[running_high_idx, "date"]) if "date" in future_df.columns else None
                    ultimate_date = str(ult_dt) if ult_dt is not None else None
                    days = self._days_between(breakout_date, ult_dt)
                    return running_high, ultimate_date, days, '20pct_reversal'

        if running_high_idx is not None:
            ult_dt = self._to_date(future_df.loc[running_high_idx, "date"]) if "date" in future_df.columns else None
            ultimate_date = str(ult_dt) if ult_dt is not None else None
            days = self._days_between(breakout_date, ult_dt)
            return running_high, ultimate_date, days, 'end_of_window'

        return None, None, None, None

    def _digitized_specs_dir(self) -> str:
        # Repo layout: <root>/scanner/post_breakout_analyzer.py
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
        return os.path.join(root, "extraction_phase_1", "digitization", "patterns_digitized")

    def _load_digitized_spec(self, pattern_name: str) -> Optional[Dict[str, Any]]:
        if pattern_name in self._digitized_spec_cache:
            return self._digitized_spec_cache[pattern_name]

        # Bulkowski-53 derived pattern keys often do not have dedicated *_digitized.json files.
        # Map them back to their base digitized spec where appropriate so evaluation can still
        # use per-pattern lookahead and breakout thresholds.
        aliases: Dict[str, str] = {
            # Broadening/BARR/Cup
            "bump_and_run_reversal_bottoms": "bump_and_run_reversal",
            "bump_and_run_reversal_tops": "bump_and_run_reversal",
            "cup_with_handle_inverted": "cup_with_handle",
            # Diamonds
            "diamond_bottoms": "diamond_bottom",
            "diamond_tops": "diamond_top",
            # Double patterns
            "double_bottoms_adam_adam": "double_bottoms",
            "double_bottoms_adam_eve": "double_bottoms",
            "double_bottoms_eve_adam": "double_bottoms",
            "double_bottoms_eve_eve": "double_bottoms",
            "double_tops_adam_adam": "double_tops",
            "double_tops_adam_eve": "double_tops",
            "double_tops_eve_adam": "double_tops",
            "double_tops_eve_eve": "double_tops",
            # Flags
            "flags_high_tight": "flags",
            # Head and shoulders
            "head_and_shoulders_bottoms": "head_and_shoulders_bottom",
            "head_and_shoulders_bottoms_complex": "head_and_shoulders_bottom",
            "head_and_shoulders_tops": "head_and_shoulders_top",
            "head_and_shoulders_tops_complex": "head_and_shoulders_top",
            # Horns
            "horn_bottoms": "horn_bottoms_tops",
            "horn_tops": "horn_bottoms_tops",
            # Islands
            "island_reversals": "islands",
            "islands_long": "islands",
            # Measured moves
            "measured_move_down": "measured_move_down_up",
            "measured_move_up": "measured_move_down_up",
            # Pipes
            "pipe_tops": "pipe_bottoms",
            # Rectangles
            "rectangle_bottoms": "rectangle_bottoms_tops",
            "rectangle_tops": "rectangle_bottoms_tops",
            # Rounding
            "rounding_bottoms": "rounding_bottoms_tops",
            "rounding_tops": "rounding_bottoms_tops",
            # Scallops
            "scallops_ascending": "scallop_ascending_descending",
            "scallops_ascending_inverted": "scallop_ascending_descending",
            "scallops_descending": "scallop_ascending_descending",
            "scallops_descending_inverted": "scallop_ascending_descending",
            # Triangles
            "triangles_ascending": "triangles",
            "triangles_descending": "triangles",
            "triangles_symmetrical": "triangles",
            # Triple patterns
            "triple_bottoms": "triple_bottoms_tops",
            "triple_tops": "triple_bottoms_tops",
            # Wedges
            "wedges_falling": "wedges_ascending_descending",
            "wedges_rising": "wedges_ascending_descending",
        }

        spec_key = str(pattern_name)
        spec_path = os.path.join(self._digitized_specs_dir(), f"{spec_key}_digitized.json")
        if not os.path.exists(spec_path):
            alias = aliases.get(spec_key)
            if alias:
                spec_path = os.path.join(self._digitized_specs_dir(), f"{alias}_digitized.json")
            if not os.path.exists(spec_path):
                self._digitized_spec_cache[pattern_name] = None
                return None

        try:
            with open(spec_path, "r", encoding="utf-8") as f:
                spec = json.load(f)
        except Exception:
            self._digitized_spec_cache[pattern_name] = None
            return None

        if not isinstance(spec, dict):
            self._digitized_spec_cache[pattern_name] = None
            return None

        self._digitized_spec_cache[pattern_name] = spec
        return spec

    def _pattern_lookahead_bars(self, pattern_name: str) -> int:
        """
        Use per-pattern lookahead_bars from digitized specs when available.
        Falls back to global config.lookahead_bars.
        """
        lookahead = None
        spec = self._load_digitized_spec(pattern_name)
        if spec:
            try:
                pb = spec.get("post_breakout_measurement", {}) or {}
                lookahead = pb.get("lookahead_bars", None)
            except Exception:
                lookahead = None

        try:
            cfg = int(self.config.lookahead_bars)
        except Exception:
            cfg = 252
        if cfg <= 0:
            cfg = 252

        try:
            if lookahead is not None:
                la = int(lookahead)
                if la > 0:
                    return min(cfg, la)
        except Exception:
            pass
        return cfg

    @staticmethod
    def _to_date(v: Any) -> Optional[date]:
        if v is None:
            return None
        if isinstance(v, date) and not isinstance(v, datetime):
            return v
        try:
            ts = pd.to_datetime(v)
            if pd.isna(ts):
                return None
            return ts.date()
        except Exception:
            return None

    @staticmethod
    def _days_between(start: Optional[date], end: Optional[date]) -> Optional[int]:
        if start is None or end is None:
            return None
        try:
            return int((end - start).days)
        except Exception:
            return None

    def _find_breakout_index(self, detection: Any, df: pd.DataFrame) -> Optional[int]:
        """Find the index of breakout in the DataFrame"""
        bi = getattr(detection, "breakout_idx", None)
        if bi is not None:
            try:
                bi_int = int(bi)
            except Exception:
                bi_int = None
            if bi_int is not None and 0 <= bi_int < len(df):
                return bi_int

        if detection.breakout_date and 'date' in df.columns:
            try:
                s = df["date"].dt.date.astype(str)
                mask = s == str(detection.breakout_date)
                if bool(mask.any()):
                    # Index is a RangeIndex in our pipeline; cast defensively.
                    return int(mask[mask].index[0])
            except Exception:
                # Fallback: slow path
                for _, (idx, row) in enumerate(df.iterrows()):
                    if str(row['date'].date()) == detection.breakout_date:
                        return int(idx) if isinstance(idx, (int, np.integer)) else None
        return None

    def _infer_direction(self, detection: Any) -> str:
        """Infer breakout direction from pattern type"""
        pt = str(getattr(detection, "pattern_type", "") or "").lower()
        if "bullish" in pt:
            return "up"
        if "bearish" in pt:
            return "down"
        return "down"

    def _infer_boundary_price(self, detection: Any, df_full: pd.DataFrame) -> Optional[float]:
        """
        Infer a reasonable "pattern boundary" price level for boundary invalidation / retest metrics.

        We prefer using pivot_indices + breakout_direction so this works for both legacy and
        digitized scanners without needing extra fields persisted in detections.
        """
        pattern_name = str(getattr(detection, "pattern_name", "") or "")
        double_family = self._double_family_name(detection)
        hs_family = self._head_shoulders_family_name(detection)

        pivots = self._extract_pivot_indices(detection, df_full)

        bdir = getattr(detection, "breakout_direction", None) or self._infer_direction(detection)

        try:
            if double_family == "double_tops" and len(pivots) >= 2:
                return float(df_full.iloc[pivots[1]]["low"])
            if double_family == "double_bottoms" and len(pivots) >= 2:
                return float(df_full.iloc[pivots[1]]["high"])
            if hs_family == "head_and_shoulders_top" and len(pivots) >= 4:
                nl1 = float(df_full.iloc[pivots[1]]["low"])
                nl2 = float(df_full.iloc[pivots[3]]["low"])
                return (nl1 + nl2) / 2.0
            if hs_family == "head_and_shoulders_bottom" and len(pivots) >= 4:
                nl1 = float(df_full.iloc[pivots[1]]["high"])
                nl2 = float(df_full.iloc[pivots[3]]["high"])
                return (nl1 + nl2) / 2.0
        except Exception:
            # Fall back to generic logic below.
            pass

        try:
            if pivots and bdir == "down":
                vals = [float(df_full.iloc[i]["low"]) for i in pivots]
                return float(min(vals)) if vals else None
            if pivots and bdir == "up":
                vals = [float(df_full.iloc[i]["high"]) for i in pivots]
                return float(max(vals)) if vals else None
        except Exception:
            pass

        # Last resort: use stop_loss_price if it's available and sane.
        stop = getattr(detection, "stop_loss_price", None)
        try:
            stop_f = float(stop) if stop is not None else None
        except Exception:
            stop_f = None
        if stop_f is not None and np.isfinite(stop_f) and stop_f > 0:
            return stop_f
        return None

    def _infer_opposite_boundary_price(self, detection: Any, df_full: pd.DataFrame) -> Optional[float]:
        """
        Infer the *opposite side* of the pattern for "ultimate failure" checks.

        This is intentionally generic: for an upward breakout, opposite boundary is support (min low);
        for a downward breakout, opposite boundary is resistance (max high).
        """
        # Prefer stop_loss_price when provided by the scanner (digitized scanners set this
        # to the opposite boundary at breakout time).
        stop = getattr(detection, "stop_loss_price", None)
        try:
            stop_f = float(stop) if stop is not None else None
        except Exception:
            stop_f = None
        if stop_f is not None and np.isfinite(stop_f) and stop_f > 0:
            return stop_f

        pivots = self._extract_pivot_indices(detection, df_full)
        if not pivots:
            return None

        bdir = getattr(detection, "breakout_direction", None) or self._infer_direction(detection)
        try:
            if bdir == "down":
                vals = [float(df_full.iloc[i]["high"]) for i in pivots]
                vals = [v for v in vals if np.isfinite(v) and v > 0]
                return float(max(vals)) if vals else None
            if bdir == "up":
                vals = [float(df_full.iloc[i]["low"]) for i in pivots]
                vals = [v for v in vals if np.isfinite(v) and v > 0]
                return float(min(vals)) if vals else None
        except Exception:
            return None
        return None

    def _infer_breakout_and_opposite_levels(
        self,
        detection: Any,
        df_full: pd.DataFrame,
        breakout_idx: int,
        breakout_price: float,
        direction: str,
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Infer (breakout_level, opposite_level) at breakout time.

        Priority:
          1) Reconstruct boundaries from digitized pivot_sequence when possible (matches PivotSequenceScanner).
          2) Use stop_loss_price for opposite boundary (already computed by digitized scanners).
          3) Approximate breakout boundary from breakout_price and breakout_threshold_pct.
        """
        pattern_name = str(getattr(detection, "pattern_name", "") or "")
        pivot_indices = self._extract_pivot_indices(detection, df_full)

        # 1) Pivot-sequence boundary reconstruction (most digitized patterns).
        spec = self._load_digitized_spec(pattern_name)
        if spec and pivot_indices:
            seq = (spec.get("detection_signature", {}) or {}).get("pivot_sequence")
            if isinstance(seq, list) and len(seq) == len(pivot_indices):
                highs: List[Tuple[int, float]] = []
                lows: List[Tuple[int, float]] = []
                for tok, pi in zip(seq, pivot_indices):
                    if not (0 <= int(pi) < len(df_full)):
                        highs = []
                        lows = []
                        break
                    if tok == "H":
                        v = _safe_float(df_full.iloc[int(pi)].get("high"))
                        if v is not None and v > 0:
                            highs.append((int(pi), float(v)))
                    elif tok == "L":
                        v = _safe_float(df_full.iloc[int(pi)].get("low"))
                        if v is not None and v > 0:
                            lows.append((int(pi), float(v)))

                def _value_at(points: List[Tuple[int, float]], idx: int) -> Optional[float]:
                    if not points:
                        return None
                    if len(points) == 1:
                        return float(points[0][1])
                    (x0, y0), (x1, y1) = points[0], points[-1]
                    dx = max(1, int(x1) - int(x0))
                    slope = (float(y1) - float(y0)) / float(dx)
                    return float(y0) + slope * float(int(idx) - int(x0))

                upper = _value_at(highs, breakout_idx)
                lower = _value_at(lows, breakout_idx)

                if direction == "up":
                    breakout_level = upper
                    opposite_level = lower
                else:
                    breakout_level = lower
                    opposite_level = upper

                # Refine opposite with stop_loss when available (scanner-calculated).
                stop = getattr(detection, "stop_loss_price", None)
                try:
                    stop_f = float(stop) if stop is not None else None
                except Exception:
                    stop_f = None
                if stop_f is not None and np.isfinite(stop_f) and stop_f > 0:
                    opposite_level = stop_f

                if breakout_level is not None:
                    try:
                        breakout_level = float(breakout_level)
                    except Exception:
                        breakout_level = None
                if opposite_level is not None:
                    try:
                        opposite_level = float(opposite_level)
                    except Exception:
                        opposite_level = None

                if breakout_level is not None and np.isfinite(breakout_level) and breakout_level > 0:
                    return breakout_level, opposite_level

        # 2) Opposite from stop_loss if present.
        opposite_level = self._infer_opposite_boundary_price(detection, df_full)

        # 3) Approximate breakout boundary using breakout threshold from digitized spec.
        thr_pct = None
        if spec:
            try:
                bo = spec.get("breakout_confirmation", {}) or {}
                thr_pct = float(bo.get("breakout_threshold_pct") or 0.0) / 100.0
            except Exception:
                thr_pct = None
        if thr_pct is not None and np.isfinite(thr_pct) and 0 <= thr_pct < 0.5 and breakout_price > 0:
            if direction == "up":
                breakout_level = breakout_price / (1.0 + thr_pct) if (1.0 + thr_pct) > 0 else None
            else:
                breakout_level = breakout_price / (1.0 - thr_pct) if (1.0 - thr_pct) > 0 else None
            if breakout_level is not None and np.isfinite(breakout_level) and breakout_level > 0:
                return float(breakout_level), opposite_level

        return None, opposite_level

    @staticmethod
    def _extract_pivot_indices(detection: Any, df_full: pd.DataFrame) -> List[int]:
        piv = getattr(detection, "pivot_indices", None)
        if isinstance(piv, str):
            try:
                piv = json.loads(piv)
            except Exception:
                piv = None
        pivots: List[int] = []
        if isinstance(piv, (list, tuple)):
            for x in piv:
                try:
                    xi = int(x)
                except Exception:
                    continue
                if 0 <= xi < len(df_full):
                    pivots.append(xi)
        return pivots

    def _infer_pattern_height(self, detection: Any, breakout_price: float) -> Optional[float]:
        """
        Infer pattern height in *price units*.

        Prefer using target_price when available: height_abs = |target - breakout|.
        """
        tp = getattr(detection, "target_price", None)
        if tp is None:
            return None
        try:
            tp_f = float(tp)
        except Exception:
            return None
        height = abs(tp_f - float(breakout_price))
        return height if np.isfinite(height) and height > 0 else None

    def _double_family_name(self, detection: Any) -> Optional[str]:
        base = str(getattr(detection, "base_pattern_name", "") or "")
        if base in ("double_tops", "double_bottoms"):
            return base

        pattern_name = str(getattr(detection, "pattern_name", "") or "")
        if pattern_name == "double_tops" or pattern_name.startswith("double_tops_"):
            return "double_tops"
        if pattern_name == "double_bottoms" or pattern_name.startswith("double_bottoms_"):
            return "double_bottoms"
        return None

    def _head_shoulders_family_name(self, detection: Any) -> Optional[str]:
        base = str(getattr(detection, "base_pattern_name", "") or "")
        if base in ("head_and_shoulders_top", "head_and_shoulders_bottom"):
            return base

        pattern_name = str(getattr(detection, "pattern_name", "") or "")
        if pattern_name == "head_and_shoulders_top" or pattern_name.startswith("head_and_shoulders_tops"):
            return "head_and_shoulders_top"
        if pattern_name == "head_and_shoulders_bottom" or pattern_name.startswith("head_and_shoulders_bottoms"):
            return "head_and_shoulders_bottom"
        return None

    def _classify_double_pattern_variant(
        self, detection: Any, df_full: pd.DataFrame
    ) -> Tuple[Optional[str], Optional[int], Optional[int], Optional[int]]:
        family = self._double_family_name(detection)
        if family is None:
            return None, None, None, None

        code = getattr(detection, "variant_code", None)
        confidence = getattr(detection, "variant_confidence", None)
        first_width = getattr(detection, "first_extreme_width_bars", None)
        second_width = getattr(detection, "second_extreme_width_bars", None)
        if code is not None or first_width is not None or second_width is not None:
            return (
                str(code) if code else None,
                int(confidence) if confidence is not None else None,
                int(first_width) if first_width is not None else None,
                int(second_width) if second_width is not None else None,
            )

        piv = getattr(detection, "pivot_indices", None)
        if not isinstance(piv, (list, tuple)) or len(piv) < 3:
            return None, None, None, None

        try:
            first_idx = int(piv[0])
            second_idx = int(piv[2])
        except Exception:
            return None, None, None, None

        if not (0 <= first_idx < len(df_full) and 0 <= second_idx < len(df_full)):
            return None, None, None, None

        kwargs = {
            "first_idx": first_idx,
            "second_idx": second_idx,
            "adam_max": int(self.config.variant_adam_max_peak_width_bars),
            "eve_min": int(self.config.variant_eve_min_peak_width_bars),
            "tol_pct": float(self.config.variant_peak_width_tolerance_pct),
            "window": max(1, int(self.config.variant_peak_width_window_bars)),
        }
        if family == "double_tops":
            result = resolve_double_top_variant(df_full, **kwargs)
        else:
            result = resolve_double_bottom_variant(df_full, **kwargs)

        first = result.get("first_extreme") or {}
        second = result.get("second_extreme") or {}
        return (
            result.get("variant_code"),
            int(result.get("variant_confidence") or 0),
            first.get("width_bars"),
            second.get("width_bars"),
        )

    def _empty_result(self, detection: Any) -> PostBreakoutResult:
        """Return empty result when evaluation cannot be performed"""
        return PostBreakoutResult(
            pattern_id=detection.pattern_id,
            symbol=detection.symbol,
            pattern_name=detection.pattern_name,
            breakout_date=detection.breakout_date,
            breakout_price=detection.breakout_price,
            breakout_direction=detection.breakout_direction,
            target_price=detection.target_price,
            stop_loss_price=detection.stop_loss_price,
            bust_failure_5pct=None,
            bust_failure_10pct=None,
            bust_failure_date=None,
            bust_failure_pct=None,
            boundary_invalidated=None,
            boundary_invalidation_date=None,
            ultimate_price=None,
            ultimate_date=None,
            days_to_ultimate=None,
            ultimate_stop_reason=None,
            throwback_pullback_occurred=None,
            throwback_pullback_date=None,
            days_to_throwback_pullback=None,
            retested_breakout_level=None,
            retested_boundary_level=None,
            target_achieved_intraday=None,
            target_achieved_close=None,
            target_achievement_date=None,
            days_to_target=None,
            max_favorable_excursion_pct=None,
            max_adverse_excursion_pct=None,
            variant_confidence=None,
            evaluation_window_bars=self._pattern_lookahead_bars(str(getattr(detection, "pattern_name", "") or "")),
        )


class StatisticsAggregator:
    """
    Aggregates evaluation results into summary statistics.
    """

    def aggregate(self, results: List[PostBreakoutResult]) -> Dict[str, Any]:
        """
        Aggregate multiple evaluation results into summary statistics.
        """
        if not results:
            return {'total_patterns': 0}

        # Filter to results with breakouts
        with_breakout = [r for r in results if r.breakout_price is not None and r.breakout_date is not None]

        stats = {
            'total_patterns': len(results),
            'patterns_with_breakout': len(with_breakout),
            'patterns_without_breakout': len(results) - len(with_breakout),
        }

        if not with_breakout:
            return stats

        # === FAILURE RATES ===
        # Bust failure
        bust_5 = [r for r in with_breakout if r.bust_failure_5pct is True]
        bust_10 = [r for r in with_breakout if r.bust_failure_10pct is True]
        stats['bust_failure_rate_5pct'] = len(bust_5) / len(with_breakout) * 100
        stats['bust_failure_rate_10pct'] = len(bust_10) / len(with_breakout) * 100

        # Boundary invalidation
        boundary_failed = [r for r in with_breakout if r.boundary_invalidated is True]
        stats['boundary_invalidation_rate_pct'] = len(boundary_failed) / len(with_breakout) * 100

        # === TARGET ACHIEVEMENT ===
        target_intraday = [r for r in with_breakout if r.target_achieved_intraday is True]
        target_close = [r for r in with_breakout if r.target_achieved_close is True]
        stats['target_achievement_rate_intraday_pct'] = len(target_intraday) / len(with_breakout) * 100
        stats['target_achievement_rate_close_pct'] = len(target_close) / len(with_breakout) * 100

        # Days to target
        target_days = [r.days_to_target for r in with_breakout if r.days_to_target is not None]
        if target_days:
            stats['avg_days_to_target'] = np.mean(target_days)
            stats['median_days_to_target'] = np.median(target_days)

        # === THROWBACK/PULLBACK ===
        throwback = [r for r in with_breakout if r.throwback_pullback_occurred is True]
        stats['throwback_pullback_rate_pct'] = len(throwback) / len(with_breakout) * 100

        # Breakout vs boundary retest
        breakout_retest = [r for r in with_breakout if r.retested_breakout_level is True]
        boundary_retest = [r for r in with_breakout if r.retested_boundary_level is True]
        stats['breakout_retest_rate_pct'] = len(breakout_retest) / len(with_breakout) * 100
        stats['boundary_retest_rate_pct'] = len(boundary_retest) / len(with_breakout) * 100

        # === ULTIMATE ===
        days_to_ultimate = [r.days_to_ultimate for r in with_breakout if r.days_to_ultimate is not None]
        if days_to_ultimate:
            stats['avg_days_to_ultimate'] = np.mean(days_to_ultimate)
            stats['median_days_to_ultimate'] = np.median(days_to_ultimate)

        # Stop reasons
        stop_reasons = [r.ultimate_stop_reason for r in with_breakout if r.ultimate_stop_reason]
        if stop_reasons:
            stats['ultimate_stop_reasons'] = pd.Series(stop_reasons).value_counts().to_dict()

        # === EXCURSION ===
        mfe = [r.max_favorable_excursion_pct for r in with_breakout if r.max_favorable_excursion_pct is not None]
        mae = [r.max_adverse_excursion_pct for r in with_breakout if r.max_adverse_excursion_pct is not None]
        if mfe:
            stats['avg_max_favorable_excursion_pct'] = np.mean(mfe)
            stats['median_max_favorable_excursion_pct'] = np.median(mfe)
        if mae:
            stats['avg_max_adverse_excursion_pct'] = np.mean(mae)
            stats['median_max_adverse_excursion_pct'] = np.median(mae)

        # === BY PATTERN TYPE ===
        by_pattern = {}
        for pattern_name in set(r.pattern_name for r in with_breakout):
            pattern_results = [r for r in with_breakout if r.pattern_name == pattern_name]
            by_pattern[pattern_name] = self._aggregate_pattern(pattern_results)
        stats['by_pattern'] = by_pattern

        # === DOUBLE PATTERN VARIANTS (AA/AE/EA/EE) ===
        for family in ("double_bottoms", "double_tops"):
            family_rows = [
                r for r in with_breakout
                if str(getattr(r, "pattern_name", "") or "") == family
                or str(getattr(r, "pattern_name", "") or "").startswith(f"{family}_")
            ]
            if not family_rows:
                continue

            unknown = 0
            by_var: Dict[str, Dict[str, Any]] = {}
            for r in family_rows:
                if not r.variant:
                    unknown += 1
                    continue
                v = str(r.variant)
                bucket = by_var.setdefault(v, {"count": 0, "mfe": [], "mae": [], "confidence": []})
                bucket["count"] += 1
                if r.max_favorable_excursion_pct is not None and np.isfinite(r.max_favorable_excursion_pct):
                    bucket["mfe"].append(float(r.max_favorable_excursion_pct))
                if r.max_adverse_excursion_pct is not None and np.isfinite(r.max_adverse_excursion_pct):
                    bucket["mae"].append(float(r.max_adverse_excursion_pct))
                if getattr(r, "variant_confidence", None) is not None and np.isfinite(getattr(r, "variant_confidence", None)):
                    bucket["confidence"].append(float(getattr(r, "variant_confidence")))

            if by_var:
                stats[f"{family}_variant_unknown_count"] = unknown
                stats[f"{family}_by_variant"] = {
                    v: {
                        "count": int(b["count"]),
                        "avg_mfe_pct": float(np.mean(b["mfe"])) if b["mfe"] else None,
                        "avg_mae_pct": float(np.mean(b["mae"])) if b["mae"] else None,
                        "avg_variant_confidence": float(np.mean(b["confidence"])) if b["confidence"] else None,
                    }
                    for v, b in sorted(by_var.items())
                }

        return stats

    def _aggregate_pattern(self, results: List[PostBreakoutResult]) -> Dict[str, Any]:
        """Aggregate statistics for a single pattern type"""
        n = len(results)
        return {
            'count': n,
            'bust_failure_rate_5pct': sum(1 for r in results if r.bust_failure_5pct) / n * 100 if n else 0,
            'bust_failure_rate_10pct': sum(1 for r in results if r.bust_failure_10pct) / n * 100 if n else 0,
            'boundary_invalidation_rate_pct': sum(1 for r in results if r.boundary_invalidated) / n * 100 if n else 0,
            'target_achievement_intraday_pct': sum(1 for r in results if r.target_achieved_intraday) / n * 100 if n else 0,
            'throwback_pullback_rate_pct': sum(1 for r in results if r.throwback_pullback_occurred) / n * 100 if n else 0,
        }


# Convenience function for batch evaluation
def evaluate_detections(detections: List[Any],
                        df_dict: Dict[str, pd.DataFrame],
                        pattern_boundaries: Optional[Dict[str, float]] = None,
                        pattern_heights: Optional[Dict[str, float]] = None,
                        config: Optional[EvaluationConfig] = None) -> Tuple[List[PostBreakoutResult], Dict[str, Any]]:
    """
    Evaluate multiple pattern detections.

    Args:
        detections: List of PatternDetection objects
        df_dict: Dictionary mapping symbol to full OHLCV DataFrame
        pattern_boundaries: Dict mapping pattern_id to boundary price
        pattern_heights: Dict mapping pattern_id to pattern height
        config: Evaluation configuration

    Returns:
        Tuple of (list of results, aggregated statistics)
    """
    evaluator = PostBreakoutEvaluator(config)
    aggregator = StatisticsAggregator()

    results = []
    for d in detections:
        df = df_dict.get(d.symbol)
        if df is None:
            continue

        boundary = pattern_boundaries.get(d.pattern_id) if pattern_boundaries else None
        height = pattern_heights.get(d.pattern_id) if pattern_heights else None

        result = evaluator.evaluate(d, df, boundary, height)
        results.append(result)

    stats = aggregator.aggregate(results)
    return results, stats


if __name__ == "__main__":
    print(__doc__)
    print("\nClasses:")
    print("  - EvaluationConfig: Configuration for evaluation")
    print("  - PostBreakoutEvaluator: Evaluates patterns with look-ahead")
    print("  - PostBreakoutResult: Result dataclass with all metrics")
    print("  - StatisticsAggregator: Aggregates results into stats")
