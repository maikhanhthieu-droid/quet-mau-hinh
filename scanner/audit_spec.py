"""
Spec audit workflow for Bulkowski-derived pattern research.

This script treats the project as a research pipeline first:
  1) static fidelity between extracted source specs and digitized scanner specs
  2) sample-based visual review queue generation
  3) recalibration / strategy-retirement triage

It writes a reusable audit pack (Markdown + JSON) that can guide future
digitization fixes, manual review, and strategy-layer gating.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Dict, Iterable, List, Optional


RAW_SOURCE_BY_SPEC_KEY: Dict[str, Optional[str]] = {
    "broadening_bottoms": "broadening_bottoms",
    "broadening_formations_right_angled_ascending": None,
    "broadening_formations_right_angled_descending": None,
    "broadening_tops": "broadening_tops",
    "broadening_wedges": "broadening_wedges",
    "bump_and_run_reversal": "bump_and_run_reversal",
    "cup_with_handle": "cup_with_handle",
    "diamond_bottom": None,
    "diamond_top": None,
    "double_bottoms": "double_bottoms",
    "double_tops": "double_tops",
    "flags": "flags",
    "gaps": "gaps",
    "head_and_shoulders_bottom": "head_and_shoulders",
    "head_and_shoulders_top": "head_and_shoulders",
    "horn_bottoms_tops": "horn_bottoms_tops",
    "inside_day": "inside_day",
    "islands": "islands",
    "measured_move_down_up": "measured_move_down_up",
    "pennants": "pennants",
    "pipe_bottoms": "pipe_bottoms",
    "rectangle_bottoms_tops": "rectangle_bottoms_tops",
    "rising_falling_three_methods": "rising_falling_three_methods",
    "rounding_bottoms_tops": "rounding_bottoms_tops",
    "scallop_ascending_descending": "scallop_ascending_descending",
    "spike_formation": "spike_formation",
    "three_falling_peaks": None,
    "three_rising_valleys": None,
    "triangles": "triangles",
    "triple_bottoms_tops": "triple_bottoms_tops",
    "wedges_ascending_descending": "wedges_ascending_descending",
}

VARIANT_NAME_BY_CODE: Dict[str, str] = {
    "AA": "adam_and_adam",
    "AE": "adam_and_eve",
    "EA": "eve_and_adam",
    "EE": "eve_and_eve",
}


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True, default=str, ensure_ascii=False)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _safe_float(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except Exception:
        return None
    if v != v:
        return None
    return v


def _base_name(s: Any) -> str:
    text = str(s or "").strip()
    if not text:
        return ""
    text = text.split(" (", 1)[0].strip()
    text = text.split(",", 1)[0].strip()
    return text


def _slugify(s: Any) -> str:
    text = str(s or "").lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def _latest_run_payload(results_db_path: Path) -> tuple[str, Dict[str, Any]]:
    conn = sqlite3.connect(str(results_db_path))
    try:
        row = conn.execute(
            "SELECT run_id, run_config_json FROM scanner_runs ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            raise SystemExit(f"No scanner_runs found in {results_db_path}")
        run_id = str(row[0])
        run_cfg = json.loads(row[1]) if row[1] else {}
        return run_id, run_cfg if isinstance(run_cfg, dict) else {}
    finally:
        conn.close()


def _load_metrics(results_db_path: Path) -> tuple[str, Dict[str, Dict[str, Any]]]:
    conn = sqlite3.connect(str(results_db_path))
    try:
        run_id = conn.execute("SELECT run_id FROM scanner_runs ORDER BY created_at DESC LIMIT 1").fetchone()[0]

        detections: Dict[str, Dict[str, Any]] = {}
        for pat, det, conf in conn.execute(
            """
            SELECT
                pattern_name,
                COUNT(*) AS detections,
                SUM(CASE WHEN breakout_date IS NOT NULL AND breakout_price IS NOT NULL THEN 1 ELSE 0 END) AS confirmed
            FROM pattern_detections
            WHERE run_id = ?
            GROUP BY pattern_name
            """,
            (run_id,),
        ).fetchall():
            detections[str(pat)] = {
                "detections": int(det or 0),
                "confirmed": int(conf or 0),
            }

        eval_rows: Dict[str, List[tuple[Any, Any, Any, Any]]] = defaultdict(list)
        for row in conn.execute(
            """
            SELECT
                pattern_name,
                max_favorable_excursion_pct,
                boundary_invalidated,
                target_achieved_intraday,
                throwback_pullback_occurred
            FROM post_breakout_results
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchall():
            eval_rows[str(row[0])].append(row[1:])

        out: Dict[str, Dict[str, Any]] = {}
        for pat in sorted(set(detections) | set(eval_rows)):
            base = dict(detections.get(pat, {}))
            rows = eval_rows.get(pat, [])
            moves = [_safe_float(r[0]) for r in rows if _safe_float(r[0]) is not None]
            boundary = [_safe_float(r[1]) for r in rows if _safe_float(r[1]) is not None]
            target = [_safe_float(r[2]) for r in rows if _safe_float(r[2]) is not None]
            tbpb = [_safe_float(r[3]) for r in rows if _safe_float(r[3]) is not None]

            base["evals"] = len(rows)
            base["median_move_pct"] = float(median(moves)) if moves else None
            base["failure_rate_5pct"] = (sum(1 for x in moves if float(x) < 5.0) / len(moves) * 100.0) if moves else None
            base["boundary_pct"] = (sum(float(x) for x in boundary) / len(boundary) * 100.0) if boundary else None
            base["target_hit_pct"] = (sum(float(x) for x in target) / len(target) * 100.0) if target else None
            base["tbpb_pct"] = (sum(float(x) for x in tbpb) / len(tbpb) * 100.0) if tbpb else None
            out[pat] = base
        return str(run_id), out
    finally:
        conn.close()


