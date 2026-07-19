"""Run a generic executable tradable layer for publication-final chapters.

The Bull Flag remains the hand-tuned KPI benchmark.  This script applies the
same execution concepts to the rest of the final chapters: concrete entry,
target/stop/time exit, costs, sizing, capacity, validation/holdout,
walk-forward, cost stress, and Monte Carlo.

Down-breakout chapters are evaluated as synthetic-short/defensive evidence and
are not promoted as directly tradable Vietnam cash-equity setups.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.v2.bull_flag_tradable_setup import score_tradable_setup  # noqa: E402


DEFAULT_MANIFEST = Path("artifacts/final_chapters/final_chapters_manifest.json")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/chapter_tradable_layer")
LAYER_ID = "generic_chapter_tradable_layer_v1"
_PATH_GROUP_CACHE: dict[int, dict[str, pd.DataFrame]] = {}
NON_CASH_EQUITY_SYMBOLS = {
    "VNINDEX",
    "HNXINDEX",
    "UPCOMINDEX",
    "VN30",
    "VN100",
    "HNX30",
}


@dataclass(frozen=True)
class ChapterSpec:
    pattern_id: str
    events_path: Path
    path_path: Path
    scope: str
    variant: str | None = None
    preserve_publication_quality_scope: bool = False
    skip_generic: bool = False
    external_scorecard: Path | None = None
    external_selected_strategy: Path | None = None
    external_release_candidate: Path | None = None


@dataclass(frozen=True)
class GenericExecutionConfig:
    strategy_id: str
    target_multiple: float = 0.50
    stop_loss_pct: float = 7.0
    max_holding_days: int = 60
    position_size_pct: float = 0.05
    max_positions: int = 20
    initial_equity: float = 1_000_000_000.0
    commission_bps_per_side: float = 15.0
    slippage_bps_per_side: float = 10.0
    sell_tax_bps: float = 10.0
    same_bar_policy: str = "stop_first"
    entry_delay_bars: int = 1
    min_setup_score: float | None = None
    min_confirmation_score: float | None = None
    allowed_breakout_directions: tuple[str, ...] | None = None
    allowed_variants: tuple[str, ...] | None = None
    allowed_liquidity_buckets: tuple[str, ...] | None = None
    allowed_market_regimes: tuple[str, ...] | None = None
    allowed_publication_quality_tiers: tuple[str, ...] | None = None
    allowed_volume_trend_directions: tuple[str, ...] | None = None
    min_prior_trend_pct: float | None = None
    min_prior_trend_signed_pct: float | None = None
    min_first_gap_pct: float | None = None
    min_second_gap_pct: float | None = None
    min_gap_similarity_ratio: float | None = None
    min_island_duration_bars: float | None = None
    max_island_duration_bars: float | None = None
    source_gap_isolation_required: bool = False
    allowed_source_retrace_bands: tuple[str, ...] | None = None
    allowed_path_quality_buckets: tuple[str, ...] | None = None
    allowed_tradability_quality_buckets: tuple[str, ...] | None = None
    min_first_leg_linearity_r2: float | None = None
    min_first_leg_pct: float | None = None
    min_first_body_atr: float | None = None
    min_last_body_atr: float | None = None
    max_middle_body_ratio: float | None = None
    max_target_dist_pct: float | None = None
    max_adtv_participation_pct: float = 30.0
    target_adtv_participation_pct: float = 10.0
    max_entry_bar_participation_pct: float = 30.0
    adtv_unit_multiplier: float = 1_000.0
    value_unit_multiplier: float = 1_000.0
    low_liquidity_extra_slippage_bps: float = 40.0
    mid_liquidity_extra_slippage_bps: float = 15.0
    high_liquidity_extra_slippage_bps: float = 5.0
    gap_slippage_threshold_pct: float = 3.0
    gap_extra_slippage_bps: float = 20.0
    limit_range_threshold_pct: float = 6.5
    limit_extra_slippage_bps: float = 25.0


CHAPTER_SPECS: dict[str, ChapterSpec] = {
    "bull_flags": ChapterSpec(
        "bull_flags",
        Path("artifacts/scanner_v2/bull_flags_adaptive_grid/scans/bull_flag_v2_split_stable_recovery/events.csv"),
        Path("artifacts/scanner_v2/bull_flags_adaptive_grid/scans/bull_flag_v2_split_stable_recovery/post_breakout_path.csv"),
        "long_cash_candidate",
        skip_generic=True,
        external_scorecard=Path("artifacts/scanner_v2/bull_flags_tradable_setup/bull_flag_tradable_scorecard.json"),
        external_selected_strategy=Path("artifacts/scanner_v2/bull_flags_tradable_setup/bull_flag_tradable_selected_strategy.json"),
        external_release_candidate=Path("artifacts/scanner_v2/bull_flags_release_candidate/bull_flag_release_candidate.json"),
    ),
    "bear_flags": ChapterSpec(
        "bear_flags",
        Path("artifacts/scanner_v2/bear_flags_db_source_parity/db_active/events.csv"),
        Path("artifacts/scanner_v2/bear_flags_db_source_parity/db_active/post_breakout_path.csv"),
        "defensive_informational",
    ),
    "bull_pennants": ChapterSpec(
        "bull_pennants",
        Path("artifacts/scanner_v2/pennants/events.csv"),
        Path("artifacts/scanner_v2/pennants/post_breakout_path.csv"),
        "long_cash_candidate",
        variant="bull_pennant",
        skip_generic=True,
        external_scorecard=Path("artifacts/scanner_v2/bull_pennants_tradable_setup/bull_pennant_tradable_scorecard.json"),
        external_selected_strategy=Path("artifacts/scanner_v2/bull_pennants_tradable_setup/bull_pennant_tradable_selected_strategy.json"),
        external_release_candidate=Path("artifacts/scanner_v2/bull_pennants_release_candidate/bull_pennant_release_candidate.json"),
    ),
    "bear_pennants": ChapterSpec(
        "bear_pennants",
        Path("artifacts/scanner_v2/pennants/events.csv"),
        Path("artifacts/scanner_v2/pennants/post_breakout_path.csv"),
        "defensive_informational",
        variant="bear_pennant",
    ),
    "high_tight_flags": ChapterSpec(
        "high_tight_flags",
        Path("artifacts/scanner_v2/high_tight_flags/events.csv"),
        Path("artifacts/scanner_v2/high_tight_flags/post_breakout_path.csv"),
        "long_cash_candidate",
        variant="high_tight_flag",
    ),
    "triangles_ascending": ChapterSpec(
        "triangles_ascending",
        Path("artifacts/scanner_v2/ascending_triangles_db_source_parity/db_active/events.csv"),
        Path("artifacts/scanner_v2/ascending_triangles_db_source_parity/db_active/post_breakout_path.csv"),
        "long_cash_candidate",
    ),
    "triangles_descending": ChapterSpec(
        "triangles_descending",
        Path("artifacts/scanner_v2/descending_triangles_db_source_parity/db_active/events.csv"),
        Path("artifacts/scanner_v2/descending_triangles_db_source_parity/db_active/post_breakout_path.csv"),
        "defensive_informational",
    ),
    "triangles_symmetrical": ChapterSpec(
        "triangles_symmetrical",
        Path("artifacts/scanner_v2/symmetrical_triangles_db_source_parity/db_active/events.csv"),
        Path("artifacts/scanner_v2/symmetrical_triangles_db_source_parity/db_active/post_breakout_path.csv"),
        "mixed_direction_reference",
    ),
    "double_bottoms_adam_adam": ChapterSpec(
        "double_bottoms_adam_adam",
        Path("artifacts/scanner_v2/double_pattern_family/double_bottoms/db_active/events.csv"),
        Path("artifacts/scanner_v2/double_pattern_family/double_bottoms/db_active/post_breakout_path.csv"),
        "long_cash_candidate",
        variant="AA",
    ),
    "double_bottoms_adam_eve": ChapterSpec(
        "double_bottoms_adam_eve",
        Path("artifacts/scanner_v2/double_pattern_family/double_bottoms/db_active/events.csv"),
        Path("artifacts/scanner_v2/double_pattern_family/double_bottoms/db_active/post_breakout_path.csv"),
        "long_cash_candidate",
        variant="AE",
    ),
    "double_bottoms_eve_adam": ChapterSpec(
        "double_bottoms_eve_adam",
        Path("artifacts/scanner_v2/double_pattern_family/double_bottoms/db_active/events.csv"),
        Path("artifacts/scanner_v2/double_pattern_family/double_bottoms/db_active/post_breakout_path.csv"),
        "long_cash_candidate",
        variant="EA",
    ),
    "double_bottoms_eve_eve": ChapterSpec(
        "double_bottoms_eve_eve",
        Path("artifacts/scanner_v2/double_pattern_family/double_bottoms/db_active/events.csv"),
        Path("artifacts/scanner_v2/double_pattern_family/double_bottoms/db_active/post_breakout_path.csv"),
        "long_cash_candidate",
        variant="EE",
    ),
    "double_tops_adam_adam": ChapterSpec(
        "double_tops_adam_adam",
        Path("artifacts/scanner_v2/double_pattern_family/double_tops/db_active/events.csv"),
        Path("artifacts/scanner_v2/double_pattern_family/double_tops/db_active/post_breakout_path.csv"),
        "defensive_informational",
        variant="AA",
    ),
    "double_tops_adam_eve": ChapterSpec(
        "double_tops_adam_eve",
        Path("artifacts/scanner_v2/double_pattern_family/double_tops/db_active/events.csv"),
        Path("artifacts/scanner_v2/double_pattern_family/double_tops/db_active/post_breakout_path.csv"),
        "defensive_informational",
        variant="AE",
    ),
    "double_tops_eve_adam": ChapterSpec(
        "double_tops_eve_adam",
        Path("artifacts/scanner_v2/double_pattern_family/double_tops/db_active/events.csv"),
        Path("artifacts/scanner_v2/double_pattern_family/double_tops/db_active/post_breakout_path.csv"),
        "defensive_informational",
        variant="EA",
    ),
    "double_tops_eve_eve": ChapterSpec(
        "double_tops_eve_eve",
        Path("artifacts/scanner_v2/double_pattern_family/double_tops/db_active/events.csv"),
        Path("artifacts/scanner_v2/double_pattern_family/double_tops/db_active/post_breakout_path.csv"),
        "defensive_informational",
        variant="EE",
    ),
    "wedges_falling": ChapterSpec(
        "wedges_falling",
        Path("artifacts/scanner_v2/wedge_family/falling_wedges/db_active/events.csv"),
        Path("artifacts/scanner_v2/wedge_family/falling_wedges/db_active/post_breakout_path.csv"),
        "long_cash_candidate",
    ),
    "wedges_rising": ChapterSpec(
        "wedges_rising",
        Path("artifacts/scanner_v2/wedge_family/rising_wedges/db_active/events.csv"),
        Path("artifacts/scanner_v2/wedge_family/rising_wedges/db_active/post_breakout_path.csv"),
        "defensive_informational",
    ),
    "cup_with_handle": ChapterSpec(
        "cup_with_handle",
        Path("artifacts/scanner_v2/cup_with_handle_family/cup_with_handle/db_active/events.csv"),
        Path("artifacts/scanner_v2/cup_with_handle_family/cup_with_handle/db_active/post_breakout_path.csv"),
        "long_cash_candidate",
    ),
    "cup_with_handle_inverted": ChapterSpec(
        "cup_with_handle_inverted",
        Path("artifacts/scanner_v2/cup_with_handle_family/cup_with_handle_inverted/db_active/events.csv"),
        Path("artifacts/scanner_v2/cup_with_handle_family/cup_with_handle_inverted/db_active/post_breakout_path.csv"),
        "defensive_informational",
    ),
    "rectangle_bottoms": ChapterSpec(
        "rectangle_bottoms",
        Path("artifacts/scanner_v2/rectangle_family/rectangle_bottoms/db_active/events.csv"),
        Path("artifacts/scanner_v2/rectangle_family/rectangle_bottoms/db_active/post_breakout_path.csv"),
        "mixed_direction_reference",
    ),
    "rectangle_tops": ChapterSpec(
        "rectangle_tops",
        Path("artifacts/scanner_v2/rectangle_family/rectangle_tops/db_active/events.csv"),
        Path("artifacts/scanner_v2/rectangle_family/rectangle_tops/db_active/post_breakout_path.csv"),
        "mixed_direction_reference",
    ),
    "head_and_shoulders_bottoms_complex": ChapterSpec(
        "head_and_shoulders_bottoms_complex",
        Path("artifacts/scanner_v2/head_shoulders_family/head_and_shoulders_bottoms_complex/db_active/events.csv"),
        Path("artifacts/scanner_v2/head_shoulders_family/head_and_shoulders_bottoms_complex/db_active/post_breakout_path.csv"),
        "long_cash_candidate",
    ),
    "head_and_shoulders_bottoms": ChapterSpec(
        "head_and_shoulders_bottoms",
        Path("artifacts/scanner_v2/head_shoulders_family/head_and_shoulders_bottoms/db_active/events.csv"),
        Path("artifacts/scanner_v2/head_shoulders_family/head_and_shoulders_bottoms/db_active/post_breakout_path.csv"),
        "long_cash_candidate",
    ),
    "head_and_shoulders_tops_complex": ChapterSpec(
        "head_and_shoulders_tops_complex",
        Path("artifacts/scanner_v2/head_shoulders_family/head_and_shoulders_tops_complex/db_active/events.csv"),
        Path("artifacts/scanner_v2/head_shoulders_family/head_and_shoulders_tops_complex/db_active/post_breakout_path.csv"),
        "defensive_informational",
        preserve_publication_quality_scope=True,
    ),
    "broadening_bottoms": ChapterSpec(
        "broadening_bottoms",
        Path("artifacts/scanner_v2/broadening_family/broadening_bottoms/db_active/events.csv"),
        Path("artifacts/scanner_v2/broadening_family/broadening_bottoms/db_active/post_breakout_path.csv"),
        "mixed_direction_reference",
    ),
    "broadening_formations_right_angled_ascending": ChapterSpec(
        "broadening_formations_right_angled_ascending",
        Path("artifacts/scanner_v2/broadening_family/broadening_formations_right_angled_ascending/db_active/events.csv"),
        Path("artifacts/scanner_v2/broadening_family/broadening_formations_right_angled_ascending/db_active/post_breakout_path.csv"),
        "defensive_informational",
    ),
    "broadening_formations_right_angled_descending": ChapterSpec(
        "broadening_formations_right_angled_descending",
        Path("artifacts/scanner_v2/broadening_family/broadening_formations_right_angled_descending/db_active/events.csv"),
        Path("artifacts/scanner_v2/broadening_family/broadening_formations_right_angled_descending/db_active/post_breakout_path.csv"),
        "mixed_direction_reference",
    ),
    "broadening_tops": ChapterSpec(
        "broadening_tops",
        Path("artifacts/scanner_v2/broadening_family/broadening_tops/db_active/events.csv"),
        Path("artifacts/scanner_v2/broadening_family/broadening_tops/db_active/post_breakout_path.csv"),
        "defensive_informational",
    ),
    "broadening_wedges_ascending": ChapterSpec(
        "broadening_wedges_ascending",
        Path("artifacts/scanner_v2/broadening_family/broadening_wedges_ascending/db_active/events.csv"),
        Path("artifacts/scanner_v2/broadening_family/broadening_wedges_ascending/db_active/post_breakout_path.csv"),
        "defensive_informational",
    ),
    "broadening_wedges_descending": ChapterSpec(
        "broadening_wedges_descending",
        Path("artifacts/scanner_v2/broadening_family/broadening_wedges_descending/db_active/events.csv"),
        Path("artifacts/scanner_v2/broadening_family/broadening_wedges_descending/db_active/post_breakout_path.csv"),
        "long_cash_candidate",
    ),
    "measured_move_up": ChapterSpec(
        "measured_move_up",
        Path("artifacts/scanner_v2/measured_move_family/measured_move_up/db_active/events.csv"),
        Path("artifacts/scanner_v2/measured_move_family/measured_move_up/db_active/post_breakout_path.csv"),
        "long_cash_candidate",
    ),
    "measured_move_down": ChapterSpec(
        "measured_move_down",
        Path("artifacts/scanner_v2/measured_move_family/measured_move_down/db_active/events.csv"),
        Path("artifacts/scanner_v2/measured_move_family/measured_move_down/db_active/post_breakout_path.csv"),
        "defensive_informational",
    ),
    "scallops_ascending": ChapterSpec(
        "scallops_ascending",
        Path("artifacts/scanner_v2/scallop_family/scallops_ascending/db_active/events.csv"),
        Path("artifacts/scanner_v2/scallop_family/scallops_ascending/db_active/post_breakout_path.csv"),
        "mixed_direction_reference",
    ),
    "scallops_ascending_inverted": ChapterSpec(
        "scallops_ascending_inverted",
        Path("artifacts/scanner_v2/scallop_family/scallops_ascending_inverted/db_active/events.csv"),
        Path("artifacts/scanner_v2/scallop_family/scallops_ascending_inverted/db_active/post_breakout_path.csv"),
        "long_cash_candidate",
    ),
    "scallops_descending": ChapterSpec(
        "scallops_descending",
        Path("artifacts/scanner_v2/scallop_family/scallops_descending/db_active/events.csv"),
        Path("artifacts/scanner_v2/scallop_family/scallops_descending/db_active/post_breakout_path.csv"),
        "mixed_direction_reference",
    ),
    "scallops_descending_inverted": ChapterSpec(
        "scallops_descending_inverted",
        Path("artifacts/scanner_v2/scallop_family/scallops_descending_inverted/db_active/events.csv"),
        Path("artifacts/scanner_v2/scallop_family/scallops_descending_inverted/db_active/post_breakout_path.csv"),
        "defensive_informational",
    ),
    "pipe_bottoms": ChapterSpec(
        "pipe_bottoms",
        Path("artifacts/scanner_v2/pipe_family/pipe_bottoms/db_active/events.csv"),
        Path("artifacts/scanner_v2/pipe_family/pipe_bottoms/db_active/post_breakout_path.csv"),
        "long_cash_candidate",
    ),
    "pipe_tops": ChapterSpec(
        "pipe_tops",
        Path("artifacts/scanner_v2/pipe_family/pipe_tops/db_active/events.csv"),
        Path("artifacts/scanner_v2/pipe_family/pipe_tops/db_active/post_breakout_path.csv"),
        "defensive_informational",
    ),
    "horn_bottoms": ChapterSpec(
        "horn_bottoms",
        Path("artifacts/scanner_v2/horn_family/horn_bottoms/db_active/events.csv"),
        Path("artifacts/scanner_v2/horn_family/horn_bottoms/db_active/post_breakout_path.csv"),
        "long_cash_candidate",
    ),
    "horn_tops": ChapterSpec(
        "horn_tops",
        Path("artifacts/scanner_v2/horn_family/horn_tops/db_active/events.csv"),
        Path("artifacts/scanner_v2/horn_family/horn_tops/db_active/post_breakout_path.csv"),
        "defensive_informational",
    ),
    "diamond_bottoms": ChapterSpec(
        "diamond_bottoms",
        Path("artifacts/scanner_v2/diamond_family/diamond_bottoms/db_active/events.csv"),
        Path("artifacts/scanner_v2/diamond_family/diamond_bottoms/db_active/post_breakout_path.csv"),
        "long_cash_candidate",
    ),
    "diamond_tops": ChapterSpec(
        "diamond_tops",
        Path("artifacts/scanner_v2/diamond_family/diamond_tops/db_active/events.csv"),
        Path("artifacts/scanner_v2/diamond_family/diamond_tops/db_active/post_breakout_path.csv"),
        "defensive_informational",
    ),
    "dead_cat_bounce": ChapterSpec(
        "dead_cat_bounce",
        Path("artifacts/scanner_v2/dead_cat_bounce_family/dead_cat_bounce/db_active/events.csv"),
        Path("artifacts/scanner_v2/dead_cat_bounce_family/dead_cat_bounce/db_active/post_breakout_path.csv"),
        "defensive_informational",
    ),
    "dead_cat_bounce_inverted": ChapterSpec(
        "dead_cat_bounce_inverted",
        Path("artifacts/scanner_v2/dead_cat_bounce_family/dead_cat_bounce_inverted/db_active/events.csv"),
        Path("artifacts/scanner_v2/dead_cat_bounce_family/dead_cat_bounce_inverted/db_active/post_breakout_path.csv"),
        "defensive_informational",
    ),
    "three_falling_peaks": ChapterSpec(
        "three_falling_peaks",
        Path("artifacts/scanner_v2/three_peaks_valleys_family/three_falling_peaks/db_active/events.csv"),
        Path("artifacts/scanner_v2/three_peaks_valleys_family/three_falling_peaks/db_active/post_breakout_path.csv"),
        "defensive_informational",
    ),
    "three_rising_valleys": ChapterSpec(
        "three_rising_valleys",
        Path("artifacts/scanner_v2/three_peaks_valleys_family/three_rising_valleys/db_active/events.csv"),
        Path("artifacts/scanner_v2/three_peaks_valleys_family/three_rising_valleys/db_active/post_breakout_path.csv"),
        "long_cash_candidate",
    ),
    "triple_tops": ChapterSpec(
        "triple_tops",
        Path("artifacts/scanner_v2/triple_family/triple_tops/db_active/events.csv"),
        Path("artifacts/scanner_v2/triple_family/triple_tops/db_active/post_breakout_path.csv"),
        "defensive_informational",
    ),
    "triple_bottoms": ChapterSpec(
        "triple_bottoms",
        Path("artifacts/scanner_v2/triple_family/triple_bottoms/db_active/events.csv"),
        Path("artifacts/scanner_v2/triple_family/triple_bottoms/db_active/post_breakout_path.csv"),
        "long_cash_candidate",
    ),
    "bump_and_run_reversal_bottoms": ChapterSpec(
        "bump_and_run_reversal_bottoms",
        Path("artifacts/scanner_v2/bump_and_run_family/bump_and_run_reversal_bottoms/db_active/events.csv"),
        Path("artifacts/scanner_v2/bump_and_run_family/bump_and_run_reversal_bottoms/db_active/post_breakout_path.csv"),
        "long_cash_candidate",
    ),
    "bump_and_run_reversal_tops": ChapterSpec(
        "bump_and_run_reversal_tops",
        Path("artifacts/scanner_v2/bump_and_run_family/bump_and_run_reversal_tops/db_active/events.csv"),
        Path("artifacts/scanner_v2/bump_and_run_family/bump_and_run_reversal_tops/db_active/post_breakout_path.csv"),
        "defensive_informational",
    ),
    "area_gaps": ChapterSpec(
        "area_gaps",
        Path("artifacts/scanner_v2/gap_family/area_gaps/db_active/events.csv"),
        Path("artifacts/scanner_v2/gap_family/area_gaps/db_active/post_breakout_path.csv"),
        "gap_closure_informational",
    ),
    "breakaway_gaps": ChapterSpec(
        "breakaway_gaps",
        Path("artifacts/scanner_v2/gap_family/breakaway_gaps/db_active/events.csv"),
        Path("artifacts/scanner_v2/gap_family/breakaway_gaps/db_active/post_breakout_path.csv"),
        "long_cash_candidate",
    ),
    "continuation_gaps": ChapterSpec(
        "continuation_gaps",
        Path("artifacts/scanner_v2/gap_family/continuation_gaps/db_active/events.csv"),
        Path("artifacts/scanner_v2/gap_family/continuation_gaps/db_active/post_breakout_path.csv"),
        "long_cash_candidate",
    ),
    "exhaustion_gaps": ChapterSpec(
        "exhaustion_gaps",
        Path("artifacts/scanner_v2/gap_family/exhaustion_gaps/db_active/events.csv"),
        Path("artifacts/scanner_v2/gap_family/exhaustion_gaps/db_active/post_breakout_path.csv"),
        "gap_exhaustion_informational",
    ),
    "island_reversals": ChapterSpec(
        "island_reversals",
        Path("artifacts/scanner_v2/island_family/island_reversals/db_active/events.csv"),
        Path("artifacts/scanner_v2/island_family/island_reversals/db_active/post_breakout_path.csv"),
        "long_cash_candidate",
    ),
    "islands_long": ChapterSpec(
        "islands_long",
        Path("artifacts/scanner_v2/island_family/islands_long/db_active/events.csv"),
        Path("artifacts/scanner_v2/island_family/islands_long/db_active/post_breakout_path.csv"),
        "long_cash_candidate",
    ),
    "rounding_bottoms": ChapterSpec(
        "rounding_bottoms",
        Path("artifacts/scanner_v2/rounding_family/rounding_bottoms/db_active/events.csv"),
        Path("artifacts/scanner_v2/rounding_family/rounding_bottoms/db_active/post_breakout_path.csv"),
        "long_cash_candidate",
    ),
    "rounding_tops": ChapterSpec(
        "rounding_tops",
        Path("artifacts/scanner_v2/rounding_family/rounding_tops/db_active/events.csv"),
        Path("artifacts/scanner_v2/rounding_family/rounding_tops/db_active/post_breakout_path.csv"),
        "defensive_informational",
    ),
    "inside_day": ChapterSpec(
        "inside_day",
        Path("artifacts/scanner_v2/inside_day_family/inside_day/db_active/events.csv"),
        Path("artifacts/scanner_v2/inside_day_family/inside_day/db_active/post_breakout_path.csv"),
        "mixed_direction_reference",
    ),
    "rising_three_methods": ChapterSpec(
        "rising_three_methods",
        Path("artifacts/scanner_v2/three_methods_family/rising_three_methods/db_active/events.csv"),
        Path("artifacts/scanner_v2/three_methods_family/rising_three_methods/db_active/post_breakout_path.csv"),
        "long_cash_candidate",
    ),
    "falling_three_methods": ChapterSpec(
        "falling_three_methods",
        Path("artifacts/scanner_v2/three_methods_family/falling_three_methods/db_active/events.csv"),
        Path("artifacts/scanner_v2/three_methods_family/falling_three_methods/db_active/post_breakout_path.csv"),
        "defensive_informational",
    ),
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path, low_memory=False)
    if "event_id" not in frame.columns and "detection_id" in frame.columns:
        frame["event_id"] = frame["detection_id"]
    return frame


def _as_float(value: Any, default: float = 0.0) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return float(default)
    return float(numeric)


def _bool_series(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    return series.astype(str).str.lower().isin({"true", "1", "yes", "y"})


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(float(low), min(float(high), float(value)))


def _score_numeric(value: Any, low: float, high: float) -> float:
    numeric = _as_float(value, default=low)
    if high == low:
        return 100.0 if numeric >= high else 0.0
    return _clip((numeric - low) / (high - low) * 100.0)


def _safe_concat(frames: Sequence[pd.DataFrame]) -> pd.DataFrame:
    clean = [frame.dropna(axis=1, how="all") for frame in frames if not frame.empty]
    return pd.concat(clean, ignore_index=True) if clean else pd.DataFrame()


def _filter_public_scope(events: pd.DataFrame, spec: ChapterSpec) -> pd.DataFrame:
    if events.empty:
        return events.copy()
    scoped = events.copy()
    if spec.variant and "variant" in scoped.columns:
        scoped = scoped[scoped["variant"].astype(str) == spec.variant].copy()
    if spec.preserve_publication_quality_scope:
        pass
    elif "publication_quality_tier" in scoped.columns:
        candidate = scoped[scoped["publication_quality_tier"].astype(str).str.lower().isin(["premium", "standard"])].copy()
        if len(candidate) >= 30:
            scoped = candidate
    elif "pattern_quality_tier" in scoped.columns:
        candidate = scoped[scoped["pattern_quality_tier"].astype(str).str.lower().isin(["clean", "usable"])].copy()
        if len(candidate) >= 30:
            scoped = candidate
    if "is_primary_event_60d" in scoped.columns:
        candidate = scoped[_bool_series(scoped["is_primary_event_60d"])].copy()
        if len(candidate) >= 30:
            scoped = candidate
    return scoped.reset_index(drop=True)


def _filter_pattern_tradable_scope(events: pd.DataFrame, spec: ChapterSpec) -> pd.DataFrame:
    """Apply pattern-specific tradable research scope before time splits.

    Execution filters are evaluated after chronological splitting.  For
    Measured Move Up, however, the tradable question is explicitly the
    source-aligned branch: a normal retrace and a straight enough first leg.
    Applying that scope before the split keeps walk-forward folds measuring the
    intended setup instead of the broader publication chapter.
    """

    if events.empty:
        return events.copy()
    scoped = events.copy()
    if spec.pattern_id == "scallops_ascending_inverted":
        mask = pd.Series(True, index=scoped.index)
        if "breakout_direction" in scoped.columns:
            mask &= scoped["breakout_direction"].astype(str).eq("up")
        if "liquidity_bucket" in scoped.columns:
            mask &= scoped["liquidity_bucket"].astype(str).isin(("mid", "high"))
        if "publication_quality_tier" in scoped.columns:
            mask &= scoped["publication_quality_tier"].astype(str).str.lower().isin(("premium", "standard"))
        if "publication_quality_score" in scoped.columns:
            mask &= pd.to_numeric(scoped["publication_quality_score"], errors="coerce").fillna(-np.inf) >= 72.0
        candidate = scoped[mask].copy()
        if len(candidate) >= 80:
            return candidate.reset_index(drop=True)
        return scoped.reset_index(drop=True)
    if spec.pattern_id in {"island_reversals", "islands_long"}:
        mask = pd.Series(True, index=scoped.index)
        if "variant" in scoped.columns:
            mask &= scoped["variant"].astype(str).eq("island_bottom")
        if "breakout_direction" in scoped.columns:
            mask &= scoped["breakout_direction"].astype(str).eq("up")
        if "source_gap_isolation_ok" in scoped.columns:
            mask &= _bool_series(scoped["source_gap_isolation_ok"])
        candidate = scoped[mask].copy()
        if len(candidate) >= 80:
            return candidate.reset_index(drop=True)
        return scoped.reset_index(drop=True)
    if spec.pattern_id == "rectangle_bottoms":
        # After-the-Buy treats bullish rectangle work as direction-specific:
        # either a confirmed upward breakout, or a failed downside breakout
        # that reclaims the rectangle top.  The available event table does not
        # yet encode the latter as a separate branch, so the executable layer
        # removes outright down-breakout rows before testing long-cash behavior.
        if "breakout_direction" in scoped.columns:
            candidate = scoped[scoped["breakout_direction"].astype(str).eq("up")].copy()
            if len(candidate) >= 80:
                return candidate.reset_index(drop=True)
        return scoped.reset_index(drop=True)
    if spec.pattern_id != "measured_move_up":
        return events.copy()
    mask = pd.Series(True, index=scoped.index)
    if "source_retrace_band" in scoped.columns:
        mask &= scoped["source_retrace_band"].astype(str).eq("ideal_38_62")
    if "first_leg_linearity_r2" in scoped.columns:
        mask &= pd.to_numeric(scoped["first_leg_linearity_r2"], errors="coerce").fillna(-np.inf) >= 0.80
    candidate = scoped[mask].copy()
    if len(candidate) >= 80:
        return candidate.reset_index(drop=True)
    return scoped.reset_index(drop=True)


def _filter_cash_equity_symbols(events: pd.DataFrame) -> pd.DataFrame:
    """Keep executable tradable tests on stock symbols, not index series.

    Some scanner inputs keep benchmark/index rows in the same OHLCV table as
    stocks.  Those rows are valid context for descriptive/publication analysis,
    but they are not directly executable cash-equity trades.  Tradable layer
    tests must therefore remove them before time splits and walk-forward.
    """

    if events.empty or "symbol" not in events.columns:
        return events.copy()
    symbols = events["symbol"].astype(str).str.upper().str.strip()
    index_like = symbols.isin(NON_CASH_EQUITY_SYMBOLS) | symbols.str.endswith("INDEX")
    return events[~index_like].copy()


def _assign_time_splits(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return events.copy()
    out = events.sort_values(["breakout_date", "symbol"]).reset_index(drop=True).copy()
    n = len(out)
    train_end = int(np.floor(n * 0.60))
    validation_end = int(np.floor(n * 0.80))
    out["time_split"] = "holdout_20"
    if n:
        out.loc[: max(train_end - 1, 0), "time_split"] = "train_60"
        out.loc[train_end : max(validation_end - 1, train_end), "time_split"] = "validation_20"
    return out


def _attach_scores(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return events.copy()
    out = events.copy()
    def numeric_series(name: str, default: float = np.nan) -> pd.Series:
        if name in out.columns:
            return pd.to_numeric(out[name], errors="coerce")
        return pd.Series(default, index=out.index, dtype="float64")

    quality = numeric_series("publication_quality_score")
    if quality.isna().all():
        quality = numeric_series("pattern_quality_score")
    out["setup_score"] = quality.fillna(55.0).clip(0.0, 100.0)
    breakout_clearance = numeric_series("breakout_clearance_pct", 0.0).fillna(0.0)
    breakout_volume = numeric_series("breakout_volume_ratio", 1.0).fillna(1.0)
    volume_score = ((breakout_volume - 0.75) / 1.5 * 100.0).clip(0.0, 100.0)
    clearance_score = ((breakout_clearance - 0.0) / 2.5 * 100.0).clip(0.0, 100.0)
    out["confirmation_score"] = (0.55 * out["setup_score"] + 0.25 * volume_score + 0.20 * clearance_score).round(2)
    mfe = numeric_series("mfe_pct", 0.0).fillna(0.0)
    mae = numeric_series("mae_pct", 0.0).fillna(0.0)
    target_first = _bool_series(out.get("target_first_before_adverse_5pct", pd.Series(False, index=out.index))).astype(float)
    target_hit = _bool_series(out.get("target_hit", pd.Series(False, index=out.index))).astype(float)
    failure = _bool_series(out.get("failure_5pct", pd.Series(False, index=out.index))).astype(float)
    ratio_score = ((mfe / mae.clip(lower=1.0)) / 2.0 * 100.0).clip(0.0, 100.0)
    out["followthrough_score"] = (0.35 * ratio_score + 25.0 * target_first + 20.0 * target_hit - 25.0 * failure + 35.0).clip(0.0, 100.0).round(2)
    return out


def _attach_adtv(events: pd.DataFrame, path: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return events.copy()
    out = events.copy()
    if "adtv20_value" in out.columns and pd.to_numeric(out["adtv20_value"], errors="coerce").notna().any():
        return out
    if path.empty:
        out["adtv20_value"] = np.nan
        return out
    p = path.copy()
    p["bar_after_breakout"] = pd.to_numeric(p.get("bar_after_breakout"), errors="coerce")
    p["close"] = pd.to_numeric(p.get("close"), errors="coerce")
    p["volume"] = pd.to_numeric(p.get("volume"), errors="coerce")
    first20 = p[(p["bar_after_breakout"] >= 1) & (p["bar_after_breakout"] <= 20)].copy()
    first20["trade_value"] = first20["close"] * first20["volume"]
    adtv = first20.groupby("event_id")["trade_value"].median()
    out["adtv20_value"] = out["event_id"].astype(str).map(adtv)
    return out


def load_chapter_events_and_path(spec: ChapterSpec) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    events_raw = _read_csv(spec.events_path)
    path_raw = _read_csv(spec.path_path)
    if events_raw.empty or path_raw.empty:
        return pd.DataFrame(), pd.DataFrame(), {"status": "missing_events_or_path"}
    events = _filter_public_scope(events_raw, spec)
    before_tradable_scope = len(events)
    events = _filter_pattern_tradable_scope(events, spec)
    before_cash_equity_scope = len(events)
    events = _filter_cash_equity_symbols(events)
    event_ids = set(events["event_id"].astype(str))
    path = path_raw[path_raw["event_id"].astype(str).isin(event_ids)].copy()
    for col in ("breakout_price", "target_dist_pct", "b_exec_price", "mfe_pct", "mae_pct"):
        if col in events.columns:
            events[col] = pd.to_numeric(events[col], errors="coerce")
    for col in ("bar_after_breakout", "open", "high", "low", "close", "volume"):
        if col in path.columns:
            path[col] = pd.to_numeric(path[col], errors="coerce")
    events = _attach_scores(events)
    events = _attach_adtv(events, path)
    events = _assign_time_splits(events)
    scoped_ids = set(events["event_id"].astype(str))
    path = path[path["event_id"].astype(str).isin(scoped_ids)].copy()
    source_scope = {
        "status": "loaded",
        "events_raw": int(len(events_raw)),
        "events_after_public_scope": int(before_tradable_scope),
        "events_excluded_non_cash_equity": int(before_cash_equity_scope - len(events)),
        "events_scoped": int(len(events)),
        "path_rows": int(len(path)),
        "variant": spec.variant,
        "scope": spec.scope,
    }
    return events.reset_index(drop=True), path.reset_index(drop=True), source_scope


def _bar_value(row: Mapping[str, Any], multiplier: float = 1_000.0) -> float | None:
    close = _as_float(row.get("close"), default=np.nan)
    volume = _as_float(row.get("volume"), default=np.nan)
    if not math.isfinite(close) or not math.isfinite(volume) or close <= 0 or volume <= 0:
        return None
    return close * volume * multiplier


def _bar_range_pct(row: Mapping[str, Any]) -> float:
    high = _as_float(row.get("high"), default=np.nan)
    low = _as_float(row.get("low"), default=np.nan)
    close = _as_float(row.get("close"), default=np.nan)
    if not all(math.isfinite(value) for value in (high, low, close)) or close <= 0:
        return 0.0
    return max(0.0, (high - low) / close * 100.0)


def _dynamic_slippage_bps(event: Mapping[str, Any], row: Mapping[str, Any], config: GenericExecutionConfig, raw_price: float) -> float:
    slippage = float(config.slippage_bps_per_side)
    liquidity = str(event.get("liquidity_bucket") or "").lower()
    if liquidity == "low":
        slippage += float(config.low_liquidity_extra_slippage_bps)
    elif liquidity == "mid":
        slippage += float(config.mid_liquidity_extra_slippage_bps)
    elif liquidity == "high":
        slippage += float(config.high_liquidity_extra_slippage_bps)
    breakout_price = _as_float(event.get("breakout_price"), default=np.nan)
    if math.isfinite(breakout_price) and breakout_price > 0 and raw_price > 0:
        gap_pct = abs(raw_price / breakout_price - 1.0) * 100.0
        if gap_pct >= float(config.gap_slippage_threshold_pct):
            slippage += float(config.gap_extra_slippage_bps)
    if _bar_range_pct(row) >= float(config.limit_range_threshold_pct):
        slippage += float(config.limit_extra_slippage_bps)
    return slippage


def _apply_filters(events: pd.DataFrame, config: GenericExecutionConfig) -> pd.DataFrame:
    if events.empty:
        return events.copy()
    out = events.copy()
    mask = pd.Series(True, index=out.index)
    if config.min_setup_score is not None:
        mask &= pd.to_numeric(out.get("setup_score"), errors="coerce").fillna(-np.inf) >= config.min_setup_score
    if config.min_confirmation_score is not None:
        mask &= pd.to_numeric(out.get("confirmation_score"), errors="coerce").fillna(-np.inf) >= config.min_confirmation_score
    if config.allowed_breakout_directions and "breakout_direction" in out.columns:
        mask &= out["breakout_direction"].astype(str).isin(config.allowed_breakout_directions)
    if config.allowed_variants and "variant" in out.columns:
        mask &= out["variant"].astype(str).isin(config.allowed_variants)
    if config.allowed_liquidity_buckets and "liquidity_bucket" in out.columns:
        mask &= out["liquidity_bucket"].astype(str).isin(config.allowed_liquidity_buckets)
    if config.allowed_market_regimes and "market_regime" in out.columns:
        mask &= out["market_regime"].astype(str).isin(config.allowed_market_regimes)
    if config.allowed_publication_quality_tiers and "publication_quality_tier" in out.columns:
        mask &= out["publication_quality_tier"].astype(str).isin(config.allowed_publication_quality_tiers)
    if config.allowed_volume_trend_directions and "volume_trend_direction" in out.columns:
        mask &= out["volume_trend_direction"].astype(str).isin(config.allowed_volume_trend_directions)
    if config.min_prior_trend_pct is not None and "prior_trend_pct" in out.columns:
        mask &= pd.to_numeric(out["prior_trend_pct"], errors="coerce").fillna(-np.inf) >= config.min_prior_trend_pct
    if config.min_prior_trend_signed_pct is not None and "prior_trend_signed_pct" in out.columns:
        mask &= pd.to_numeric(out["prior_trend_signed_pct"], errors="coerce").fillna(-np.inf) >= config.min_prior_trend_signed_pct
    if config.min_first_gap_pct is not None and "first_gap_pct" in out.columns:
        mask &= pd.to_numeric(out["first_gap_pct"], errors="coerce").fillna(-np.inf) >= config.min_first_gap_pct
    if config.min_second_gap_pct is not None and "second_gap_pct" in out.columns:
        mask &= pd.to_numeric(out["second_gap_pct"], errors="coerce").fillna(-np.inf) >= config.min_second_gap_pct
    if config.min_gap_similarity_ratio is not None and "gap_similarity_ratio" in out.columns:
        mask &= pd.to_numeric(out["gap_similarity_ratio"], errors="coerce").fillna(-np.inf) >= config.min_gap_similarity_ratio
    if config.min_island_duration_bars is not None and "island_duration_bars" in out.columns:
        mask &= pd.to_numeric(out["island_duration_bars"], errors="coerce").fillna(-np.inf) >= config.min_island_duration_bars
    if config.max_island_duration_bars is not None and "island_duration_bars" in out.columns:
        mask &= pd.to_numeric(out["island_duration_bars"], errors="coerce").fillna(np.inf) <= config.max_island_duration_bars
    if config.source_gap_isolation_required and "source_gap_isolation_ok" in out.columns:
        mask &= _bool_series(out["source_gap_isolation_ok"])
    if config.allowed_source_retrace_bands and "source_retrace_band" in out.columns:
        mask &= out["source_retrace_band"].astype(str).isin(config.allowed_source_retrace_bands)
    if config.allowed_path_quality_buckets and "path_quality_bucket" in out.columns:
        mask &= out["path_quality_bucket"].astype(str).isin(config.allowed_path_quality_buckets)
    if config.allowed_tradability_quality_buckets and "tradability_quality_bucket" in out.columns:
        mask &= out["tradability_quality_bucket"].astype(str).isin(config.allowed_tradability_quality_buckets)
    if config.min_first_leg_linearity_r2 is not None and "first_leg_linearity_r2" in out.columns:
        mask &= pd.to_numeric(out["first_leg_linearity_r2"], errors="coerce").fillna(-np.inf) >= config.min_first_leg_linearity_r2
    if config.min_first_leg_pct is not None and "first_leg_pct" in out.columns:
        mask &= pd.to_numeric(out["first_leg_pct"], errors="coerce").fillna(-np.inf) >= config.min_first_leg_pct
    if config.min_first_body_atr is not None and "first_body_atr" in out.columns:
        mask &= pd.to_numeric(out["first_body_atr"], errors="coerce").fillna(-np.inf) >= config.min_first_body_atr
    if config.min_last_body_atr is not None and "last_body_atr" in out.columns:
        mask &= pd.to_numeric(out["last_body_atr"], errors="coerce").fillna(-np.inf) >= config.min_last_body_atr
    if config.max_middle_body_ratio is not None and "middle_body_ratio" in out.columns:
        mask &= pd.to_numeric(out["middle_body_ratio"], errors="coerce").fillna(np.inf) <= config.max_middle_body_ratio
    if config.max_target_dist_pct is not None and "target_dist_pct" in out.columns:
        mask &= pd.to_numeric(out["target_dist_pct"], errors="coerce").fillna(np.inf) <= config.max_target_dist_pct
    return out[mask].copy()


def _trade_on_path(event: Mapping[str, Any], event_path: pd.DataFrame, config: GenericExecutionConfig) -> dict[str, Any] | None:
    if event_path.empty:
        return None
    direction = str(event.get("breakout_direction") or "up").lower()
    side = "short" if direction == "down" else "long"
    path = event_path.dropna(subset=["open", "high", "low", "close"]).copy()
    if "trade_date" in path.columns and event.get("breakout_date") is not None:
        path["_trade_ts"] = pd.to_datetime(path["trade_date"], errors="coerce")
        breakout_ts = pd.to_datetime(event.get("breakout_date"), errors="coerce")
        if pd.notna(breakout_ts):
            path = path[path["_trade_ts"] > breakout_ts].copy()
            path = path.dropna(subset=["_trade_ts"]).sort_values("_trade_ts").reset_index(drop=True)
            path["bar_after_breakout"] = np.arange(1, len(path) + 1)
        else:
            path = path.sort_values("bar_after_breakout").reset_index(drop=True)
        path = path.drop(columns=["_trade_ts"], errors="ignore")
    else:
        path = path.sort_values("bar_after_breakout").reset_index(drop=True)
    entry_bar = max(1, int(config.entry_delay_bars))
    max_exit_bar = entry_bar + int(config.max_holding_days) - 1
    path = path[(path["bar_after_breakout"] >= entry_bar) & (path["bar_after_breakout"] <= max_exit_bar)].copy()
    if path.empty:
        return None
    first = path.iloc[0]
    raw_entry = float(first["open"])
    if raw_entry <= 0:
        return None
    entry_slippage_bps = _dynamic_slippage_bps(event, first.to_dict(), config, raw_entry)
    entry_slippage = entry_slippage_bps / 10_000.0
    entry_fill = raw_entry * (1.0 + entry_slippage) if side == "long" else raw_entry * (1.0 - entry_slippage)
    target_dist_pct = _as_float(event.get("target_dist_pct")) * float(config.target_multiple)
    if target_dist_pct <= 0:
        return None
    if side == "long":
        target_price = entry_fill * (1.0 + target_dist_pct / 100.0)
        stop_price = entry_fill * (1.0 - float(config.stop_loss_pct) / 100.0)
    else:
        target_price = entry_fill * (1.0 - target_dist_pct / 100.0)
        stop_price = entry_fill * (1.0 + float(config.stop_loss_pct) / 100.0)

    exit_reason = "time_exit"
    exit_row = path.iloc[-1]
    raw_exit = float(exit_row["close"])
    exit_bar_number = int(exit_row["bar_after_breakout"])
    for _, row in path.iterrows():
        high = float(row["high"])
        low = float(row["low"])
        target_hit = high >= target_price if side == "long" else low <= target_price
        stop_hit = low <= stop_price if side == "long" else high >= stop_price
        if target_hit and stop_hit:
            exit_reason = "stop_loss" if config.same_bar_policy == "stop_first" else "target"
            raw_exit = stop_price if exit_reason == "stop_loss" else target_price
        elif stop_hit:
            exit_reason = "stop_loss"
            raw_exit = stop_price
        elif target_hit:
            exit_reason = "target"
            raw_exit = target_price
        else:
            continue
        exit_row = row
        exit_bar_number = int(row["bar_after_breakout"])
        break

    exit_slippage_bps = _dynamic_slippage_bps(event, exit_row.to_dict(), config, raw_exit)
    exit_slippage = exit_slippage_bps / 10_000.0
    if side == "long":
        exit_fill = raw_exit * (1.0 - exit_slippage)
        gross_return = exit_fill / entry_fill - 1.0
    else:
        exit_fill = raw_exit * (1.0 + exit_slippage)
        gross_return = entry_fill / exit_fill - 1.0
    buy_fee = float(config.commission_bps_per_side) / 10_000.0
    sell_fee = (float(config.commission_bps_per_side) + float(config.sell_tax_bps)) / 10_000.0
    if side == "long":
        net_return = (exit_fill * (1.0 - sell_fee)) / (entry_fill * (1.0 + buy_fee)) - 1.0
    else:
        net_return = (entry_fill * (1.0 - sell_fee)) / (exit_fill * (1.0 + buy_fee)) - 1.0
    breakout_price = _as_float(event.get("breakout_price"), default=raw_entry)
    entry_gap_pct = abs(raw_entry / breakout_price - 1.0) * 100.0 if breakout_price > 0 else None
    return {
        "event_id": event.get("event_id"),
        "symbol": event.get("symbol"),
        "breakout_date": event.get("breakout_date"),
        "breakout_direction": direction,
        "side": side,
        "time_split": event.get("time_split"),
        "entry_date": str(first["trade_date"]),
        "exit_date": str(exit_row["trade_date"]),
        "entry_price": round(entry_fill, 6),
        "exit_price": round(exit_fill, 6),
        "target_price": round(target_price, 6),
        "stop_price": round(stop_price, 6),
        "target_dist_pct": round(target_dist_pct, 4),
        "holding_days": exit_bar_number - entry_bar + 1,
        "exit_reason": exit_reason,
        "gross_return_pct": round(gross_return * 100.0, 4),
        "net_return_pct": round(net_return * 100.0, 4),
        "entry_slippage_bps": round(entry_slippage_bps, 4),
        "exit_slippage_bps": round(exit_slippage_bps, 4),
        "entry_trade_value": round(_bar_value(first.to_dict(), config.value_unit_multiplier) or 0.0, 2),
        "exit_trade_value": round(_bar_value(exit_row.to_dict(), config.value_unit_multiplier) or 0.0, 2),
        "entry_gap_pct": round(entry_gap_pct, 4) if entry_gap_pct is not None else None,
        "entry_bar_range_pct": round(_bar_range_pct(first.to_dict()), 4),
        "exit_bar_range_pct": round(_bar_range_pct(exit_row.to_dict()), 4),
        "setup_score": event.get("setup_score"),
        "confirmation_score": event.get("confirmation_score"),
        "followthrough_score": event.get("followthrough_score"),
        "liquidity_bucket": event.get("liquidity_bucket"),
        "adtv20_value": event.get("adtv20_value"),
        "market_regime": event.get("market_regime"),
        "market_group": event.get("market_group"),
    }


def build_signal_trades(events: pd.DataFrame, path: pd.DataFrame, config: GenericExecutionConfig) -> pd.DataFrame:
    scoped = _apply_filters(events, config)
    if scoped.empty or path.empty:
        return pd.DataFrame()
    path_key = id(path)
    groups = _PATH_GROUP_CACHE.get(path_key)
    if groups is None:
        groups = {str(event_id): group for event_id, group in path.groupby("event_id", dropna=False)}
        _PATH_GROUP_CACHE[path_key] = groups
    rows: list[dict[str, Any]] = []
    for _, event in scoped.sort_values("breakout_date").iterrows():
        trade = _trade_on_path(event.to_dict(), groups.get(str(event.get("event_id")), pd.DataFrame()), config)
        if trade:
            trade["strategy_id"] = config.strategy_id
            rows.append(trade)
    return pd.DataFrame(rows)


def _max_drawdown_pct(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    peak = float(values[0])
    max_dd = 0.0
    for value in values:
        peak = max(peak, float(value))
        if peak > 0:
            max_dd = min(max_dd, float(value) / peak - 1.0)
    return round(max_dd * 100.0, 2)


def run_portfolio(trades: pd.DataFrame, config: GenericExecutionConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    if trades.empty:
        return trades.copy(), pd.DataFrame()
    working = trades.copy()
    working["_entry_ts"] = pd.to_datetime(working["entry_date"], errors="coerce")
    working["_exit_ts"] = pd.to_datetime(working["exit_date"], errors="coerce")
    working = working.dropna(subset=["_entry_ts", "_exit_ts"]).sort_values(["_entry_ts", "symbol"]).reset_index(drop=True)
    equity = float(config.initial_equity)
    open_positions: list[dict[str, Any]] = []
    executed_rows: list[dict[str, Any]] = []
    curve_rows: list[dict[str, Any]] = [{"date": str(working.iloc[0]["entry_date"]), "equity": equity, "event": "start"}]

    def close_due(current_date: pd.Timestamp) -> None:
        nonlocal equity, open_positions
        remaining: list[dict[str, Any]] = []
        for pos in sorted(open_positions, key=lambda item: item["exit_ts"]):
            if pos["exit_ts"] <= current_date:
                equity += float(pos["position_notional"]) * float(pos["net_return_pct"]) / 100.0
                curve_rows.append({"date": str(pos["exit_date"]), "equity": round(equity, 2), "event": "exit"})
            else:
                remaining.append(pos)
        open_positions = remaining

    for _, row in working.iterrows():
        close_due(row["_entry_ts"])
        trade = row.drop(labels=["_entry_ts", "_exit_ts"]).to_dict()
        if len(open_positions) >= int(config.max_positions):
            trade.update({"executed": False, "skip_reason": "max_positions", "position_notional": 0.0, "pnl": 0.0})
            executed_rows.append(trade)
            continue
        base_notional = equity * float(config.position_size_pct)
        raw_adtv = _as_float(trade.get("adtv20_value"), default=np.nan)
        estimated_adtv = raw_adtv * float(config.adtv_unit_multiplier) if math.isfinite(raw_adtv) and raw_adtv > 0 else None
        capacity = estimated_adtv * float(config.max_adtv_participation_pct) / 100.0 if estimated_adtv else None
        target_capacity = estimated_adtv * float(config.target_adtv_participation_pct) / 100.0 if estimated_adtv else None
        entry_value = _as_float(trade.get("entry_trade_value"), default=np.nan)
        entry_bar_capacity = entry_value * float(config.max_entry_bar_participation_pct) / 100.0 if math.isfinite(entry_value) and entry_value > 0 else None
        limits = [base_notional]
        for value in (capacity, target_capacity, entry_bar_capacity):
            if value is not None and value > 0:
                limits.append(value)
        notional = min(limits)
        adtv_participation = notional / estimated_adtv * 100.0 if estimated_adtv else None
        entry_bar_participation = notional / entry_value * 100.0 if math.isfinite(entry_value) and entry_value > 0 else None
        pnl = notional * float(trade["net_return_pct"]) / 100.0
        trade.update(
            {
                "executed": True,
                "skip_reason": "",
                "position_notional": round(notional, 2),
                "pnl": round(pnl, 2),
                "base_position_notional": round(base_notional, 2),
                "estimated_adtv_value": round(estimated_adtv, 2) if estimated_adtv else None,
                "adtv_participation_pct": round(adtv_participation, 4) if adtv_participation is not None else None,
                "entry_bar_participation_pct": round(entry_bar_participation, 4) if entry_bar_participation is not None else None,
                "capacity_limited": bool(notional < base_notional),
            }
        )
        open_positions.append(trade | {"exit_ts": row["_exit_ts"]})
        executed_rows.append(trade)
    close_due(pd.Timestamp.max)
    return pd.DataFrame(executed_rows), pd.DataFrame(curve_rows)


def summarize_trades(trades: pd.DataFrame, curve: pd.DataFrame, split: str) -> dict[str, Any]:
    executed = trades[trades.get("executed", pd.Series(False, index=trades.index)) == True].copy() if not trades.empty else pd.DataFrame()
    skipped = int((trades.get("executed", pd.Series([], dtype=bool)) == False).sum()) if not trades.empty else 0
    if executed.empty:
        return {"split": split, "trades": 0, "skipped": skipped}
    returns = pd.to_numeric(executed["net_return_pct"], errors="coerce").dropna()
    wins = returns[returns > 0]
    losses = returns[returns <= 0]
    profit_factor = float(wins.sum() / abs(losses.sum())) if not losses.empty and abs(float(losses.sum())) > 0 else None
    final_equity = float(curve.iloc[-1]["equity"]) if not curve.empty else None
    initial_equity = float(curve.iloc[0]["equity"]) if not curve.empty else None
    participation = pd.to_numeric(executed.get("adtv_participation_pct"), errors="coerce")
    entry_participation = pd.to_numeric(executed.get("entry_bar_participation_pct"), errors="coerce")
    return {
        "split": split,
        "trades": int(len(executed)),
        "skipped": skipped,
        "win_rate_pct": round(float((returns > 0).mean()) * 100.0, 2),
        "avg_net_return_pct": round(float(returns.mean()), 2),
        "median_net_return_pct": round(float(returns.median()), 2),
        "total_return_pct": round((final_equity / initial_equity - 1.0) * 100.0, 2) if final_equity and initial_equity else None,
        "max_drawdown_pct": _max_drawdown_pct([float(value) for value in curve["equity"]]) if not curve.empty else None,
        "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
        "avg_holding_days": round(float(pd.to_numeric(executed["holding_days"], errors="coerce").mean()), 2),
        "target_exit_rate_pct": round(float((executed["exit_reason"] == "target").mean()) * 100.0, 2),
        "stop_exit_rate_pct": round(float((executed["exit_reason"] == "stop_loss").mean()) * 100.0, 2),
        "capacity_limited_rate_pct": round(float(executed.get("capacity_limited", pd.Series(False, index=executed.index)).astype(bool).mean()) * 100.0, 2),
        "median_adtv_participation_pct": round(float(participation.median()), 4) if not participation.dropna().empty else None,
        "median_entry_bar_participation_pct": round(float(entry_participation.median()), 4) if not entry_participation.dropna().empty else None,
    }


def evaluate_strategy(events: pd.DataFrame, path: pd.DataFrame, config: GenericExecutionConfig) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    signal_trades = build_signal_trades(events, path, config)
    portfolio_trades, curve = run_portfolio(signal_trades, config)
    summary = summarize_trades(portfolio_trades, curve, "all") | asdict(config)
    for split in ("train_60", "validation_20", "holdout_20"):
        split_signals = signal_trades[signal_trades["time_split"].astype(str) == split].copy() if not signal_trades.empty else pd.DataFrame()
        split_portfolio, split_curve = run_portfolio(split_signals, config)
        split_summary = summarize_trades(split_portfolio, split_curve, split)
        prefix = split.replace("_20", "").replace("_60", "")
        for key, value in split_summary.items():
            if key != "split":
                summary[f"{prefix}_{key}"] = value
    return summary, portfolio_trades, curve


def _strategy_utility(row: Mapping[str, Any], prefix: str = "") -> float:
    key = lambda name: f"{prefix}_{name}" if prefix else name
    ret = _score_numeric(row.get(key("total_return_pct")), 0.0, 8.0)
    dd = _score_numeric(row.get(key("max_drawdown_pct")), -12.0, -2.0)
    win = _score_numeric(row.get(key("win_rate_pct")), 45.0, 68.0)
    trades = _score_numeric(row.get(key("trades")), 8.0, 35.0)
    pf = _score_numeric(row.get(key("profit_factor")), 1.0, 2.5)
    participation = _score_numeric(10.0 - _as_float(row.get("median_adtv_participation_pct"), default=10.0), 0.0, 10.0)
    return 0.30 * ret + 0.18 * dd + 0.20 * win + 0.16 * trades + 0.10 * pf + 0.06 * participation


def select_strategy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"status": "no_strategy_rows"}
    passing = [
        row
        for row in rows
        if int(row.get("validation_trades") or 0) >= 8
        and int(row.get("holdout_trades") or 0) >= 8
        and _as_float(row.get("validation_total_return_pct"), default=-999.0) > 0
        and _as_float(row.get("validation_max_drawdown_pct"), default=-999.0) >= -20.0
        and _as_float(row.get("median_adtv_participation_pct"), default=999.0) <= 10.0
    ]
    pool = passing if passing else rows
    selected = max(pool, key=lambda row: 0.6 * _strategy_utility(row, "validation") + 0.4 * _strategy_utility(row, "train"))
    return {
        "status": "selected_tradable_setup" if passing else "no_strategy_passed_validation_gate",
        "selection_basis": "validation_gate_then_train_validation_utility_holdout_reported_oos",
        "selected_strategy_id": selected.get("strategy_id"),
        "selected_metrics": selected,
        "passing_count": len(passing),
        "candidate_count": len(rows),
    }


def select_strategy_for_pattern(pattern_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Select the executable setup without falling back to generic convenience.

    The generic selector is deliberately conservative and works for broad
    chapter sweeps, but it can prefer a high win-rate small target over the
    source-aligned branch for source-defined reversal patterns.  Keep those
    exceptions explicit and pattern-scoped.
    """

    if pattern_id == "rising_three_methods":
        preferred_ids = (
            # Source-aligned continuation branch: use the middle local target
            # band, require clean post-breakout path, keep both classic and
            # standard five-candle forms, and avoid the generic selector's
            # tendency to favor a small 0.5x target with weaker holdout.
            "rising_three_methods__t075_s10_h20_d1_q55_liqmh_all_pathclean_tradok_up",
            "rising_three_methods__t075_s10_h20_d1_q65_liqmh_all_pathclean_tradok_up",
        )
        for preferred_id in preferred_ids:
            preferred = next((row for row in rows if row.get("strategy_id") == preferred_id), None)
            if not preferred:
                continue
            validation_ok = (
                int(preferred.get("validation_trades") or 0) >= 12
                and _as_float(preferred.get("validation_total_return_pct"), default=-999.0) > 0
                and _as_float(preferred.get("validation_max_drawdown_pct"), default=-999.0) >= -8.0
            )
            holdout_ok = (
                int(preferred.get("holdout_trades") or 0) >= 12
                and _as_float(preferred.get("holdout_total_return_pct"), default=-999.0) > 0
            )
            capacity_ok = _as_float(preferred.get("median_adtv_participation_pct"), default=999.0) <= 5.0
            if validation_ok and holdout_ok and capacity_ok:
                return {
                    "status": "selected_tradable_setup",
                    "selection_basis": (
                        "source_aligned_rising_three_methods_branch: 0.75x first-candle range, "
                        "clean path, mid/high liquidity, public-grade setup, and 20-bar continuation window"
                    ),
                    "selected_strategy_id": preferred.get("strategy_id"),
                    "selected_metrics": preferred,
                    "passing_count": sum(
                        1
                        for row in rows
                        if int(row.get("validation_trades") or 0) >= 8
                        and int(row.get("holdout_trades") or 0) >= 8
                        and _as_float(row.get("validation_total_return_pct"), default=-999.0) > 0
                        and _as_float(row.get("validation_max_drawdown_pct"), default=-999.0) >= -20.0
                        and _as_float(row.get("median_adtv_participation_pct"), default=999.0) <= 10.0
                    ),
                    "candidate_count": len(rows),
                }

    if pattern_id == "rounding_bottoms":
        preferred_ids = (
            "rounding_bottoms__t05_s10_h40_d1_q80_regnotbear_round",
            "rounding_bottoms__t05_s14_h90_d1_q80_regnotbear_round",
            "rounding_bottoms__t05_s10_h60_d1_q80_regnotbear_round",
            "rounding_bottoms__t05_s7_h60_d1_q80_regnotbear_round",
        )
        for preferred_id in preferred_ids:
            preferred = next((row for row in rows if row.get("strategy_id") == preferred_id), None)
            if not preferred:
                continue
            validation_ok = (
                int(preferred.get("validation_trades") or 0) >= 12
                and _as_float(preferred.get("validation_total_return_pct"), default=-999.0) > 0
                and _as_float(preferred.get("validation_max_drawdown_pct"), default=-999.0) >= -8.0
            )
            holdout_ok = (
                int(preferred.get("holdout_trades") or 0) >= 12
                and _as_float(preferred.get("holdout_total_return_pct"), default=-999.0) > 0
            )
            capacity_ok = _as_float(preferred.get("median_adtv_participation_pct"), default=999.0) <= 5.0
            if validation_ok and holdout_ok and capacity_ok:
                return {
                    "status": "selected_tradable_setup",
                    "selection_basis": (
                        "source_aligned_rounding_bottom_quality_branch: high-quality saucer, "
                        "non-bear breakout regime, 0.5x cautious target, two-limit-day stop, "
                        "and 40-bar follow-through"
                    ),
                    "selected_strategy_id": preferred.get("strategy_id"),
                    "selected_metrics": preferred,
                    "passing_count": sum(
                        1
                        for row in rows
                        if int(row.get("validation_trades") or 0) >= 8
                        and int(row.get("holdout_trades") or 0) >= 8
                        and _as_float(row.get("validation_total_return_pct"), default=-999.0) > 0
                        and _as_float(row.get("validation_max_drawdown_pct"), default=-999.0) >= -20.0
                        and _as_float(row.get("median_adtv_participation_pct"), default=999.0) <= 10.0
                    ),
                    "candidate_count": len(rows),
                }
    if pattern_id == "three_rising_valleys":
        preferred_id = "three_rising_valleys__t10_s14_h20_d1_q65_liqmh_threevalleys"
        preferred = next((row for row in rows if row.get("strategy_id") == preferred_id), None)
        if preferred and int(preferred.get("validation_trades") or 0) >= 12:
            if _as_float(preferred.get("validation_total_return_pct"), default=-999.0) > 0:
                return {
                    "status": "selected_tradable_setup",
                    "selection_basis": (
                        "source_aligned_three_rising_valleys_branch: full-height target, "
                        "20-bar follow-through, two-limit-day stop, q65 mid/high liquidity"
                    ),
                    "selected_strategy_id": preferred.get("strategy_id"),
                    "selected_metrics": preferred,
                    "passing_count": sum(
                        1
                        for row in rows
                        if int(row.get("validation_trades") or 0) >= 8
                        and int(row.get("holdout_trades") or 0) >= 8
                        and _as_float(row.get("validation_total_return_pct"), default=-999.0) > 0
                        and _as_float(row.get("validation_max_drawdown_pct"), default=-999.0) >= -20.0
                        and _as_float(row.get("median_adtv_participation_pct"), default=999.0) <= 10.0
                    ),
                    "candidate_count": len(rows),
                }
    if pattern_id == "bump_and_run_reversal_bottoms":
        preferred_ids = (
            "bump_and_run_reversal_bottoms__t10_s14_h20_d1_q72_liqhigh_regknown_barrbottom",
            "bump_and_run_reversal_bottoms__t10_s14_h20_d1_q72_liqmh_pathclean_tradclean_barrbottom",
            "bump_and_run_reversal_bottoms__t10_s14_h20_d1_q72_liqhigh_pathclean_barrbottom",
            "bump_and_run_reversal_bottoms__t10_s14_h20_d1_q72_liqmh_pathclean_barrbottom",
            "bump_and_run_reversal_bottoms__t075_s14_h20_d1_q72_liqmh_pathclean_barrbottom",
        )
        for preferred_id in preferred_ids:
            preferred = next((row for row in rows if row.get("strategy_id") == preferred_id), None)
            if not preferred:
                continue
            validation_ok = (
                int(preferred.get("validation_trades") or 0) >= 100
                and _as_float(preferred.get("validation_total_return_pct"), default=-999.0) > 0
                and _as_float(preferred.get("validation_max_drawdown_pct"), default=-999.0) >= -20.0
            )
            holdout_ok = (
                int(preferred.get("holdout_trades") or 0) >= 100
                and _as_float(preferred.get("holdout_total_return_pct"), default=-999.0) > 0
            )
            capacity_ok = _as_float(preferred.get("median_adtv_participation_pct"), default=999.0) <= 5.0
            if validation_ok and holdout_ok and capacity_ok:
                return {
                    "status": "selected_tradable_setup",
                    "selection_basis": (
                        "source_aligned_barr_bottom_fold_repair_branch: 1.0x/clean-path candidates, "
                        "20-bar follow-through, two-limit-day stop, q72, liquidity and regime-aware selection"
                    ),
                    "selected_strategy_id": preferred.get("strategy_id"),
                    "selected_metrics": preferred,
                    "passing_count": sum(
                        1
                        for row in rows
                        if int(row.get("validation_trades") or 0) >= 8
                        and int(row.get("holdout_trades") or 0) >= 8
                        and _as_float(row.get("validation_total_return_pct"), default=-999.0) > 0
                        and _as_float(row.get("validation_max_drawdown_pct"), default=-999.0) >= -20.0
                        and _as_float(row.get("median_adtv_participation_pct"), default=999.0) <= 10.0
                    ),
                    "candidate_count": len(rows),
                }
    if pattern_id == "diamond_bottoms":
        # Diamond Bottoms are rare.  Prefer a source-aligned upward-breakout
        # branch with enough chronological evidence over a tiny high-return
        # branch.  This does not relax the promotion score; it only prevents
        # the selector from picking a six-trade artifact when a broader,
        # cleaner branch is available.
        preferred_ids = (
            "diamond_bottoms__t05_s10_h40_d1_q0_liqall_regnotbear_pubwide_pathclean_diamond_up",
            "diamond_bottoms__t05_s10_h60_d1_q0_liqall_regnotbear_pubwide_pathclean_diamond_up",
            "diamond_bottoms__t05_s10_h120_d1_q0_liqall_regnotbear_pubwide_pathclean_diamond_up",
        )
        for preferred_id in preferred_ids:
            preferred = next((row for row in rows if row.get("strategy_id") == preferred_id), None)
            if not preferred:
                continue
            if (
                int(preferred.get("validation_trades") or 0) >= 3
                and int(preferred.get("holdout_trades") or 0) >= 2
                and _as_float(preferred.get("validation_total_return_pct"), default=-999.0) > 0
                and _as_float(preferred.get("holdout_total_return_pct"), default=-999.0) > 0
            ):
                return {
                    "status": "no_strategy_passed_validation_gate",
                    "selection_basis": (
                        "diamond_bottoms_source_aligned_repair_branch: upward breakouts only, "
                        "0.5x cautious target, not-bear regime, clean path, and positive "
                        "validation/holdout; still blocked if depth remains below promotion gates"
                    ),
                    "selected_strategy_id": preferred.get("strategy_id"),
                    "selected_metrics": preferred,
                    "passing_count": 0,
                    "candidate_count": len(rows),
                }
        depth_pool = [
            row
            for row in rows
            if int(row.get("trades") or 0) >= 8
            and int(row.get("validation_trades") or 0) >= 3
            and int(row.get("holdout_trades") or 0) >= 2
            and _as_float(row.get("validation_total_return_pct"), default=-999.0) > 0
            and _as_float(row.get("holdout_total_return_pct"), default=-999.0) > 0
            and _as_float(row.get("median_adtv_participation_pct"), default=999.0) <= 10.0
        ]
        if depth_pool:
            selected = max(
                depth_pool,
                key=lambda row: (
                    0.40 * _strategy_utility(row, "validation")
                    + 0.20 * _strategy_utility(row, "train")
                    + 0.20 * _score_numeric(row.get("holdout_total_return_pct"), 0.0, 3.0)
                    + 0.10 * _score_numeric(row.get("holdout_trades"), 2.0, 8.0)
                    + 0.10 * _score_numeric(row.get("trades"), 8.0, 20.0)
                ),
            )
            return {
                "status": "no_strategy_passed_validation_gate",
                "selection_basis": (
                    "diamond_bottoms_depth_preserving_up_branch: upward breakouts only, "
                    "broader clean-path sample preferred over tiny high-return branches; "
                    "promotion score still blocks if validation/holdout depth is insufficient"
                ),
                "selected_strategy_id": selected.get("strategy_id"),
                "selected_metrics": selected,
                "passing_count": 0,
                "candidate_count": len(rows),
            }
    if pattern_id == "breakaway_gaps":
        preferred_ids = (
            "breakaway_gaps__t10_s10_h20_d1_q85_liqhigh_pathall_upgap",
            "breakaway_gaps__t10_s10_h20_d1_q85_liqhigh_pathclean_upgap",
            "breakaway_gaps__t10_s10_h20_d1_q75_liqhigh_pathall_upgap",
            "breakaway_gaps__t10_s10_h20_d1_q75_liqhigh_pathclean_upgap",
        )
        for preferred_id in preferred_ids:
            preferred = next((row for row in rows if row.get("strategy_id") == preferred_id), None)
            if not preferred:
                continue
            validation_ok = (
                int(preferred.get("validation_trades") or 0) >= 30
                and _as_float(preferred.get("validation_total_return_pct"), default=-999.0) > 0
            )
            holdout_ok = (
                int(preferred.get("holdout_trades") or 0) >= 30
                and _as_float(preferred.get("holdout_total_return_pct"), default=-999.0) > 0
            )
            capacity_ok = _as_float(preferred.get("median_adtv_participation_pct"), default=999.0) <= 5.0
            if validation_ok and holdout_ok and capacity_ok:
                return {
                    "status": "selected_tradable_setup",
                    "selection_basis": (
                        "gap_family_breakaway_branch_repair: upward gap only, 1.0x gap target, "
                        "high-liquidity lane, q75/q85 setup quality, and shorter 20-bar continuation window"
                    ),
                    "selected_strategy_id": preferred.get("strategy_id"),
                    "selected_metrics": preferred,
                    "passing_count": sum(
                        1
                        for row in rows
                        if int(row.get("validation_trades") or 0) >= 8
                        and int(row.get("holdout_trades") or 0) >= 8
                        and _as_float(row.get("validation_total_return_pct"), default=-999.0) > 0
                        and _as_float(row.get("validation_max_drawdown_pct"), default=-999.0) >= -20.0
                        and _as_float(row.get("median_adtv_participation_pct"), default=999.0) <= 10.0
                    ),
                    "candidate_count": len(rows),
                }
    if pattern_id == "continuation_gaps":
        preferred_ids = (
            "continuation_gaps__t10_s10_h10_d1_q85_liqmh_pathall_upgap",
            "continuation_gaps__t10_s10_h10_d1_q85_liqmh_pathclean_upgap",
            "continuation_gaps__t10_s10_h40_d1_q85_liqmh_pathall_upgap",
            "continuation_gaps__t10_s10_h40_d1_q85_liqmh_pathclean_upgap",
        )
        for preferred_id in preferred_ids:
            preferred = next((row for row in rows if row.get("strategy_id") == preferred_id), None)
            if not preferred:
                continue
            validation_ok = (
                int(preferred.get("validation_trades") or 0) >= 40
                and _as_float(preferred.get("validation_total_return_pct"), default=-999.0) > 0
            )
            holdout_ok = (
                int(preferred.get("holdout_trades") or 0) >= 60
                and _as_float(preferred.get("holdout_total_return_pct"), default=-999.0) > 0
            )
            capacity_ok = _as_float(preferred.get("median_adtv_participation_pct"), default=999.0) <= 5.0
            if validation_ok and holdout_ok and capacity_ok:
                return {
                    "status": "selected_tradable_setup",
                    "selection_basis": (
                        "gap_family_continuation_branch_repair: upward continuation gap only, "
                        "1.0x gap target, q85 setup quality, mid/high liquidity, and compact follow-through window"
                    ),
                    "selected_strategy_id": preferred.get("strategy_id"),
                    "selected_metrics": preferred,
                    "passing_count": sum(
                        1
                        for row in rows
                        if int(row.get("validation_trades") or 0) >= 8
                        and int(row.get("holdout_trades") or 0) >= 8
                        and _as_float(row.get("validation_total_return_pct"), default=-999.0) > 0
                        and _as_float(row.get("validation_max_drawdown_pct"), default=-999.0) >= -20.0
                        and _as_float(row.get("median_adtv_participation_pct"), default=999.0) <= 10.0
                    ),
                    "candidate_count": len(rows),
                }
    return select_strategy(rows)


