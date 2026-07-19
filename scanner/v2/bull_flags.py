"""Flag-family V2 fixture-level detectors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


BULL_FLAGS_SUPPORTED_RULE_IDS = {
    "bf.prior_trend.steep_up",
    "bf.shape.parallel_channel",
    "bf.duration.max_three_weeks",
    "bf.countertrend.drift",
    "bf.breakout.close_above_trendline",
    "bf.volume.downward_context",
    "bf.measure.pole_height_legacy",
    "bf.invalidation.no_strong_advance",
}

BEAR_FLAGS_SUPPORTED_RULE_IDS = {
    "brf.prior_trend.steep_down",
    "brf.shape.parallel_channel",
    "brf.duration.max_three_weeks",
    "brf.countertrend.drift",
    "brf.breakout.close_below_trendline",
    "brf.volume.downward_context",
    "brf.measure.pole_height_legacy",
    "brf.invalidation.no_strong_decline",
}


@dataclass(frozen=True)
class BullFlagResult:
    matched: bool
    breakout_direction: Optional[str]
    breakout_idx: Optional[int]
    breakout_price: Optional[float]
    reasons: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "matched": self.matched,
            "breakout_direction": self.breakout_direction,
            "breakout_idx": self.breakout_idx,
            "breakout_price": self.breakout_price,
            "reasons": list(self.reasons),
        }


def _line_slope(point_a: Mapping[str, Any], point_b: Mapping[str, Any], price_key: str) -> float:
    bars = max(1, int(point_b["idx"]) - int(point_a["idx"]))
    return (float(point_b[price_key]) - float(point_a[price_key])) / bars


def _line_value(point_a: Mapping[str, Any], point_b: Mapping[str, Any], price_key: str, idx: int) -> float:
    return float(point_a[price_key]) + _line_slope(point_a, point_b, price_key) * (idx - int(point_a["idx"]))


class BullFlagV2Detector:
    """Evaluate the minimal Bull Flag rule set on synthetic golden fixtures."""

    width_max_bars = 15
    parallel_slope_tolerance = 0.15

    def scan_fixture(self, fixture: Mapping[str, Any]) -> BullFlagResult:
        reasons = []
        prior = fixture.get("prior_trend") if isinstance(fixture.get("prior_trend"), Mapping) else {}
        if prior.get("direction") != "up":
            reasons.append("prior_trend_not_up")
        if float(prior.get("move_pct") or 0.0) < 10.0:
            reasons.append("prior_advance_not_steep")

        pivots = fixture.get("pivots")
        if not isinstance(pivots, Sequence) or len(pivots) != 4:
            return BullFlagResult(False, None, None, None, tuple(reasons + ["pivot_count_not_four"]))
        if [str(p.get("type")) for p in pivots] != ["H", "L", "H", "L"]:
            reasons.append("not_bull_flag_pivot_sequence")
        idxs = [int(p.get("idx")) for p in pivots]
        if idxs != sorted(idxs) or len(set(idxs)) != len(idxs):
            reasons.append("pivots_not_ascending")

        width = idxs[-1] - idxs[0] + 1
        if width > self.width_max_bars:
            reasons.append("flag_too_long")

        upper_a = {"idx": idxs[0], "price": float(pivots[0]["price"])}
        upper_b = {"idx": idxs[2], "price": float(pivots[2]["price"])}
        lower_a = {"idx": idxs[1], "price": float(pivots[1]["price"])}
        lower_b = {"idx": idxs[3], "price": float(pivots[3]["price"])}
        upper_slope = _line_slope(upper_a, upper_b, "price")
        lower_slope = _line_slope(lower_a, lower_b, "price")
        if abs(upper_slope - lower_slope) > self.parallel_slope_tolerance:
            reasons.append("trendlines_not_parallel")
        if (upper_slope + lower_slope) / 2.0 > 0.0:
            reasons.append("flag_not_countertrend")

        if bool(reasons):
            return BullFlagResult(False, None, None, None, tuple(reasons))

        closes = fixture.get("post_formation_closes")
        if not isinstance(closes, Sequence):
            closes = []
        for close in closes:
            idx = int(close["idx"])
            price = float(close["close"])
            boundary = _line_value(upper_a, upper_b, "price", idx)
            if price > boundary:
                return BullFlagResult(True, "up", idx, price, tuple())
        return BullFlagResult(False, None, None, None, ("no_close_above_upper_trendline",))


def run_bull_flags_fixture(fixture: Mapping[str, Any]) -> BullFlagResult:
    return BullFlagV2Detector().scan_fixture(fixture)


class BearFlagV2Detector:
    """Evaluate the minimal Bear Flag rule set on synthetic golden fixtures."""

    width_max_bars = 15
    parallel_slope_tolerance = 0.15

    def scan_fixture(self, fixture: Mapping[str, Any]) -> BullFlagResult:
        reasons = []
        prior = fixture.get("prior_trend") if isinstance(fixture.get("prior_trend"), Mapping) else {}
        if prior.get("direction") != "down":
            reasons.append("prior_trend_not_down")
        if abs(float(prior.get("move_pct") or 0.0)) < 10.0:
            reasons.append("prior_decline_not_steep")

        pivots = fixture.get("pivots")
        if not isinstance(pivots, Sequence) or len(pivots) != 4:
            return BullFlagResult(False, None, None, None, tuple(reasons + ["pivot_count_not_four"]))
        if [str(p.get("type")) for p in pivots] != ["L", "H", "L", "H"]:
            reasons.append("not_bear_flag_pivot_sequence")
        idxs = [int(p.get("idx")) for p in pivots]
        if idxs != sorted(idxs) or len(set(idxs)) != len(idxs):
            reasons.append("pivots_not_ascending")

        width = idxs[-1] - idxs[0] + 1
        if width > self.width_max_bars:
            reasons.append("flag_too_long")

        lower_a = {"idx": idxs[0], "price": float(pivots[0]["price"])}
        lower_b = {"idx": idxs[2], "price": float(pivots[2]["price"])}
        upper_a = {"idx": idxs[1], "price": float(pivots[1]["price"])}
        upper_b = {"idx": idxs[3], "price": float(pivots[3]["price"])}
        lower_slope = _line_slope(lower_a, lower_b, "price")
        upper_slope = _line_slope(upper_a, upper_b, "price")
        if abs(upper_slope - lower_slope) > self.parallel_slope_tolerance:
            reasons.append("trendlines_not_parallel")
        if (upper_slope + lower_slope) / 2.0 < 0.0:
            reasons.append("flag_not_countertrend")

        if bool(reasons):
            return BullFlagResult(False, None, None, None, tuple(reasons))

        closes = fixture.get("post_formation_closes")
        if not isinstance(closes, Sequence):
            closes = []
        for close in closes:
            idx = int(close["idx"])
            price = float(close["close"])
            boundary = _line_value(lower_a, lower_b, "price", idx)
            if price < boundary:
                return BullFlagResult(True, "down", idx, price, tuple())
        return BullFlagResult(False, None, None, None, ("no_close_below_lower_trendline",))


def run_bear_flags_fixture(fixture: Mapping[str, Any]) -> BullFlagResult:
    return BearFlagV2Detector().scan_fixture(fixture)