def _metrics_for(metrics: Dict[str, Dict[str, Any]], pattern_key: str) -> Dict[str, Any]:
    return dict(metrics.get(str(pattern_key), {}))


def _instability_flags(calib: Dict[str, Any], valid: Dict[str, Any]) -> List[str]:
    flags: List[str] = []
    if int(calib.get("evals") or 0) < 20 or int(valid.get("evals") or 0) < 20:
        return flags

    move_c = _safe_float(calib.get("median_move_pct"))
    move_v = _safe_float(valid.get("median_move_pct"))
    if move_c is not None and move_v is not None and abs(move_v - move_c) >= 5.0:
        flags.append("move_drift")

    fail_c = _safe_float(calib.get("failure_rate_5pct"))
    fail_v = _safe_float(valid.get("failure_rate_5pct"))
    if fail_c is not None and fail_v is not None and abs(fail_v - fail_c) >= 10.0:
        flags.append("fail5_drift")

    tgt_c = _safe_float(calib.get("target_hit_pct"))
    tgt_v = _safe_float(valid.get("target_hit_pct"))
    if tgt_c is not None and tgt_v is not None and abs(tgt_v - tgt_c) >= 15.0:
        flags.append("target_drift")

    return flags


def _status_for(
    static_flags: List[str],
    calib: Dict[str, Any],
    valid: Dict[str, Any],
    instability_flags: List[str],
) -> str:
    valid_evals = int(valid.get("evals") or 0)
    calib_evals = int(calib.get("evals") or 0)
    fail5 = _safe_float(valid.get("failure_rate_5pct"))
    boundary = _safe_float(valid.get("boundary_pct"))
    target = _safe_float(valid.get("target_hit_pct"))

    weak_signals = 0
    if fail5 is not None and fail5 > 35.0:
        weak_signals += 1
    if boundary is not None and boundary > 60.0:
        weak_signals += 1
    if target is not None and target < 40.0:
        weak_signals += 1

    if valid_evals == 0 and calib_evals <= 5:
        return "retire_from_strategy"
    if valid_evals < 20:
        return "research_only"
    if len(static_flags) >= 2 or len(instability_flags) >= 2 or weak_signals >= 2:
        return "recalibrate"
    if valid_evals >= 50 and len(static_flags) <= 1 and len(instability_flags) <= 1:
        if (fail5 is None or fail5 <= 30.0) and (boundary is None or boundary <= 55.0) and (target is None or target >= 50.0):
            return "candidate_after_review"
    return "research_only"


def _priority_score(
    *,
    static_flags: List[str],
    calib: Dict[str, Any],
    valid: Dict[str, Any],
    instability_flags: List[str],
    figures_count: int,
) -> int:
    score = 0
    score += len(static_flags) * 3
    score += len(instability_flags) * 2

    valid_evals = int(valid.get("evals") or 0)
    calib_evals = int(calib.get("evals") or 0)
    if valid_evals == 0:
        score += 5
    elif valid_evals < 10:
        score += 4
    elif valid_evals < 50:
        score += 2

    fail5 = _safe_float(valid.get("failure_rate_5pct"))
    boundary = _safe_float(valid.get("boundary_pct"))
    target = _safe_float(valid.get("target_hit_pct"))
    if fail5 is not None and fail5 > 35.0:
        score += 2
    if boundary is not None and boundary > 60.0:
        score += 2
    if target is not None and target < 40.0:
        score += 2

    if calib_evals == 0:
        score += 1
    if figures_count == 0:
        score += 1
    return score


