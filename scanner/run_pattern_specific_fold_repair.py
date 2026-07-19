"""Fold-repair pass for blocked pattern chapters.

This pass starts from the best branch-redesign evidence and asks a narrower
question: can source-safe sub-branches reduce fixed walk-forward fold failures
without collapsing validation/holdout depth?  It does not use outcome labels
such as MFE, MAE, target-hit, or post-breakout quality as branch selectors.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.run_chapter_tradable_layer import (  # noqa: E402
    CHAPTER_SPECS,
    GenericExecutionConfig,
    evaluate_strategy,
    load_chapter_events_and_path,
    run_cost_stress,
    run_monte_carlo,
    run_walk_forward,
    score_tradable_setup,
)


REDESIGN_ID = "pattern_specific_fold_repair_v1"
NO_OVERLIFT_POLICY_ID = "pattern_specific_fold_repair_no_overlift_guard_v1"
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/pattern_specific_fold_repair")
DEFAULT_PATTERNS = (
    "triangles_symmetrical",
    "triangles_descending",
    "bear_flags",
    "triangles_ascending",
    "wedges_falling",
    "wedges_rising",
)
BROADENING_LONG_UP_PATTERNS = {
    "broadening_bottoms",
    "broadening_formations_right_angled_descending",
    "broadening_wedges_descending",
}
BROADENING_DEFENSIVE_DOWN_PATTERNS = {
    "broadening_formations_right_angled_ascending",
    "broadening_tops",
    "broadening_wedges_ascending",
}


@dataclass(frozen=True)
class BranchRule:
    branch_id: str
    description: str
    predicate: Callable[[pd.DataFrame], pd.Series]


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _score_between(value: Any, low: float, high: float) -> float:
    numeric = _as_float(value, default=low)
    if high == low:
        return 100.0 if numeric >= high else 0.0
    return max(0.0, min(100.0, (numeric - low) / (high - low) * 100.0))


def _num(frame: pd.DataFrame, column: str, default: float = np.nan) -> pd.Series:
    if column not in frame:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _bool(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(False, index=frame.index, dtype="bool")
    series = frame[column]
    if series.dtype == bool:
        return series.fillna(False)
    return series.astype(str).str.lower().isin({"true", "1", "yes", "y"})


def _cat(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series("", index=frame.index, dtype="object")
    return frame[column].astype(str)


def _liq(frame: pd.DataFrame, *buckets: str) -> pd.Series:
    return _cat(frame, "liquidity_bucket").isin(buckets)


def _regime(frame: pd.DataFrame, *regimes: str) -> pd.Series:
    return _cat(frame, "market_regime").isin(regimes)


def _direction(pattern_id: str) -> tuple[str, ...]:
    if pattern_id in BROADENING_DEFENSIVE_DOWN_PATTERNS:
        return ("down",)
    if pattern_id in BROADENING_LONG_UP_PATTERNS:
        return ("up",)
    if pattern_id in {"triangles_descending", "bear_flags", "wedges_rising", "head_and_shoulders_tops_complex"}:
        return ("down",)
    return ("up",)


def _scope(pattern_id: str) -> str:
    if pattern_id in {"broadening_bottoms", "broadening_formations_right_angled_descending"}:
        return "long_up_breakout_branch"
    if pattern_id == "broadening_wedges_descending":
        return "long_cash_candidate"
    if pattern_id in BROADENING_DEFENSIVE_DOWN_PATTERNS:
        return "defensive_informational"
    if pattern_id == "triangles_symmetrical":
        return "long_up_breakout_branch"
    if pattern_id == "head_and_shoulders_bottoms_complex":
        return "long_cash_candidate"
    if pattern_id == "head_and_shoulders_tops_complex":
        return "defensive_exit_setup"
    if _direction(pattern_id) == ("down",):
        return "defensive_informational"
    return "long_cash_candidate"


def build_branch_rules(pattern_id: str) -> list[BranchRule]:
    rules: list[BranchRule] = [
        BranchRule("all", "Baseline public-scope events.", lambda f: pd.Series(True, index=f.index)),
        BranchRule("primary_mid_high", "Primary events with mid/high liquidity.", lambda f: _bool(f, "is_primary_event_60d") & _liq(f, "mid", "high")),
    ]
    if pattern_id == "bear_flags":
        rules.extend(
            [
                BranchRule("headline_high_liq", "Bear Flag headline branch in high liquidity.", lambda f: _bool(f, "bear_branch_is_headline_candidate") & _liq(f, "high")),
                BranchRule("headline_high_liq_compact", "Headline high-liquidity Bear Flag with compact flag body.", lambda f: _bool(f, "bear_branch_is_headline_candidate") & _liq(f, "high") & (_num(f, "flag_to_pole_pct") <= 45.0)),
                BranchRule("headline_high_liq_volume", "Headline high-liquidity Bear Flag with volume confirmation.", lambda f: _bool(f, "bear_branch_is_headline_candidate") & _liq(f, "high") & _bool(f, "volume_confirmed")),
                BranchRule("headline_high_range", "Headline Bear Flag from upper yearly-range zone.", lambda f: _bool(f, "bear_branch_is_headline_candidate") & _num(f, "yearly_range_position_pct").between(55.0, 95.0)),
                BranchRule("defensive_core_high_liq", "Defensive-core lane in high liquidity.", lambda f: _cat(f, "bear_branch_lane").eq("defensive-core") & _liq(f, "high")),
                BranchRule("clean_breakdown_body", "Cleaner bearish breakdown candle shape.", lambda f: _bool(f, "bear_branch_is_headline_candidate") & (_num(f, "breakout_body_to_range") >= 0.35) & (_num(f, "breakout_close_location") <= 0.55)),
            ]
        )
        return rules

    if "triangle" in pattern_id:
        up_mask = lambda f: _cat(f, "breakout_direction").eq("up")
        down_mask = lambda f: _cat(f, "breakout_direction").eq("down")
        direction_mask = down_mask if pattern_id == "triangles_descending" else up_mask
        rules.extend(
            [
                BranchRule("clean_apex_tight", "Clean triangle near apex with low crossings.", lambda f, dm=direction_mask: dm(f) & (_num(f, "triangle_white_space_score") >= 85.0) & (_num(f, "triangle_crossing_count") <= 4.0) & _num(f, "apex_progress_pct").between(60.0, 115.0)),
                BranchRule("liquid_clear_breakout", "Liquid breakout with clear price confirmation.", lambda f, dm=direction_mask: dm(f) & _liq(f, "mid", "high") & (_num(f, "breakout_clearance_pct") >= 1.50)),
                BranchRule("liquid_volume_breakout", "Liquid breakout with volume confirmation.", lambda f, dm=direction_mask: dm(f) & _liq(f, "mid", "high") & (_num(f, "breakout_volume_ratio") >= 1.20)),
                BranchRule("mature_compression", "Mature compressed triangle before/near apex.", lambda f, dm=direction_mask: dm(f) & (_num(f, "compression_ratio") <= 0.55) & _num(f, "apex_progress_pct").between(70.0, 110.0)),
                BranchRule("high_quality_liquid", "High publication quality and mid/high liquidity.", lambda f, dm=direction_mask: dm(f) & (_num(f, "publication_quality_score") >= 80.0) & _liq(f, "mid", "high")),
            ]
        )
        if pattern_id in {"triangles_ascending", "triangles_symmetrical"}:
            rules.extend(
                [
                    BranchRule("bear_high_liq_long_up", "Long-up branch in bear regime and high liquidity.", lambda f, dm=direction_mask: dm(f) & _regime(f, "bear") & _liq(f, "high")),
                    BranchRule("bear_high_liq_clear", "Bear-regime high-liquidity long-up with clear breakout.", lambda f, dm=direction_mask: dm(f) & _regime(f, "bear") & _liq(f, "high") & (_num(f, "breakout_clearance_pct") >= 1.0)),
                    BranchRule("bear_high_liq_mature", "Bear-regime high-liquidity mature triangle.", lambda f, dm=direction_mask: dm(f) & _regime(f, "bear") & _liq(f, "high") & _num(f, "apex_progress_pct").between(65.0, 115.0)),
                ]
            )
        if pattern_id == "triangles_descending":
            rules.extend(
                [
                    BranchRule("high_liq_breakdown", "High-liquidity down breakout branch.", lambda f, dm=direction_mask: dm(f) & _liq(f, "high") & (_num(f, "breakout_clearance_pct") >= 0.50)),
                    BranchRule("high_liq_breakdown_clean_apex", "High-liquidity breakdown with clean apex geometry.", lambda f, dm=direction_mask: dm(f) & _liq(f, "high") & (_num(f, "breakout_clearance_pct") >= 0.50) & (_num(f, "triangle_crossing_count") <= 5.0) & _num(f, "apex_progress_pct").between(55.0, 120.0)),
                    BranchRule("high_liq_bull_breakdown", "High-liquidity breakdown during bull regime.", lambda f, dm=direction_mask: dm(f) & _liq(f, "high") & _regime(f, "bull") & (_num(f, "breakout_clearance_pct") >= 0.50)),
                    BranchRule("high_liq_volume_breakdown", "High-liquidity breakdown with volume confirmation.", lambda f, dm=direction_mask: dm(f) & _liq(f, "high") & (_num(f, "breakout_volume_ratio") >= 1.20)),
                ]
            )
        return rules

    if pattern_id.startswith("broadening_"):
        rules = []
        direction_mask = (
            lambda f: _cat(f, "breakout_direction").eq("down")
        ) if pattern_id in BROADENING_DEFENSIVE_DOWN_PATTERNS else (
            lambda f: _cat(f, "breakout_direction").eq("up")
        )
        rules.extend(
            [
                BranchRule("broadening_mid_high_clear", "Broadening breakout in mid/high liquidity with clear confirmation.", lambda f, dm=direction_mask: dm(f) & _liq(f, "mid", "high") & (_num(f, "breakout_clearance_pct") >= 1.0)),
                BranchRule("broadening_high_quality", "High-quality broadening geometry with enough expansion.", lambda f, dm=direction_mask: dm(f) & (_num(f, "publication_quality_score") >= 75.0) & (_num(f, "expansion_ratio") >= 1.20)),
                BranchRule("broadening_strong_expansion", "Stronger widening geometry with mid/high liquidity.", lambda f, dm=direction_mask: dm(f) & (_num(f, "expansion_ratio") >= 1.35) & _liq(f, "mid", "high")),
                BranchRule("broadening_core_width", "Core-width broadening structure to avoid very short/noisy formations.", lambda f, dm=direction_mask: dm(f) & _num(f, "pattern_width_bars").between(25.0, 90.0)),
                BranchRule("broadening_volume_confirmed", "Broadening breakout with volume confirmation.", lambda f, dm=direction_mask: dm(f) & _bool(f, "volume_confirmed") & _liq(f, "mid", "high")),
            ]
        )
        if pattern_id in BROADENING_LONG_UP_PATTERNS:
            rules.extend(
                [
                    BranchRule("broadening_bear_reversal", "Up-breakout broadening reversal branch during bear regime.", lambda f, dm=direction_mask: dm(f) & _regime(f, "bear") & _liq(f, "mid", "high")),
                    BranchRule("broadening_high_liq_up", "High-liquidity up-breakout broadening branch.", lambda f, dm=direction_mask: dm(f) & _liq(f, "high") & (_num(f, "breakout_clearance_pct") >= 0.5)),
                ]
            )
        else:
            rules.extend(
                [
                    BranchRule("broadening_bull_breakdown", "Down-breakout broadening defensive branch during bull regime.", lambda f, dm=direction_mask: dm(f) & _regime(f, "bull") & _liq(f, "mid", "high")),
                    BranchRule("broadening_high_liq_down", "High-liquidity down-breakout broadening branch.", lambda f, dm=direction_mask: dm(f) & _liq(f, "high") & (_num(f, "breakout_clearance_pct") >= 0.5)),
                ]
            )
        return rules

    if "wedge" in pattern_id:
        rules.extend(
            [
                BranchRule("compact_clear", "Compact wedge with clear breakout.", lambda f: (_num(f, "compression_ratio") <= 0.55) & (_num(f, "breakout_clearance_pct") >= 1.0)),
                BranchRule("moderate_height", "Moderate-height wedge to avoid tiny/noisy structures.", lambda f: _num(f, "pattern_height_pct").between(8.0, 28.0)),
                BranchRule("width_core", "Wedge width in core 25-60 bar zone.", lambda f: _num(f, "pattern_width_bars").between(25.0, 60.0)),
                BranchRule("width_core_clear", "Core-width wedge with clear breakout.", lambda f: _num(f, "pattern_width_bars").between(25.0, 60.0) & (_num(f, "breakout_clearance_pct") >= 1.0)),
                BranchRule("quality_liquid", "Quality wedge in mid/high liquidity.", lambda f: (_num(f, "publication_quality_score") >= 75.0) & _liq(f, "mid", "high")),
            ]
        )
        if pattern_id == "wedges_falling":
            rules.extend(
                [
                    BranchRule("bear_regime_reversal", "Falling Wedge reversal branch in bear regime.", lambda f: _regime(f, "bear") & _liq(f, "mid", "high")),
                    BranchRule("bear_width_core_reversal", "Bear-regime Falling Wedge with core width.", lambda f: _regime(f, "bear") & _liq(f, "mid", "high") & _num(f, "pattern_width_bars").between(25.0, 60.0)),
                    BranchRule("bear_compact_clear", "Bear-regime compact Falling Wedge with clear breakout.", lambda f: _regime(f, "bear") & _liq(f, "mid", "high") & (_num(f, "compression_ratio") <= 0.55) & (_num(f, "breakout_clearance_pct") >= 1.0)),
                ]
            )
        if pattern_id == "wedges_rising":
            rules.extend(
                [
                    BranchRule("bull_regime_breakdown", "Rising Wedge breakdown branch in bull regime.", lambda f: _regime(f, "bull") & _liq(f, "mid", "high")),
                    BranchRule("bull_high_liq_width_core", "Bull-regime high-liquidity Rising Wedge with core width.", lambda f: _regime(f, "bull") & _liq(f, "high") & _num(f, "pattern_width_bars").between(25.0, 60.0)),
                    BranchRule("bull_high_liq_clear", "Bull-regime high-liquidity Rising Wedge with clear breakdown.", lambda f: _regime(f, "bull") & _liq(f, "high") & (_num(f, "breakout_clearance_pct") >= 1.0)),
                ]
            )
        return rules

    if "head_and_shoulders" in pattern_id:
        direction_mask = (lambda f: _cat(f, "breakout_direction").eq("down")) if pattern_id == "head_and_shoulders_tops_complex" else (lambda f: _cat(f, "breakout_direction").eq("up"))
        rules.extend(
            [
                BranchRule(
                    "source_clean_liquid",
                    "Source-aligned H&S geometry with mid/high liquidity.",
                    lambda f, dm=direction_mask: dm(f)
                    & (_num(f, "pattern_quality_score") >= 82.0)
                    & (_num(f, "shoulder_diff_pct") <= 5.0)
                    & (_num(f, "head_prominence_pct") >= 5.0)
                    & _liq(f, "mid", "high"),
                ),
                BranchRule(
                    "flat_neckline_quality",
                    "Flat-to-moderate neckline and strong source geometry.",
                    lambda f, dm=direction_mask: dm(f)
                    & (_num(f, "neckline_slope_deg") <= 3.25)
                    & (_num(f, "pattern_quality_score") >= 84.0)
                    & (_num(f, "shoulder_diff_pct") <= 4.5),
                ),
                BranchRule(
                    "volume_confirmed_quality",
                    "Volume-confirmed breakout with clean H&S geometry.",
                    lambda f, dm=direction_mask: dm(f)
                    & _bool(f, "volume_confirmed")
                    & (_num(f, "breakout_volume_ratio") >= 1.20)
                    & (_num(f, "pattern_quality_score") >= 80.0),
                ),
                BranchRule(
                    "high_liq_quality",
                    "High-liquidity H&S branch with balanced shoulders.",
                    lambda f, dm=direction_mask: dm(f)
                    & _liq(f, "high")
                    & (_num(f, "pattern_quality_score") >= 80.0)
                    & (_num(f, "shoulder_diff_pct") <= 5.5),
                ),
            ]
        )
        if pattern_id == "head_and_shoulders_bottoms_complex":
            rules.extend(
                [
                    BranchRule(
                        "bull_reversal_liquid",
                        "Long H&S Bottom Complex in bull/known regimes with liquid execution.",
                        lambda f, dm=direction_mask: dm(f)
                        & _regime(f, "bull", "bear")
                        & _liq(f, "mid", "high")
                        & (_num(f, "head_prominence_pct") >= 5.0)
                        & (_num(f, "neckline_slope_deg") <= 4.0),
                    ),
                    BranchRule(
                        "standard_premium_quality",
                        "Publication standard/premium H&S Bottom Complex.",
                        lambda f, dm=direction_mask: dm(f)
                        & _cat(f, "publication_quality_tier").isin(["standard", "premium"])
                        & (_num(f, "pattern_quality_score") >= 82.0),
                    ),
                ]
            )
        else:
            rules.extend(
                [
                    BranchRule(
                        "bull_exit_high_liq",
                        "H&S Top Complex defensive exit branch in bull regime and high liquidity.",
                        lambda f, dm=direction_mask: dm(f)
                        & _regime(f, "bull")
                        & _liq(f, "high")
                        & (_num(f, "head_prominence_pct") >= 6.0)
                        & (_num(f, "shoulder_diff_pct") <= 5.0),
                    ),
                    BranchRule(
                        "known_regime_defensive",
                        "Defensive H&S Top Complex outside unknown-regime events.",
                        lambda f, dm=direction_mask: dm(f)
                        & _regime(f, "bull", "bear")
                        & _liq(f, "mid", "high")
                        & (_num(f, "pattern_quality_score") >= 82.0),
                    ),
                ]
            )
        return rules

    return rules


def build_configs(pattern_id: str) -> list[GenericExecutionConfig]:
    direction = _direction(pattern_id)
    configs: list[GenericExecutionConfig] = []
    seen: set[str] = set()

    def add(
        target: float,
        stop: float,
        hold: int,
        delay: int,
        size_label: str,
        position_size: float,
        max_positions: int,
        participation: float,
        *,
        regime: tuple[str, ...] | None = None,
        liquidity: tuple[str, ...] | None = None,
    ) -> None:
        regime_label = "all" if not regime else "".join(regime)
        liq_label = "all" if not liquidity else "".join(liquidity)
        strategy_id = (
            f"{pattern_id}__fold_t{str(target).replace('.', '')}"
            f"_s{int(stop)}_h{hold}_d{delay}_reg{regime_label}_liq{liq_label}_{size_label}"
        )
        if strategy_id in seen:
            return
        seen.add(strategy_id)
        configs.append(
            GenericExecutionConfig(
                strategy_id=strategy_id,
                target_multiple=target,
                stop_loss_pct=stop,
                max_holding_days=hold,
                entry_delay_bars=delay,
                allowed_breakout_directions=direction,
                allowed_market_regimes=regime,
                allowed_liquidity_buckets=liquidity,
                position_size_pct=position_size,
                max_positions=max_positions,
                target_adtv_participation_pct=participation,
            )
        )

    def add_core(targets: Sequence[float], stops: Sequence[float], holds: Sequence[int], delays: Sequence[int], sizes: Sequence[tuple[str, float, int, float]]) -> None:
        for target in targets:
            for stop in stops:
                for hold in holds:
                    for delay in delays:
                        for size_label, position_size, max_positions, participation in sizes:
                            add(target, stop, hold, delay, size_label, position_size, max_positions, participation)

    if pattern_id == "bear_flags":
        add_core((0.50, 0.75), (7.0, 10.0), (40,), (1,), (("p005", 0.05, 20, 7.5), ("p0075", 0.075, 12, 5.0)))
        add(0.75, 10.0, 40, 1, "p0075", 0.075, 10, 5.0, liquidity=("high",))
        add(0.50, 7.0, 60, 3, "p0033", 0.033, 30, 8.0, regime=("bull",), liquidity=("mid", "high"))
    elif pattern_id == "triangles_descending":
        add_core((0.50, 0.75), (7.0, 10.0), (20,), (1,), (("p005", 0.05, 20, 7.5), ("p0075", 0.075, 12, 5.0)))
        add(1.00, 7.0, 20, 3, "p0033", 0.033, 30, 8.0, regime=("bull",), liquidity=("mid", "high"))
        add(0.75, 10.0, 20, 1, "p0075", 0.075, 10, 5.0, liquidity=("high",))
    elif pattern_id == "triangles_ascending":
        add_core((0.75, 1.00), (7.0,), (60,), (3,), (("p0075", 0.075, 12, 5.0), ("p010", 0.10, 10, 4.0)))
        for target in (0.65, 0.75, 1.00):
            add(target, 7.0, 60, 3, "p010", 0.10, 10, 4.0, regime=("bear",), liquidity=("high",))
            add(target, 7.0, 80, 3, "p0075", 0.075, 12, 5.0, regime=("bear",), liquidity=("mid", "high"))
    elif pattern_id == "triangles_symmetrical":
        add_core((0.75, 1.00), (7.0, 10.0), (20, 60), (1, 3), (("p005", 0.05, 20, 7.5),))
        add(1.00, 7.0, 60, 3, "p0033", 0.033, 30, 8.0, regime=("bull",), liquidity=("mid", "high"))
        add(1.00, 7.0, 60, 3, "p005", 0.05, 20, 7.5, regime=("bull",), liquidity=("mid", "high"))
        add(1.00, 7.0, 60, 3, "p0033", 0.033, 30, 8.0, regime=("bear",), liquidity=("mid", "high"))
    elif pattern_id == "wedges_falling":
        add_core((0.75, 1.00), (7.0,), (60,), (3,), (("p0033", 0.033, 30, 8.0), ("p005", 0.05, 30, 7.5)))
        for target in (0.75, 1.00, 1.25):
            add(target, 7.0, 60, 3, "p0033", 0.033, 30, 8.0, regime=("bear",), liquidity=("mid", "high"))
            add(target, 7.0, 60, 3, "p005", 0.05, 30, 7.5, regime=("bear",), liquidity=("mid", "high"))
            add(target, 7.0, 80, 3, "p005", 0.05, 20, 7.5, regime=("bear",), liquidity=("high",))
    elif pattern_id == "wedges_rising":
        add_core((0.75, 1.00), (7.0,), (60,), (3,), (("p0033", 0.033, 30, 8.0), ("p005", 0.05, 20, 7.5)))
        for target in (0.75, 1.00, 1.25):
            add(target, 7.0, 60, 3, "p0075", 0.075, 12, 5.0, regime=("bull",), liquidity=("high",))
            add(target, 7.0, 60, 3, "p010", 0.10, 10, 4.0, regime=("bull",), liquidity=("high",))
            add(target, 7.0, 80, 3, "p005", 0.05, 20, 7.5, regime=("bull",), liquidity=("mid", "high"))
    elif pattern_id == "head_and_shoulders_bottoms_complex":
        add_core((0.50, 0.65, 0.75, 1.00), (7.0, 10.0), (40, 60, 80), (1, 3), (("p0033", 0.033, 20, 7.5), ("p005", 0.05, 15, 5.0)))
        for target in (0.50, 0.65, 0.75):
            add(target, 7.0, 60, 3, "p0033", 0.033, 20, 7.5, regime=("bull",), liquidity=("mid", "high"))
            add(target, 10.0, 80, 3, "p0033", 0.033, 20, 7.5, regime=("bear",), liquidity=("mid", "high"))
            add(target, 7.0, 60, 1, "p005", 0.05, 12, 5.0, liquidity=("high",))
    elif pattern_id == "head_and_shoulders_tops_complex":
        add_core((0.50, 0.65, 0.75), (7.0, 10.0, 12.0), (20, 40, 60), (1, 3), (("p0033", 0.033, 20, 7.5), ("p005", 0.05, 15, 5.0)))
        for target in (0.50, 0.65, 0.75):
            add(target, 10.0, 40, 1, "p005", 0.05, 12, 5.0, regime=("bull",), liquidity=("high",))
            add(target, 12.0, 60, 3, "p0033", 0.033, 20, 7.5, regime=("bull", "bear"), liquidity=("mid", "high"))
            add(target, 10.0, 40, 1, "p005", 0.05, 15, 5.0, liquidity=("high",))
    elif pattern_id.startswith("broadening_"):
        add_core((0.50, 0.65), (10.0,), (40, 60), (1, 3), (("p0033", 0.033, 30, 8.0),))
        preferred_regime = ("bear",) if pattern_id in BROADENING_LONG_UP_PATTERNS else ("bull",)
        for target in (0.50, 0.65):
            add(target, 10.0, 40, 1, "p005", 0.05, 15, 5.0)
            add(target, 12.0, 40, 1, "p005", 0.05, 15, 5.0)
            add(target, 10.0, 40, 1, "p005", 0.05, 15, 5.0, regime=preferred_regime, liquidity=("high",))
            add(target, 10.0, 60, 3, "p0033", 0.033, 30, 8.0, regime=preferred_regime, liquidity=("mid", "high"))
    else:
        add_core((0.50, 0.75, 1.00), (7.0, 10.0), (20, 60), (1, 3), (("p005", 0.05, 20, 7.5),))
    return configs


def _branch_events(events: pd.DataFrame, branch: BranchRule) -> pd.DataFrame:
    mask = branch.predicate(events)
    mask = mask.reindex(events.index).fillna(False).astype(bool)
    scoped = events[mask].copy()
    scoped["pattern_specific_branch_id"] = branch.branch_id
    return scoped


def _utility(row: Mapping[str, Any], prefix: str) -> float:
    key = lambda name: f"{prefix}_{name}"
    return (
        0.30 * _score_between(row.get(key("total_return_pct")), 0.0, 8.0)
        + 0.18 * _score_between(row.get(key("max_drawdown_pct")), -12.0, -2.0)
        + 0.18 * _score_between(row.get(key("win_rate_pct")), 45.0, 68.0)
        + 0.14 * _score_between(row.get(key("trades")), 8.0, 45.0)
        + 0.10 * _score_between(row.get(key("profit_factor")), 1.0, 2.5)
        + 0.10 * _score_between(8.0 - _as_float(row.get("median_adtv_participation_pct"), default=8.0), 0.0, 8.0)
    )


def _candidate_score(row: Mapping[str, Any]) -> float:
    return 0.66 * _utility(row, "validation") + 0.24 * _utility(row, "train") + 0.10 * _score_between(row.get("branch_event_count"), 20.0, 160.0)


def first_pass(events: pd.DataFrame, path: pd.DataFrame, branches: Sequence[BranchRule], configs: Sequence[GenericExecutionConfig]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for branch in branches:
        scoped = _branch_events(events, branch)
        if len(scoped) < 24:
            continue
        split_counts = scoped.get("time_split", pd.Series("", index=scoped.index)).value_counts().to_dict()
        if min(int(split_counts.get(split, 0)) for split in ("train_60", "validation_20", "holdout_20")) < 5:
            continue
        for config in configs:
            summary, _, _ = evaluate_strategy(scoped, path, config)
            rows.append(
                summary
                | {
                    "branch_id": branch.branch_id,
                    "branch_description": branch.description,
                    "branch_event_count": int(len(scoped)),
                    "strategy_id": f"{branch.branch_id}__{config.strategy_id}",
                    "base_strategy_id": config.strategy_id,
                }
            )
    return rows


def select_shortlist(rows: Sequence[Mapping[str, Any]], branches: Sequence[BranchRule], configs: Sequence[GenericExecutionConfig], *, top_n: int) -> tuple[list[tuple[BranchRule, GenericExecutionConfig]], int]:
    branch_by_id = {branch.branch_id: branch for branch in branches}
    config_by_id = {config.strategy_id: config for config in configs}
    candidates = [dict(row) for row in rows]
    passing = [
        row
        for row in candidates
        if _as_int(row.get("validation_trades")) >= 8
        and _as_float(row.get("validation_total_return_pct"), default=-999.0) > 0.0
        and _as_float(row.get("validation_max_drawdown_pct"), default=-999.0) >= -18.0
        and _as_float(row.get("median_adtv_participation_pct"), default=999.0) <= 8.0
    ]
    pool = passing if passing else candidates
    ranked = sorted(pool, key=_candidate_score, reverse=True)
    chosen: list[tuple[BranchRule, GenericExecutionConfig]] = []
    seen: set[tuple[str, str]] = set()
    for row in ranked:
        pair = (str(row.get("branch_id")), str(row.get("base_strategy_id")))
        if pair in seen or pair[0] not in branch_by_id or pair[1] not in config_by_id:
            continue
        chosen.append((branch_by_id[pair[0]], config_by_id[pair[1]]))
        seen.add(pair)
        if len(chosen) >= top_n:
            break
    return chosen, len(passing)


def evaluate_full_candidate(events: pd.DataFrame, path: pd.DataFrame, branch: BranchRule, config: GenericExecutionConfig, *, selection_status: str) -> dict[str, Any]:
    scoped = _branch_events(events, branch)
    config = GenericExecutionConfig(**(asdict(config) | {"strategy_id": f"{branch.branch_id}__{config.strategy_id}"}))
    summary, trades, _ = evaluate_strategy(scoped, path, config)
    _, _, fixed_folds, fixed_summary = run_walk_forward(scoped, path, [config], config)
    _, cost_stress_summary = run_cost_stress(scoped, path, config)
    _, monte_carlo_summary = run_monte_carlo(trades, config, iterations=300)
    scorecard = score_tradable_setup(
        {"status": selection_status, "selected_metrics": summary},
        fixed_summary,
        cost_stress_summary,
        monte_carlo_summary,
    )
    negative_folds = int((pd.to_numeric(fixed_folds.get("test_total_return_pct"), errors="coerce") < 0).sum()) if not fixed_folds.empty else None
    return {
        "strategy_id": config.strategy_id,
        "branch_id": branch.branch_id,
        "branch_description": branch.description,
        "branch_event_count": int(len(scoped)),
        "score": scorecard.get("score"),
        "classification": scorecard.get("classification"),
        "promotion_blockers": ",".join(scorecard.get("promotion_blockers") or []),
        "selection_status": selection_status,
        "trades": summary.get("trades"),
        "validation_trades": summary.get("validation_trades"),
        "validation_total_return_pct": summary.get("validation_total_return_pct"),
        "validation_max_drawdown_pct": summary.get("validation_max_drawdown_pct"),
        "holdout_trades": summary.get("holdout_trades"),
        "holdout_total_return_pct": summary.get("holdout_total_return_pct"),
        "holdout_max_drawdown_pct": summary.get("holdout_max_drawdown_pct"),
        "total_return_pct": summary.get("total_return_pct"),
        "max_drawdown_pct": summary.get("max_drawdown_pct"),
        "win_rate_pct": summary.get("win_rate_pct"),
        "profit_factor": summary.get("profit_factor"),
        "median_adtv_participation_pct": summary.get("median_adtv_participation_pct"),
        "walk_forward_positive_fold_rate_pct": fixed_summary.get("positive_fold_rate_pct"),
        "walk_forward_negative_folds": negative_folds,
        "walk_forward_sum_return_pct": fixed_summary.get("sum_fold_return_pct"),
        "walk_forward_worst_fold_return_pct": fixed_summary.get("worst_fold_return_pct"),
        "cost_worst_scenario_return_pct": cost_stress_summary.get("worst_scenario_return_pct"),
        "monte_carlo_prob_positive_pct": monte_carlo_summary.get("prob_positive_pct"),
        "scorecard_component_scores": scorecard.get("component_scores"),
        "selected_config": asdict(config),
    }


def _guard(pattern_id: str, best: Mapping[str, Any]) -> dict[str, Any]:
    scope = _scope(pattern_id)
    score = _as_float(best.get("score"))
    blockers = {item.strip() for item in str(best.get("promotion_blockers") or "").split(",") if item.strip()}
    direct_scope = scope in {"long_cash_candidate", "long_up_breakout_branch"}
    remaining = set(blockers)
    if not direct_scope:
        remaining.add("scope_not_direct_long_cash_equity")
    if score < 95.0:
        remaining.add("score_below_95")
    checks = [
        {"check": "score_threshold_95", "status": "fail" if score < 95.0 else "pass", "observed": best.get("score"), "rule": "score must be >= 95"},
        {"check": "direct_long_cash_scope", "status": "fail" if not direct_scope else "pass", "observed": scope, "rule": "must be direct long-cash or explicit long-up branch"},
        {"check": "promotion_blockers_clear", "status": "fail" if blockers else "pass", "observed": ",".join(sorted(blockers)) or "none", "rule": "scorecard blockers must clear"},
        {"check": "fixed_walk_forward_positive", "status": "fail" if _as_float(best.get("walk_forward_positive_fold_rate_pct")) < 100.0 else "pass", "observed": best.get("walk_forward_positive_fold_rate_pct"), "rule": "fixed walk-forward must have no negative fold"},
    ]
    failures = [check["check"] for check in checks if check["status"] == "fail"]
    return {
        "policy_id": NO_OVERLIFT_POLICY_ID,
        "promotion_decision": "ELIGIBLE_FOR_FORMAL_PROMOTION_REVIEW" if not failures else "STOP_NO_PROMOTION_UNDER_NO_OVERLIFT_POLICY",
        "failures": failures,
        "remaining_tradable_blockers": sorted(item for item in remaining if item),
        "checks": checks,
    }


def run_one(pattern_id: str, out_dir: Path, *, shortlist_size: int) -> dict[str, Any]:
    chapter_dir = out_dir / pattern_id
    chapter_dir.mkdir(parents=True, exist_ok=True)
    spec = CHAPTER_SPECS[pattern_id]
    events, path, source_scope = load_chapter_events_and_path(spec)
    branches = build_branch_rules(pattern_id)
    configs = build_configs(pattern_id)
    print(f"[fold-repair] {pattern_id}: {len(branches)} branches x {len(configs)} configs", flush=True)
    first_rows = first_pass(events, path, branches, configs)
    print(f"[fold-repair] {pattern_id}: first pass rows={len(first_rows)}", flush=True)
    shortlist, passing_count = select_shortlist(first_rows, branches, configs, top_n=shortlist_size)
    selection_status = "selected_tradable_setup" if passing_count > 0 else "no_strategy_passed_validation_gate"
    rows = [
        evaluate_full_candidate(events, path, branch, config, selection_status=selection_status)
        for branch, config in shortlist
    ]
    rows = sorted(rows, key=lambda row: _as_float(row.get("score")), reverse=True)
    print(f"[fold-repair] {pattern_id}: full rows={len(rows)}", flush=True)
    best = rows[0] if rows else {}
    payload = {
        "redesign_id": REDESIGN_ID,
        "pattern_id": pattern_id,
        "scope": _scope(pattern_id),
        "source_scope": source_scope,
        "source_safe_selector_note": "branch rules use morphology, liquidity, regime, and breakout-confirmation fields only; no outcome labels are branch selectors",
        "branch_count": len(branches),
        "config_count": len(configs),
        "first_pass_count": len(first_rows),
        "validation_passing_count": passing_count,
        "shortlist_size": len(shortlist),
        "best_score": best.get("score"),
        "best_strategy_id": best.get("strategy_id"),
        "no_overlift_guard": _guard(pattern_id, best),
        "rows": rows,
        "first_pass_top_rows": sorted(first_rows, key=_candidate_score, reverse=True)[:30],
    }
    paths = {
        "json": chapter_dir / f"{pattern_id}_fold_repair.json",
        "csv": chapter_dir / f"{pattern_id}_fold_repair.csv",
        "grid": chapter_dir / f"{pattern_id}_fold_repair_grid.csv",
        "md": chapter_dir / f"{pattern_id}_fold_repair.md",
    }
    _write_json(paths["json"], payload)
    _write_csv(paths["csv"], rows)
    _write_csv(paths["grid"], first_rows)
    paths["md"].write_text(render_pattern_markdown(payload), encoding="utf-8")
    return payload | {"artifact_paths": {key: str(value) for key, value in paths.items()}}


def write_aggregate(out_dir: Path, rows: Sequence[Mapping[str, Any]], *, shortlist_size: int) -> dict[str, Path]:
    payload = {
        "redesign_id": REDESIGN_ID,
        "pattern_count": len(rows),
        "patterns": [str(row.get("pattern_id")) for row in rows],
        "shortlist_size": shortlist_size,
        "rows": list(rows),
    }
    paths = {
        "json": out_dir / "pattern_specific_fold_repair.json",
        "csv": out_dir / "pattern_specific_fold_repair.csv",
        "md": out_dir / "pattern_specific_fold_repair.md",
    }
    _write_json(paths["json"], payload)
    _write_csv(
        paths["csv"],
        [
            {
                "pattern_id": row.get("pattern_id"),
                "scope": row.get("scope"),
                "best_score": row.get("best_score"),
                "best_strategy_id": row.get("best_strategy_id"),
                "decision": (row.get("no_overlift_guard") or {}).get("promotion_decision"),
                "remaining_tradable_blockers": ",".join((row.get("no_overlift_guard") or {}).get("remaining_tradable_blockers") or []),
            }
            for row in rows
        ],
    )
    paths["md"].write_text(render_aggregate_markdown(payload), encoding="utf-8")
    return paths


def run_all(*, out_dir: Path, patterns: Sequence[str], shortlist_size: int) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [run_one(pattern_id, out_dir, shortlist_size=shortlist_size) for pattern_id in patterns]
    return write_aggregate(out_dir, rows, shortlist_size=shortlist_size)


def aggregate_existing(*, out_dir: Path, patterns: Sequence[str], shortlist_size: int) -> dict[str, Path]:
    rows: list[dict[str, Any]] = []
    for pattern_id in patterns:
        path = out_dir / pattern_id / f"{pattern_id}_fold_repair.json"
        if path.exists():
            rows.append(json.loads(path.read_text(encoding="utf-8")))
    return write_aggregate(out_dir, rows, shortlist_size=shortlist_size)


def render_pattern_markdown(payload: Mapping[str, Any]) -> str:
    guard = payload.get("no_overlift_guard") if isinstance(payload.get("no_overlift_guard"), Mapping) else {}
    lines = [
        f"# {payload.get('pattern_id')} Pattern-Specific Fold Repair",
        "",
        f"Redesign: `{REDESIGN_ID}`",
        "",
        f"- Best score: `{payload.get('best_score')}`",
        f"- Best strategy: `{payload.get('best_strategy_id')}`",
        f"- Decision: `{guard.get('promotion_decision')}`",
        f"- Remaining blockers: `{', '.join(guard.get('remaining_tradable_blockers') or [])}`",
        "",
        "| Strategy | Branch | Score | Blockers | Events | Trades | Validation | Holdout | WF positive | WF sum |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload.get("rows") or []:
        lines.append(
            "| {strategy} | {branch} | {score:.2f} | {blockers} | {events} | {trades} | {validation} | {holdout} | {wf_pos} | {wf_sum} |".format(
                strategy=row.get("strategy_id"),
                branch=row.get("branch_id"),
                score=_as_float(row.get("score")),
                blockers=row.get("promotion_blockers") or "",
                events=row.get("branch_event_count") or "",
                trades=row.get("trades") or "",
                validation=row.get("validation_total_return_pct") or "",
                holdout=row.get("holdout_total_return_pct") or "",
                wf_pos=row.get("walk_forward_positive_fold_rate_pct") or "",
                wf_sum=row.get("walk_forward_sum_return_pct") or "",
            )
        )
    return "\n".join(lines) + "\n"


def render_aggregate_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Pattern-Specific Fold Repair",
        "",
        f"Redesign: `{REDESIGN_ID}`",
        "",
        "Branch rules are pattern-specific and source-safe.",
        "",
        "| Pattern | Scope | Best score | Decision | Remaining blockers |",
        "|---|---|---:|---|---|",
    ]
    for row in payload.get("rows") or []:
        guard = row.get("no_overlift_guard") if isinstance(row.get("no_overlift_guard"), Mapping) else {}
        score = "" if row.get("best_score") is None else f"{_as_float(row.get('best_score')):.2f}"
        lines.append(
            f"| {row.get('pattern_id')} | {row.get('scope')} | {score} | {guard.get('promotion_decision')} | {', '.join(guard.get('remaining_tradable_blockers') or [])} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run pattern-specific fold repair for blocked chapters.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--patterns", default=",".join(DEFAULT_PATTERNS))
    parser.add_argument("--shortlist-size", type=int, default=6)
    parser.add_argument("--aggregate-existing", action="store_true")
    args = parser.parse_args()
    patterns = [item.strip() for item in str(args.patterns).split(",") if item.strip()]
    if args.aggregate_existing:
        paths = aggregate_existing(out_dir=Path(args.out_dir), patterns=patterns, shortlist_size=int(args.shortlist_size))
    else:
        paths = run_all(out_dir=Path(args.out_dir), patterns=patterns, shortlist_size=int(args.shortlist_size))
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