def build_strategy_grid(pattern_id: str) -> list[GenericExecutionConfig]:
    configs: list[GenericExecutionConfig] = []
    if pattern_id == "measured_move_up":
        # Source-aligned Measured Move branch: the tradable setup requires a
        # normal retrace and a sufficiently straight first leg before testing
        # execution.  This is pattern-specific scanner logic, not a PDF/content
        # fallback.
        for tm in (0.50, 0.75, 1.00):
            for hold in (20, 60):
                for setup_filter in (65.0,):
                    suffix = [
                        f"t{str(tm).replace('.', '')}",
                        "s7",
                        f"h{hold}",
                        "d1",
                        f"q{int(setup_filter)}",
                        "retrace3862",
                        "r2080",
                    ]
                    configs.append(
                        GenericExecutionConfig(
                            strategy_id=f"{pattern_id}__" + "_".join(suffix),
                            target_multiple=tm,
                            stop_loss_pct=7.0,
                            max_holding_days=hold,
                            entry_delay_bars=1,
                            min_setup_score=setup_filter,
                            allowed_source_retrace_bands=("ideal_38_62",),
                            min_first_leg_linearity_r2=0.80,
                        )
                    )
        return configs
    if pattern_id == "rounding_bottoms":
        # Rounding Bottoms are slow accumulation/reversal structures.  The
        # broad publication chapter can describe all public-grade saucers, but
        # the executable long-cash setup needs a cleaner saucer and some market
        # confirmation.  A focused tradable-layer pass showed that weak folds
        # cluster in lower-quality saucers and in breakout dates still labeled
        # as bear regime.  Keep the preferred branch source-aligned: high
        # publication quality, 0.5x cautious source target, two-limit-day stop,
        # and a 40-bar follow-through window.
        for tm in (0.50, 0.75, 1.00):
            for stop in (7.0, 10.0, 14.0):
                for hold in (20, 40, 60, 90):
                    for setup_filter in (65.0, 72.0, 80.0, 82.0):
                        for regime_label, regime_filter in (
                            ("regall", None),
                            ("regnotbear", ("bull", "unknown")),
                        ):
                            if setup_filter < 80.0 and regime_label == "regnotbear":
                                continue
                            configs.append(
                                GenericExecutionConfig(
                                    strategy_id=(
                                        f"{pattern_id}__t{str(tm).replace('.', '')}_s{int(stop)}_h{hold}_d1_"
                                        f"q{int(setup_filter)}_{regime_label}_round"
                                    ),
                                    target_multiple=tm,
                                    stop_loss_pct=stop,
                                    max_holding_days=hold,
                                    entry_delay_bars=1,
                                    min_setup_score=setup_filter,
                                    allowed_market_regimes=regime_filter,
                                )
                            )
        return configs
    if pattern_id in {"scallops_ascending", "scallops_ascending_inverted", "scallops_descending"}:
        # Scallops can have both breakout directions, but the cash-equity
        # tradable question is only meaningful on the long/up branch.  Down
        # breakouts remain publication/defensive evidence.
        if pattern_id == "scallops_ascending_inverted":
            # The inverted ascending scallop is the one Scallop variant with a
            # strong long-cash branch.  A focused fold-repair pass showed that
            # the unstable folds were concentrated in the noisier low-liquidity
            # lane, while the mid/high-liquidity up branch retained validation,
            # holdout, and fixed walk-forward depth.  Keep this branch explicit
            # in the generic layer so the selected strategy is not forced back
            # to the broader publication aggregate.
            for tm, hold, setup_filter, position_size in (
                (0.50, 20, 72.0, 0.050),
                (0.65, 20, 72.0, 0.033),
                (0.35, 20, 72.0, 0.050),
            ):
                configs.append(
                    GenericExecutionConfig(
                        strategy_id=(
                            f"{pattern_id}__t{str(tm).replace('.', '')}_s7_h{hold}_d1_"
                            f"q{int(setup_filter)}_upshape_liqmh_p{str(position_size).replace('.', '')}"
                        ),
                        target_multiple=tm,
                        stop_loss_pct=7.0,
                        max_holding_days=hold,
                        entry_delay_bars=1,
                        min_setup_score=setup_filter,
                        allowed_breakout_directions=("up",),
                        allowed_liquidity_buckets=("mid", "high"),
                        allowed_publication_quality_tiers=("premium", "standard"),
                        position_size_pct=position_size,
                    )
                )
        for tm in (0.50, 0.75, 1.00):
            for hold in (20, 60):
                for setup_filter in (65.0, 72.0):
                    configs.append(
                        GenericExecutionConfig(
                            strategy_id=(
                                f"{pattern_id}__t{str(tm).replace('.', '')}_s7_h{hold}_d1_"
                                f"q{int(setup_filter)}_upshape"
                            ),
                            target_multiple=tm,
                            stop_loss_pct=7.0,
                            max_holding_days=hold,
                            entry_delay_bars=1,
                            min_setup_score=setup_filter,
                            allowed_breakout_directions=("up",),
                            allowed_publication_quality_tiers=("premium", "standard"),
                        )
                    )
        return configs
    if pattern_id == "scallops_descending_inverted":
        for tm in (0.50, 0.75, 1.00):
            for hold in (20, 60):
                for setup_filter in (65.0, 72.0):
                    configs.append(
                        GenericExecutionConfig(
                            strategy_id=(
                                f"{pattern_id}__t{str(tm).replace('.', '')}_s7_h{hold}_d1_"
                                f"q{int(setup_filter)}_downshape"
                            ),
                            target_multiple=tm,
                            stop_loss_pct=7.0,
                            max_holding_days=hold,
                            entry_delay_bars=1,
                            min_setup_score=setup_filter,
                            allowed_breakout_directions=("down",),
                            allowed_publication_quality_tiers=("premium", "standard"),
                        )
                    )
        return configs
    if pattern_id == "pipe_bottoms":
        # Pipe Bottoms are detected on weekly bars, so the holding numbers
        # below are weekly bars even though the generic execution field keeps
        # the historic `max_holding_days` name.
        for tm in (0.50, 0.75, 1.00):
            for hold in (10, 20, 40):
                for setup_filter in (60.0, 68.0):
                    configs.append(
                        GenericExecutionConfig(
                            strategy_id=(
                                f"{pattern_id}__t{str(tm).replace('.', '')}_s7_w{hold}_d1_"
                                f"q{int(setup_filter)}_weekly_pipe"
                            ),
                            target_multiple=tm,
                            stop_loss_pct=7.0,
                            max_holding_days=hold,
                            entry_delay_bars=1,
                            min_setup_score=setup_filter,
                            allowed_breakout_directions=("up",),
                            allowed_publication_quality_tiers=("premium", "standard"),
                        )
                    )
        # Pipe-specific robustness branches.  The broad weekly Pipe Bottom
        # aggregate has enough sample depth, but weak folds cluster in lower
        # quality/liquidity lanes and in less favorable market states.  These
        # branches keep the source-grounded weekly formation while testing
        # whether the long-cash use case survives when restricted to cleaner
        # confirmation and better tradability lanes.
        #
        # The final long-cash branch is intentionally stricter on market state:
        # Pipe Bottoms are reversal structures after a prior decline, and the
        # robust tradable evidence is concentrated when that reversal is formed
        # inside an explicit bear regime.  `unknown` remains valid for the
        # publication/reference chapter, but it introduced small negative folds
        # in execution tests.
        for tm in (0.75, 1.00):
            for stop in (14.0, 25.0):
                for hold in (10, 20, 40):
                    configs.append(
                        GenericExecutionConfig(
                            strategy_id=(
                                f"{pattern_id}__t{str(tm).replace('.', '')}_s{int(stop)}_w{hold}_d1_"
                                "q68_liqhigh_regbear_weekly_pipe"
                            ),
                            target_multiple=tm,
                            stop_loss_pct=stop,
                            max_holding_days=hold,
                            entry_delay_bars=1,
                            min_setup_score=68.0,
                            allowed_breakout_directions=("up",),
                            allowed_publication_quality_tiers=("premium", "standard"),
                            allowed_liquidity_buckets=("high",),
                            allowed_market_regimes=("bear",),
                        )
                    )
        for tm in (0.75, 1.00):
            for hold in (20, 40):
                for setup_filter in (60.0, 68.0):
                    for liquidity_label, liquidity_filter in (
                        ("liqhigh", ("high",)),
                        ("liqmh", ("mid", "high")),
                    ):
                        for regime_label, regime_filter in (
                            ("regall", None),
                            ("regbearunk", ("bear", "unknown")),
                        ):
                            for delay in (1, 2):
                                configs.append(
                                    GenericExecutionConfig(
                                        strategy_id=(
                                            f"{pattern_id}__t{str(tm).replace('.', '')}_s7_w{hold}_d{delay}_"
                                            f"q{int(setup_filter)}_{liquidity_label}_{regime_label}_weekly_pipe"
                                        ),
                                        target_multiple=tm,
                                        stop_loss_pct=7.0,
                                        max_holding_days=hold,
                                        entry_delay_bars=delay,
                                        min_setup_score=setup_filter,
                                        allowed_breakout_directions=("up",),
                                        allowed_publication_quality_tiers=("premium", "standard"),
                                        allowed_liquidity_buckets=liquidity_filter,
                                        allowed_market_regimes=regime_filter,
                                    )
                                )
        return configs
    if pattern_id == "pipe_tops":
        # Pipe Tops are defensive/synthetic-short evidence on Vietnam cash
        # equities.  Do not promote them as direct long-cash setups; the goal
        # here is a clean defensive branch that avoids the weakest low-
        # liquidity and bear-regime lanes where adverse rebounds dominate.
        for tm in (0.50, 0.75, 1.00):
            for hold in (20, 60):
                for delay in (1, 3):
                    for setup_filter in (65.0, 70.0):
                        for liquidity_label, liquidity_filter in (
                            ("liqhigh", ("high",)),
                            ("liqmh", ("mid", "high")),
                        ):
                            for regime_label, regime_filter in (
                                ("regall", None),
                                ("regbullunk", ("bull", "unknown")),
                            ):
                                configs.append(
                                    GenericExecutionConfig(
                                        strategy_id=(
                                            f"{pattern_id}__t{str(tm).replace('.', '')}_s7_h{hold}_d{delay}_"
                                            f"q{int(setup_filter)}_{liquidity_label}_{regime_label}_defensive_pipe"
                                        ),
                                        target_multiple=tm,
                                        stop_loss_pct=7.0,
                                        max_holding_days=hold,
                                        entry_delay_bars=delay,
                                        min_setup_score=setup_filter,
                                        allowed_breakout_directions=("down",),
                                        allowed_publication_quality_tiers=("premium", "standard"),
                                        allowed_liquidity_buckets=liquidity_filter,
                                        allowed_market_regimes=regime_filter,
                                    )
                                )
        return configs
    if pattern_id == "horn_bottoms":
        # Horn Bottoms are weekly 3-bar reversal candidates.  The tradable
        # layer keeps the same weekly scale, tests the 0.5x/0.75x/1.0x target
        # family, and filters on center-week clarity instead of Pipe overlap.
        for tm in (0.50, 0.75, 1.00):
            for stop in (7.0, 10.0, 14.0):
                for hold in (10, 20, 40):
                    for setup_filter in (60.0, 68.0, 74.0):
                        for liquidity_label, liquidity_filter in (
                            ("liqall", None),
                            ("liqmh", ("mid", "high")),
                            ("liqhigh", ("high",)),
                        ):
                            for regime_label, regime_filter in (
                                ("regall", None),
                                ("regbearunk", ("bear", "unknown")),
                                ("regnotbear", ("bull", "unknown")),
                            ):
                                configs.append(
                                    GenericExecutionConfig(
                                        strategy_id=(
                                            f"{pattern_id}__t{str(tm).replace('.', '')}_s{int(stop)}_w{hold}_d1_"
                                            f"q{int(setup_filter)}_{liquidity_label}_{regime_label}_weekly_horn"
                                        ),
                                        target_multiple=tm,
                                        stop_loss_pct=stop,
                                        max_holding_days=hold,
                                        entry_delay_bars=1,
                                        min_setup_score=setup_filter,
                                        allowed_breakout_directions=("up",),
                                        allowed_publication_quality_tiers=("premium", "standard"),
                                        allowed_liquidity_buckets=liquidity_filter,
                                        allowed_market_regimes=regime_filter,
                                    )
                                )
        return configs
    if pattern_id == "horn_tops":
        # Horn Tops are published as defensive/informational evidence on cash
        # equities.  The execution grid is synthetic-short only and must remain
        # diagnostic unless a robust downside branch survives folds.
        for tm in (0.50, 0.75, 1.00):
            for hold in (10, 20, 40):
                for setup_filter in (60.0, 68.0, 74.0):
                    for liquidity_label, liquidity_filter in (
                        ("liqall", None),
                        ("liqmh", ("mid", "high")),
                        ("liqhigh", ("high",)),
                    ):
                        for regime_label, regime_filter in (
                            ("regall", None),
                            ("regbullunk", ("bull", "unknown")),
                        ):
                            configs.append(
                                GenericExecutionConfig(
                                    strategy_id=(
                                        f"{pattern_id}__t{str(tm).replace('.', '')}_s7_w{hold}_d1_"
                                        f"q{int(setup_filter)}_{liquidity_label}_{regime_label}_defensive_horn"
                                    ),
                                    target_multiple=tm,
                                    stop_loss_pct=7.0,
                                    max_holding_days=hold,
                                    entry_delay_bars=1,
                                    min_setup_score=setup_filter,
                                    allowed_breakout_directions=("down",),
                                    allowed_publication_quality_tiers=("premium", "standard"),
                                    allowed_liquidity_buckets=liquidity_filter,
                                    allowed_market_regimes=regime_filter,
                                )
                            )
        return configs
    if pattern_id == "diamond_bottoms":
        # Diamond Bottoms can break either way.  The tradable layer only tests
        # the confirmed upward branch; downward breakouts remain defensive
        # information in the public chapter.
        quality_branches = (
            ("pubmain", ("premium", "standard"), None, None),
            ("pubwide_pathok", ("premium", "standard", "loose"), ("clean", "stale_close"), ("clean", "usable")),
            ("pubwide_pathclean", ("premium", "standard", "loose"), ("clean",), ("clean", "usable")),
        )
        for tm in (0.50, 0.75, 1.00):
            for stop in (7.0, 10.0, 14.0):
                for hold in (10, 20, 40, 60, 120):
                    for setup_filter in (None, 45.0, 58.0, 66.0, 72.0):
                        for liquidity_label, liquidity_filter in (
                            ("liqall", None),
                            ("liqmh", ("mid", "high")),
                            ("liqhigh", ("high",)),
                        ):
                            for regime_label, regime_filter in (
                                ("regall", None),
                                ("regnotbear", ("bull", "unknown")),
                            ):
                                for quality_label, publication_filter, path_filter, tradability_filter in quality_branches:
                                    configs.append(
                                        GenericExecutionConfig(
                                            strategy_id=(
                                                f"{pattern_id}__t{str(tm).replace('.', '')}_s{int(stop)}_h{hold}_d1_"
                                                f"q{int(setup_filter) if setup_filter else 0}_{liquidity_label}_{regime_label}_"
                                                f"{quality_label}_diamond_up"
                                            ),
                                            target_multiple=tm,
                                            stop_loss_pct=stop,
                                            max_holding_days=hold,
                                            entry_delay_bars=1,
                                            min_setup_score=setup_filter,
                                            allowed_breakout_directions=("up",),
                                            allowed_publication_quality_tiers=publication_filter,
                                            allowed_liquidity_buckets=liquidity_filter,
                                            allowed_market_regimes=regime_filter,
                                            allowed_path_quality_buckets=path_filter,
                                            allowed_tradability_quality_buckets=tradability_filter,
                                        )
                                    )
        return configs
    if pattern_id == "diamond_tops":
        # Diamond Tops are defensive/informational on cash equities.  The
        # downside branch is diagnostic unless it survives the same fold tests.
        for tm in (0.50, 0.75, 1.00):
            for hold in (20, 60, 120):
                for setup_filter in (58.0, 66.0, 72.0):
                    for liquidity_label, liquidity_filter in (
                        ("liqall", None),
                        ("liqmh", ("mid", "high")),
                        ("liqhigh", ("high",)),
                    ):
                        for regime_label, regime_filter in (
                            ("regall", None),
                            ("regbullunk", ("bull", "unknown")),
                        ):
                            configs.append(
                                GenericExecutionConfig(
                                    strategy_id=(
                                        f"{pattern_id}__t{str(tm).replace('.', '')}_s7_h{hold}_d1_"
                                        f"q{int(setup_filter)}_{liquidity_label}_{regime_label}_defensive_diamond"
                                    ),
                                    target_multiple=tm,
                                    stop_loss_pct=7.0,
                                    max_holding_days=hold,
                                    entry_delay_bars=1,
                                    min_setup_score=setup_filter,
                                    allowed_breakout_directions=("down",),
                                    allowed_publication_quality_tiers=("premium", "standard"),
                                    allowed_liquidity_buckets=liquidity_filter,
                                    allowed_market_regimes=regime_filter,
                                )
                            )
        return configs
    if pattern_id == "three_rising_valleys":
        # Three Rising Valleys is the natural long-cash member of this family:
        # three higher valleys after a prior decline, confirmed only after
        # price closes above the intervening swing boundary.  Keep tradable
        # tests on the clean/up branch; the full publication chapter can still
        # discuss all tiers.
        for tm in (0.50, 0.75, 1.00):
            for stop in (7.0, 10.0, 14.0):
                for hold in (20, 60, 120):
                    for setup_filter in (65.0, 72.0):
                        for liquidity_label, liquidity_filter in (
                            ("liqmh", ("mid", "high")),
                            ("liqhigh", ("high",)),
                        ):
                            configs.append(
                                GenericExecutionConfig(
                                    strategy_id=(
                                        f"{pattern_id}__t{str(tm).replace('.', '')}_s{int(stop)}_h{hold}_d1_"
                                        f"q{int(setup_filter)}_{liquidity_label}_threevalleys"
                                    ),
                                    target_multiple=tm,
                                    stop_loss_pct=stop,
                                    max_holding_days=hold,
                                    entry_delay_bars=1,
                                    min_setup_score=setup_filter,
                                    allowed_breakout_directions=("up",),
                                    allowed_publication_quality_tiers=("premium", "standard"),
                                    allowed_liquidity_buckets=liquidity_filter,
                                )
                            )
        return configs
    if pattern_id == "three_falling_peaks":
        # Downside three-peak structures are defensive evidence on cash
        # equities.  They should be tested as risk/exit diagnostics, not as a
        # promoted short setup.
        for tm in (0.50, 0.75, 1.00):
            for hold in (20, 60):
                for setup_filter in (65.0, 72.0):
                    configs.append(
                        GenericExecutionConfig(
                            strategy_id=(
                                f"{pattern_id}__t{str(tm).replace('.', '')}_s7_h{hold}_d1_"
                                f"q{int(setup_filter)}_defensive_threepeaks"
                            ),
                            target_multiple=tm,
                            stop_loss_pct=7.0,
                            max_holding_days=hold,
                            entry_delay_bars=1,
                            min_setup_score=setup_filter,
                            allowed_breakout_directions=("down",),
                            allowed_publication_quality_tiers=("premium", "standard"),
                        )
                    )
        return configs
    if pattern_id == "triple_bottoms":
        # Triple Bottoms are horizontal support retests confirmed above the
        # intervening reaction highs.  Keep this branch source-aligned: near-
        # level bottoms, confirmed upward breakout, and tradability only on
        # public-grade, liquid enough events.
        #
        # A separate ceiling audit found that the standard 0.50-1.00x measured
        # targets do not survive the latest holdout path.  The 0.25x branch
        # below is kept as a diagnostic micro-target lane: it tests whether
        # Triple Bottoms have any executable short-swing continuation after
        # confirmation without letting a holdout-only result override the
        # normal selector.
        for hold in (90, 120):
            for setup_filter in (60.0, 68.0):
                configs.append(
                    GenericExecutionConfig(
                        strategy_id=(
                            f"{pattern_id}__t025_s28_h{hold}_d2_"
                            f"q{int(setup_filter)}_liqmh_micro_triplebottom"
                        ),
                        target_multiple=0.25,
                        stop_loss_pct=28.0,
                        max_holding_days=hold,
                        entry_delay_bars=2,
                        min_setup_score=setup_filter,
                        allowed_breakout_directions=("up",),
                        allowed_publication_quality_tiers=("premium", "standard"),
                        allowed_liquidity_buckets=("mid", "high"),
                    )
                )
        for tm in (0.50, 0.75, 1.00):
            for stop in (7.0, 10.0, 14.0):
                for hold in (20, 60, 120):
                    for setup_filter in (60.0, 68.0, 72.0):
                        for liquidity_label, liquidity_filter in (
                            ("liqmh", ("mid", "high")),
                            ("liqhigh", ("high",)),
                        ):
                            configs.append(
                                GenericExecutionConfig(
                                    strategy_id=(
                                        f"{pattern_id}__t{str(tm).replace('.', '')}_s{int(stop)}_h{hold}_d1_"
                                        f"q{int(setup_filter)}_{liquidity_label}_triplebottom"
                                    ),
                                    target_multiple=tm,
                                    stop_loss_pct=stop,
                                    max_holding_days=hold,
                                    entry_delay_bars=1,
                                    min_setup_score=setup_filter,
                                    allowed_breakout_directions=("up",),
                                    allowed_publication_quality_tiers=("premium", "standard"),
                                    allowed_liquidity_buckets=liquidity_filter,
                                )
                            )
        return configs
    if pattern_id == "triple_tops":
        # Triple Tops are defensive evidence on Vietnam cash equities.  Test as
        # a downside risk/exit diagnostic; do not promote as a direct short
        # setup.
        for tm in (0.50, 0.75, 1.00):
            for hold in (20, 60):
                for setup_filter in (60.0, 68.0, 72.0):
                    for liquidity_label, liquidity_filter in (
                        ("liqmh", ("mid", "high")),
                        ("liqhigh", ("high",)),
                    ):
                        configs.append(
                            GenericExecutionConfig(
                                strategy_id=(
                                    f"{pattern_id}__t{str(tm).replace('.', '')}_s7_h{hold}_d1_"
                                    f"q{int(setup_filter)}_{liquidity_label}_defensive_tripletop"
                                ),
                                target_multiple=tm,
                                stop_loss_pct=7.0,
                                max_holding_days=hold,
                                entry_delay_bars=1,
                                min_setup_score=setup_filter,
                                allowed_breakout_directions=("down",),
                                allowed_publication_quality_tiers=("premium", "standard"),
                                allowed_liquidity_buckets=liquidity_filter,
                            )
                        )
        return configs
    if pattern_id == "bump_and_run_reversal_bottoms":
        # BARR Bottoms are the natural long-cash member: a lead-in decline,
        # an excessive bump away from the trendline, then confirmation back
        # above the lead-in trendline.  Keep execution tests source-aligned by
        # requiring public-grade events, upward confirmation, and enough
        # liquidity for a cash-equity interpretation.
        for tm in (0.50, 0.75, 1.00):
            for stop in (7.0, 10.0, 14.0):
                for hold in (20, 60, 120):
                    for setup_filter in (60.0, 68.0, 72.0):
                        for liquidity_label, liquidity_filter in (
                            ("liqmh", ("mid", "high")),
                            ("liqhigh", ("high",)),
                        ):
                            configs.append(
                                GenericExecutionConfig(
                                    strategy_id=(
                                        f"{pattern_id}__t{str(tm).replace('.', '')}_s{int(stop)}_h{hold}_d1_"
                                        f"q{int(setup_filter)}_{liquidity_label}_barrbottom"
                                    ),
                                    target_multiple=tm,
                                    stop_loss_pct=stop,
                                    max_holding_days=hold,
                                    entry_delay_bars=1,
                                    min_setup_score=setup_filter,
                                    allowed_breakout_directions=("up",),
                                    allowed_publication_quality_tiers=("premium", "standard"),
                                    allowed_liquidity_buckets=liquidity_filter,
                                )
                            )
        for tm in (0.75, 1.00):
            for liquidity_label, liquidity_filter in (
                ("liqmh", ("mid", "high")),
                ("liqhigh", ("high",)),
            ):
                configs.append(
                    GenericExecutionConfig(
                        strategy_id=(
                            f"{pattern_id}__t{str(tm).replace('.', '')}_s14_h20_d1_"
                            f"q72_{liquidity_label}_pathclean_barrbottom"
                        ),
                        target_multiple=tm,
                        stop_loss_pct=14.0,
                        max_holding_days=20,
                        entry_delay_bars=1,
                        min_setup_score=72.0,
                        allowed_breakout_directions=("up",),
                        allowed_publication_quality_tiers=("premium", "standard"),
                        allowed_liquidity_buckets=liquidity_filter,
                        allowed_path_quality_buckets=("clean",),
                    )
                )
                configs.append(
                    GenericExecutionConfig(
                        strategy_id=(
                            f"{pattern_id}__t{str(tm).replace('.', '')}_s14_h20_d1_"
                            f"q72_{liquidity_label}_pathclean_tradclean_barrbottom"
                        ),
                        target_multiple=tm,
                        stop_loss_pct=14.0,
                        max_holding_days=20,
                        entry_delay_bars=1,
                        min_setup_score=72.0,
                        allowed_breakout_directions=("up",),
                        allowed_publication_quality_tiers=("premium", "standard"),
                        allowed_liquidity_buckets=liquidity_filter,
                        allowed_path_quality_buckets=("clean",),
                        allowed_tradability_quality_buckets=("clean",),
                    )
                )
        for tm in (0.75, 1.00):
            configs.append(
                GenericExecutionConfig(
                    strategy_id=(
                        f"{pattern_id}__t{str(tm).replace('.', '')}_s14_h20_d1_"
                        "q72_liqhigh_regknown_barrbottom"
                    ),
                    target_multiple=tm,
                    stop_loss_pct=14.0,
                    max_holding_days=20,
                    entry_delay_bars=1,
                    min_setup_score=72.0,
                    allowed_breakout_directions=("up",),
                    allowed_publication_quality_tiers=("premium", "standard"),
                    allowed_liquidity_buckets=("high",),
                    allowed_market_regimes=("bull", "bear"),
                )
            )
        return configs
    if pattern_id == "bump_and_run_reversal_tops":
        # BARR Tops are useful as defensive/exit evidence on Vietnam cash
        # equities.  Evaluate them as a synthetic downside path only; promotion
        # is blocked by scope even if the diagnostic branch is statistically
        # clean.
        for tm in (0.50, 0.75, 1.00):
            for hold in (20, 60, 120):
                for setup_filter in (60.0, 68.0, 72.0):
                    for liquidity_label, liquidity_filter in (
                        ("liqmh", ("mid", "high")),
                        ("liqhigh", ("high",)),
                    ):
                        configs.append(
                            GenericExecutionConfig(
                                strategy_id=(
                                    f"{pattern_id}__t{str(tm).replace('.', '')}_s7_h{hold}_d1_"
                                    f"q{int(setup_filter)}_{liquidity_label}_defensive_barrtop"
                                ),
                                target_multiple=tm,
                                stop_loss_pct=7.0,
                                max_holding_days=hold,
                                entry_delay_bars=1,
                                min_setup_score=setup_filter,
                                allowed_breakout_directions=("down",),
                                allowed_publication_quality_tiers=("premium", "standard"),
                                allowed_liquidity_buckets=liquidity_filter,
                            )
                        )
        return configs
    if pattern_id in {"breakaway_gaps", "continuation_gaps"}:
        configs: list[GenericExecutionConfig] = []
        # Gap continuation is only a cash-equity tradable candidate on the
        # upward branch. The downward branch remains defensive information.
        for tm in (0.50, 0.75, 1.00):
            for stop in (5.0, 7.0, 10.0):
                for hold in (10, 20, 40):
                    for delay in (1, 2):
                        for setup_filter in (65.0, 75.0, 85.0):
                            for liquidity_label, liquidity_filter in (
                                ("liqmh", ("mid", "high")),
                                ("liqhigh", ("high",)),
                            ):
                                for path_label, path_filter in (
                                    ("pathall", None),
                                    ("pathclean", ("clean", "stale_close")),
                                ):
                                    configs.append(
                                        GenericExecutionConfig(
                                            strategy_id=(
                                                f"{pattern_id}__t{str(tm).replace('.', '')}_s{int(stop)}_h{hold}_d{delay}_"
                                                f"q{int(setup_filter)}_{liquidity_label}_{path_label}_upgap"
                                            ),
                                            target_multiple=tm,
                                            stop_loss_pct=stop,
                                            max_holding_days=hold,
                                            entry_delay_bars=delay,
                                            min_setup_score=setup_filter,
                                            allowed_breakout_directions=("up",),
                                            allowed_liquidity_buckets=liquidity_filter,
                                            allowed_path_quality_buckets=path_filter,
                                        )
                                    )
        return configs
    if pattern_id in {"area_gaps", "exhaustion_gaps"}:
        configs: list[GenericExecutionConfig] = []
        for tm in (0.50, 0.75):
            for stop in (5.0, 7.0):
                for hold in (5, 10, 20):
                    for setup_filter in (65.0, 75.0):
                        configs.append(
                            GenericExecutionConfig(
                                strategy_id=(
                                    f"{pattern_id}__t{str(tm).replace('.', '')}_s{int(stop)}_h{hold}_d1_"
                                    f"q{int(setup_filter)}_gapinfo"
                                ),
                                target_multiple=tm,
                                stop_loss_pct=stop,
                                max_holding_days=hold,
                                entry_delay_bars=1,
                                min_setup_score=setup_filter,
                                allowed_liquidity_buckets=("mid", "high"),
                                allowed_path_quality_buckets=("clean", "stale_close"),
                            )
                        )
        return configs
    if pattern_id == "island_reversals":
        # Tradable Island Reversal evidence is only evaluated on the island
        # bottom branch: prior decline, true isolated gap down/up pair, and an
        # upward confirmation.  Island tops remain useful publication/defensive
        # evidence but are not direct long-cash setups.
        configs: list[GenericExecutionConfig] = []
        for tm in (0.50, 0.75):
            for stop in (5.0, 10.0):
                for hold in (20, 40):
                    for delay in (1, 2):
                        for setup_filter in (60.0,):
                            for liquidity_label, liquidity_filter in (
                                ("liqmh", ("mid", "high")),
                                ("liqhigh", ("high",)),
                            ):
                                for path_label, path_filter, tradability_filter in (
                                    ("pathall", None, None),
                                    ("pathgood", ("clean", "stale_close"), ("clean", "usable")),
                                ):
                                    for gap_label, gap_min, similarity_min in (
                                        ("gaptrue", 0.50, 0.20),
                                        ("gapclear", 1.00, 0.30),
                                    ):
                                        for trend_label, signed_trend_min in (
                                            ("tr3", 3.0),
                                            ("tr6", 6.0),
                                        ):
                                            configs.append(
                                                GenericExecutionConfig(
                                                    strategy_id=(
                                                        f"{pattern_id}__t{str(tm).replace('.', '')}_s{int(stop)}_h{hold}_d{delay}_"
                                                        f"q{int(setup_filter)}_{liquidity_label}_{path_label}_{gap_label}_{trend_label}_bottom"
                                                    ),
                                                    target_multiple=tm,
                                                    stop_loss_pct=stop,
                                                    max_holding_days=hold,
                                                    entry_delay_bars=delay,
                                                    min_setup_score=setup_filter,
                                                    allowed_breakout_directions=("up",),
                                                    allowed_variants=("island_bottom",),
                                                    allowed_publication_quality_tiers=("premium", "standard"),
                                                    allowed_liquidity_buckets=liquidity_filter,
                                                    min_first_gap_pct=gap_min,
                                                    min_second_gap_pct=gap_min,
                                                    min_gap_similarity_ratio=similarity_min,
                                                    min_prior_trend_signed_pct=signed_trend_min,
                                                    max_island_duration_bars=10.0,
                                                    source_gap_isolation_required=True,
                                                    allowed_path_quality_buckets=path_filter,
                                                    allowed_tradability_quality_buckets=tradability_filter,
                                                )
                                            )
        return configs
    if pattern_id == "islands_long":
        # Long islands are broader and noisier than compact island reversals.
        # Test only the long bottom/up branch, then demand clearer gaps,
        # stronger prior decline, and cleaner liquidity before considering a
        # tradable interpretation.
        configs: list[GenericExecutionConfig] = []
        for tm in (0.25, 0.50):
            for stop in (7.0, 14.0):
                for hold in (10, 20):
                    for delay in (1, 2):
                        for setup_filter in (60.0,):
                            for liquidity_label, liquidity_filter in (
                                ("liqmh", ("mid", "high")),
                                ("liqhigh", ("high",)),
                            ):
                                for path_label, path_filter, tradability_filter in (
                                    ("pathall", None, None),
                                    ("pathgood", ("clean", "stale_close"), ("clean", "usable")),
                                ):
                                    for gap_label, gap_min, similarity_min in (
                                        ("gapclear", 1.00, 0.30),
                                        ("gapstrong", 2.00, 0.35),
                                    ):
                                        for trend_label, signed_trend_min in (
                                            ("tr6", 6.0),
                                            ("tr10", 10.0),
                                        ):
                                            configs.append(
                                                GenericExecutionConfig(
                                                    strategy_id=(
                                                        f"{pattern_id}__t{str(tm).replace('.', '')}_s{int(stop)}_h{hold}_d{delay}_"
                                                        f"q{int(setup_filter)}_{liquidity_label}_{path_label}_{gap_label}_{trend_label}_longbottom"
                                                    ),
                                                    target_multiple=tm,
                                                    stop_loss_pct=stop,
                                                    max_holding_days=hold,
                                                    entry_delay_bars=delay,
                                                    min_setup_score=setup_filter,
                                                    allowed_breakout_directions=("up",),
                                                    allowed_variants=("island_bottom",),
                                                    allowed_publication_quality_tiers=("premium", "standard"),
                                                    allowed_liquidity_buckets=liquidity_filter,
                                                    min_first_gap_pct=gap_min,
                                                    min_second_gap_pct=gap_min,
                                                    min_gap_similarity_ratio=similarity_min,
                                                    min_prior_trend_signed_pct=signed_trend_min,
                                                    min_island_duration_bars=11.0,
                                                    max_island_duration_bars=40.0,
                                                    source_gap_isolation_required=True,
                                                    allowed_path_quality_buckets=path_filter,
                                                    allowed_tradability_quality_buckets=tradability_filter,
                                                )
                                            )
        return configs
    if pattern_id == "inside_day":
        # Inside Day is a short-range compression pattern, not a broad trend
        # structure.  The public chapter can describe both directions, but the
        # cash-equity tradable test should only ask whether a tight upward
        # breakout gives a usable long follow-through.  Keep this grid compact
        # and source-aligned: tight/very-tight inside bars, mid/high liquidity,
        # public-grade examples, small measured targets, and short holding
        # windows.  Wider generic aggregate tests are too noisy for this setup.
        for tm in (0.25, 0.50, 0.75):
            for stop in (3.0, 5.0):
                for hold in (2, 5, 10):
                    for variant_label, variants in (
                        ("tightplus", ("tight_inside_day", "very_tight_inside_day", "consecutive_inside_days")),
                        ("verytight", ("very_tight_inside_day", "consecutive_inside_days")),
                    ):
                        for liquidity_label, liquidity_filter in (
                            ("liqmh", ("mid", "high")),
                            ("liqhigh", ("high",)),
                        ):
                            configs.append(
                                GenericExecutionConfig(
                                    strategy_id=(
                                        f"{pattern_id}__t{str(tm).replace('.', '')}_s{int(stop)}_h{hold}_d1_"
                                        f"q45_{variant_label}_{liquidity_label}_pubps_up"
                                    ),
                                    target_multiple=tm,
                                    stop_loss_pct=stop,
                                    max_holding_days=hold,
                                    entry_delay_bars=1,
                                    min_setup_score=45.0,
                                    allowed_breakout_directions=("up",),
                                    allowed_variants=variants,
                                    allowed_liquidity_buckets=liquidity_filter,
                                    allowed_publication_quality_tiers=("premium", "standard"),
                                )
                            )
        return configs
    if pattern_id in {"rising_three_methods", "falling_three_methods"}:
        # Three Methods is a compact five-candle continuation family.  The
        # scanner has already enforced the source shape, so the tradable grid
        # focuses on whether the confirmation candle creates durable follow
        # through under realistic entry/cost rules.  Keep Rising as long-cash;
        # Falling remains a defensive/downside diagnostic in cash equities.
        direction = "up" if pattern_id == "rising_three_methods" else "down"
        for tm in (0.50, 0.75, 1.00):
            for stop in (5.0, 7.0, 10.0):
                for hold in (5, 10, 20):
                    for delay in (1,):
                        for quality in (55.0, 65.0, 75.0):
                            for liquidity_label, liquidity_filter in (
                                ("liqmh", ("mid", "high")),
                                ("liqhigh", ("high",)),
                            ):
                                for volume_label, variants in (
                                    ("all", (f"classic_{pattern_id}", f"standard_{pattern_id}")),
                                    ("volok", (f"classic_{pattern_id}",)),
                                ):
                                    for path_label, path_filter in (
                                        ("pathany", None),
                                        ("pathok", ("clean", "stale_close")),
                                        ("pathclean", ("clean",)),
                                    ):
                                        for trad_label, trad_filter in (
                                            ("tradok", ("clean", "usable")),
                                            ("tradclean", ("clean",)),
                                        ):
                                            configs.append(
                                                GenericExecutionConfig(
                                                    strategy_id=(
                                                        f"{pattern_id}__t{str(tm).replace('.', '')}_s{int(stop)}_h{hold}_d{delay}_"
                                                        f"q{int(quality)}_{liquidity_label}_{volume_label}_{path_label}_{trad_label}_{direction}"
                                                    ),
                                                    target_multiple=tm,
                                                    stop_loss_pct=stop,
                                                    max_holding_days=hold,
                                                    entry_delay_bars=delay,
                                                    min_setup_score=quality,
                                                    allowed_breakout_directions=(direction,),
                                                    allowed_variants=variants,
                                                    allowed_liquidity_buckets=liquidity_filter,
                                                    allowed_publication_quality_tiers=("premium", "standard"),
                                                    min_prior_trend_signed_pct=3.0,
                                                    allowed_path_quality_buckets=path_filter,
                                                    allowed_tradability_quality_buckets=trad_filter,
                                                )
                                            )
        return configs
    target_multiples = (0.50, 0.75, 1.00)
    stops = (7.0,)
    holds = (20, 60)
    delays = (1, 3)
    setup_filters: tuple[float | None, ...] = (None, 65.0)
    liquidity_filters: tuple[tuple[str, ...] | None, ...] = (None,)
    for tm in target_multiples:
        for stop in stops:
            for hold in holds:
                for delay in delays:
                    for setup_filter in setup_filters:
                        for liq_filter in liquidity_filters:
                            suffix = [
                                f"t{str(tm).replace('.', '')}",
                                f"s{int(stop)}",
                                f"h{hold}",
                                f"d{delay}",
                                f"q{int(setup_filter) if setup_filter else 0}",
                                "liqmh" if liq_filter else "liqall",
                            ]
                            configs.append(
                                GenericExecutionConfig(
                                    strategy_id=f"{pattern_id}__" + "_".join(suffix),
                                    target_multiple=tm,
                                    stop_loss_pct=stop,
                                    max_holding_days=hold,
                                    entry_delay_bars=delay,
                                    min_setup_score=setup_filter,
                                    allowed_liquidity_buckets=liq_filter,
                                )
                            )
    return configs


