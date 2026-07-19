"""
Build a Bulkowski reference pack for the double-bottoms / double-tops family.

This pack is intentionally research-first:
  - keep Bulkowski chapter/variant taxonomy as the reference benchmark
  - summarize the current scanner implementation as a family detector plus
    variant resolver
  - expose where current VN metrics drift from the reference baseline

Outputs:
  - double_family_reference.json
  - double_family_reference.md
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any, Dict, Iterable, List, Optional

try:
    from .pattern_set_metadata import BULKOWSKI_53_META  # type: ignore
except ImportError:  # pragma: no cover
    from pattern_set_metadata import BULKOWSKI_53_META  # type: ignore


FAMILY_DEFS: Dict[str, Dict[str, Any]] = {
    "double_bottoms": {
        "title": "Double Bottoms",
        "direction": "up",
        "chapter_range": "13-16",
        "raw_key": "double_bottoms",
        "spec_key": "double_bottoms",
        "variant_order": ["AA", "AE", "EA", "EE"],
        "variant_pattern_keys": {
            "AA": "double_bottoms_adam_adam",
            "AE": "double_bottoms_adam_eve",
            "EA": "double_bottoms_eve_adam",
            "EE": "double_bottoms_eve_eve",
        },
        "move_key": "average_rise_pct",
        "move_label": "rise",
        "time_key": "time_to_ultimate_high_days",
        "return_rate_key": "pullback_rate_pct",
        "return_label": "pullback",
        "family_detector_ref": "scanner/digitized_pattern_engine.py:2792",
        "variant_resolver_ref": "scanner/digitized_pattern_engine.py:2795",
        "post_breakout_ref": "scanner/post_breakout_analyzer.py:949",
    },
    "double_tops": {
        "title": "Double Tops",
        "direction": "down",
        "chapter_range": "17-20",
        "raw_key": "double_tops",
        "spec_key": "double_tops",
        "variant_order": ["AA", "AE", "EA", "EE"],
        "variant_pattern_keys": {
            "AA": "double_tops_adam_adam",
            "AE": "double_tops_adam_eve",
            "EA": "double_tops_eve_adam",
            "EE": "double_tops_eve_eve",
        },
        "move_key": "average_decline_pct",
        "move_label": "decline",
        "time_key": "time_to_ultimate_low_days",
        "return_rate_key": "throwback_rate_pct",
        "return_label": "throwback",
        "family_detector_ref": "scanner/digitized_pattern_engine.py:2818",
        "variant_resolver_ref": "scanner/digitized_pattern_engine.py:2821",
        "post_breakout_ref": "scanner/post_breakout_analyzer.py:1191",
    },
}


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True, ensure_ascii=False)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _safe_float(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except Exception:
        return None
    return v if v == v else None


def _fmt_pct(x: Any) -> str:
    v = _safe_float(x)
    return "" if v is None else f"{v:.2f}"


def _load_visual_review_map(path: Optional[Path]) -> Dict[str, Dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    try:
        rows = _read_json(path)
    except Exception:
        return {}
    if not isinstance(rows, list):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        pattern_key = str(row.get("pattern_key") or "").strip()
        if not pattern_key:
            continue
        out[pattern_key] = dict(row)
    return out


def _load_status_map(path: Optional[Path]) -> Dict[str, str]:
    if path is None or not path.exists():
        return {}
    try:
        rows = _read_json(path)
    except Exception:
        return {}
    if not isinstance(rows, list):
        return {}
    out: Dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        pattern_key = str(row.get("pattern_key") or "").strip()
        status = str(row.get("status") or "").strip()
        if pattern_key and status:
            out[pattern_key] = status
    return out


def _latest_run_id(db_path: Path) -> str:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT run_id FROM scanner_runs ORDER BY created_at DESC LIMIT 1").fetchone()
        if not row:
            raise SystemExit(f"No scanner_runs in {db_path}")
        return str(row[0])
    finally:
        conn.close()


def _pattern_rows_for_run(db_path: Path, run_id: str) -> Dict[str, Dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    try:
        detections: Dict[str, Dict[str, Any]] = {}
        for pat, det, conf in conn.execute(
            """
            SELECT
                pattern_name,
                COUNT(*) AS detections,
                SUM(CASE WHEN breakout_date IS NOT NULL AND breakout_price IS NOT NULL THEN 1 ELSE 0 END) AS confirmed
            FROM pattern_detections
            WHERE run_id = ? AND pattern_name LIKE 'double_%'
            GROUP BY pattern_name
            """,
            (run_id,),
        ).fetchall():
            detections[str(pat)] = {
                "detections": int(det or 0),
                "confirmed": int(conf or 0),
            }

        evals: Dict[str, List[tuple[Any, Any, Any]]] = {}
        for pat, mfe, boundary, target in conn.execute(
            """
            SELECT
                pattern_name,
                max_favorable_excursion_pct,
                boundary_invalidated,
                target_achieved_intraday
            FROM post_breakout_results
            WHERE run_id = ? AND pattern_name LIKE 'double_%'
            """,
            (run_id,),
        ).fetchall():
            evals.setdefault(str(pat), []).append((mfe, boundary, target))

        out: Dict[str, Dict[str, Any]] = {}
        for pat in sorted(set(detections) | set(evals)):
            base = dict(detections.get(pat, {}))
            rows = evals.get(pat, [])
            moves = [_safe_float(r[0]) for r in rows if _safe_float(r[0]) is not None]
            boundary = [_safe_float(r[1]) for r in rows if _safe_float(r[1]) is not None]
            target = [_safe_float(r[2]) for r in rows if _safe_float(r[2]) is not None]
            base["evals"] = len(rows)
            base["median_move_pct"] = float(median(moves)) if moves else None
            base["failure_rate_5pct"] = (sum(1 for x in moves if float(x) < 5.0) / len(moves) * 100.0) if moves else None
            base["boundary_pct"] = (sum(float(x) for x in boundary) / len(boundary) * 100.0) if boundary else None
            base["target_hit_pct"] = (sum(float(x) for x in target) / len(target) * 100.0) if target else None
            out[pat] = base
        return out
    finally:
        conn.close()


def _aggregate_rows(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    row_list = [dict(r) for r in rows]
    out: Dict[str, Any] = {
        "detections": sum(int(r.get("detections") or 0) for r in row_list),
        "confirmed": sum(int(r.get("confirmed") or 0) for r in row_list),
        "evals": sum(int(r.get("evals") or 0) for r in row_list),
    }
    move_samples: List[float] = []
    for r in row_list:
        v = _safe_float(r.get("median_move_pct"))
        n = int(r.get("evals") or 0)
        if v is not None and n > 0:
            move_samples.extend([float(v)] * n)
    if move_samples:
        out["median_move_pct"] = float(median(move_samples))
        out["failure_rate_5pct_proxy"] = (
            sum(int(r.get("evals") or 0) * float(r.get("failure_rate_5pct") or 0.0) for r in row_list if r.get("failure_rate_5pct") is not None)
            / max(1, out["evals"])
        )
        out["boundary_pct_proxy"] = (
            sum(int(r.get("evals") or 0) * float(r.get("boundary_pct") or 0.0) for r in row_list if r.get("boundary_pct") is not None)
            / max(1, out["evals"])
        )
        out["target_hit_pct_proxy"] = (
            sum(int(r.get("evals") or 0) * float(r.get("target_hit_pct") or 0.0) for r in row_list if r.get("target_hit_pct") is not None)
            / max(1, out["evals"])
        )
    else:
        out["median_move_pct"] = None
        out["failure_rate_5pct_proxy"] = None
        out["boundary_pct_proxy"] = None
        out["target_hit_pct_proxy"] = None
    return out


def _family_detector_summary(spec: Dict[str, Any]) -> Dict[str, Any]:
    ds = (spec.get("detection_signature") or {}) if isinstance(spec, dict) else {}
    geom = (spec.get("geometry_constraints") or {}) if isinstance(spec, dict) else {}
    prior = (spec.get("prior_trend_requirements") or {}) if isinstance(spec, dict) else {}
    breakout = (spec.get("breakout_confirmation") or {}) if isinstance(spec, dict) else {}
    measure = (spec.get("post_breakout_measurement") or {}) if isinstance(spec, dict) else {}
    time_between = geom.get("time_between_bottoms") or geom.get("time_between_tops") or {}
    return {
        "pattern_type": spec.get("pattern_type"),
        "pivot_sequence": ds.get("pivot_sequence"),
        "prior_trend_direction": prior.get("direction"),
        "prior_trend_min_change_pct": prior.get("min_change_pct"),
        "prior_trend_min_period_bars": prior.get("min_period_bars"),
        "width_min_bars": geom.get("width_min_bars"),
        "width_max_bars": geom.get("width_max_bars"),
        "width_optimal_bars": geom.get("width_optimal_bars"),
        "height_min_pct": geom.get("height_ratio_min"),
        "height_max_pct": geom.get("height_ratio_max"),
        "near_equal_tolerance_pct": geom.get("near_equal_tolerance_pct"),
        "time_between_extremes": time_between,
        "breakout_direction": breakout.get("breakout_direction"),
        "breakout_threshold_pct": breakout.get("breakout_threshold_pct"),
        "breakout_volume_required": breakout.get("volume_required"),
        "target_formula": ((measure.get("target_calculation") or {}).get("formula")),
    }


def _raw_variant_schema(raw_spec: Dict[str, Any]) -> Dict[str, Any]:
    variants = ((raw_spec.get("structural_spec") or {}).get("variants")) if isinstance(raw_spec, dict) else None
    schema_type = type(variants).__name__
    return {
        "type": schema_type,
        "value": variants,
        "structured": isinstance(variants, dict),
    }


def _benchmark_summary(spec: Dict[str, Any], family: Dict[str, Any]) -> Dict[str, Any]:
    perf = (spec.get("performance_statistics") or {}) if isinstance(spec, dict) else {}
    move_key = str(family["move_key"])
    return {
        "overall_move_pct": perf.get(move_key),
        "median_move_pct": perf.get(f"median_{family['move_label']}_pct"),
        "failure_rate_5pct": perf.get("failure_rate_5pct"),
        "failure_rate_10pct": perf.get("failure_rate_10pct"),
        "time_to_outcome_days": perf.get(family["time_key"]),
        "return_rate_pct": perf.get(family["return_rate_key"]),
        "best_variant": perf.get("best_variant"),
        "worst_variant": perf.get("worst_variant"),
        "height_effect": perf.get("height_effect"),
        "width_effect": perf.get("width_effect"),
    }


def _variant_benchmarks(
    *,
    family_key: str,
    family_cfg: Dict[str, Any],
    spec: Dict[str, Any],
    calib_metrics: Dict[str, Dict[str, Any]],
    valid_metrics: Dict[str, Dict[str, Any]],
    visual_review: Dict[str, Dict[str, Any]],
    status_map: Dict[str, str],
) -> List[Dict[str, Any]]:
    variants = (((spec.get("variant_handling") or {}).get("variants")) or []) if isinstance(spec, dict) else []
    variant_by_code = {str(v.get("name")): dict(v) for v in variants if isinstance(v, dict) and v.get("name")}
    avg_section = (((spec.get("post_breakout_measurement") or {}).get(f"average_{family_cfg['move_label']}")) or {})
    out: List[Dict[str, Any]] = []
    for code in family_cfg["variant_order"]:
        pat = family_cfg["variant_pattern_keys"][code]
        meta = dict(BULKOWSKI_53_META.get(pat, {}))
        spec_variant = variant_by_code.get(code, {})
        current_valid = dict(valid_metrics.get(pat, {}))
        current_calib = dict(calib_metrics.get(pat, {}))
        review = visual_review.get(pat, {})
        variant_perf_key = f"{str(code).lower()}_variant_pct"
        out.append(
            {
                "variant_code": code,
                "pattern_key": pat,
                "chapter": meta.get("bulkowski_chapter"),
                "bulkowski_name": meta.get("bulkowski_name"),
                "description": spec_variant.get("description"),
                "detection_rules": spec_variant.get("detection_rules"),
                "parameter_overrides": spec_variant.get("parameter_overrides"),
                "bulkowski_reference": {
                    "average_move_pct": avg_section.get(variant_perf_key),
                    "failure_rate_pct": ((spec_variant.get("parameter_overrides") or {}).get("failure_rate_pct")),
                },
                "valid_metrics": current_valid,
                "calib_metrics": current_calib,
                "audit_status": status_map.get(pat),
                "visual_review": review or None,
            }
        )
    return out


def _threshold_mismatch_notes(spec: Dict[str, Any]) -> List[str]:
    notes: List[str] = []
    edge_cases = ((spec.get("test_fixtures") or {}).get("edge_cases")) or []
    for row in edge_cases:
        if not isinstance(row, dict):
            continue
        if str(row.get("name") or "") != "variant_boundary_case":
            continue
        rule = str(row.get("threshold_rule") or "").strip()
        if rule:
            notes.append(f"fixture threshold rule: {rule}")
    if notes:
        notes.append("current scanner/analyzer logic classifies Adam if width<=3 and Eve if width>=7, leaving widths 4-6 unresolved")
    return notes


def build_reference_pack(
    *,
    calib_db: Path,
    valid_db: Path,
    extraction_dir: Path,
    out_dir: Path,
    audit_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    calib_run_id = _latest_run_id(calib_db)
    valid_run_id = _latest_run_id(valid_db)
    calib_metrics = _pattern_rows_for_run(calib_db, calib_run_id)
    valid_metrics = _pattern_rows_for_run(valid_db, valid_run_id)

    raw_dir = extraction_dir / "patterns"
    digitized_dir = extraction_dir / "digitization" / "patterns_digitized"

    visual_review = _load_visual_review_map((audit_dir / "visual_review_round1.json") if audit_dir else None)
    status_map = _load_status_map((audit_dir / "recalibration_matrix.json") if audit_dir else None)

    families: List[Dict[str, Any]] = []
    for family_key, family_cfg in FAMILY_DEFS.items():
        raw_spec = _read_json(raw_dir / f"{family_cfg['raw_key']}.json")
        digitized_spec = _read_json(digitized_dir / f"{family_cfg['spec_key']}_digitized.json")
        variant_rows = _variant_benchmarks(
            family_key=family_key,
            family_cfg=family_cfg,
            spec=digitized_spec,
            calib_metrics=calib_metrics,
            valid_metrics=valid_metrics,
            visual_review=visual_review,
            status_map=status_map,
        )
        valid_family = _aggregate_rows([v["valid_metrics"] for v in variant_rows])
        calib_family = _aggregate_rows([v["calib_metrics"] for v in variant_rows])
        verdict_counts = Counter(
            str((v.get("visual_review") or {}).get("verdict"))
            for v in variant_rows
            if isinstance(v.get("visual_review"), dict) and (v.get("visual_review") or {}).get("verdict")
        )

        families.append(
            {
                "family_key": family_key,
                "title": family_cfg["title"],
                "direction": family_cfg["direction"],
                "chapter_range": family_cfg["chapter_range"],
                "base_spec_key": family_cfg["spec_key"],
                "bulkowski_reference_role": "reference_research_baseline",
                "current_scanner_role": "family_detector_plus_variant_resolver",
                "implementation_refs": {
                    "family_detector": family_cfg["family_detector_ref"],
                    "variant_resolver": family_cfg["variant_resolver_ref"],
                    "post_breakout_analyzer": family_cfg["post_breakout_ref"],
                },
                "raw_variant_schema": _raw_variant_schema(raw_spec),
                "family_detector_baseline": _family_detector_summary(digitized_spec),
                "benchmark_summary": _benchmark_summary(digitized_spec, family_cfg),
                "variant_benchmarks": variant_rows,
                "current_metrics": {
                    "valid": valid_family,
                    "calib": calib_family,
                },
                "current_variant_thresholds": {
                    "adam_max_width_bars": 3,
                    "eve_min_width_bars": 7,
                    "classification_gap_widths": [4, 5, 6],
                    "notes": _threshold_mismatch_notes(digitized_spec),
                },
                "visual_review_summary": {
                    "reviewed_variants": sum(1 for v in variant_rows if v.get("visual_review")),
                    "verdict_counts": dict(verdict_counts),
                },
                "recommended_architecture": {
                    "family_detector_outputs": [
                        "family_key",
                        "pivot_indices",
                        "neckline_price",
                        "pattern_width_bars",
                        "pattern_height_pct",
                        "breakout_direction",
                        "family_confidence",
                    ],
                    "variant_resolver_inputs": [
                        "first_extreme_width_bars",
                        "second_extreme_width_bars",
                        "first_extreme_shape_score",
                        "second_extreme_shape_score",
                        "liquidity_noise_flags",
                    ],
                    "variant_resolver_outputs": [
                        "variant_code",
                        "variant_confidence",
                        "variant_evidence",
                    ],
                },
                "recommended_next_actions": [
                    "Persist and evaluate family-level detector quality before splitting variants.",
                    "Move Adam/Eve classification into an explicit resolver with evidence and confidence.",
                    "Replace hardcoded width-only thresholds with spec-backed shape measurements plus fixtures.",
                    "Rerun calib/valid at the family level, then re-audit only the best 3-5 samples per variant.",
                ],
            }
        )

    summary = {
        "goal": "Use Bulkowski as quantitative baseline while refactoring the scanner around canonical double-pattern families.",
        "calib_run_id": calib_run_id,
        "valid_run_id": valid_run_id,
        "families": [f["family_key"] for f in families],
    }
    payload = {"summary": summary, "families": families}
    _write_json(out_dir / "double_family_reference.json", payload)
    _write_text(out_dir / "double_family_reference.md", _render_markdown(payload))
    return payload


def _render_markdown(payload: Dict[str, Any]) -> str:
    summary = payload["summary"]
    families = payload["families"]
    lines: List[str] = []
    lines.append("# Double Family Reference Pack")
    lines.append("")
    lines.append("## Intent")
    lines.append("")
    lines.append(
        "Bulkowski được xem là baseline nghiên cứu định lượng cho họ double bottoms / double tops. "
        "Pack này tách rõ family detector với variant resolver, nhưng vẫn giữ chapter/variant taxonomy của Bulkowski "
        "làm chuẩn tham chiếu để đánh giá scanner."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- calib_run_id: `{summary['calib_run_id']}`")
    lines.append(f"- valid_run_id: `{summary['valid_run_id']}`")
    lines.append(f"- families: `{', '.join(summary['families'])}`")
    lines.append("")

    for fam in families:
        lines.append(f"## {fam['title']}")
        lines.append("")
        lines.append(f"- chapter_range: `{fam['chapter_range']}`")
        lines.append(f"- base_spec_key: `{fam['base_spec_key']}`")
        lines.append(f"- family_detector: `{fam['implementation_refs']['family_detector']}`")
        lines.append(f"- variant_resolver: `{fam['implementation_refs']['variant_resolver']}`")
        lines.append(f"- post_breakout_analyzer: `{fam['implementation_refs']['post_breakout_analyzer']}`")
        lines.append("")
        lines.append("### Detector Baseline")
        lines.append("")
        lines.append("| Field | Value |")
        lines.append("|---|---|")
        for key in [
            "pivot_sequence",
            "prior_trend_direction",
            "prior_trend_min_change_pct",
            "prior_trend_min_period_bars",
            "width_min_bars",
            "width_max_bars",
            "width_optimal_bars",
            "height_min_pct",
            "height_max_pct",
            "near_equal_tolerance_pct",
            "breakout_direction",
            "breakout_threshold_pct",
            "target_formula",
        ]:
            lines.append(f"| {key} | {fam['family_detector_baseline'].get(key)} |")
        lines.append("")
        lines.append("### Benchmark vs Current VN Metrics")
        lines.append("")
        lines.append("| Layer | Evals | MedianMove% | Fail<5% | Boundary% | TgtHit% |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        valid = fam["current_metrics"]["valid"]
        lines.append(
            "| current_valid_family | "
            + " | ".join(
                [
                    str(int(valid.get("evals") or 0)),
                    _fmt_pct(valid.get("median_move_pct")),
                    _fmt_pct(valid.get("failure_rate_5pct_proxy")),
                    _fmt_pct(valid.get("boundary_pct_proxy")),
                    _fmt_pct(valid.get("target_hit_pct_proxy")),
                ]
            )
            + " |"
        )
        lines.append(
            "| bulkowski_reference | "
            + " | ".join(
                [
                    "",
                    _fmt_pct(fam["benchmark_summary"].get("overall_move_pct")),
                    _fmt_pct(fam["benchmark_summary"].get("failure_rate_5pct")),
                    "",
                    "",
                ]
            )
            + " |"
        )
        lines.append("")
        lines.append("### Variant Matrix")
        lines.append("")
        lines.append("| Variant | Pattern | RefMove% | RefFail% | Valid evals | Valid medMove% | Visual | Audit status |")
        lines.append("|---|---|---:|---:|---:|---:|---|---|")
        for row in fam["variant_benchmarks"]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row["variant_code"]),
                        str(row["pattern_key"]),
                        _fmt_pct((row["bulkowski_reference"] or {}).get("average_move_pct")),
                        _fmt_pct((row["bulkowski_reference"] or {}).get("failure_rate_pct")),
                        str(int((row["valid_metrics"] or {}).get("evals") or 0)),
                        _fmt_pct((row["valid_metrics"] or {}).get("median_move_pct")),
                        str(((row.get("visual_review") or {}).get("verdict")) or ""),
                        str(row.get("audit_status") or ""),
                    ]
                )
                + " |"
            )
        lines.append("")
        lines.append("### Refactor Notes")
        lines.append("")
        for note in fam["current_variant_thresholds"]["notes"]:
            lines.append(f"- {note}")
        for note in fam["recommended_next_actions"]:
            lines.append(f"- {note}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calib-db", required=True)
    parser.add_argument("--valid-db", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--extraction-dir", default="extraction_phase_1")
    parser.add_argument("--audit-dir")
    args = parser.parse_args()

    audit_dir = Path(args.audit_dir).resolve() if args.audit_dir else None
    payload = build_reference_pack(
        calib_db=Path(args.calib_db).resolve(),
        valid_db=Path(args.valid_db).resolve(),
        extraction_dir=Path(args.extraction_dir).resolve(),
        out_dir=Path(args.out_dir).resolve(),
        audit_dir=audit_dir,
    )
    print("=== Double Family Reference Pack ===")
    print(f"out_dir: {Path(args.out_dir).resolve()}")
    print(f"families: {', '.join(payload['summary']['families'])}")
    print(f"valid_run_id: {payload['summary']['valid_run_id']}")


if __name__ == "__main__":
    main()
