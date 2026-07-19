"""Build the dual-axis governance matrix for final chapters.

The project now separates two claims that were previously easy to conflate:

1. publication/reference readiness: the chapter reads like a source-grounded
   Bulkowski-style reference entry.
2. tradable readiness: the pattern has an executable entry/exit/cost/sizing
   layer that passes the Bull Flag-style 95+ release gate.

This script does not infer missing tradable scores. A chapter without an
explicit tradable scorecard is marked `not_tested`, not failed.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Mapping


DEFAULT_MANIFEST = Path("artifacts/final_chapters/final_chapters_manifest.json")
DEFAULT_OUT_DIR = Path("artifacts/final_chapters/governance")
DEFAULT_PREFLIGHT_MATRIX = Path("artifacts/final_chapters/governance/chapter_tradable_preflight_matrix.json")
DEFAULT_GENERIC_TRADABLE_DIR = Path("artifacts/scanner_v2/chapter_tradable_layer")
DEFAULT_BRANCH_OPTIMIZATION_DIR = Path("artifacts/scanner_v2/chapter_branch_optimization")
DEFAULT_PRIORITY_OPTIMIZATION_DIR = Path("artifacts/scanner_v2/priority_candidate_tradable_optimization")
DUAL_AXIS_POLICY_ID = "dual_axis_chapter_scoring_v1"

LOCAL_BLOCKER_AUDITS: dict[str, list[Path]] = {
    "bear_flags": [
        Path("artifacts/scanner_v2/remaining_pattern_branch_ceiling_audit/bear_flags/bear_flags_branch_ceiling_audit.json"),
        Path("artifacts/scanner_v2/feature_filter_ceiling_push/bear_flags/bear_flags_feature_filter_push.json"),
        Path("artifacts/scanner_v2/pattern_specific_branch_redesign/bear_flags/bear_flags_branch_redesign.json"),
        Path("artifacts/scanner_v2/pattern_specific_fold_repair/bear_flags/bear_flags_fold_repair.json"),
        Path("artifacts/scanner_v2/pattern_specific_final_push/bear_flags/bear_flags_final_push.json"),
    ],
    "bull_pennants": [
        Path("artifacts/scanner_v2/bull_pennants_tradable_setup/bull_pennant_tradable_ceiling_audit/bull_pennant_tradable_ceiling_audit.json"),
    ],
    "triangles_ascending": [
        Path("artifacts/scanner_v2/ascending_triangle_tradable_blocker_audit/ascending_triangle_tradable_blocker_audit.json"),
        Path("artifacts/scanner_v2/feature_filter_ceiling_push/triangles_ascending/triangles_ascending_feature_filter_push.json"),
        Path("artifacts/scanner_v2/pattern_specific_branch_redesign/triangles_ascending/triangles_ascending_branch_redesign.json"),
        Path("artifacts/scanner_v2/pattern_specific_fold_repair/triangles_ascending/triangles_ascending_fold_repair.json"),
        Path("artifacts/scanner_v2/pattern_specific_final_push/triangles_ascending/triangles_ascending_final_push.json"),
    ],
    "triangles_symmetrical": [
        Path("artifacts/scanner_v2/symmetrical_triangle_tradable_blocker_audit/symmetrical_triangle_tradable_blocker_audit.json"),
        Path("artifacts/scanner_v2/feature_filter_ceiling_push/triangles_symmetrical/triangles_symmetrical_feature_filter_push.json"),
        Path("artifacts/scanner_v2/pattern_specific_branch_redesign/triangles_symmetrical/triangles_symmetrical_branch_redesign.json"),
        Path("artifacts/scanner_v2/pattern_specific_fold_repair/triangles_symmetrical/triangles_symmetrical_fold_repair.json"),
        Path("artifacts/scanner_v2/pattern_specific_final_push/triangles_symmetrical/triangles_symmetrical_final_push.json"),
    ],
    "wedges_falling": [
        Path("artifacts/scanner_v2/falling_wedge_tradable_blocker_audit/falling_wedge_tradable_blocker_audit.json"),
        Path("artifacts/scanner_v2/targeted_pattern_ceiling_push/wedges_falling/wedges_falling_targeted_ceiling_push.json"),
        Path("artifacts/scanner_v2/feature_filter_ceiling_push/wedges_falling/wedges_falling_feature_filter_push.json"),
        Path("artifacts/scanner_v2/pattern_specific_branch_redesign/wedges_falling/wedges_falling_branch_redesign.json"),
        Path("artifacts/scanner_v2/pattern_specific_fold_repair/wedges_falling/wedges_falling_fold_repair.json"),
        Path("artifacts/scanner_v2/pattern_specific_final_push/wedges_falling/wedges_falling_final_push.json"),
    ],
    "wedges_rising": [
        Path("artifacts/scanner_v2/targeted_pattern_ceiling_push/wedges_rising/wedges_rising_targeted_ceiling_push.json"),
        Path("artifacts/scanner_v2/feature_filter_ceiling_push/wedges_rising/wedges_rising_feature_filter_push.json"),
        Path("artifacts/scanner_v2/pattern_specific_branch_redesign/wedges_rising/wedges_rising_branch_redesign.json"),
        Path("artifacts/scanner_v2/pattern_specific_fold_repair/wedges_rising/wedges_rising_fold_repair.json"),
        Path("artifacts/scanner_v2/pattern_specific_final_push/wedges_rising/wedges_rising_final_push.json"),
    ],
    "double_bottoms_adam_adam": [
        Path("artifacts/scanner_v2/double_bottom_aa_tradable_blocker_audit/double_bottom_aa_tradable_blocker_audit.json"),
        Path("artifacts/scanner_v2/double_bottom_aa_entry_branch_audit/double_bottom_aa_entry_branch_audit.json"),
        Path("artifacts/scanner_v2/double_bottom_entry_branch_audit/double_bottoms_adam_adam/double_bottoms_adam_adam_entry_branch_audit.json"),
    ],
    "double_bottoms_adam_eve": [
        Path("artifacts/scanner_v2/double_bottom_entry_branch_audit/double_bottoms_adam_eve/double_bottoms_adam_eve_entry_branch_audit.json"),
    ],
    "double_bottoms_eve_adam": [
        Path("artifacts/scanner_v2/double_bottom_entry_branch_audit/double_bottoms_eve_adam/double_bottoms_eve_adam_entry_branch_audit.json"),
    ],
    "double_bottoms_eve_eve": [
        Path("artifacts/scanner_v2/double_bottom_entry_branch_audit/double_bottoms_eve_eve/double_bottoms_eve_eve_entry_branch_audit.json"),
    ],
    "double_tops_adam_adam": [
        Path("artifacts/scanner_v2/double_top_aa_defensive_branch_audit/double_top_aa_defensive_branch_audit.json"),
    ],
    "double_tops_adam_eve": [
        Path("artifacts/scanner_v2/remaining_pattern_branch_ceiling_audit/double_tops_adam_eve/double_tops_adam_eve_branch_ceiling_audit.json"),
    ],
    "double_tops_eve_adam": [
        Path("artifacts/scanner_v2/remaining_pattern_branch_ceiling_audit/double_tops_eve_adam/double_tops_eve_adam_branch_ceiling_audit.json"),
    ],
    "double_tops_eve_eve": [
        Path("artifacts/scanner_v2/remaining_pattern_branch_ceiling_audit/double_tops_eve_eve/double_tops_eve_eve_branch_ceiling_audit.json"),
    ],
    "triangles_descending": [
        Path("artifacts/scanner_v2/remaining_pattern_branch_ceiling_audit/triangles_descending/triangles_descending_branch_ceiling_audit.json"),
        Path("artifacts/scanner_v2/feature_filter_ceiling_push/triangles_descending/triangles_descending_feature_filter_push.json"),
        Path("artifacts/scanner_v2/pattern_specific_branch_redesign/triangles_descending/triangles_descending_branch_redesign.json"),
        Path("artifacts/scanner_v2/pattern_specific_fold_repair/triangles_descending/triangles_descending_fold_repair.json"),
        Path("artifacts/scanner_v2/pattern_specific_final_push/triangles_descending/triangles_descending_final_push.json"),
    ],
    "head_and_shoulders_bottoms_complex": [
        Path("artifacts/scanner_v2/pattern_specific_final_push/head_and_shoulders_bottoms_complex/head_and_shoulders_bottoms_complex_final_push.json"),
    ],
    "head_and_shoulders_tops_complex": [
        Path("artifacts/scanner_v2/pattern_specific_final_push/head_and_shoulders_tops_complex/head_and_shoulders_tops_complex_final_push.json"),
    ],
    "broadening_bottoms": [
        Path("artifacts/scanner_v2/pattern_specific_branch_redesign/broadening_bottoms/broadening_bottoms_branch_redesign.json"),
        Path("artifacts/scanner_v2/pattern_specific_fold_repair/broadening_bottoms/broadening_bottoms_fold_repair.json"),
        Path("artifacts/scanner_v2/pattern_specific_final_push/broadening_bottoms/broadening_bottoms_final_push.json"),
    ],
    "broadening_formations_right_angled_ascending": [
        Path("artifacts/scanner_v2/pattern_specific_branch_redesign/broadening_formations_right_angled_ascending/broadening_formations_right_angled_ascending_branch_redesign.json"),
        Path("artifacts/scanner_v2/pattern_specific_fold_repair/broadening_formations_right_angled_ascending/broadening_formations_right_angled_ascending_fold_repair.json"),
        Path("artifacts/scanner_v2/pattern_specific_final_push/broadening_formations_right_angled_ascending/broadening_formations_right_angled_ascending_final_push.json"),
    ],
    "broadening_formations_right_angled_descending": [
        Path("artifacts/scanner_v2/pattern_specific_branch_redesign/broadening_formations_right_angled_descending/broadening_formations_right_angled_descending_branch_redesign.json"),
        Path("artifacts/scanner_v2/pattern_specific_fold_repair/broadening_formations_right_angled_descending/broadening_formations_right_angled_descending_fold_repair.json"),
        Path("artifacts/scanner_v2/pattern_specific_final_push/broadening_formations_right_angled_descending/broadening_formations_right_angled_descending_final_push.json"),
    ],
    "broadening_tops": [
        Path("artifacts/scanner_v2/pattern_specific_branch_redesign/broadening_tops/broadening_tops_branch_redesign.json"),
        Path("artifacts/scanner_v2/pattern_specific_fold_repair/broadening_tops/broadening_tops_fold_repair.json"),
        Path("artifacts/scanner_v2/pattern_specific_final_push/broadening_tops/broadening_tops_final_push.json"),
    ],
    "broadening_wedges_ascending": [
        Path("artifacts/scanner_v2/pattern_specific_branch_redesign/broadening_wedges_ascending/broadening_wedges_ascending_branch_redesign.json"),
        Path("artifacts/scanner_v2/pattern_specific_fold_repair/broadening_wedges_ascending/broadening_wedges_ascending_fold_repair.json"),
        Path("artifacts/scanner_v2/pattern_specific_final_push/broadening_wedges_ascending/broadening_wedges_ascending_final_push.json"),
    ],
    "broadening_wedges_descending": [
        Path("artifacts/scanner_v2/pattern_specific_branch_redesign/broadening_wedges_descending/broadening_wedges_descending_branch_redesign.json"),
        Path("artifacts/scanner_v2/pattern_specific_fold_repair/broadening_wedges_descending/broadening_wedges_descending_fold_repair.json"),
        Path("artifacts/scanner_v2/pattern_specific_final_push/broadening_wedges_descending/broadening_wedges_descending_final_push.json"),
    ],
}

TRADABLE_ARTIFACTS: dict[str, dict[str, Path]] = {
    "bull_flags": {
        "scorecard": Path("artifacts/scanner_v2/bull_flags_tradable_setup/bull_flag_tradable_scorecard.json"),
        "selected_strategy": Path("artifacts/scanner_v2/bull_flags_tradable_setup/bull_flag_tradable_selected_strategy.json"),
        "release_candidate": Path("artifacts/scanner_v2/bull_flags_release_candidate/bull_flag_release_candidate.json"),
    },
}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "family",
        "pattern_id",
        "title",
        "publication_status",
        "publication_claim_level",
        "publication_classification",
        "tradable_status",
        "tradable_score_available",
        "tradable_score",
        "tradable_release_status",
        "tradable_claim_level",
        "tradable_evidence_id",
        "tradable_blockers",
        "tradable_scorecard",
        "tradable_release_candidate",
        "tradable_preflight_status",
        "tradable_preflight_score",
        "tradable_preflight_scope",
        "tradable_preflight_warnings",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows([{key: row.get(key) for key in fieldnames} for row in rows])


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _defensive_or_informational(chapter: Mapping[str, Any]) -> bool:
    text = " ".join(
        str(chapter.get(key) or "")
        for key in ("classification", "claim_level", "note", "title", "pattern_id")
    ).lower()
    return any(token in text for token in ("defensive", "informational", "bear", "top", "downside", "giảm", "đỉnh"))


def _tradable_axis(pattern_id: str, chapter: Mapping[str, Any]) -> dict[str, Any]:
    artifacts = TRADABLE_ARTIFACTS.get(pattern_id)
    if not artifacts:
        evidence_candidates: list[dict[str, Any]] = []
        for evidence_id, base_dir in (
            ("generic_tradable_layer", DEFAULT_GENERIC_TRADABLE_DIR),
            ("branch_optimization_layer", DEFAULT_BRANCH_OPTIMIZATION_DIR),
            ("priority_candidate_layer", DEFAULT_PRIORITY_OPTIMIZATION_DIR),
        ):
            evidence_dir = base_dir / pattern_id
            scorecard_path = evidence_dir / "scorecard.json"
            release_path = evidence_dir / "release_candidate.json"
            selected_path = evidence_dir / "selected_strategy.json"
            if not scorecard_path.exists() or not release_path.exists():
                continue
            scorecard = _read_json(scorecard_path)
            release = _read_json(release_path)
            score = _as_float(scorecard.get("score") if scorecard else release.get("score"))
            evidence_candidates.append(
                {
                    "evidence_id": evidence_id,
                    "scorecard_path": scorecard_path,
                    "release_path": release_path,
                    "selected_path": selected_path,
                    "scorecard": scorecard,
                    "release": release,
                    "score": score,
                }
            )
        for local_audit_path in LOCAL_BLOCKER_AUDITS.get(pattern_id, []):
            local_audit = _read_json(local_audit_path) if local_audit_path and local_audit_path.exists() else {}
            if not local_audit:
                continue
            local_rows = local_audit.get("rows") if isinstance(local_audit.get("rows"), list) else []
            local_best = local_rows[0] if local_rows and isinstance(local_rows[0], Mapping) else {}
            guard = local_audit.get("no_overlift_guard") if isinstance(local_audit.get("no_overlift_guard"), Mapping) else {}
            blockers = [
                item.strip()
                for item in str(local_best.get("promotion_blockers") or "").split(",")
                if item.strip()
            ]
            failures = list(guard.get("failures") or []) if isinstance(guard.get("failures"), list) else []
            remaining_blockers = list(guard.get("remaining_tradable_blockers") or []) if isinstance(guard.get("remaining_tradable_blockers"), list) else []
            guard_decision = str(guard.get("promotion_decision") or "")
            local_release_status = "PASS" if guard_decision == "ELIGIBLE_FOR_FORMAL_PROMOTION_REVIEW" and not blockers and not failures else "BLOCK"
            normalized_failures = []
            for failure in failures:
                if failure in {"score_threshold", "score_threshold_95", "diagnostic_score_90", "defensive_reference_score_90"}:
                    normalized_failures.append("score_below_95")
                elif failure in {"walk_forward_positive", "fixed_walk_forward_positive"}:
                    normalized_failures.append("walk_forward_has_negative_fold")
                elif failure == "direct_long_cash_scope":
                    normalized_failures.append("scope_not_direct_long_cash_equity")
                elif failure == "promotion_blockers_clear":
                    continue
                elif failure == "promotion_blockers":
                    continue
                else:
                    normalized_failures.append(str(failure))
            score = _as_float(local_audit.get("best_score"))
            evidence_candidates.append(
                {
                    "evidence_id": "local_blocker_audit",
                    "scorecard_path": local_audit_path,
                    "release_path": local_audit_path,
                    "selected_path": local_audit_path,
                    "scorecard": {
                        "score": score,
                        "classification": local_best.get("classification") or "local-blocker-audit",
                        "promotion_blockers": sorted(set(blockers + [str(item) for item in remaining_blockers if str(item)])),
                    },
                    "release": {
                        "release_status": local_release_status,
                        "classification": "local audit eligible for promotion review" if local_release_status == "PASS" else "local blocker audit; not promoted",
                        "claim_level": "tested executable layer; local audit passed no-overlift guard" if local_release_status == "PASS" else "local blocker audit; not promoted",
                        "failures": normalized_failures,
                        "scope": local_audit.get("scope"),
                    },
                    "score": score,
                }
            )
        if evidence_candidates:
            evidence = max(evidence_candidates, key=lambda item: float(item.get("score") or -1.0))
            scorecard = evidence["scorecard"]
            release = evidence["release"]
            score = evidence["score"]
            scorecard_path = evidence["scorecard_path"]
            release_path = evidence["release_path"]
            selected_path = evidence["selected_path"]
            release_status = str(release.get("release_status") or "UNKNOWN")
            blockers = list(scorecard.get("promotion_blockers") or []) if isinstance(scorecard.get("promotion_blockers"), list) else []
            failures = list(release.get("failures") or []) if isinstance(release.get("failures"), list) else []
            combined_blockers = blockers + failures
            if release_status == "PASS" and score is not None and score >= 95.0 and not combined_blockers:
                status = "tradable_final_95"
            elif score is not None and score >= 90.0:
                status = "tradable_research_candidate_blocked"
            else:
                status = "tradable_tested_blocked"
            return {
                "tradable_status": status,
                "tradable_score_available": True,
                "tradable_score": score,
                "tradable_release_status": release_status,
                "tradable_claim_level": release.get("claim_level") or scorecard.get("classification"),
                "tradable_blockers": ",".join(sorted(set(str(item) for item in combined_blockers if item))),
                "tradable_scorecard": str(scorecard_path),
                "tradable_release_candidate": str(release_path),
                "tradable_selected_strategy": str(selected_path),
                "tradable_applicability": release.get("scope") or evidence["evidence_id"],
                "tradable_evidence_id": evidence["evidence_id"],
            }
        applicability = (
            "defensive_or_informational_not_primary_long_cash_equity"
            if _defensive_or_informational(chapter)
            else "not_built_yet"
        )
        return {
            "tradable_status": "not_tested",
            "tradable_score_available": False,
            "tradable_score": None,
            "tradable_release_status": None,
            "tradable_claim_level": "No executable entry/exit/cost/sizing/OOS gate exists for this chapter.",
            "tradable_blockers": "tradable_layer_missing",
            "tradable_scorecard": None,
            "tradable_release_candidate": None,
            "tradable_applicability": applicability,
        }

    scorecard_path = artifacts["scorecard"]
    release_path = artifacts["release_candidate"]
    scorecard = _read_json(scorecard_path)
    release = _read_json(release_path)
    score = _as_float(scorecard.get("score") if scorecard else release.get("score"))
    release_status = str(release.get("release_status") or "UNKNOWN")
    blockers = list(scorecard.get("promotion_blockers") or []) if isinstance(scorecard.get("promotion_blockers"), list) else []
    failures = list(release.get("failures") or []) if isinstance(release.get("failures"), list) else []
    if release_status == "PASS" and score is not None and score >= 95.0 and not blockers and not failures:
        status = "tradable_final_95"
    elif score is not None and score >= 90.0:
        status = "tradable_research_candidate_blocked"
    elif score is not None:
        status = "tradable_provisional_blocked"
    else:
        status = "tradable_artifacts_incomplete"
    combined_blockers = blockers + failures
    return {
        "tradable_status": status,
        "tradable_score_available": True,
        "tradable_score": score,
        "tradable_release_status": release_status,
        "tradable_claim_level": release.get("claim_level") or scorecard.get("classification"),
        "tradable_blockers": ",".join(combined_blockers),
        "tradable_scorecard": str(scorecard_path),
        "tradable_release_candidate": str(release_path),
        "tradable_applicability": "tested_executable_layer",
        "tradable_evidence_id": "specialized_tradable_layer",
    }


def _load_preflight_rows(path: Path) -> dict[str, Mapping[str, Any]]:
    payload = _read_json(path)
    rows = payload.get("chapters") if isinstance(payload.get("chapters"), list) else []
    return {
        str(row.get("pattern_id") or ""): row
        for row in rows
        if isinstance(row, Mapping) and str(row.get("pattern_id") or "")
    }


def _render_markdown(payload: Mapping[str, Any]) -> str:
    rows = list(payload.get("chapters") or [])
    counts = payload.get("counts") if isinstance(payload.get("counts"), Mapping) else {}
    lines = [
        "# Chapter Governance Matrix",
        "",
        "Policy: `dual_axis_chapter_scoring_v1`.",
        "",
        "A chapter can be `publication-final` without being `tradable-final-95`. Tradable status is only assigned when an executable entry/exit/cost/sizing/OOS gate exists.",
        "",
        "## Summary",
        "",
        f"- Final publication chapters: `{counts.get('chapters')}`",
        f"- Tradable final 95: `{counts.get('tradable_final_95')}`",
        f"- Tradable research candidate but blocked: `{counts.get('tradable_research_candidate_blocked')}`",
        f"- Tradable not tested: `{counts.get('not_tested')}`",
        "",
        "## Matrix",
        "",
        "| Pattern | Publication | Tradable | Evidence | Score | Preflight | Preflight score | Blockers / warnings |",
        "|---|---|---|---|---:|---|---:|---|",
    ]
    for row in rows:
        score = "" if row.get("tradable_score") is None else f"{float(row['tradable_score']):.2f}"
        preflight_score = "" if row.get("tradable_preflight_score") is None else f"{float(row['tradable_preflight_score']):.2f}"
        blockers = ", ".join(
            item
            for item in [str(row.get("tradable_blockers") or ""), str(row.get("tradable_preflight_warnings") or "")]
            if item
        )
        lines.append(
            "| {pattern} | {publication} | {tradable} | {evidence} | {score} | {preflight} | {preflight_score} | {blockers} |".format(
                pattern=row.get("pattern_id"),
                publication=row.get("publication_status"),
                tradable=row.get("tradable_status"),
                evidence=row.get("tradable_evidence_id") or "",
                score=score,
                preflight=row.get("tradable_preflight_status"),
                preflight_score=preflight_score,
                blockers=blockers,
            )
        )
    lines.extend(
        [
            "",
            "## Rule",
            "",
            "- `publication-final`: đủ điều kiện xuất bản như tài liệu tham khảo.",
            "- `tradable-final-95`: chỉ được dùng khi có scorecard tradable, release candidate PASS, score >= 95, và không còn blocker.",
            "- `not_tested`: không phải điểm thấp; nghĩa là chapter chưa có lớp thực thi.",
            "- `tradable-preflight`: lớp rà soát nhanh bằng event statistics; nó chỉ chỉ ra chapter nào đáng ưu tiên chạy scorecard thực thi đầy đủ.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_chapter_governance_matrix(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    out_dir: Path = DEFAULT_OUT_DIR,
    preflight_path: Path = DEFAULT_PREFLIGHT_MATRIX,
) -> dict[str, Path]:
    manifest = _read_json(manifest_path)
    preflight_rows = _load_preflight_rows(preflight_path)
    chapters = manifest.get("chapters") if isinstance(manifest.get("chapters"), list) else []
    rows: list[dict[str, Any]] = []
    for chapter in chapters:
        if not isinstance(chapter, Mapping):
            continue
        pattern_id = str(chapter.get("pattern_id") or "")
        tradable = _tradable_axis(pattern_id, chapter)
        preflight = preflight_rows.get(pattern_id, {})
        rows.append(
            {
                "family": chapter.get("family"),
                "pattern_id": pattern_id,
                "title": chapter.get("title"),
                "publication_status": "publication_final" if chapter.get("status") == "final" else str(chapter.get("status") or "unknown"),
                "publication_claim_level": chapter.get("claim_level"),
                "publication_classification": chapter.get("classification"),
                **tradable,
                "tradable_preflight_status": preflight.get("preflight_status"),
                "tradable_preflight_score": preflight.get("preflight_score"),
                "tradable_preflight_scope": preflight.get("scope"),
                "tradable_preflight_warnings": ",".join(preflight.get("warnings") or []),
            }
        )

    counts = {
        "chapters": len(rows),
        "publication_final": sum(1 for row in rows if row["publication_status"] == "publication_final"),
        "tradable_final_95": sum(1 for row in rows if row["tradable_status"] == "tradable_final_95"),
        "tradable_research_candidate_blocked": sum(1 for row in rows if row["tradable_status"] == "tradable_research_candidate_blocked"),
        "tradable_tested_blocked": sum(1 for row in rows if row["tradable_status"] == "tradable_tested_blocked"),
        "not_tested": sum(1 for row in rows if row["tradable_status"] == "not_tested"),
        "preflight_available": sum(1 for row in rows if row.get("tradable_preflight_status")),
        "preflight_strong": sum(1 for row in rows if row.get("tradable_preflight_status") == "preflight_strong"),
        "preflight_candidate": sum(1 for row in rows if row.get("tradable_preflight_status") == "preflight_candidate"),
        "preflight_watchlist": sum(1 for row in rows if row.get("tradable_preflight_status") == "preflight_watchlist"),
        "preflight_weak_or_poor": sum(
            1 for row in rows if row.get("tradable_preflight_status") in {"preflight_weak", "preflight_poor"}
        ),
    }
    payload = {
        "governance_matrix_id": DUAL_AXIS_POLICY_ID,
        "manifest": str(manifest_path),
        "rule": "Every final chapter is scored on publication/reference readiness and separately on tradable/execution readiness. Publication final does not imply tradable final.",
        "preflight_matrix": str(preflight_path),
        "counts": counts,
        "chapters": rows,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": out_dir / "chapter_governance_matrix.json",
        "csv": out_dir / "chapter_governance_matrix.csv",
        "md": out_dir / "chapter_governance_matrix.md",
    }
    _write_json(paths["json"], payload)
    _write_csv(paths["csv"], rows)
    paths["md"].write_text(_render_markdown(payload), encoding="utf-8")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Build chapter dual-axis governance matrix.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--preflight", default=str(DEFAULT_PREFLIGHT_MATRIX))
    args = parser.parse_args()
    paths = build_chapter_governance_matrix(
        manifest_path=Path(args.manifest),
        out_dir=Path(args.out_dir),
        preflight_path=Path(args.preflight),
    )
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
