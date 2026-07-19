"""
Pattern-set metadata (chapter/name/spec mapping) for Bulkowski-style research.

This module centralizes human-readable labels and canonical/spec mappings for
the various `--pattern-set` options exposed by `scanner/run_full_scan.py`.

Design goals:
  - Keep reporting/audit stable even when pattern keys differ from digitized spec keys
    (e.g., Bulkowski per-chapter variants like double_tops_adam_eve).
  - Persist metadata into `scanner_runs.run_config_json` at scan time for reproducibility.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def _meta(
    *,
    part: int,
    chapter: Optional[int],
    name: str,
    spec_key: Optional[str],
    canonical_key: Optional[str] = None,
    variant: Optional[str] = None,
    kind: str = "chart",
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "kind": str(kind),
        "proxy": spec_key is None,
        "bulkowski_part": int(part),
        "bulkowski_chapter": int(chapter) if chapter is not None else None,
        "bulkowski_name": str(name),
        "spec_key": str(spec_key) if spec_key is not None else None,
    }
    ck = canonical_key or spec_key
    if ck:
        out["canonical_key"] = str(ck)
    if variant is not None:
        out["variant"] = str(variant)
    return out


# Bulkowski Part One: 53 chart-pattern chapters.
BULKOWSKI_53_META: Dict[str, Dict[str, Any]] = {
    # 1-6: broadening patterns
    "broadening_bottoms": _meta(part=1, chapter=1, name="Broadening Bottoms", spec_key="broadening_bottoms", canonical_key="broadening_bottoms"),
    "broadening_formations_right_angled_ascending": _meta(part=1, chapter=2, name="Broadening Formations, Right-Angled and Ascending", spec_key="broadening_formations_right_angled_ascending", canonical_key="broadening_formations_right_angled_ascending"),
    "broadening_formations_right_angled_descending": _meta(part=1, chapter=3, name="Broadening Formations, Right-Angled and Descending", spec_key="broadening_formations_right_angled_descending", canonical_key="broadening_formations_right_angled_descending"),
    "broadening_tops": _meta(part=1, chapter=4, name="Broadening Tops", spec_key="broadening_tops", canonical_key="broadening_tops"),
    "broadening_wedges_ascending": _meta(part=1, chapter=5, name="Broadening Wedges, Ascending", spec_key="broadening_wedges", canonical_key="broadening_wedges", variant="ascending"),
    "broadening_wedges_descending": _meta(part=1, chapter=6, name="Broadening Wedges, Descending", spec_key="broadening_wedges", canonical_key="broadening_wedges", variant="descending"),

    # 7-12: bump-and-run, cup, diamonds
    "bump_and_run_reversal_bottoms": _meta(part=1, chapter=7, name="Bump-and-Run Reversal Bottoms", spec_key="bump_and_run_reversal", canonical_key="bump_and_run_reversal"),
    "bump_and_run_reversal_tops": _meta(part=1, chapter=8, name="Bump-and-Run Reversal Tops", spec_key="bump_and_run_reversal", canonical_key="bump_and_run_reversal"),
    "cup_with_handle": _meta(part=1, chapter=9, name="Cup with Handle", spec_key="cup_with_handle", canonical_key="cup_with_handle"),
    "cup_with_handle_inverted": _meta(part=1, chapter=10, name="Cup with Handle (Inverted)", spec_key="cup_with_handle", canonical_key="cup_with_handle"),
    "diamond_bottoms": _meta(part=1, chapter=11, name="Diamond Bottoms", spec_key="diamond_bottom", canonical_key="diamond_bottom"),
    "diamond_tops": _meta(part=1, chapter=12, name="Diamond Tops", spec_key="diamond_top", canonical_key="diamond_top"),

    # 13-20: double bottoms/tops by Adam/Eve variant (per-chapter in Bulkowski)
    "double_bottoms_adam_adam": _meta(part=1, chapter=13, name="Double Bottoms, Adam & Adam", spec_key="double_bottoms", canonical_key="double_bottoms", variant="AA"),
    "double_bottoms_adam_eve": _meta(part=1, chapter=14, name="Double Bottoms, Adam & Eve", spec_key="double_bottoms", canonical_key="double_bottoms", variant="AE"),
    "double_bottoms_eve_adam": _meta(part=1, chapter=15, name="Double Bottoms, Eve & Adam", spec_key="double_bottoms", canonical_key="double_bottoms", variant="EA"),
    "double_bottoms_eve_eve": _meta(part=1, chapter=16, name="Double Bottoms, Eve & Eve", spec_key="double_bottoms", canonical_key="double_bottoms", variant="EE"),
    "double_tops_adam_adam": _meta(part=1, chapter=17, name="Double Tops, Adam & Adam", spec_key="double_tops", canonical_key="double_tops", variant="AA"),
    "double_tops_adam_eve": _meta(part=1, chapter=18, name="Double Tops, Adam & Eve", spec_key="double_tops", canonical_key="double_tops", variant="AE"),
    "double_tops_eve_adam": _meta(part=1, chapter=19, name="Double Tops, Eve & Adam", spec_key="double_tops", canonical_key="double_tops", variant="EA"),
    "double_tops_eve_eve": _meta(part=1, chapter=20, name="Double Tops, Eve & Eve", spec_key="double_tops", canonical_key="double_tops", variant="EE"),

    # 21-23: flags + gaps
    "flags": _meta(part=1, chapter=21, name="Flags", spec_key="flags", canonical_key="flags"),
    "flags_high_tight": _meta(part=1, chapter=22, name="Flags, High and Tight", spec_key="flags", canonical_key="flags"),
    "gaps": _meta(part=1, chapter=23, name="Gaps", spec_key="gaps", canonical_key="gaps"),

    # 24-27: head and shoulders (standard vs complex)
    "head_and_shoulders_bottoms": _meta(part=1, chapter=24, name="Head-and-Shoulders Bottoms", spec_key="head_and_shoulders_bottom", canonical_key="head_and_shoulders_bottom"),
    "head_and_shoulders_bottoms_complex": _meta(part=1, chapter=25, name="Head-and-Shoulders Bottoms (Complex)", spec_key="head_and_shoulders_bottom", canonical_key="head_and_shoulders_bottom"),
    "head_and_shoulders_tops": _meta(part=1, chapter=26, name="Head-and-Shoulders Tops", spec_key="head_and_shoulders_top", canonical_key="head_and_shoulders_top"),
    "head_and_shoulders_tops_complex": _meta(part=1, chapter=27, name="Head-and-Shoulders Tops (Complex)", spec_key="head_and_shoulders_top", canonical_key="head_and_shoulders_top"),

    # 28-40: horns, islands, measured moves, pennants, pipes, rectangles, rounding
    "horn_bottoms": _meta(part=1, chapter=28, name="Horn Bottoms", spec_key="horn_bottoms_tops", canonical_key="horn_bottoms_tops"),
    "horn_tops": _meta(part=1, chapter=29, name="Horn Tops", spec_key="horn_bottoms_tops", canonical_key="horn_bottoms_tops"),
    "island_reversals": _meta(part=1, chapter=30, name="Island Reversals", spec_key="islands", canonical_key="islands"),
    "islands_long": _meta(part=1, chapter=31, name="Islands, Long", spec_key="islands", canonical_key="islands"),
    "measured_move_down": _meta(part=1, chapter=32, name="Measured Move Down", spec_key="measured_move_down_up", canonical_key="measured_move_down_up"),
    "measured_move_up": _meta(part=1, chapter=33, name="Measured Move Up", spec_key="measured_move_down_up", canonical_key="measured_move_down_up"),
    "pennants": _meta(part=1, chapter=34, name="Pennants", spec_key="pennants", canonical_key="pennants"),
    "pipe_bottoms": _meta(part=1, chapter=35, name="Pipe Bottoms", spec_key="pipe_bottoms", canonical_key="pipe_bottoms"),
    "pipe_tops": _meta(part=1, chapter=36, name="Pipe Tops", spec_key="pipe_bottoms", canonical_key="pipe_bottoms"),
    "rectangle_bottoms": _meta(part=1, chapter=37, name="Rectangle Bottoms", spec_key="rectangle_bottoms_tops", canonical_key="rectangle_bottoms_tops"),
    "rectangle_tops": _meta(part=1, chapter=38, name="Rectangle Tops", spec_key="rectangle_bottoms_tops", canonical_key="rectangle_bottoms_tops"),
    "rounding_bottoms": _meta(part=1, chapter=39, name="Rounding Bottoms", spec_key="rounding_bottoms_tops", canonical_key="rounding_bottoms_tops"),
    "rounding_tops": _meta(part=1, chapter=40, name="Rounding Tops", spec_key="rounding_bottoms_tops", canonical_key="rounding_bottoms_tops"),

    # 41-44: scallops
    "scallops_ascending": _meta(part=1, chapter=41, name="Scallops, Ascending", spec_key="scallop_ascending_descending", canonical_key="scallop_ascending_descending"),
    "scallops_ascending_inverted": _meta(part=1, chapter=42, name="Scallops, Ascending (Inverted)", spec_key="scallop_ascending_descending", canonical_key="scallop_ascending_descending"),
    "scallops_descending": _meta(part=1, chapter=43, name="Scallops, Descending", spec_key="scallop_ascending_descending", canonical_key="scallop_ascending_descending"),
    "scallops_descending_inverted": _meta(part=1, chapter=44, name="Scallops, Descending (Inverted)", spec_key="scallop_ascending_descending", canonical_key="scallop_ascending_descending"),

    # 45-53: three methods, triangles, triple, wedges
    "three_falling_peaks": _meta(part=1, chapter=45, name="Three Falling Peaks", spec_key="three_falling_peaks", canonical_key="three_falling_peaks"),
    "three_rising_valleys": _meta(part=1, chapter=46, name="Three Rising Valleys", spec_key="three_rising_valleys", canonical_key="three_rising_valleys"),
    "triangles_ascending": _meta(part=1, chapter=47, name="Triangles, Ascending", spec_key="triangles", canonical_key="triangles"),
    "triangles_descending": _meta(part=1, chapter=48, name="Triangles, Descending", spec_key="triangles", canonical_key="triangles"),
    "triangles_symmetrical": _meta(part=1, chapter=49, name="Triangles, Symmetrical", spec_key="triangles", canonical_key="triangles"),
    "triple_bottoms": _meta(part=1, chapter=50, name="Triple Bottoms", spec_key="triple_bottoms_tops", canonical_key="triple_bottoms_tops"),
    "triple_tops": _meta(part=1, chapter=51, name="Triple Tops", spec_key="triple_bottoms_tops", canonical_key="triple_bottoms_tops"),
    "wedges_falling": _meta(part=1, chapter=52, name="Wedges, Falling", spec_key="wedges_ascending_descending", canonical_key="wedges_ascending_descending"),
    "wedges_rising": _meta(part=1, chapter=53, name="Wedges, Rising", spec_key="wedges_ascending_descending", canonical_key="wedges_ascending_descending"),
}


# Bulkowski Part Two: Event patterns (only OHLCV-proxy subset here).
EVENT_OHLCV_META: Dict[str, Dict[str, Any]] = {
    "dead_cat_bounce": _meta(part=2, chapter=54, name="Dead-Cat Bounce", spec_key=None, kind="event"),
    "dead_cat_bounce_inverted": _meta(part=2, chapter=55, name="Dead-Cat Bounce (Inverted)", spec_key=None, kind="event"),
}


def base_metadata_for_pattern_set(pattern_set: str) -> Dict[str, Dict[str, Any]]:
    ps = str(pattern_set or "").strip()
    if ps == "bulkowski_53":
        return dict(BULKOWSKI_53_META)
    if ps == "bulkowski_53_strict":
        return dict(BULKOWSKI_53_META)
    if ps in ("bulkowski_strict_ohlcv", "bulkowski_49_strict_ohlcv"):
        out = dict(BULKOWSKI_53_META)
        out.update(EVENT_OHLCV_META)
        return out
    if ps == "event_ohlcv":
        return dict(EVENT_OHLCV_META)
    if ps == "bulkowski_55_ohlcv":
        out = dict(BULKOWSKI_53_META)
        out.update(EVENT_OHLCV_META)
        return out
    # digitized (26) and any future sets: metadata may be computed elsewhere
    return {}


def _safe_int(x: Any) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return None


def _safe_float(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except Exception:
        return None
    return v if v == v else None  # NaN guard


def _find_spec(scanner: Any) -> Optional[Dict[str, Any]]:
    """
    Try to retrieve an underlying `spec` dict from wrapper scanners.

    Supports:
      - BaseDigitizedScanner / PivotSequenceScanner (has `.spec`)
      - _CachedScanner (has `._scanner`)
      - _DerivedScanner (has `._base`)
    """
    if scanner is None:
        return None
    spec = getattr(scanner, "spec", None)
    if isinstance(spec, dict):
        return spec
    inner = getattr(scanner, "_scanner", None)
    if inner is not None:
        s = _find_spec(inner)
        if s is not None:
            return s
    base = getattr(scanner, "_base", None)
    if base is not None:
        s = _find_spec(base)
        if s is not None:
            return s
    return None


def build_pattern_metadata(
    *,
    pattern_set: str,
    scanners: Dict[str, Any],
    patterns: Optional[list[str]] = None,
    version: str = "pattern_meta_v1",
) -> Dict[str, Any]:
    """
    Build metadata payload to persist into `scanner_runs.run_config_json`.

    Returns:
      {
        "version": "...",
        "pattern_set": "...",
        "patterns": { pattern_key: {...meta...}, ... }
      }
    """
    base = base_metadata_for_pattern_set(pattern_set)
    keys = list(patterns) if patterns is not None else list(scanners.keys())

    out: Dict[str, Dict[str, Any]] = {}
    for key in sorted(set(keys)):
        m = dict(base.get(key, {}))
        m.setdefault("pattern_key", str(key))
        if str(pattern_set or "").strip() == "digitized" and m.get("spec_key") is None:
            m["spec_key"] = str(key)
        if not m.get("canonical_key"):
            m["canonical_key"] = str(m.get("spec_key") or key)
        m.setdefault("proxy", m.get("spec_key") is None)

        spec = _find_spec(scanners.get(key))
        geom = (spec.get("geometry_constraints") if isinstance(spec, dict) else None) or {}
        if isinstance(geom, dict) and geom:
            m.setdefault("width_min_bars", _safe_int(geom.get("width_min_bars")))
            m.setdefault("width_max_bars", _safe_int(geom.get("width_max_bars")))
            m.setdefault("height_min_pct", _safe_float(geom.get("height_ratio_min")))
            m.setdefault("height_max_pct", _safe_float(geom.get("height_ratio_max")))

        out[str(key)] = m

    return {"version": str(version), "pattern_set": str(pattern_set), "patterns": out}