def _raw_variant_supported(raw_obj: Dict[str, Any], variant_code: Optional[str]) -> bool:
    if not variant_code:
        return True
    variants = ((raw_obj.get("structural_spec") or {}).get("variants") or {}) if isinstance(raw_obj, dict) else {}
    if not isinstance(variants, dict):
        return False
    return VARIANT_NAME_BY_CODE.get(str(variant_code)) in variants


def _label_differs(meta_name: str, spec_name: str) -> bool:
    a = _slugify(_base_name(meta_name))
    b = _slugify(_base_name(spec_name))
    return bool(a and b and a != b)


def _chapter_figure_paths(chapter_path: Path) -> List[str]:
    if not chapter_path.exists():
        return []
    try:
        text = chapter_path.read_text(encoding="utf-8")
    except Exception:
        return []

    matches = re.findall(r"!\[\]\((figures/[^)]+\.png)\)", text)
    seen: set[str] = set()
    out: List[str] = []
    book_dir = chapter_path.parent.parent
    for rel in matches:
        path = str((book_dir / rel).resolve())
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def _load_visual_review_map(path: Optional[Path]) -> Dict[str, Dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    try:
        payload = _read_json(path)
    except Exception:
        return {}
    if not isinstance(payload, list):
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        pattern_key = str(row.get("pattern_key") or "").strip()
        if not pattern_key:
            continue
        out[pattern_key] = dict(row)
    return out


def build_audit_pack(
    *,
    calib_db: Path,
    valid_db: Path,
    book_dir: Path,
    extraction_dir: Path,
    out_dir: Path,
    visual_review_file: Optional[Path] = None,
) -> Dict[str, Any]:
    valid_run_id, valid_cfg = _latest_run_payload(valid_db)
    calib_run_id, _ = _latest_run_payload(calib_db)

    meta_payload = valid_cfg.get("pattern_metadata") if isinstance(valid_cfg, dict) else None
    if not isinstance(meta_payload, dict):
        raise SystemExit("valid run_config_json is missing pattern_metadata")
    meta_map = meta_payload.get("patterns")
    if not isinstance(meta_map, dict):
        raise SystemExit("valid pattern_metadata.patterns missing")

    raw_dir = extraction_dir / "patterns"
    raw_map = {p.stem: _read_json(p) for p in raw_dir.glob("*.json")}

    digitized_dir = extraction_dir / "digitization" / "patterns_digitized"
    digitized_map = {p.name.replace("_digitized.json", ""): _read_json(p) for p in digitized_dir.glob("*_digitized.json")}

    valid_metrics_run_id, valid_metrics = _load_metrics(valid_db)
    calib_metrics_run_id, calib_metrics = _load_metrics(calib_db)
    visual_review_map = _load_visual_review_map(visual_review_file)

    spec_counter = Counter(str(m.get("spec_key") or "") for m in meta_map.values())
    canonical_counter = Counter(str(m.get("canonical_key") or "") for m in meta_map.values())

    case_dir = book_dir / "cases"
    chapter_dir = book_dir / "chapters"

    rows: List[Dict[str, Any]] = []
    for pattern_key, meta in sorted(meta_map.items(), key=lambda kv: (int(kv[1].get("bulkowski_chapter") or 10**9), kv[0])):
        if not isinstance(meta, dict):
            continue

        spec_key = str(meta.get("spec_key") or pattern_key)
        canonical_key = str(meta.get("canonical_key") or spec_key or pattern_key)
        raw_key = RAW_SOURCE_BY_SPEC_KEY.get(spec_key, spec_key if spec_key in raw_map else None)
        digitized = digitized_map.get(spec_key)
        raw_obj = raw_map.get(str(raw_key)) if raw_key else None

        spec_name = str((digitized or {}).get("pattern_name") or spec_key)
        raw_name = str((raw_obj or {}).get("pattern_name") or raw_key or "")
        variant = meta.get("variant")

        static_flags: List[str] = []
        if raw_obj is None:
            static_flags.append("raw_source_missing")
        if spec_counter.get(spec_key, 0) > 1:
            static_flags.append("shared_digitized_spec")
        if canonical_counter.get(canonical_key, 0) > 1:
            static_flags.append("shared_canonical_group")
        if digitized is not None and not (digitized.get("test_fixtures") or []):
            static_flags.append("no_test_fixtures")
        if digitized is not None and _label_differs(str(meta.get("bulkowski_name") or pattern_key), spec_name):
            static_flags.append("chapter_label_differs_from_spec")
        if raw_obj is not None and not _raw_variant_supported(raw_obj, str(variant) if variant is not None else None):
            static_flags.append("variant_not_explicit_in_raw_source")

        chapter_path = chapter_dir / f"chap_{int(meta.get('bulkowski_chapter') or 0):02d}_{pattern_key}.md"
        figure_paths = _chapter_figure_paths(chapter_path)
        cases_path = case_dir / f"{pattern_key}.json"
        case_count = 0
        if cases_path.exists():
            try:
                case_payload = _read_json(cases_path)
                case_count = len(case_payload) if isinstance(case_payload, list) else 0
            except Exception:
                case_count = 0

        calib = _metrics_for(calib_metrics, pattern_key)
        valid = _metrics_for(valid_metrics, pattern_key)
        instability = _instability_flags(calib, valid)
        status = _status_for(static_flags, calib, valid, instability)
        priority = _priority_score(
            static_flags=static_flags,
            calib=calib,
            valid=valid,
            instability_flags=instability,
            figures_count=len(figure_paths),
        )
        visual_review = visual_review_map.get(pattern_key) or {}

        rows.append(
            {
                "pattern_key": pattern_key,
                "chapter": int(meta.get("bulkowski_chapter") or 0),
                "bulkowski_name": str(meta.get("bulkowski_name") or pattern_key),
                "canonical_key": canonical_key,
                "spec_key": spec_key,
                "variant": variant,
                "raw_source_key": raw_key,
                "raw_pattern_name": raw_name,
                "digitized_pattern_name": spec_name,
                "static_flags": static_flags,
                "shared_spec_count": int(spec_counter.get(spec_key, 0)),
                "shared_canonical_count": int(canonical_counter.get(canonical_key, 0)),
                "static_risk_score": len(static_flags),
                "calib": calib,
                "valid": valid,
                "instability_flags": instability,
                "status": status,
                "visual_priority_score": int(priority),
                "chapter_path": str(chapter_path),
                "case_path": str(cases_path) if cases_path.exists() else None,
                "case_count": int(case_count),
                "figure_paths": figure_paths,
                "figure_count": len(figure_paths),
                "visual_review": visual_review or None,
                "visual_verdict": visual_review.get("verdict"),
                "visual_decision": visual_review.get("decision"),
                "visual_confidence": visual_review.get("confidence"),
                "visual_summary": visual_review.get("summary"),
            }
        )

    visual_queue = sorted(rows, key=lambda r: (-int(r["visual_priority_score"]), int(r["chapter"]), str(r["pattern_key"])))
    recalibration = sorted(
        rows,
        key=lambda r: (
            {"retire_from_strategy": 0, "recalibrate": 1, "research_only": 2, "candidate_after_review": 3}.get(str(r["status"]), 9),
            -int(r["visual_priority_score"]),
            int(r["chapter"]),
        ),
    )

    summary = {
        "goal": "Research fidelity to Bulkowski first; strategy-layer eligibility only after spec audit.",
        "valid_run_id": valid_run_id,
        "calib_run_id": calib_run_id,
        "valid_metrics_run_id": valid_metrics_run_id,
        "calib_metrics_run_id": calib_metrics_run_id,
        "chapter_patterns_total": len(rows),
        "digitized_specs_total": len(digitized_map),
        "raw_pattern_files_total": len(raw_map),
        "chapter_patterns_missing_raw_source": sum(1 for r in rows if "raw_source_missing" in r["static_flags"]),
        "chapter_patterns_using_shared_spec": sum(1 for r in rows if "shared_digitized_spec" in r["static_flags"]),
        "patterns_with_valid_evals": sum(1 for r in rows if int(r["valid"].get("evals") or 0) > 0),
        "patterns_without_valid_evals": sum(1 for r in rows if int(r["valid"].get("evals") or 0) == 0),
        "status_counts": dict(Counter(str(r["status"]) for r in rows)),
        "visual_reviewed_patterns": sum(1 for r in rows if r.get("visual_verdict")),
        "visual_verdict_counts": dict(Counter(str(r["visual_verdict"]) for r in rows if r.get("visual_verdict"))),
        "visual_review_file": str(visual_review_file) if visual_review_file and visual_review_map else None,
    }

    payload = {
        "summary": summary,
        "rows": rows,
        "visual_review_queue": visual_queue,
        "recalibration_matrix": recalibration,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "summary.json", summary)
    _write_json(out_dir / "static_fidelity.json", rows)
    _write_json(out_dir / "visual_review_queue.json", visual_queue)
    _write_json(out_dir / "recalibration_matrix.json", recalibration)
    _write_text(out_dir / "spec_audit_report.md", _render_markdown(payload))
    return payload


def _fmt_pct(x: Any) -> str:
    v = _safe_float(x)
    return "" if v is None else f"{v:.2f}"


def _render_markdown(payload: Dict[str, Any]) -> str:
    summary = payload["summary"]
    rows = payload["rows"]
    visual_queue = payload["visual_review_queue"]
    recalibration = payload["recalibration_matrix"]

    lines: List[str] = []
    lines.append("# Spec Audit Pack")
    lines.append("")
    lines.append("## Audit Intent")
    lines.append("")
    lines.append(
        "Mục tiêu của audit này là bảo vệ trục nghiên cứu kế thừa ý tưởng từ Thomas Bulkowski: "
        "độ trung thành của spec và detector đứng trước mọi nhu cầu xuất bản tài liệu. "
        "Book/report chỉ là một hướng dùng lại; strategy layer chỉ được phép dùng subset pattern đã qua audit."
    )
    lines.append("")
    lines.append("## Three-Phase Plan")
    lines.append("")
    lines.append("1. `Static fidelity`")
    lines.append("   Đối chiếu chapter pattern -> canonical/spec key -> raw extraction -> digitized scanner spec. Gate của pha này là phải biết pattern nào đang dùng spec chia sẻ, pattern nào thiếu raw source trực tiếp, và pattern nào cần audit thủ công trước khi tin kết quả.")
    lines.append("2. `Sample-based visual review`")
    lines.append("   Review bằng mắt các detection/figure ưu tiên cao để xác nhận shape thực sự khớp với logic của Bulkowski, không chỉ khớp KPI. Gate của pha này là pattern phải có sample pass trước khi coi là ứng viên cho strategy layer.")
    lines.append("3. `Recalibration / retirement`")
    lines.append("   Dựa trên sample + KPI drift giữa calib/valid để chia pattern thành `candidate_after_review`, `recalibrate`, `research_only`, hoặc `retire_from_strategy`.")
    lines.append("")
    lines.append("## Executed Summary")
    lines.append("")
    lines.append(f"- valid_run_id: `{summary['valid_run_id']}`")
    lines.append(f"- calib_run_id: `{summary['calib_run_id']}`")
    lines.append(f"- chapter patterns: `{summary['chapter_patterns_total']}`")
    lines.append(f"- digitized specs: `{summary['digitized_specs_total']}`")
    lines.append(f"- raw extraction files: `{summary['raw_pattern_files_total']}`")
    lines.append(f"- chapter patterns missing direct raw source: `{summary['chapter_patterns_missing_raw_source']}`")
    lines.append(f"- chapter patterns using shared digitized spec: `{summary['chapter_patterns_using_shared_spec']}`")
    lines.append(f"- patterns without valid evals: `{summary['patterns_without_valid_evals']}`")
    lines.append(f"- status_counts: `{summary['status_counts']}`")
    if int(summary.get("visual_reviewed_patterns") or 0) > 0:
        lines.append(f"- visual reviewed patterns: `{summary['visual_reviewed_patterns']}`")
        lines.append(f"- visual verdict_counts: `{summary['visual_verdict_counts']}`")
    lines.append("")

    lines.append("## Phase 1: Static Fidelity")
    lines.append("")
    lines.append("| Chap | Pattern | Spec | Raw source | Static flags | Valid evals | Status |")
    lines.append("|---:|---|---|---|---|---:|---|")
    for row in sorted(rows, key=lambda r: (-int(r["static_risk_score"]), int(r["chapter"]), str(r["pattern_key"])))[:20]:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["chapter"]),
                    str(row["pattern_key"]),
                    str(row["spec_key"]),
                    str(row["raw_source_key"] or ""),
                    ", ".join(row["static_flags"]) if row["static_flags"] else "",
                    str(int(row["valid"].get("evals") or 0)),
                    str(row["status"]),
                ]
            )
            + " |"
        )
    lines.append("")

    lines.append("## Phase 2: Visual Review Queue")
    lines.append("")
    lines.append("| Rank | Chap | Pattern | Priority | Valid evals | Figures | Cases | Why review first |")
    lines.append("|---:|---:|---|---:|---:|---:|---:|---|")
    for i, row in enumerate(visual_queue[:20], start=1):
        reasons = row["static_flags"] + row["instability_flags"]
        if not reasons:
            reasons = [row["status"]]
        lines.append(
            "| "
            + " | ".join(
                [
                    str(i),
                    str(row["chapter"]),
                    str(row["pattern_key"]),
                    str(row["visual_priority_score"]),
                    str(int(row["valid"].get("evals") or 0)),
                    str(int(row["figure_count"] or 0)),
                    str(int(row["case_count"] or 0)),
                    ", ".join(reasons),
                ]
            )
            + " |"
        )
    lines.append("")

    reviewed_rows = [row for row in visual_queue if row.get("visual_verdict")]
    if reviewed_rows:
        lines.append("## Phase 2 Review Round 1")
        lines.append("")
        lines.append("| Pattern | Verdict | Decision | Notes |")
        lines.append("|---|---|---|---|")
        for row in reviewed_rows[:20]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row["pattern_key"]),
                        str(row.get("visual_verdict") or ""),
                        str(row.get("visual_decision") or ""),
                        str(row.get("visual_summary") or "").replace("\n", " ").strip(),
                    ]
                )
                + " |"
            )
        lines.append("")

    lines.append("## Phase 3: Recalibration / Retirement")
    lines.append("")
    lines.append("| Status | Chap | Pattern | Valid evals | Calib evals | Valid fail<5 | Valid boundary | Valid target |")
    lines.append("|---|---:|---|---:|---:|---:|---:|---:|")
    for row in recalibration[:25]:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["status"]),
                    str(row["chapter"]),
                    str(row["pattern_key"]),
                    str(int(row["valid"].get("evals") or 0)),
                    str(int(row["calib"].get("evals") or 0)),
                    _fmt_pct(row["valid"].get("failure_rate_5pct")),
                    _fmt_pct(row["valid"].get("boundary_pct")),
                    _fmt_pct(row["valid"].get("target_hit_pct")),
                ]
            )
            + " |"
        )
    lines.append("")

    lines.append("## Strategy Policy")
    lines.append("")
    lines.append("- `candidate_after_review`: được giữ làm ứng viên cho strategy layer, nhưng vẫn phải qua visual review.")
    lines.append("- `recalibrate`: chưa dùng cho tín hiệu mua/bán; ưu tiên sửa spec hoặc detector.")
    lines.append("- `research_only`: giữ cho nghiên cứu và scan khám phá, chưa đưa vào chiến lược.")
    lines.append("- `retire_from_strategy`: loại khỏi strategy layer cho tới khi có spec mới hoặc bằng chứng mới.")
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calib-db", required=True)
    parser.add_argument("--valid-db", required=True)
    parser.add_argument("--book-dir", required=True)
    parser.add_argument("--extraction-dir", default="extraction_phase_1")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--visual-review-file")
    args = parser.parse_args()

    visual_review_file: Optional[Path]
    if args.visual_review_file:
        visual_review_file = Path(args.visual_review_file).resolve()
    else:
        candidate = (Path(args.out_dir).resolve() / "visual_review_round1.json")
        visual_review_file = candidate if candidate.exists() else None

    payload = build_audit_pack(
        calib_db=Path(args.calib_db).resolve(),
        valid_db=Path(args.valid_db).resolve(),
        book_dir=Path(args.book_dir).resolve(),
        extraction_dir=Path(args.extraction_dir).resolve(),
        out_dir=Path(args.out_dir).resolve(),
        visual_review_file=visual_review_file,
    )

    summary = payload["summary"]
    print("=== Spec Audit Pack ===")
    print(f"out_dir: {Path(args.out_dir).resolve()}")
    print(f"chapter_patterns: {summary['chapter_patterns_total']}")
    print(f"missing_raw_source: {summary['chapter_patterns_missing_raw_source']}")
    print(f"shared_digitized_spec: {summary['chapter_patterns_using_shared_spec']}")
    print(f"status_counts: {summary['status_counts']}")
    print(f"visual_reviewed_patterns: {summary['visual_reviewed_patterns']}")


if __name__ == "__main__":
    main()
