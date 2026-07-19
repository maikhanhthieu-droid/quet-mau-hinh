"""Build a lightweight tradable-preflight matrix for all final chapters.

This is deliberately not a full tradable scorecard.  It uses the event/path
metrics that already exist for publication chapters to flag whether a pattern
looks execution-promising, execution-weak, or mainly defensive/informational.

The full `tradable-final-95` gate remains stricter and requires an executable
entry/exit/cost/sizing/OOS scorecard.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections.abc import Callable, Mapping
from pathlib import Path
from statistics import median
from typing import Any


DEFAULT_MANIFEST = Path("artifacts/final_chapters/final_chapters_manifest.json")
DEFAULT_OUT_DIR = Path("artifacts/final_chapters/governance")
DEFAULT_TARGET_CALIBRATION = Path("artifacts/scanner_v2/final_chapters_target_calibration_audit/chapter_target_calibration_summary.json")
PREFLIGHT_MATRIX_ID = "tradable_preflight_matrix_v1"


EVENT_SOURCES: dict[str, dict[str, Any]] = {
    "bull_flags": {
        "events": Path("artifacts/scanner_v2/bull_flags_adaptive_grid/scans/bull_flag_v2_split_stable_recovery/events.csv"),
        "scope": "long_cash_candidate",
    },
    "bear_flags": {
        "events": Path("artifacts/scanner_v2/bear_flags_db_source_parity/db_active/events.csv"),
        "scope": "defensive_informational",
    },
    "bull_pennants": {
        "events": Path("artifacts/scanner_v2/pennants/events.csv"),
        "variant": "bull_pennant",
        "scope": "long_cash_candidate",
    },
    "bear_pennants": {
        "events": Path("artifacts/scanner_v2/pennants/events.csv"),
        "variant": "bear_pennant",
        "scope": "defensive_informational",
    },
    "high_tight_flags": {
        "events": Path("artifacts/scanner_v2/high_tight_flags/events.csv"),
        "scope": "long_cash_candidate",
    },
    "triangles_ascending": {
        "events": Path("artifacts/scanner_v2/ascending_triangles_db_source_parity/db_active/events.csv"),
        "scope": "long_cash_candidate",
    },
    "triangles_descending": {
        "events": Path("artifacts/scanner_v2/descending_triangles_db_source_parity/db_active/events.csv"),
        "scope": "defensive_informational",
    },
    "triangles_symmetrical": {
        "events": Path("artifacts/scanner_v2/symmetrical_triangles_db_source_parity/db_active/events.csv"),
        "scope": "mixed_direction_reference",
    },
    "double_bottoms_adam_adam": {
        "events": Path("artifacts/scanner_v2/double_pattern_family/double_bottoms/db_active/events.csv"),
        "variant": "AA",
        "scope": "long_cash_candidate",
    },
    "double_bottoms_adam_eve": {
        "events": Path("artifacts/scanner_v2/double_pattern_family/double_bottoms/db_active/events.csv"),
        "variant": "AE",
        "scope": "long_cash_candidate",
    },
    "double_bottoms_eve_adam": {
        "events": Path("artifacts/scanner_v2/double_pattern_family/double_bottoms/db_active/events.csv"),
        "variant": "EA",
        "scope": "long_cash_candidate",
    },
    "double_bottoms_eve_eve": {
        "events": Path("artifacts/scanner_v2/double_pattern_family/double_bottoms/db_active/events.csv"),
        "variant": "EE",
        "scope": "long_cash_candidate",
    },
    "double_tops_adam_adam": {
        "events": Path("artifacts/scanner_v2/double_pattern_family/double_tops/db_active/events.csv"),
        "variant": "AA",
        "scope": "defensive_informational",
    },
    "double_tops_adam_eve": {
        "events": Path("artifacts/scanner_v2/double_pattern_family/double_tops/db_active/events.csv"),
        "variant": "AE",
        "scope": "defensive_informational",
    },
    "double_tops_eve_adam": {
        "events": Path("artifacts/scanner_v2/double_pattern_family/double_tops/db_active/events.csv"),
        "variant": "EA",
        "scope": "defensive_informational",
    },
    "double_tops_eve_eve": {
        "events": Path("artifacts/scanner_v2/double_pattern_family/double_tops/db_active/events.csv"),
        "variant": "EE",
        "scope": "defensive_informational",
    },
    "wedges_falling": {
        "events": Path("artifacts/scanner_v2/wedge_family/falling_wedges/db_active/events.csv"),
        "scope": "long_cash_candidate",
    },
    "wedges_rising": {
        "events": Path("artifacts/scanner_v2/wedge_family/rising_wedges/db_active/events.csv"),
        "scope": "defensive_informational",
    },
    "cup_with_handle": {
        "events": Path("artifacts/scanner_v2/cup_with_handle_family/cup_with_handle/db_active/events.csv"),
        "scope": "long_cash_candidate",
    },
    "cup_with_handle_inverted": {
        "events": Path("artifacts/scanner_v2/cup_with_handle_family/cup_with_handle_inverted/db_active/events.csv"),
        "scope": "defensive_informational",
    },
    "rectangle_bottoms": {
        "events": Path("artifacts/scanner_v2/rectangle_family/rectangle_bottoms/db_active/events.csv"),
        "scope": "mixed_direction_reference",
    },
    "rectangle_tops": {
        "events": Path("artifacts/scanner_v2/rectangle_family/rectangle_tops/db_active/events.csv"),
        "scope": "mixed_direction_reference",
    },
    "head_and_shoulders_bottoms": {
        "events": Path("artifacts/scanner_v2/head_shoulders_family/head_and_shoulders_bottoms/db_active/events.csv"),
        "scope": "long_cash_candidate",
    },
    "head_and_shoulders_bottoms_complex": {
        "events": Path("artifacts/scanner_v2/head_shoulders_family/head_and_shoulders_bottoms_complex/db_active/events.csv"),
        "scope": "long_cash_candidate",
    },
    "head_and_shoulders_tops": {
        "events": Path("artifacts/scanner_v2/head_shoulders_family/head_and_shoulders_tops/db_active/events.csv"),
        "scope": "defensive_informational",
    },
    "head_and_shoulders_tops_complex": {
        "events": Path("artifacts/scanner_v2/head_shoulders_family/head_and_shoulders_tops_complex/db_active/events.csv"),
        "scope": "defensive_informational",
    },
    "broadening_bottoms": {
        "events": Path("artifacts/scanner_v2/broadening_family/broadening_bottoms/db_active/events.csv"),
        "scope": "mixed_direction_reference",
    },
    "broadening_formations_right_angled_ascending": {
        "events": Path("artifacts/scanner_v2/broadening_family/broadening_formations_right_angled_ascending/db_active/events.csv"),
        "scope": "defensive_informational",
    },
    "broadening_formations_right_angled_descending": {
        "events": Path("artifacts/scanner_v2/broadening_family/broadening_formations_right_angled_descending/db_active/events.csv"),
        "scope": "mixed_direction_reference",
    },
    "broadening_tops": {
        "events": Path("artifacts/scanner_v2/broadening_family/broadening_tops/db_active/events.csv"),
        "scope": "defensive_informational",
    },
    "broadening_wedges_ascending": {
        "events": Path("artifacts/scanner_v2/broadening_family/broadening_wedges_ascending/db_active/events.csv"),
        "scope": "defensive_informational",
    },
    "broadening_wedges_descending": {
        "events": Path("artifacts/scanner_v2/broadening_family/broadening_wedges_descending/db_active/events.csv"),
        "scope": "long_cash_candidate",
    },
    "measured_move_up": {
        "events": Path("artifacts/scanner_v2/measured_move_family/measured_move_up/db_active/events.csv"),
        "scope": "long_cash_candidate",
    },
    "measured_move_down": {
        "events": Path("artifacts/scanner_v2/measured_move_family/measured_move_down/db_active/events.csv"),
        "scope": "defensive_informational",
    },
    "scallops_ascending": {
        "events": Path("artifacts/scanner_v2/scallop_family/scallops_ascending/db_active/events.csv"),
        "scope": "mixed_direction_reference",
    },
    "scallops_ascending_inverted": {
        "events": Path("artifacts/scanner_v2/scallop_family/scallops_ascending_inverted/db_active/events.csv"),
        "scope": "long_cash_candidate",
    },
    "scallops_descending": {
        "events": Path("artifacts/scanner_v2/scallop_family/scallops_descending/db_active/events.csv"),
        "scope": "mixed_direction_reference",
    },
    "scallops_descending_inverted": {
        "events": Path("artifacts/scanner_v2/scallop_family/scallops_descending_inverted/db_active/events.csv"),
        "scope": "defensive_informational",
    },
    "pipe_bottoms": {
        "events": Path("artifacts/scanner_v2/pipe_family/pipe_bottoms/db_active/events.csv"),
        "scope": "long_cash_candidate",
    },
    "pipe_tops": {
        "events": Path("artifacts/scanner_v2/pipe_family/pipe_tops/db_active/events.csv"),
        "scope": "defensive_informational",
    },
    "horn_bottoms": {
        "events": Path("artifacts/scanner_v2/horn_family/horn_bottoms/db_active/events.csv"),
        "scope": "long_cash_candidate",
    },
    "horn_tops": {
        "events": Path("artifacts/scanner_v2/horn_family/horn_tops/db_active/events.csv"),
        "scope": "defensive_informational",
    },
    "diamond_bottoms": {
        "events": Path("artifacts/scanner_v2/diamond_family/diamond_bottoms/db_active/events.csv"),
        "scope": "mixed_direction_reference",
    },
    "diamond_tops": {
        "events": Path("artifacts/scanner_v2/diamond_family/diamond_tops/db_active/events.csv"),
        "scope": "defensive_informational",
    },
    "dead_cat_bounce": {
        "events": Path("artifacts/scanner_v2/dead_cat_bounce_family/dead_cat_bounce/db_active/events.csv"),
        "scope": "defensive_informational",
    },
    "dead_cat_bounce_inverted": {
        "events": Path("artifacts/scanner_v2/dead_cat_bounce_family/dead_cat_bounce_inverted/db_active/events.csv"),
        "scope": "defensive_informational",
    },
    "three_falling_peaks": {
        "events": Path("artifacts/scanner_v2/three_peaks_valleys_family/three_falling_peaks/db_active/events.csv"),
        "scope": "defensive_informational",
    },
    "three_rising_valleys": {
        "events": Path("artifacts/scanner_v2/three_peaks_valleys_family/three_rising_valleys/db_active/events.csv"),
        "scope": "long_cash_candidate",
    },
    "triple_tops": {
        "events": Path("artifacts/scanner_v2/triple_family/triple_tops/db_active/events.csv"),
        "scope": "defensive_informational",
    },
    "triple_bottoms": {
        "events": Path("artifacts/scanner_v2/triple_family/triple_bottoms/db_active/events.csv"),
        "scope": "long_cash_candidate",
    },
    "bump_and_run_reversal_bottoms": {
        "events": Path("artifacts/scanner_v2/bump_and_run_family/bump_and_run_reversal_bottoms/db_active/events.csv"),
        "scope": "long_cash_candidate",
    },
    "bump_and_run_reversal_tops": {
        "events": Path("artifacts/scanner_v2/bump_and_run_family/bump_and_run_reversal_tops/db_active/events.csv"),
        "scope": "defensive_informational",
    },
    "area_gaps": {
        "events": Path("artifacts/scanner_v2/gap_family/area_gaps/db_active/events.csv"),
        "scope": "gap_closure_informational",
    },
    "breakaway_gaps": {
        "events": Path("artifacts/scanner_v2/gap_family/breakaway_gaps/db_active/events.csv"),
        "scope": "long_cash_candidate",
    },
    "continuation_gaps": {
        "events": Path("artifacts/scanner_v2/gap_family/continuation_gaps/db_active/events.csv"),
        "scope": "long_cash_candidate",
    },
    "exhaustion_gaps": {
        "events": Path("artifacts/scanner_v2/gap_family/exhaustion_gaps/db_active/events.csv"),
        "scope": "gap_exhaustion_informational",
    },
    "island_reversals": {
        "events": Path("artifacts/scanner_v2/island_family/island_reversals/db_active/events.csv"),
        "scope": "mixed_direction_reference",
    },
    "islands_long": {
        "events": Path("artifacts/scanner_v2/island_family/islands_long/db_active/events.csv"),
        "scope": "mixed_direction_reference",
    },
    "rounding_bottoms": {
        "events": Path("artifacts/scanner_v2/rounding_family/rounding_bottoms/db_active/events.csv"),
        "scope": "long_cash_candidate",
    },
    "rounding_tops": {
        "events": Path("artifacts/scanner_v2/rounding_family/rounding_tops/db_active/events.csv"),
        "scope": "defensive_informational",
    },
    "inside_day": {
        "events": Path("artifacts/scanner_v2/inside_day_family/inside_day/db_active/events.csv"),
        "scope": "mixed_direction_reference",
    },
    "rising_three_methods": {
        "events": Path("artifacts/scanner_v2/three_methods_family/rising_three_methods/db_active/events.csv"),
        "scope": "long_cash_candidate",
    },
    "falling_three_methods": {
        "events": Path("artifacts/scanner_v2/three_methods_family/falling_three_methods/db_active/events.csv"),
        "scope": "defensive_informational",
    },
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _read_events(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _event_id(row: Mapping[str, Any]) -> str:
    return str(row.get("event_id") or row.get("detection_id") or "").strip()


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        result = float(text)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _as_bool(value: Any) -> bool | None:
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _clip(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _values(rows: list[Mapping[str, Any]], column: str) -> list[float]:
    return [value for row in rows if (value := _as_float(row.get(column))) is not None]


def _rate(rows: list[Mapping[str, Any]], column: str) -> float | None:
    values = [value for row in rows if (value := _as_bool(row.get(column))) is not None]
    if not values:
        return None
    return sum(1 for value in values if value) / len(values)


def _share(rows: list[Mapping[str, Any]], column: str, predicate: Callable[[str], bool]) -> float | None:
    values = [str(row.get(column) or "").strip().lower() for row in rows if str(row.get(column) or "").strip()]
    if not values:
        return None
    return sum(1 for value in values if predicate(value)) / len(values)


def _median(rows: list[Mapping[str, Any]], column: str) -> float | None:
    values = _values(rows, column)
    return float(median(values)) if values else None


def _filter_rows(rows: list[dict[str, str]], source: Mapping[str, Any]) -> tuple[list[dict[str, str]], list[str]]:
    warnings: list[str] = []
    selected = rows
    variant = source.get("variant")
    if variant:
        selected = [row for row in selected if str(row.get("variant") or "") == str(variant)]
        if not selected:
            return [], [f"variant_filter_empty:{variant}"]

    publication_filtered = selected
    quality_column = "publication_quality_tier" if selected and "publication_quality_tier" in selected[0] else "pattern_quality_tier"
    if selected and quality_column in selected[0]:
        good_public = {"premium", "standard"}
        candidate = [row for row in selected if str(row.get(quality_column) or "").strip().lower() in good_public]
        if len(candidate) >= 30:
            publication_filtered = candidate
        elif candidate:
            warnings.append("publication_quality_filter_not_applied_due_to_low_n")
    selected = publication_filtered

    if selected and "is_primary_event_60d" in selected[0]:
        candidate = [row for row in selected if _as_bool(row.get("is_primary_event_60d")) is True]
        if len(candidate) >= 30:
            selected = candidate
        elif candidate:
            warnings.append("primary_event_filter_not_applied_due_to_low_n")

    return selected, warnings


def _target_calibration_map(path: Path = DEFAULT_TARGET_CALIBRATION) -> dict[str, float]:
    payload = _read_json(path)
    out: dict[str, float] = {}
    for row in payload.get("rows") or []:
        if not isinstance(row, Mapping):
            continue
        pattern_id = str(row.get("pattern_id") or "")
        multiple = _as_float(row.get("selected_base_target_multiple"))
        if pattern_id and multiple is not None and multiple > 0:
            out[pattern_id] = float(multiple)
    return out


def _source_path(source: Mapping[str, Any]) -> Path | None:
    explicit = source.get("path")
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None
    events_path = Path(source["events"])
    candidate = events_path.with_name("post_breakout_path.csv")
    return candidate if candidate.exists() else None


def _recompute_target_flags(rows: list[dict[str, Any]], source: Mapping[str, Any], target_multiple: float | None) -> list[dict[str, Any]]:
    if not rows or target_multiple is None:
        return rows
    path = _source_path(source)
    if path is None:
        return rows
    target_by_id: dict[str, float] = {}
    for row in rows:
        event_id = _event_id(row)
        target_dist = _as_float(row.get("target_dist_pct"))
        if event_id and target_dist is not None and target_dist > 0:
            target_by_id[event_id] = target_dist * float(target_multiple)
    if not target_by_id:
        return rows

    days_to_target: dict[str, int] = {}
    days_to_adverse: dict[str, int] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            event_id = str(row.get("event_id") or "").strip()
            if event_id not in target_by_id:
                continue
            bar = _as_float(row.get("bar_after_breakout"))
            if bar is None or bar < 1 or bar > 120:
                continue
            high_exc = _as_float(row.get("signed_high_excursion_pct"))
            low_exc = _as_float(row.get("signed_low_excursion_pct"))
            bar_i = int(bar)
            if event_id not in days_to_target and high_exc is not None and high_exc >= target_by_id[event_id]:
                days_to_target[event_id] = bar_i
            if event_id not in days_to_adverse and low_exc is not None and low_exc <= -5.0:
                days_to_adverse[event_id] = bar_i

    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        event_id = _event_id(item)
        hit_day = days_to_target.get(event_id)
        adverse_day = days_to_adverse.get(event_id)
        target_hit = hit_day is not None
        item["target_hit"] = str(bool(target_hit))
        item["target_first_before_adverse_5pct"] = str(bool(target_hit and (adverse_day is None or hit_day < adverse_day)))
        item["days_to_target"] = "" if hit_day is None else str(hit_day)
        item["preflight_target_multiple"] = str(float(target_multiple))
        if "event_id" not in item and event_id:
            item["event_id"] = event_id
        out.append(item)
    return out


def _num(row: Mapping[str, Any], column: str, default: float = 0.0) -> float:
    value = _as_float(row.get(column))
    return float(default) if value is None else float(value)


def _text(row: Mapping[str, Any], column: str) -> str:
    return str(row.get(column) or "").strip().lower()


def _bool_text(row: Mapping[str, Any], column: str) -> bool:
    return _as_bool(row.get(column)) is True


def _branch_candidates(pattern_id: str, rows: list[dict[str, Any]]) -> list[tuple[str, str, list[dict[str, Any]]]]:
    if not rows:
        return []
    candidates: list[tuple[str, str, list[dict[str, Any]]]] = []

    def add(branch_id: str, description: str, predicate: Callable[[Mapping[str, Any]], bool]) -> None:
        selected = [row for row in rows if predicate(row)]
        if len(selected) >= 30:
            candidates.append((branch_id, description, selected))

    if pattern_id == "wedges_rising":
        add("primary_mid_high", "Primary events with mid/high liquidity.", lambda r: _bool_text(r, "is_primary_event_60d") and _text(r, "liquidity_bucket") in {"mid", "high"})
        add("quality_liquid", "Quality rising wedges in mid/high liquidity.", lambda r: _num(r, "publication_quality_score", 0.0) >= 75.0 and _text(r, "liquidity_bucket") in {"mid", "high"})
        add("bull_high_liq_width_core", "Bull-regime high-liquidity rising wedges with core width.", lambda r: _text(r, "market_regime") == "bull" and _text(r, "liquidity_bucket") == "high" and 25.0 <= _num(r, "pattern_width_bars") <= 60.0)
        add("bull_high_liq_clear", "Bull-regime high-liquidity rising wedges with clear breakdown.", lambda r: _text(r, "market_regime") == "bull" and _text(r, "liquidity_bucket") == "high" and _num(r, "breakout_clearance_pct") >= 1.0)
    elif pattern_id == "triangles_symmetrical":
        add("clean_apex_tight", "Clean symmetrical triangle near apex with low crossings.", lambda r: _text(r, "breakout_direction") == "up" and _num(r, "triangle_white_space_score") >= 85.0 and _num(r, "triangle_crossing_count") <= 4.0 and 60.0 <= _num(r, "apex_progress_pct") <= 115.0)
        add("liquid_clear_breakout", "Liquid up-breakout with clear price confirmation.", lambda r: _text(r, "breakout_direction") == "up" and _text(r, "liquidity_bucket") in {"mid", "high"} and _num(r, "breakout_clearance_pct") >= 1.5)
        add("mature_compression", "Mature compressed symmetrical triangle.", lambda r: _text(r, "breakout_direction") == "up" and _num(r, "compression_ratio") <= 0.55 and 70.0 <= _num(r, "apex_progress_pct") <= 110.0)
        add("high_quality_liquid", "High publication quality in mid/high liquidity.", lambda r: _text(r, "breakout_direction") == "up" and _num(r, "publication_quality_score") >= 80.0 and _text(r, "liquidity_bucket") in {"mid", "high"})
        add("bear_high_liq_long_up", "Long-up branch in bear regime and high liquidity.", lambda r: _text(r, "breakout_direction") == "up" and _text(r, "market_regime") == "bear" and _text(r, "liquidity_bucket") == "high")
    elif pattern_id == "bear_flags":
        add("headline_high_liq", "Headline Bear Flag branch in high liquidity.", lambda r: _bool_text(r, "bear_branch_is_headline_candidate") and _text(r, "liquidity_bucket") == "high")
        add("headline_high_liq_compact", "Headline high-liquidity Bear Flag with compact flag body.", lambda r: _bool_text(r, "bear_branch_is_headline_candidate") and _text(r, "liquidity_bucket") == "high" and _num(r, "flag_to_pole_pct", 999.0) <= 45.0)
        add("clean_breakdown_body", "Cleaner bearish breakdown candle shape.", lambda r: _bool_text(r, "bear_branch_is_headline_candidate") and _num(r, "breakout_body_to_range") >= 0.35 and _num(r, "breakout_close_location", 1.0) <= 0.55)
    elif pattern_id == "bull_pennants":
        add("compact_pennant", "Compact Pennant body relative to pole.", lambda r: _num(r, "pennant_to_pole_pct", _num(r, "flag_to_pole_pct", 999.0)) <= 45.0)
        add("strong_quality", "High pattern-quality Bull Pennants.", lambda r: _num(r, "pattern_quality_score", 0.0) >= 70.0)
        add("volume_confirmed", "Bull Pennants with breakout-volume confirmation.", lambda r: _bool_text(r, "volume_confirmed"))
        add("bear_mid_high", "Bear-regime mid/high liquidity Pennants.", lambda r: _text(r, "market_regime") == "bear" and _text(r, "liquidity_bucket") in {"mid", "high"})
    elif pattern_id == "bear_pennants":
        add("compact_pennant", "Compact Bear Pennant body relative to pole.", lambda r: _num(r, "pennant_to_pole_pct", _num(r, "flag_to_pole_pct", 999.0)) <= 45.0)
        add("strong_quality", "High pattern-quality Bear Pennants.", lambda r: _num(r, "pattern_quality_score", 0.0) >= 70.0)
        add("volume_confirmed", "Bear Pennants with contraction/breakout-volume confirmation.", lambda r: _bool_text(r, "volume_confirmed"))
        add("high_liq_compact", "High-liquidity compact Bear Pennants.", lambda r: _text(r, "liquidity_bucket") == "high" and _num(r, "pennant_to_pole_pct", _num(r, "flag_to_pole_pct", 999.0)) <= 45.0)
    elif pattern_id == "high_tight_flags":
        add("near_high_compact", "High-and-Tight Flags with compact high consolidation.", lambda r: _num(r, "consolidation_pullback_pct", 999.0) <= 25.0 and _num(r, "flag_to_pole_pct", 999.0) <= 35.0)
        add("strong_quality", "High-quality High-and-Tight Flag formations.", lambda r: _num(r, "pattern_quality_score", 0.0) >= 80.0)
        add("volume_contracts", "High-and-Tight Flags with contracting volume during consolidation.", lambda r: _bool_text(r, "volume_contracts"))
        add("bull_high_liq", "Bull-regime high-liquidity High-and-Tight Flags.", lambda r: _text(r, "market_regime") == "bull" and _text(r, "liquidity_bucket") == "high")
    elif pattern_id.startswith("broadening_"):
        if pattern_id in {"broadening_bottoms", "broadening_formations_right_angled_descending", "broadening_wedges_descending"}:
            add("up_mid_high_clear", "Up-breakout broadening events in mid/high liquidity with clear confirmation.", lambda r: _text(r, "breakout_direction") == "up" and _text(r, "liquidity_bucket") in {"mid", "high"} and _num(r, "breakout_clearance_pct") >= 1.0)
            add("up_strong_expansion", "Up-breakout broadening events with strong widening geometry.", lambda r: _text(r, "breakout_direction") == "up" and _num(r, "expansion_ratio") >= 1.35 and _num(r, "publication_quality_score") >= 65.0)
        else:
            add("down_mid_high_clear", "Down-breakout broadening events in mid/high liquidity with clear confirmation.", lambda r: _text(r, "breakout_direction") == "down" and _text(r, "liquidity_bucket") in {"mid", "high"} and _num(r, "breakout_clearance_pct") >= 1.0)
            add("down_strong_expansion", "Down-breakout broadening events with strong widening geometry.", lambda r: _text(r, "breakout_direction") == "down" and _num(r, "expansion_ratio") >= 1.35 and _num(r, "publication_quality_score") >= 65.0)
    return candidates


def _sample_depth_score(n_events: int, n_symbols: int) -> float:
    event_score = (
        15.0
        if n_events >= 500
        else 12.0
        if n_events >= 250
        else 9.0
        if n_events >= 100
        else 6.0
        if n_events >= 50
        else 4.0
        if n_events >= 30
        else 1.5
    )
    concentration_penalty = 1.0 if n_events and n_symbols / n_events < 0.08 else 0.0
    return max(0.0, event_score - concentration_penalty)


def _quality_score(rows: list[Mapping[str, Any]]) -> float:
    good_tradability = _share(rows, "tradability_quality_bucket", lambda value: value in {"clean", "usable"})
    cleanish_path = _share(rows, "path_quality_bucket", lambda value: value in {"clean", "stale_close"})
    if good_tradability is None and cleanish_path is None:
        numeric = _median(rows, "tradability_quality_score")
        return _clip((numeric or 55.0) / 100.0) * 15.0
    trad = 0.60 if good_tradability is None else good_tradability
    path = 0.55 if cleanish_path is None else cleanish_path
    return (0.65 * trad + 0.35 * path) * 15.0


def _asymmetry_score(median_mfe: float | None, median_mae: float | None) -> tuple[float, float | None]:
    if median_mfe is None or median_mae is None:
        return 6.0, None
    ratio = median_mfe / max(median_mae, 0.01)
    return _clip((ratio - 0.80) / 0.70) * 20.0, ratio


def _target_first_score(target_first_rate: float | None, failure_rate: float | None) -> float:
    if target_first_rate is None and failure_rate is None:
        return 8.0
    target_first = target_first_rate if target_first_rate is not None else 0.0
    failure = failure_rate if failure_rate is not None else 0.35
    spread = target_first - failure
    return _clip((spread + 0.20) / 0.40) * 25.0


def _target_attainment_score(target_hit_rate: float | None) -> float:
    if target_hit_rate is None:
        return 6.0
    return _clip(target_hit_rate / 0.50) * 15.0


def _liquidity_score(rows: list[Mapping[str, Any]]) -> float:
    mid_high_share = _share(rows, "liquidity_bucket", lambda value: value in {"mid", "high"})
    if mid_high_share is None:
        return 5.0
    return mid_high_share * 10.0


def _preflight_status(score: float | None, n_events: int) -> str:
    if score is None or n_events < 30:
        return "insufficient_data"
    if score >= 85:
        return "preflight_strong"
    if score >= 75:
        return "preflight_candidate"
    if score >= 65:
        return "preflight_watchlist"
    if score >= 50:
        return "preflight_weak"
    return "preflight_poor"


def _flags(row: Mapping[str, Any]) -> list[str]:
    warnings: list[str] = list(row.get("warnings") or [])
    if int(row.get("n_events") or 0) < 100:
        warnings.append("thin_sample")
    if (row.get("scope") or "") == "defensive_informational":
        warnings.append("cash_equity_downside_not_direct_tradable")
    ratio = row.get("mfe_mae_ratio")
    if isinstance(ratio, (int, float)) and ratio < 1.0:
        warnings.append("median_mfe_below_median_mae")
    target_first = row.get("target_first_before_adverse_5pct_rate")
    failure = row.get("failure_5pct_rate")
    if isinstance(target_first, (int, float)) and isinstance(failure, (int, float)) and target_first <= failure:
        warnings.append("target_first_not_above_failure")
    if isinstance(row.get("mid_high_liquidity_share"), (int, float)) and row["mid_high_liquidity_share"] < 0.45:
        warnings.append("low_mid_high_liquidity_share")
    return sorted(set(warnings))


def _score_rows(
    *,
    chapter: Mapping[str, Any],
    pattern_id: str,
    source: Mapping[str, Any],
    rows: list[dict[str, Any]],
    warnings: list[str],
    branch_id: str = "aggregate",
    branch_description: str = "Aggregate preflight selection.",
    target_multiple: float | None = None,
) -> dict[str, Any]:
    symbols = {str(row.get("symbol") or "") for row in rows if str(row.get("symbol") or "")}
    n_events = len(rows)
    n_symbols = len(symbols)
    target_hit_rate = _rate(rows, "target_hit")
    failure_rate = _rate(rows, "failure_5pct")
    target_first_rate = _rate(rows, "target_first_before_adverse_5pct")
    median_mfe = _median(rows, "mfe_pct")
    median_mae = _median(rows, "mae_pct")
    median_days_to_target = _median(rows, "days_to_target")
    median_target_dist = _median(rows, "target_dist_pct")
    mid_high_liquidity_share = _share(rows, "liquidity_bucket", lambda value: value in {"mid", "high"})
    good_tradability_share = _share(rows, "tradability_quality_bucket", lambda value: value in {"clean", "usable"})
    public_grade_share = _share(rows, "publication_quality_tier", lambda value: value in {"premium", "standard"})
    if public_grade_share is None:
        public_grade_share = _share(rows, "pattern_quality_tier", lambda value: value in {"premium", "standard"})
    primary_event_share = _share(rows, "is_primary_event_60d", lambda value: value == "true")

    sample_score = _sample_depth_score(n_events, n_symbols)
    quality_score = _quality_score(rows) if rows else 0.0
    asymmetry_score, mfe_mae_ratio = _asymmetry_score(median_mfe, median_mae)
    target_path_score = _target_first_score(target_first_rate, failure_rate)
    target_attainment_score = _target_attainment_score(target_hit_rate)
    liquidity_score = _liquidity_score(rows) if rows else 0.0
    total_score = round(
        sample_score + quality_score + asymmetry_score + target_path_score + target_attainment_score + liquidity_score,
        2,
    )

    row: dict[str, Any] = {
        "pattern_id": pattern_id,
        "family": chapter.get("family"),
        "title": chapter.get("title"),
        "preflight_available": bool(rows),
        "preflight_status": _preflight_status(total_score if rows else None, n_events),
        "preflight_score": total_score if rows else None,
        "scope": source.get("scope"),
        "events_path": str(source["events"]),
        "variant_filter": source.get("variant"),
        "n_events_raw": None,
        "n_events": n_events,
        "n_symbols": n_symbols,
        "target_hit_rate": target_hit_rate,
        "target_first_before_adverse_5pct_rate": target_first_rate,
        "failure_5pct_rate": failure_rate,
        "median_mfe_pct": median_mfe,
        "median_mae_pct": median_mae,
        "mfe_mae_ratio": mfe_mae_ratio,
        "median_target_dist_pct": median_target_dist,
        "median_days_to_target": median_days_to_target,
        "public_grade_share": public_grade_share,
        "good_tradability_share": good_tradability_share,
        "mid_high_liquidity_share": mid_high_liquidity_share,
        "primary_event_share": primary_event_share,
        "preflight_branch_id": branch_id,
        "preflight_branch_description": branch_description,
        "preflight_target_multiple": target_multiple,
        "score_components": {
            "sample_depth": round(sample_score, 2),
            "path_and_tradability_quality": round(quality_score, 2),
            "forward_asymmetry": round(asymmetry_score, 2),
            "target_first_vs_failure": round(target_path_score, 2),
            "target_attainment": round(target_attainment_score, 2),
            "liquidity_executability": round(liquidity_score, 2),
        },
        "warnings": warnings,
    }
    row["warnings"] = _flags(row)
    if branch_id != "aggregate":
        row["warnings"] = sorted(set(row["warnings"] + ["branch_scoped_preflight"]))
    if target_multiple is not None and abs(float(target_multiple) - 1.0) > 1e-9:
        row["warnings"] = sorted(set(row["warnings"] + ["calibrated_target_preflight"]))
    return row


def _build_row(chapter: Mapping[str, Any], target_multiples: Mapping[str, float] | None = None) -> dict[str, Any]:
    pattern_id = str(chapter.get("pattern_id") or "")
    source = EVENT_SOURCES.get(pattern_id)
    if not source:
        return {
            "pattern_id": pattern_id,
            "family": chapter.get("family"),
            "title": chapter.get("title"),
            "preflight_available": False,
            "preflight_status": "missing_event_source",
            "preflight_score": None,
            "scope": "unknown",
            "warnings": ["event_source_not_mapped"],
        }

    all_rows = _read_events(Path(source["events"]))
    selected_rows, warnings = _filter_rows(all_rows, source)
    target_multiple = (target_multiples or {}).get(pattern_id)
    selected_rows = _recompute_target_flags(selected_rows, source, target_multiple)
    aggregate = _score_rows(
        chapter=chapter,
        pattern_id=pattern_id,
        source=source,
        rows=selected_rows,
        warnings=warnings,
        target_multiple=target_multiple,
    )
    aggregate["n_events_raw"] = len(all_rows)

    branch_rows = [
        _score_rows(
            chapter=chapter,
            pattern_id=pattern_id,
            source=source,
            rows=branch_rows,
            warnings=warnings,
            branch_id=branch_id,
            branch_description=description,
            target_multiple=target_multiple,
        )
        for branch_id, description, branch_rows in _branch_candidates(pattern_id, selected_rows)
    ]
    branch_rows = [row | {"n_events_raw": len(all_rows)} for row in branch_rows]
    candidates = [aggregate] + branch_rows
    best = max(candidates, key=lambda row: float(row.get("preflight_score") or -1.0))
    if best is not aggregate and float(best.get("preflight_score") or 0.0) >= float(aggregate.get("preflight_score") or 0.0) + 3.0:
        best["aggregate_preflight_score"] = aggregate.get("preflight_score")
        best["aggregate_preflight_status"] = aggregate.get("preflight_status")
        best["branch_candidate_count"] = len(branch_rows)
        best["preflight_branch_candidates"] = [
            {
                "branch_id": row.get("preflight_branch_id"),
                "preflight_score": row.get("preflight_score"),
                "preflight_status": row.get("preflight_status"),
                "n_events": row.get("n_events"),
                "mfe_mae_ratio": row.get("mfe_mae_ratio"),
                "target_first_before_adverse_5pct_rate": row.get("target_first_before_adverse_5pct_rate"),
                "failure_5pct_rate": row.get("failure_5pct_rate"),
            }
            for row in sorted(branch_rows, key=lambda item: float(item.get("preflight_score") or -1.0), reverse=True)[:8]
        ]
        return best
    aggregate["branch_candidate_count"] = len(branch_rows)
    aggregate["preflight_branch_candidates"] = [
        {
            "branch_id": row.get("preflight_branch_id"),
            "preflight_score": row.get("preflight_score"),
            "preflight_status": row.get("preflight_status"),
            "n_events": row.get("n_events"),
        }
        for row in sorted(branch_rows, key=lambda item: float(item.get("preflight_score") or -1.0), reverse=True)[:8]
    ]
    return aggregate


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "family",
        "pattern_id",
        "title",
        "preflight_status",
        "preflight_score",
        "scope",
        "n_events",
        "n_symbols",
        "target_hit_rate",
        "target_first_before_adverse_5pct_rate",
        "failure_5pct_rate",
        "median_mfe_pct",
        "median_mae_pct",
        "mfe_mae_ratio",
        "median_days_to_target",
        "public_grade_share",
        "good_tradability_share",
        "mid_high_liquidity_share",
        "preflight_branch_id",
        "preflight_target_multiple",
        "aggregate_preflight_score",
        "warnings",
        "events_path",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            out = {key: row.get(key) for key in fieldnames}
            out["warnings"] = ",".join(row.get("warnings") or [])
            writer.writerow(out)


def _render_markdown(payload: Mapping[str, Any]) -> str:
    rows = list(payload.get("chapters") or [])
    lines = [
        "# Tradable Preflight Matrix",
        "",
        "Policy: `tradable_preflight_matrix_v1`.",
        "",
        "This matrix is a fast execution-readiness screen for every publication-final chapter. It does not replace the stricter `tradable-final-95` scorecard.",
        "",
        "## Matrix",
        "",
        "| Pattern | Scope | Branch | Target | Status | Score | N | MFE/MAE | Target-first | Failure | Main warnings |",
        "|---|---|---|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        score = "" if row.get("preflight_score") is None else f"{float(row['preflight_score']):.2f}"
        ratio = "" if row.get("mfe_mae_ratio") is None else f"{float(row['mfe_mae_ratio']):.2f}"
        target_first = "" if row.get("target_first_before_adverse_5pct_rate") is None else f"{float(row['target_first_before_adverse_5pct_rate']) * 100:.1f}%"
        failure = "" if row.get("failure_5pct_rate") is None else f"{float(row['failure_5pct_rate']) * 100:.1f}%"
        warnings = ", ".join(row.get("warnings") or [])
        target = "" if row.get("preflight_target_multiple") is None else f"{float(row['preflight_target_multiple']):.2f}x"
        lines.append(
            f"| {row.get('pattern_id')} | {row.get('scope')} | {row.get('preflight_branch_id') or 'aggregate'} | {target} | {row.get('preflight_status')} | {score} | {row.get('n_events')} | {ratio} | {target_first} | {failure} | {warnings} |"
        )
    lines.extend(
        [
            "",
            "## Reading Rule",
            "",
            "- `preflight_strong` means the event statistics look promising enough to justify a full tradable scorecard.",
            "- `preflight_candidate` / `preflight_watchlist` means the chapter may be useful, but execution testing should focus on the listed warnings.",
            "- `defensive_informational` scope is not treated as direct long-cash tradability on Vietnam cash equities.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_chapter_tradable_preflight_matrix(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> dict[str, Path]:
    manifest = _read_json(manifest_path)
    chapters = manifest.get("chapters") if isinstance(manifest.get("chapters"), list) else []
    target_multiples = _target_calibration_map()
    rows = [_build_row(chapter, target_multiples) for chapter in chapters if isinstance(chapter, Mapping)]
    counts = {
        "chapters": len(rows),
        "preflight_available": sum(1 for row in rows if row.get("preflight_available")),
        "preflight_strong": sum(1 for row in rows if row.get("preflight_status") == "preflight_strong"),
        "preflight_candidate": sum(1 for row in rows if row.get("preflight_status") == "preflight_candidate"),
        "preflight_watchlist": sum(1 for row in rows if row.get("preflight_status") == "preflight_watchlist"),
        "preflight_weak_or_poor": sum(
            1 for row in rows if row.get("preflight_status") in {"preflight_weak", "preflight_poor"}
        ),
        "insufficient_or_missing": sum(
            1 for row in rows if row.get("preflight_status") in {"insufficient_data", "missing_event_source"}
        ),
    }
    payload = {
        "preflight_matrix_id": PREFLIGHT_MATRIX_ID,
        "manifest": str(manifest_path),
        "rule": "Tradable preflight is a comparable event-statistics screen. It is not an executable tradable-final scorecard.",
        "counts": counts,
        "chapters": rows,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": out_dir / "chapter_tradable_preflight_matrix.json",
        "csv": out_dir / "chapter_tradable_preflight_matrix.csv",
        "md": out_dir / "chapter_tradable_preflight_matrix.md",
    }
    _write_json(paths["json"], payload)
    _write_csv(paths["csv"], rows)
    paths["md"].write_text(_render_markdown(payload), encoding="utf-8")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Build tradable-preflight matrix for final chapters.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    paths = build_chapter_tradable_preflight_matrix(manifest_path=Path(args.manifest), out_dir=Path(args.out_dir))
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
