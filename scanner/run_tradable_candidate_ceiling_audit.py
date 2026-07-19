"""Summarize tradable ceiling evidence for non-final chapters worth pushing.

The project uses two distinct gates:

* preflight/reference readiness, which can use calibrated event statistics;
* tradable/execution readiness, which requires executable entry/exit/cost/
  sizing/OOS/walk-forward evidence.

This script is the tradable-side counterpart to the preflight branch ceiling
audit. It reads the already-computed tradable evidence layers plus local blocker
audits, confirms whether governance is already using the best available score,
and records why remaining non-final chapters should stop under the current
contract instead of being forced to 95 by overfitting.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.build_chapter_governance_matrix import (
    DEFAULT_BRANCH_OPTIMIZATION_DIR,
    DEFAULT_GENERIC_TRADABLE_DIR,
    DEFAULT_PRIORITY_OPTIMIZATION_DIR,
    LOCAL_BLOCKER_AUDITS,
)


DEFAULT_GOVERNANCE = Path("artifacts/final_chapters/governance/chapter_governance_matrix.json")
DEFAULT_OUT_DIR = Path("artifacts/final_chapters/governance")
AUDIT_ID = "tradable_candidate_ceiling_audit_v1"
PROMOTION_THRESHOLD = 95.0
MATERIAL_SCORE_LIFT = 3.0
DEFAULT_PATTERNS = (
    "bull_pennants",
    "wedges_rising",
    "double_tops_adam_adam",
    "triangles_descending",
    "wedges_falling",
    "triangles_ascending",
    "triangles_symmetrical",
    "bear_flags",
)


EVIDENCE_DIRS = {
    "generic_tradable_layer": DEFAULT_GENERIC_TRADABLE_DIR,
    "branch_optimization_layer": DEFAULT_BRANCH_OPTIMIZATION_DIR,
    "priority_candidate_layer": DEFAULT_PRIORITY_OPTIMIZATION_DIR,
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


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


def _items(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fieldnames = [
        "pattern_id",
        "current_score",
        "current_status",
        "current_evidence_id",
        "best_known_score",
        "best_known_evidence_id",
        "best_known_strategy_id",
        "score_lift_vs_current_pp",
        "technical_ceiling_decision",
        "remaining_ceiling_reason",
        "remaining_blockers",
        "evidence_count",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            out = {key: row.get(key) for key in fieldnames}
            out["remaining_blockers"] = ",".join(row.get("remaining_blockers") or [])
            writer.writerow(out)


def _summary_evidence(pattern_id: str, evidence_id: str, base_dir: Path) -> dict[str, Any]:
    chapter_dir = base_dir / pattern_id
    scorecard = _read_json(chapter_dir / "scorecard.json")
    release = _read_json(chapter_dir / "release_candidate.json")
    selected = _read_json(chapter_dir / "selected_strategy.json")
    summary = _read_json(chapter_dir / "priority_optimization_summary.json")
    if not summary:
        summary = _read_json(chapter_dir / "branch_optimization_summary.json")
    if not summary:
        summary = _read_json(chapter_dir / "tradable_layer_summary.json")
    if not scorecard and not release and not summary:
        return {}
    selected_metrics = summary.get("selected_metrics") if isinstance(summary.get("selected_metrics"), Mapping) else {}
    fixed = summary.get("fixed_walk_forward_summary") if isinstance(summary.get("fixed_walk_forward_summary"), Mapping) else {}
    return {
        "pattern_id": pattern_id,
        "evidence_id": evidence_id,
        "score": scorecard.get("score") if scorecard else summary.get("score"),
        "strategy_id": selected.get("strategy_id") or release.get("selected_strategy_id") or summary.get("selected_strategy_id"),
        "release_status": release.get("release_status") or summary.get("release_status"),
        "scope": release.get("scope") or summary.get("scope"),
        "blockers": sorted(set(_items(scorecard.get("promotion_blockers")) + _items(release.get("failures")) + _items(summary.get("promotion_blockers")))),
        "trades": selected_metrics.get("trades"),
        "validation_trades": selected_metrics.get("validation_trades"),
        "holdout_trades": selected_metrics.get("holdout_trades"),
        "validation_total_return_pct": selected_metrics.get("validation_total_return_pct"),
        "holdout_total_return_pct": selected_metrics.get("holdout_total_return_pct"),
        "walk_forward_positive_fold_rate_pct": fixed.get("positive_fold_rate_pct"),
        "walk_forward_sum_return_pct": fixed.get("sum_fold_return_pct"),
        "path": str(chapter_dir),
    }


def _local_evidence(pattern_id: str, path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    if not payload:
        return {}
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    best = rows[0] if rows and isinstance(rows[0], Mapping) else {}
    guard = payload.get("no_overlift_guard") if isinstance(payload.get("no_overlift_guard"), Mapping) else {}
    blockers = set(_items(best.get("promotion_blockers")))
    blockers.update(_items(guard.get("remaining_tradable_blockers")))
    blockers.update(_items(guard.get("failures")))
    return {
        "pattern_id": pattern_id,
        "evidence_id": f"local_blocker_audit:{path.parent.name}",
        "score": payload.get("best_score") if payload.get("best_score") is not None else best.get("score"),
        "strategy_id": payload.get("best_strategy_id") or guard.get("best_diagnostic_strategy_id") or best.get("strategy_id"),
        "release_status": "PASS" if guard.get("promotion_decision") == "ELIGIBLE_FOR_FORMAL_PROMOTION_REVIEW" else "BLOCK",
        "scope": payload.get("scope"),
        "blockers": sorted(item for item in blockers if item),
        "trades": best.get("trades") or guard.get("best_diagnostic_trades"),
        "validation_trades": best.get("validation_trades"),
        "holdout_trades": best.get("holdout_trades"),
        "validation_total_return_pct": best.get("validation_total_return_pct"),
        "holdout_total_return_pct": best.get("holdout_total_return_pct"),
        "walk_forward_positive_fold_rate_pct": best.get("walk_forward_positive_fold_rate_pct"),
        "walk_forward_sum_return_pct": best.get("walk_forward_sum_return_pct"),
        "path": str(path),
    }


def _evidence_rows(pattern_id: str) -> list[dict[str, Any]]:
    rows = [
        row
        for evidence_id, base_dir in EVIDENCE_DIRS.items()
        if (row := _summary_evidence(pattern_id, evidence_id, base_dir))
    ]
    for path in LOCAL_BLOCKER_AUDITS.get(pattern_id, []):
        if path.exists() and (row := _local_evidence(pattern_id, path)):
            rows.append(row)
    return sorted(rows, key=lambda row: _as_float(row.get("score"), -1.0), reverse=True)


def _reason(blockers: Sequence[str], scope: str, score: float) -> str:
    blocker_set = set(blockers)
    if "scope_not_direct_long_cash_equity" in blocker_set or "scope_direct_long_cash" in blocker_set or scope == "defensive_informational":
        if score >= 90.0:
            return "defensive_or_downside_scope_caps_direct_tradable_promotion"
        return "defensive_scope_and_return_depth_cap_promotion"
    if "walk_forward_has_negative_fold" in blocker_set or "walk_forward_negative_folds" in blocker_set:
        return "fixed_walk_forward_instability_caps_promotion"
    if "validation_trade_count_below_12" in blocker_set or "holdout_trade_count_below_12" in blocker_set:
        return "validation_or_holdout_trade_depth_caps_promotion"
    if "median_adtv_participation_above_5pct" in blocker_set:
        return "liquidity_capacity_caps_promotion"
    if score < PROMOTION_THRESHOLD:
        return "score_threshold_caps_promotion_under_current_contract"
    return "promotion_blocker_remains_under_current_contract"


def _decision(current: Mapping[str, Any], best: Mapping[str, Any]) -> str:
    current_score = _as_float(current.get("tradable_score"), -1.0)
    best_score = _as_float(best.get("score"), -1.0)
    blockers = set(_items(current.get("tradable_blockers"))) | set(_items(best.get("blockers")))
    scope = str(best.get("scope") or current.get("tradable_applicability") or "")
    if best_score >= PROMOTION_THRESHOLD and not blockers and scope in {"long_cash_candidate", "long_up_breakout_branch", "tested_executable_layer"}:
        return "PROMOTION_REVIEW_AVAILABLE"
    if best_score >= current_score + MATERIAL_SCORE_LIFT:
        return "ADDITIONAL_TRADABLE_LIFT_AVAILABLE"
    return "STOP_TRADABLE_CEILING_REACHED"


def _audit_row(current: Mapping[str, Any]) -> dict[str, Any]:
    pattern_id = str(current.get("pattern_id") or "")
    evidence = _evidence_rows(pattern_id)
    best = evidence[0] if evidence else {}
    current_score = _as_float(current.get("tradable_score"), -1.0)
    best_score = _as_float(best.get("score"), -1.0)
    blockers = sorted(set(_items(current.get("tradable_blockers")) + _items(best.get("blockers"))))
    scope = str(best.get("scope") or current.get("tradable_applicability") or "")
    decision = _decision(current, best)
    return {
        "pattern_id": pattern_id,
        "current_score": None if current_score < 0 else round(current_score, 2),
        "current_status": current.get("tradable_status"),
        "current_evidence_id": current.get("tradable_evidence_id"),
        "best_known_score": None if best_score < 0 else round(best_score, 2),
        "best_known_evidence_id": best.get("evidence_id"),
        "best_known_strategy_id": best.get("strategy_id"),
        "score_lift_vs_current_pp": None if best_score < 0 or current_score < 0 else round(best_score - current_score, 2),
        "technical_ceiling_decision": decision,
        "remaining_ceiling_reason": _reason(blockers, scope, best_score),
        "remaining_blockers": blockers,
        "scope": scope,
        "evidence_count": len(evidence),
        "evidence_rows": evidence,
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Tradable Candidate Ceiling Audit",
        "",
        f"Audit: `{AUDIT_ID}`.",
        "",
        "This audit covers non-final chapters that still looked worth improving on the tradable/execution axis. It records whether any computed evidence layer still offers material score lift.",
        "",
        f"Promotion threshold: `{PROMOTION_THRESHOLD:.0f}`. Material score lift: `{MATERIAL_SCORE_LIFT:.1f}` points.",
        "",
        "| Pattern | Current | Best known | Lift | Decision | Remaining reason |",
        "|---|---:|---:|---:|---|---|",
    ]
    for row in payload.get("rows") or []:
        lines.append(
            f"| {row.get('pattern_id')} | {_as_float(row.get('current_score')):.2f} | {_as_float(row.get('best_known_score')):.2f} | "
            f"{_as_float(row.get('score_lift_vs_current_pp')):.2f} | {row.get('technical_ceiling_decision')} | {row.get('remaining_ceiling_reason')} |"
        )
    lines.extend(["", "## Evidence Detail", ""])
    for row in payload.get("rows") or []:
        lines.extend(
            [
                f"### {row.get('pattern_id')}",
                "",
                "| Evidence | Score | Strategy | Scope | Blockers |",
                "|---|---:|---|---|---|",
            ]
        )
        for evidence in row.get("evidence_rows") or []:
            lines.append(
                f"| {evidence.get('evidence_id')} | {_as_float(evidence.get('score')):.2f} | "
                f"{evidence.get('strategy_id') or ''} | {evidence.get('scope') or ''} | {', '.join(evidence.get('blockers') or [])} |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def run_audit(
    *,
    governance_path: Path = DEFAULT_GOVERNANCE,
    out_dir: Path = DEFAULT_OUT_DIR,
    patterns: Sequence[str] = DEFAULT_PATTERNS,
) -> dict[str, Path]:
    governance = _read_json(governance_path)
    current_by_pattern = {
        str(row.get("pattern_id")): row
        for row in governance.get("chapters", [])
        if isinstance(row, Mapping)
    }
    rows = [_audit_row(current_by_pattern[pattern_id]) for pattern_id in patterns if pattern_id in current_by_pattern]
    counts = {
        "patterns": len(rows),
        "ceiling_reached": sum(1 for row in rows if row.get("technical_ceiling_decision") == "STOP_TRADABLE_CEILING_REACHED"),
        "additional_tradable_lift_available": sum(1 for row in rows if row.get("technical_ceiling_decision") == "ADDITIONAL_TRADABLE_LIFT_AVAILABLE"),
        "promotion_review_available": sum(1 for row in rows if row.get("technical_ceiling_decision") == "PROMOTION_REVIEW_AVAILABLE"),
        "score_90_plus": sum(1 for row in rows if _as_float(row.get("best_known_score")) >= 90.0),
        "score_95_plus": sum(1 for row in rows if _as_float(row.get("best_known_score")) >= 95.0),
    }
    payload = {
        "audit_id": AUDIT_ID,
        "governance_matrix": str(governance_path),
        "promotion_threshold": PROMOTION_THRESHOLD,
        "material_score_lift": MATERIAL_SCORE_LIFT,
        "counts": counts,
        "rows": rows,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": out_dir / "tradable_candidate_ceiling_audit.json",
        "csv": out_dir / "tradable_candidate_ceiling_audit.csv",
        "md": out_dir / "tradable_candidate_ceiling_audit.md",
    }
    _write_json(paths["json"], payload)
    _write_csv(paths["csv"], rows)
    paths["md"].write_text(render_markdown(payload), encoding="utf-8")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Run tradable candidate ceiling audit.")
    parser.add_argument("--governance", default=str(DEFAULT_GOVERNANCE))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--patterns", default=",".join(DEFAULT_PATTERNS))
    args = parser.parse_args()
    patterns = tuple(item.strip() for item in str(args.patterns).split(",") if item.strip())
    paths = run_audit(governance_path=Path(args.governance), out_dir=Path(args.out_dir), patterns=patterns)
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