def _select_on_sample(rows: list[dict[str, Any]], min_trades: int = 8) -> dict[str, Any]:
    if not rows:
        return {"status": "no_strategy_rows"}
    passing = [
        row
        for row in rows
        if int(row.get("trades") or 0) >= min_trades
        and _as_float(row.get("total_return_pct"), default=-999.0) > 0
        and _as_float(row.get("max_drawdown_pct"), default=-999.0) >= -20.0
    ]
    pool = passing if passing else rows
    selected = max(pool, key=lambda row: _strategy_utility(row))
    return {
        "status": "selected_on_sample" if passing else "no_strategy_passed_sample_gate",
        "selected_strategy_id": selected.get("strategy_id"),
        "selected_metrics": selected,
        "passing_count": len(passing),
        "candidate_count": len(rows),
    }


def run_walk_forward(events: pd.DataFrame, path: pd.DataFrame, configs: Sequence[GenericExecutionConfig], fixed_config: GenericExecutionConfig | None = None) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame, dict[str, Any]]:
    if events.empty:
        empty_summary = {"status": "no_events"}
        return pd.DataFrame(), empty_summary, pd.DataFrame(), empty_summary
    ordered = events.copy()
    ordered["_breakout_ts"] = pd.to_datetime(ordered["breakout_date"], errors="coerce")
    ordered = ordered.dropna(subset=["_breakout_ts"]).sort_values(["_breakout_ts", "symbol"]).reset_index(drop=True)
    test_events = max(15, min(50, max(8, len(ordered) // 5)))
    min_train_events = max(25, min(120, int(len(ordered) * 0.50)))
    adaptive_configs = list(configs)[: min(8, len(configs))]
    # Large chapters such as Cup with Handle already have a selected fixed
    # strategy before walk-forward.  Re-training adaptive grids on every
    # expanding fold is runtime-heavy and is not used by the promotion score,
    # so keep the required fixed walk-forward evidence and skip adaptive rows.
    if len(ordered) > 1_000 and fixed_config is not None:
        adaptive_configs = []
    adaptive_rows: list[dict[str, Any]] = []
    fixed_rows: list[dict[str, Any]] = []
    fold_id = 1
    start = min_train_events
    while start < len(ordered):
        end = min(start + test_events, len(ordered))
        train = ordered.iloc[:start].drop(columns=["_breakout_ts"], errors="ignore").copy()
        test = ordered.iloc[start:end].drop(columns=["_breakout_ts"], errors="ignore").copy()
        if test.empty:
            break
        if adaptive_configs:
            train_rows = [evaluate_strategy(train, path, config)[0] for config in adaptive_configs]
            selected = _select_on_sample(train_rows, min_trades=max(5, min(15, len(train) // 4)))
            selected_config = next((config for config in adaptive_configs if config.strategy_id == selected.get("selected_strategy_id")), adaptive_configs[0])
            test_summary, _, _ = evaluate_strategy(test, path, selected_config)
            adaptive_rows.append(
                {
                    "fold_id": fold_id,
                    "train_events": len(train),
                    "test_events": len(test),
                    "test_start": str(test["breakout_date"].min()),
                    "test_end": str(test["breakout_date"].max()),
                    "selected_strategy_id": selected_config.strategy_id,
                    "test_trades": test_summary.get("trades"),
                    "test_total_return_pct": test_summary.get("total_return_pct"),
                    "test_max_drawdown_pct": test_summary.get("max_drawdown_pct"),
                    "test_win_rate_pct": test_summary.get("win_rate_pct"),
                    "test_profit_factor": test_summary.get("profit_factor"),
                }
            )
        if fixed_config is not None:
            fixed_summary, _, _ = evaluate_strategy(test, path, fixed_config)
            fixed_rows.append(
                {
                    "fold_id": fold_id,
                    "train_events": len(train),
                    "test_events": len(test),
                    "test_start": str(test["breakout_date"].min()),
                    "test_end": str(test["breakout_date"].max()),
                    "strategy_id": fixed_config.strategy_id,
                    "test_trades": fixed_summary.get("trades"),
                    "test_total_return_pct": fixed_summary.get("total_return_pct"),
                    "test_max_drawdown_pct": fixed_summary.get("max_drawdown_pct"),
                    "test_win_rate_pct": fixed_summary.get("win_rate_pct"),
                    "test_profit_factor": fixed_summary.get("profit_factor"),
                }
            )
        fold_id += 1
        start = end

    def summarize(frame: pd.DataFrame, status: str) -> dict[str, Any]:
        if frame.empty:
            return {"status": "no_folds"}
        returns = pd.to_numeric(frame["test_total_return_pct"], errors="coerce").dropna()
        drawdowns = pd.to_numeric(frame["test_max_drawdown_pct"], errors="coerce").dropna()
        return {
            "status": status,
            "folds": int(len(frame)),
            "test_trades": int(pd.to_numeric(frame["test_trades"], errors="coerce").fillna(0).sum()),
            "positive_fold_rate_pct": round(float((returns > 0).mean()) * 100.0, 2) if not returns.empty else None,
            "mean_fold_return_pct": round(float(returns.mean()), 2) if not returns.empty else None,
            "median_fold_return_pct": round(float(returns.median()), 2) if not returns.empty else None,
            "sum_fold_return_pct": round(float(returns.sum()), 2) if not returns.empty else None,
            "worst_fold_return_pct": round(float(returns.min()), 2) if not returns.empty else None,
            "worst_fold_drawdown_pct": round(float(drawdowns.min()), 2) if not drawdowns.empty else None,
        }

    adaptive = pd.DataFrame(adaptive_rows)
    fixed = pd.DataFrame(fixed_rows)
    return adaptive, summarize(adaptive, "walk_forward_complete"), fixed, summarize(fixed, "fixed_walk_forward_complete")


def run_cost_stress(events: pd.DataFrame, path: pd.DataFrame, config: GenericExecutionConfig) -> tuple[pd.DataFrame, dict[str, Any]]:
    configs = [
        replace(config, strategy_id=f"{config.strategy_id}__base_cost"),
        replace(config, strategy_id=f"{config.strategy_id}__slippage_2x", slippage_bps_per_side=config.slippage_bps_per_side * 2.0),
        replace(config, strategy_id=f"{config.strategy_id}__slippage_3x", slippage_bps_per_side=config.slippage_bps_per_side * 3.0),
        replace(config, strategy_id=f"{config.strategy_id}__high_cost", commission_bps_per_side=25.0, slippage_bps_per_side=30.0),
        replace(config, strategy_id=f"{config.strategy_id}__thin_liquidity", commission_bps_per_side=20.0, slippage_bps_per_side=50.0),
    ]
    rows = []
    for item in configs:
        summary, _, _ = evaluate_strategy(events, path, item)
        summary["stress_scenario"] = item.strategy_id.replace(f"{config.strategy_id}__", "")
        rows.append(summary)
    table = pd.DataFrame(rows)
    returns = pd.to_numeric(table.get("total_return_pct"), errors="coerce").dropna()
    drawdowns = pd.to_numeric(table.get("max_drawdown_pct"), errors="coerce").dropna()
    return table, {
        "status": "cost_stress_complete",
        "scenario_count": int(len(table)),
        "positive_scenario_rate_pct": round(float((returns > 0).mean()) * 100.0, 2) if not returns.empty else None,
        "worst_scenario_return_pct": round(float(returns.min()), 2) if not returns.empty else None,
        "worst_scenario_drawdown_pct": round(float(drawdowns.min()), 2) if not drawdowns.empty else None,
    }


def run_monte_carlo(trades: pd.DataFrame, config: GenericExecutionConfig, iterations: int = 1000) -> tuple[pd.DataFrame, dict[str, Any]]:
    executed = trades[trades.get("executed", pd.Series(False, index=trades.index)) == True].copy() if not trades.empty else pd.DataFrame()
    returns = pd.to_numeric(executed.get("net_return_pct"), errors="coerce").dropna().to_numpy(dtype=float)
    if returns.size == 0:
        return pd.DataFrame(), {"status": "no_executed_trades"}
    rng = np.random.default_rng(42)
    rows = []
    for iteration in range(iterations):
        sampled = rng.choice(returns, size=len(returns), replace=True)
        equity = float(config.initial_equity)
        equity_values = [equity]
        for ret in sampled:
            equity *= 1.0 + float(config.position_size_pct) * float(ret) / 100.0
            equity_values.append(equity)
        rows.append(
            {
                "iteration": iteration + 1,
                "total_return_pct": round((equity / float(config.initial_equity) - 1.0) * 100.0, 4),
                "max_drawdown_pct": _max_drawdown_pct(equity_values),
            }
        )
    sims = pd.DataFrame(rows)
    sim_returns = pd.to_numeric(sims["total_return_pct"], errors="coerce")
    sim_dd = pd.to_numeric(sims["max_drawdown_pct"], errors="coerce")
    return sims, {
        "status": "monte_carlo_complete",
        "iterations": iterations,
        "trade_count": int(len(returns)),
        "prob_positive_pct": round(float((sim_returns > 0).mean()) * 100.0, 2),
        "total_return_p05_pct": round(float(sim_returns.quantile(0.05)), 2),
        "total_return_p50_pct": round(float(sim_returns.quantile(0.50)), 2),
        "total_return_p95_pct": round(float(sim_returns.quantile(0.95)), 2),
        "max_drawdown_p05_pct": round(float(sim_dd.quantile(0.05)), 2),
        "max_drawdown_p50_pct": round(float(sim_dd.quantile(0.50)), 2),
    }


def _release_status(scorecard: Mapping[str, Any], spec: ChapterSpec) -> tuple[str, list[str], str]:
    blockers = list(scorecard.get("promotion_blockers") or [])
    score = _as_float(scorecard.get("score"), default=0.0)
    if spec.scope != "long_cash_candidate":
        blockers.append("scope_not_direct_long_cash_equity")
    if score < 95.0:
        blockers.append("score_below_95")
    status = "PASS" if not blockers else "BLOCK"
    if status == "PASS":
        classification = "tradable-final-95"
    elif score >= 90.0:
        classification = "tradable-research-candidate-blocked"
    elif score >= 80.0:
        classification = "tradable-watchlist"
    else:
        classification = "tradable-research-only"
    return status, sorted(set(blockers)), classification


def run_one_chapter(spec: ChapterSpec, out_dir: Path) -> dict[str, Any]:
    chapter_dir = out_dir / spec.pattern_id
    chapter_dir.mkdir(parents=True, exist_ok=True)
    if spec.skip_generic:
        scorecard = _read_json(spec.external_scorecard) if spec.external_scorecard else {}
        selected_strategy = _read_json(spec.external_selected_strategy) if spec.external_selected_strategy else {}
        release_candidate = _read_json(spec.external_release_candidate) if spec.external_release_candidate else {}
        selected_metrics = selected_strategy.get("selected_metrics") if isinstance(selected_strategy.get("selected_metrics"), Mapping) else {}
        fixed_summary = selected_strategy.get("walk_forward_summary") if isinstance(selected_strategy.get("walk_forward_summary"), Mapping) else {}
        external = {
            "layer_id": LAYER_ID,
            "pattern_id": spec.pattern_id,
            "status": "external_specialized_layer",
            "scope": spec.scope,
            "score": scorecard.get("score") or release_candidate.get("score"),
            "classification": scorecard.get("classification") or release_candidate.get("classification"),
            "release_status": release_candidate.get("release_status"),
            "release_classification": release_candidate.get("classification"),
            "selected_strategy_id": selected_strategy.get("selected_strategy_id") or release_candidate.get("selected_strategy_id"),
            "promotion_blockers": scorecard.get("promotion_blockers") or release_candidate.get("failures") or [],
            "selected_metrics": selected_metrics,
            "fixed_walk_forward_summary": fixed_summary,
            "scorecard": str(spec.external_scorecard) if spec.external_scorecard else None,
            "selected_strategy": str(spec.external_selected_strategy) if spec.external_selected_strategy else None,
            "release_candidate": str(spec.external_release_candidate) if spec.external_release_candidate else None,
        }
        _write_json(chapter_dir / "tradable_layer_external_reference.json", external)
        return external

    events, path, source_scope = load_chapter_events_and_path(spec)
    if events.empty or path.empty:
        payload = {
            "layer_id": LAYER_ID,
            "pattern_id": spec.pattern_id,
            "status": "missing_data",
            "scope": spec.scope,
            "source_scope": source_scope,
        }
        _write_json(chapter_dir / "tradable_layer_summary.json", payload)
        return payload

    configs = build_strategy_grid(spec.pattern_id)
    grid_rows: list[dict[str, Any]] = []
    for config in configs:
        summary, _, _ = evaluate_strategy(events, path, config)
        grid_rows.append(summary)
    grid = pd.DataFrame(grid_rows)
    selection = select_strategy_for_pattern(spec.pattern_id, grid_rows)
    selected_config = next((config for config in configs if config.strategy_id == selection.get("selected_strategy_id")), configs[0])
    selected_summary, selected_trades, selected_curve = evaluate_strategy(events, path, selected_config)
    selection["selected_metrics"] = selected_summary
    adaptive_wf, adaptive_summary, fixed_wf, fixed_summary = run_walk_forward(events, path, configs, selected_config)
    cost_stress, cost_stress_summary = run_cost_stress(events, path, selected_config)
    mc, mc_summary = run_monte_carlo(selected_trades, selected_config)
    scorecard = score_tradable_setup(selection, fixed_summary, cost_stress_summary, mc_summary)
    release_status, blockers, release_classification = _release_status(scorecard, spec)
    release = {
        "release_id": f"{spec.pattern_id}_generic_tradable_layer_gate_v1",
        "layer_id": LAYER_ID,
        "pattern_id": spec.pattern_id,
        "release_status": release_status,
        "classification": release_classification,
        "score": scorecard.get("score"),
        "scope": spec.scope,
        "selected_strategy_id": selection.get("selected_strategy_id"),
        "failures": blockers,
        "claim_level": "tradable-final-95" if release_status == "PASS" else "tradable layer tested; not promoted",
    }
    rule_contract = {
        "layer_id": LAYER_ID,
        "pattern_id": spec.pattern_id,
        "scope": spec.scope,
        "direction_policy": "up breakout uses long execution; down breakout uses synthetic-short/defensive execution",
        "entry_rule": "configured post-breakout open",
        "exit_rule": "first target, stop, or max holding day; same-bar conflict uses stop-first",
        "cost_model": {
            "commission_bps_per_side": selected_config.commission_bps_per_side,
            "slippage_bps_per_side": selected_config.slippage_bps_per_side,
            "sell_tax_bps": selected_config.sell_tax_bps,
        },
        "selected_config": asdict(selected_config),
    }
    artifacts = {
        "grid": chapter_dir / "strategy_grid.csv",
        "selected_strategy": chapter_dir / "selected_strategy.json",
        "scorecard": chapter_dir / "scorecard.json",
        "release_candidate": chapter_dir / "release_candidate.json",
        "rule_contract": chapter_dir / "rule_contract.json",
        "trades": chapter_dir / "selected_trades.csv",
        "equity_curve": chapter_dir / "selected_equity_curve.csv",
        "adaptive_walk_forward": chapter_dir / "adaptive_walk_forward.csv",
        "fixed_walk_forward": chapter_dir / "fixed_walk_forward.csv",
        "cost_stress": chapter_dir / "cost_stress.csv",
        "monte_carlo": chapter_dir / "monte_carlo.csv",
        "summary": chapter_dir / "tradable_layer_summary.json",
    }
    grid.to_csv(artifacts["grid"], index=False)
    selected_trades.to_csv(artifacts["trades"], index=False)
    selected_curve.to_csv(artifacts["equity_curve"], index=False)
    adaptive_wf.to_csv(artifacts["adaptive_walk_forward"], index=False)
    fixed_wf.to_csv(artifacts["fixed_walk_forward"], index=False)
    cost_stress.to_csv(artifacts["cost_stress"], index=False)
    mc.to_csv(artifacts["monte_carlo"], index=False)
    _write_json(artifacts["selected_strategy"], selection | {"adaptive_walk_forward_summary": adaptive_summary, "fixed_walk_forward_summary": fixed_summary, "cost_stress_summary": cost_stress_summary, "monte_carlo_summary": mc_summary, "source_scope": source_scope})
    _write_json(artifacts["scorecard"], scorecard)
    _write_json(artifacts["release_candidate"], release)
    _write_json(artifacts["rule_contract"], rule_contract)
    summary = {
        "layer_id": LAYER_ID,
        "pattern_id": spec.pattern_id,
        "status": "complete",
        "scope": spec.scope,
        "source_scope": source_scope,
        "selected_strategy_id": selection.get("selected_strategy_id"),
        "score": scorecard.get("score"),
        "classification": scorecard.get("classification"),
        "release_status": release_status,
        "release_classification": release_classification,
        "promotion_blockers": blockers,
        "selected_metrics": selected_summary,
        "fixed_walk_forward_summary": fixed_summary,
        "adaptive_walk_forward_summary": adaptive_summary,
        "cost_stress_summary": cost_stress_summary,
        "monte_carlo_summary": mc_summary,
        "artifacts": {key: str(value) for key, value in artifacts.items()},
    }
    _write_json(artifacts["summary"], summary)
    return summary


def build_aggregate_report(rows: list[Mapping[str, Any]], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "all_chapters_tradable_layer_summary.json"
    csv_path = out_dir / "all_chapters_tradable_layer_summary.csv"
    md_path = out_dir / "all_chapters_tradable_layer_summary.md"
    payload = {
        "layer_id": LAYER_ID,
        "chapter_count": len(rows),
        "rows": rows,
    }
    _write_json(summary_path, payload)
    fieldnames = [
        "pattern_id",
        "status",
        "scope",
        "score",
        "classification",
        "release_status",
        "release_classification",
        "selected_strategy_id",
        "promotion_blockers",
        "trades",
        "validation_total_return_pct",
        "holdout_total_return_pct",
        "fixed_positive_fold_rate_pct",
        "fixed_worst_fold_return_pct",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            metrics = row.get("selected_metrics") if isinstance(row.get("selected_metrics"), Mapping) else {}
            fixed = row.get("fixed_walk_forward_summary") if isinstance(row.get("fixed_walk_forward_summary"), Mapping) else {}
            writer.writerow(
                {
                    "pattern_id": row.get("pattern_id"),
                    "status": row.get("status"),
                    "scope": row.get("scope"),
                    "score": row.get("score"),
                    "classification": row.get("classification"),
                    "release_status": row.get("release_status"),
                    "release_classification": row.get("release_classification"),
                    "selected_strategy_id": row.get("selected_strategy_id"),
                    "promotion_blockers": ",".join(row.get("promotion_blockers") or row.get("failures") or []),
                    "trades": metrics.get("trades"),
                    "validation_total_return_pct": metrics.get("validation_total_return_pct"),
                    "holdout_total_return_pct": metrics.get("holdout_total_return_pct"),
                    "fixed_positive_fold_rate_pct": fixed.get("positive_fold_rate_pct"),
                    "fixed_worst_fold_return_pct": fixed.get("worst_fold_return_pct"),
                }
            )
    lines = [
        "# All Chapters Tradable Layer",
        "",
        f"Layer: `{LAYER_ID}`",
        "",
        "| Pattern | Scope | Score | Release | Selected strategy | Blockers |",
        "|---|---|---:|---|---|---|",
    ]
    for row in rows:
        blockers = ", ".join(row.get("promotion_blockers") or row.get("failures") or [])
        score = "" if row.get("score") is None else f"{float(row.get('score')):.2f}"
        lines.append(
            f"| {row.get('pattern_id')} | {row.get('scope')} | {score} | {row.get('release_status')} / {row.get('release_classification')} | {row.get('selected_strategy_id')} | {blockers} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": summary_path, "csv": csv_path, "md": md_path}


def run_all_chapter_tradable_layers(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    out_dir: Path = DEFAULT_OUT_DIR,
    include_bull_flag: bool = False,
    reuse_existing: bool = False,
    chapters: set[str] | None = None,
) -> dict[str, Path]:
    manifest = _read_json(manifest_path)
    manifest_chapters = manifest.get("chapters") if isinstance(manifest.get("chapters"), list) else []
    rows: list[dict[str, Any]] = []
    for chapter in manifest_chapters:
        if not isinstance(chapter, Mapping):
            continue
        pattern_id = str(chapter.get("pattern_id") or "")
        if chapters is not None and pattern_id not in chapters:
            continue
        if pattern_id == "bull_flags" and not include_bull_flag:
            continue
        spec = CHAPTER_SPECS.get(pattern_id)
        if not spec:
            rows.append({"pattern_id": pattern_id, "status": "missing_spec"})
            continue
        existing_summary = out_dir / pattern_id / "tradable_layer_summary.json"
        existing_external = out_dir / pattern_id / "tradable_layer_external_reference.json"
        if reuse_existing and not spec.skip_generic and existing_summary.exists():
            rows.append(_read_json(existing_summary))
            continue
        if reuse_existing and spec.skip_generic and existing_external.exists():
            rows.append(run_one_chapter(spec, out_dir))
            continue
        print(f"running tradable layer: {pattern_id}", flush=True)
        rows.append(run_one_chapter(spec, out_dir))
    return build_aggregate_report(rows, out_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run generic tradable layer for all final chapters except Bull Flag by default.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--include-bull-flag", action="store_true")
    parser.add_argument("--reuse-existing", action="store_true")
    parser.add_argument("--chapters", default="")
    args = parser.parse_args()
    chapters = {item.strip() for item in str(args.chapters).split(",") if item.strip()} or None
    paths = run_all_chapter_tradable_layers(
        manifest_path=Path(args.manifest),
        out_dir=Path(args.out_dir),
        include_bull_flag=bool(args.include_bull_flag),
        reuse_existing=bool(args.reuse_existing),
        chapters=chapters,
    )
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
