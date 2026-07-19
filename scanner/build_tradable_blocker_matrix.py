"""Build a blocker-specific action matrix for tradable chapter work.

The governance matrix answers "what is the score/status?".  This file answers
"what should we do next for each pattern without over-lifting the evidence?".
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Mapping


GOVERNANCE_PATH = Path("artifacts/final_chapters/governance/chapter_governance_matrix.json")
OUT_DIR = Path("artifacts/final_chapters/governance")
MATRIX_ID = "tradable_blocker_matrix_v1"

LOCAL_AUDITS: dict[str, list[Path]] = {
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
    "head_and_shoulders_bottoms_complex": [
        Path("artifacts/scanner_v2/pattern_specific_final_push/head_and_shoulders_bottoms_complex/head_and_shoulders_bottoms_complex_final_push.json"),
    ],
    "head_and_shoulders_tops_complex": [
        Path("artifacts/scanner_v2/pattern_specific_final_push/head_and_shoulders_tops_complex/head_and_shoulders_tops_complex_final_push.json"),
    ],
    "broadening_formations_right_angled_descending": [
        Path("artifacts/scanner_v2/pattern_specific_branch_redesign/broadening_formations_right_angled_descending/broadening_formations_right_angled_descending_branch_redesign.json"),
        Path("artifacts/scanner_v2/pattern_specific_fold_repair/broadening_formations_right_angled_descending/broadening_formations_right_angled_descending_fold_repair.json"),
        Path("artifacts/scanner_v2/pattern_specific_final_push/broadening_formations_right_angled_descending/broadening_formations_right_angled_descending_final_push.json"),
    ],
    "broadening_wedges_descending": [
        Path("artifacts/scanner_v2/pattern_specific_branch_redesign/broadening_wedges_descending/broadening_wedges_descending_branch_redesign.json"),
        Path("artifacts/scanner_v2/pattern_specific_fold_repair/broadening_wedges_descending/broadening_wedges_descending_fold_repair.json"),
        Path("artifacts/scanner_v2/pattern_specific_final_push/broadening_wedges_descending/broadening_wedges_descending_final_push.json"),
    ],
}

ACTION_RULES: dict[str, dict[str, str]] = {
    "bull_pennants": {
        "primary_blocker": "walk_forward_fold_instability",
        "next_action": "keep as blocked research candidate; target/size/capacity are not the main issue, and promotion requires a pre-registered branch that removes fixed walk-forward losses without weakening the fold contract",
        "ceiling_note": "best diagnostic branch reaches 93.8 with strong return/cost/capacity, but many small negative 10-event folds keep it below the 95+ no-overlift gate",
    },
    "double_bottoms_adam_adam": {
        "primary_blocker": "none",
        "next_action": "promote as tradable-final-95 candidate under current available-series scope; monitor publication text and avoid broad-market overclaim",
        "ceiling_note": "retest-reclaim plus Bull Flag-style sizing parity clears score, validation/holdout, walk-forward, and capacity gates",
    },
    "double_bottoms_adam_eve": {
        "primary_blocker": "sample_depth_and_walk_forward_instability",
        "next_action": "keep as publication/reference; validation/holdout event depth is below the trade-count gate even before entry filtering",
        "ceiling_note": "current available-series scope has only 36 variant events, so this variant cannot satisfy the 12-trade validation/holdout gate without broader data",
    },
    "double_bottoms_eve_adam": {
        "primary_blocker": "sample_depth_and_walk_forward_instability",
        "next_action": "keep as publication/reference; validation/holdout event depth is below the trade-count gate even before entry filtering",
        "ceiling_note": "current available-series scope has only 30 variant events, so this variant is data-depth blocked rather than scanner-entry blocked",
    },
    "double_bottoms_eve_eve": {
        "primary_blocker": "low_walk_forward_sum_and_trade_depth",
        "next_action": "keep as publication/reference; low setup-threshold probe recovers some holdout depth but worsens walk-forward stability and score",
        "ceiling_note": "fixed entry remains best under current audit; this is an available-data ceiling, not a missing dynamic-entry rule",
    },
    "double_tops_adam_adam": {
        "primary_blocker": "defensive_scope_and_return_depth",
        "next_action": "upgrade evidence label to defensive research candidate; do not promote as direct long-cash tradable because the setup is downside/synthetic-short in Vietnam cash equities",
        "ceiling_note": "targeted defensive branch reaches 90+ with 100% positive fixed walk-forward folds, but remains below tradable-final 95 and outside direct long-cash scope",
    },
    "double_tops_adam_eve": {
        "primary_blocker": "defensive_scope_and_return_depth",
        "next_action": "keep as defensive/informational reference; diagnostic branch fixes liquidity and fixed-fold sign but not return depth",
        "ceiling_note": "best diagnostic branch improves the score to the mid-60s, but validation return is still weak and walk-forward sum remains far below executable threshold",
    },
    "double_tops_eve_adam": {
        "primary_blocker": "defensive_scope_sample_depth_and_low_fold_return",
        "next_action": "keep as defensive/informational reference; diagnostic high-liquidity branch improves path quality but collapses validation/holdout trade count",
        "ceiling_note": "positive fixed folds are not enough: trade depth and fold-return sum remain below tradable-standard thresholds",
    },
    "double_tops_eve_eve": {
        "primary_blocker": "sample_depth_and_defensive_scope",
        "next_action": "keep as appendix/defensive reference; diagnostic branch confirms the available-series sample is too thin for execution claims",
        "ceiling_note": "score improves from weak to high-50s, but validation/holdout each have only one trade in the best branch",
    },
    "triangles_ascending": {
        "primary_blocker": "walk_forward_fold_instability",
        "next_action": "keep publication/investment-reference; fold-repair nudges the bear/high-liquidity branch higher but still leaves a negative fixed walk-forward fold",
        "ceiling_note": "fold-repair reaches the mid-80s; promotion remains blocked by fold instability rather than target/position sizing alone",
    },
    "triangles_descending": {
        "primary_blocker": "defensive_scope_and_fold_instability",
        "next_action": "keep as defensive/informational reference; high-liquidity breakdown branch is now a strong blocked research candidate but remains outside direct long-cash scope",
        "ceiling_note": "branch redesign raises the score to the high-80s with positive validation/holdout, but one negative fixed fold and downside scope still block promotion",
    },
    "bear_flags": {
        "primary_blocker": "defensive_scope_and_return_depth",
        "next_action": "keep as defensive/informational reference; final high-liquidity stress branch improves score but still misses validation-depth and fold-return thresholds",
        "ceiling_note": "final push reaches low-80s with 100% positive fixed folds; remaining blockers are sample depth, downside scope, and fold-return depth",
    },
    "wedges_falling": {
        "primary_blocker": "liquidity_and_walk_forward_instability",
        "next_action": "keep as improved watchlist/reference; final push adds small score lift but still leaves fixed walk-forward instability and capacity pressure",
        "ceiling_note": "best evidence is now high-80s; remaining blocker is path robustness/capacity rather than simple target selection",
    },
    "triangles_symmetrical": {
        "primary_blocker": "mixed_direction_not_direct_long_cash_setup",
        "next_action": "keep mixed-direction/reference chapter; targeted long-up sizing parity probe did not clear holdout or walk-forward instability",
        "ceiling_note": "current best evidence is branch/reference; the mixed-direction pattern should not be promoted as a universal long-cash execution setup",
    },
    "wedges_rising": {
        "primary_blocker": "defensive_scope_and_score_threshold",
        "next_action": "upgrade evidence label to defensive research candidate; fold-repair clears fixed-fold sign but remains below 95 and outside direct long-cash scope",
        "ceiling_note": "fold-repair lifts the score above 90 with positive fixed walk-forward folds; the ceiling is now defensive/downside scope plus score threshold",
    },
    "head_and_shoulders_bottoms_complex": {
        "primary_blocker": "low_executable_return_depth",
        "next_action": "keep as publication/reference long setup; do not promote to tradable-final until broader data or a source-grounded entry model materially improves validation and walk-forward return depth",
        "ceiling_note": "selected long branch has positive fixed folds but the executable return sum is shallow and validation depth is one trade below the 12-trade gate under the current series",
    },
    "head_and_shoulders_tops_complex": {
        "primary_blocker": "defensive_scope_and_validation_depth",
        "next_action": "use as defensive/exit watchlist evidence, not direct cash-equity short setup; broader data or an exit-specific portfolio overlay is needed before stronger claims",
        "ceiling_note": "defensive branch improves to mid-80s with positive fixed folds, but remains below 95 and outside direct long-cash scope",
    },
    "broadening_formations_right_angled_descending": {
        "primary_blocker": "walk_forward_fold_instability",
        "next_action": "keep as publication/reference candidate; right-angled descending can be studied as a long-up branch, but current data do not support promotion beyond blocked executable evidence",
        "ceiling_note": "the final no-double-filter branch lifts the score into the mid-80s and clears the 8% walk-forward-return floor, but still leaves a negative fixed fold",
    },
    "broadening_wedges_descending": {
        "primary_blocker": "walk_forward_fold_instability",
        "next_action": "keep as strong blocked research candidate; last-mile no-double-filter probes improve some fold-return totals but do not remove the negative fixed fold",
        "ceiling_note": "best available branch remains in the low-80s under current data. The blocker is temporal stability, not target multiple alone or a missing publication chapter.",
    },
}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _audit_summary(pattern_id: str) -> dict[str, Any]:
    audits: list[tuple[Path, dict[str, Any]]] = []
    for path in LOCAL_AUDITS.get(pattern_id, []):
        payload = _read_json(path)
        if payload:
            audits.append((path, payload))
    path, audit = max(audits, key=lambda item: _as_float(item[1].get("best_score")) or -1.0) if audits else (Path("__missing__"), {})
    rows = audit.get("rows") if isinstance(audit.get("rows"), list) else []
    best = rows[0] if rows and isinstance(rows[0], Mapping) else {}
    return {
        "audit_path": str(path) if audits else None,
        "audit_best_score": audit.get("best_score"),
        "audit_best_strategy_id": audit.get("best_strategy_id"),
        "audit_best_blockers": best.get("promotion_blockers"),
        "audit_guard_decision": (audit.get("no_overlift_guard") or {}).get("promotion_decision")
        if isinstance(audit.get("no_overlift_guard"), Mapping)
        else None,
        "audit_grid_count": audit.get("grid_count"),
    }


def build_matrix(*, governance_path: Path = GOVERNANCE_PATH, out_dir: Path = OUT_DIR) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    governance = _read_json(governance_path)
    rows: list[dict[str, Any]] = []
    for chapter in governance.get("chapters") or []:
        pattern_id = str(chapter.get("pattern_id") or "")
        if not pattern_id:
            continue
        rules = ACTION_RULES.get(
            pattern_id,
            {
                "primary_blocker": "not_prioritized_for_current_tradable_work",
                "next_action": "no immediate scanner/source branch work",
                "ceiling_note": "outside current blocker-specific queue",
            },
        )
        score = _as_float(chapter.get("tradable_score"))
        row = {
            "pattern_id": pattern_id,
            "family": chapter.get("family"),
            "title": chapter.get("title"),
            "publication_status": chapter.get("publication_status"),
            "tradable_status": chapter.get("tradable_status"),
            "tradable_score": score,
            "tradable_evidence_id": chapter.get("tradable_evidence_id"),
            "tradable_blockers": chapter.get("tradable_blockers"),
            "primary_blocker": rules["primary_blocker"],
            "next_action": rules["next_action"],
            "ceiling_note": rules["ceiling_note"],
            **_audit_summary(pattern_id),
        }
        rows.append(row)
    payload = {
        "matrix_id": MATRIX_ID,
        "source": str(governance_path),
        "row_count": len(rows),
        "policy": "no-overlift: blocker work may diagnose or improve, but promotion still requires score >=95 and no hard blocker.",
        "rows": rows,
    }
    paths = {
        "json": out_dir / "tradable_blocker_matrix.json",
        "csv": out_dir / "tradable_blocker_matrix.csv",
        "md": out_dir / "tradable_blocker_matrix.md",
    }
    _write_json(paths["json"], payload)
    fieldnames = [
        "pattern_id",
        "family",
        "title",
        "tradable_status",
        "tradable_score",
        "tradable_evidence_id",
        "tradable_blockers",
        "primary_blocker",
        "next_action",
        "ceiling_note",
        "audit_best_score",
        "audit_best_strategy_id",
        "audit_best_blockers",
    ]
    with paths["csv"].open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows([{key: row.get(key) for key in fieldnames} for row in rows])
    lines = [
        "# Tradable Blocker Matrix",
        "",
        f"Matrix: `{MATRIX_ID}`",
        "",
        "| Pattern | Score | Status | Primary blocker | Next action |",
        "|---|---:|---|---|---|",
    ]
    for row in rows:
        if row.get("primary_blocker") == "not_prioritized_for_current_tradable_work":
            continue
        lines.append(
            "| {pattern} | {score} | {status} | {blocker} | {action} |".format(
                pattern=row.get("pattern_id"),
                score=row.get("tradable_score") if row.get("tradable_score") is not None else "",
                status=row.get("tradable_status"),
                blocker=row.get("primary_blocker"),
                action=row.get("next_action"),
            )
        )
    paths["md"].write_text("\n".join(lines) + "\n", encoding="utf-8")
    return paths


def main() -> None:
    for key, path in build_matrix().items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
