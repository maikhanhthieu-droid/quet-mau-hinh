"""No-overlift ceiling audit for non-Pennant priority candidates.

This script does not run new optimization.  It reads the already-computed
generic, branch, and priority tradable layers, chooses the strongest available
evidence per pattern, and applies the same no-overlift promotion guard used for
Bull Pennant.  It is intentionally conservative: a diagnostic score is not a
promotion unless the score, blockers, scope, and walk-forward checks all pass.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/other_candidate_tradable_ceiling_audit")
AUDIT_ID = "other_candidate_tradable_ceiling_audit_v1"
NO_OVERLIFT_POLICY_ID = "tradable_no_overlift_guard_v1"
PROMOTION_SCORE_THRESHOLD = 95.0
DEFAULT_PATTERNS = (
    "triangles_ascending",
    "triangles_symmetrical",
    "wedges_falling",
    "double_bottoms_adam_adam",
)

EVIDENCE_LAYERS = {
    "generic_tradable_layer": Path("artifacts/scanner_v2/chapter_tradable_layer"),
    "branch_optimization_layer": Path("artifacts/scanner_v2/chapter_branch_optimization"),
    "priority_candidate_layer": Path("artifacts/scanner_v2/priority_candidate_tradable_optimization"),
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


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


def _scope_override(pattern_id: str, scope: Any) -> str:
    if pattern_id == "triangles_symmetrical" and scope == "long_up_breakout_branch":
        return "long_up_breakout_branch"
    return str(scope or "")


def _load_evidence(pattern_id: str, layer_id: str, base_dir: Path) -> dict[str, Any]:
    chapter_dir = base_dir / pattern_id
    summary = _read_json(chapter_dir / "priority_optimization_summary.json")
    if not summary:
        summary = _read_json(chapter_dir / "branch_optimization_summary.json")
    if not summary:
        summary = _read_json(chapter_dir / "tradable_layer_summary.json")
    scorecard = _read_json(chapter_dir / "scorecard.json")
    release = _read_json(chapter_dir / "release_candidate.json")
    if not scorecard and not summary:
        return {}
    selected_metrics = summary.get("selected_metrics") if isinstance(summary.get("selected_metrics"), Mapping) else {}
    fixed = summary.get("fixed_walk_forward_summary") if isinstance(summary.get("fixed_walk_forward_summary"), Mapping) else {}
    blockers = scorecard.get("promotion_blockers") or release.get("failures") or summary.get("promotion_blockers") or []
    return {
        "pattern_id": pattern_id,
        "evidence_id": layer_id,
        "score": scorecard.get("score") if scorecard else summary.get("score"),
        "classification": scorecard.get("classification") if scorecard else summary.get("classification"),
        "release_status": release.get("release_status") or summary.get("release_status"),
        "release_classification": release.get("classification") or summary.get("release_classification"),
        "scope": _scope_override(pattern_id, release.get("scope") or summary.get("scope")),
        "selected_strategy_id": release.get("selected_strategy_id") or summary.get("selected_strategy_id"),
        "promotion_blockers": ",".join(str(item) for item in blockers),
        "trades": selected_metrics.get("trades"),
        "validation_trades": selected_metrics.get("validation_trades"),
        "validation_total_return_pct": selected_metrics.get("validation_total_return_pct"),
        "holdout_trades": selected_metrics.get("holdout_trades"),
        "holdout_total_return_pct": selected_metrics.get("holdout_total_return_pct"),
        "median_adtv_participation_pct": selected_metrics.get("median_adtv_participation_pct"),
        "walk_forward_positive_fold_rate_pct": fixed.get("positive_fold_rate_pct"),
        "walk_forward_sum_return_pct": fixed.get("sum_fold_return_pct"),
        "walk_forward_worst_fold_return_pct": fixed.get("worst_fold_return_pct"),
        "scorecard_component_scores": scorecard.get("component_scores") if scorecard else None,
    }


def _build_no_overlift_guard(best: Mapping[str, Any]) -> dict[str, Any]:
    score = _as_float(best.get("score"))
    scope = str(best.get("scope") or "")
    blockers = {item.strip() for item in str(best.get("promotion_blockers") or "").split(",") if item.strip()}
    positive_fold_rate = _as_float(best.get("walk_forward_positive_fold_rate_pct"))
    checks: list[dict[str, Any]] = []

    def add_check(name: str, status: str, observed: Any, rule: str) -> None:
        checks.append({"check": name, "status": status, "observed": observed, "rule": rule})

    add_check(
        "score_threshold",
        "fail" if score < PROMOTION_SCORE_THRESHOLD else "pass",
        round(score, 2),
        f"best evidence score must be >= {PROMOTION_SCORE_THRESHOLD:.0f} before promotion review",
    )
    add_check(
        "scope_direct_long_cash",
        "fail" if scope not in {"long_cash_candidate", "long_up_breakout_branch"} else "pass",
        scope,
        "tradable-final review is only allowed for direct long-cash or explicit long-up branch scope",
    )
    add_check(
        "promotion_blockers",
        "fail" if blockers else "pass",
        ",".join(sorted(blockers)) or "none",
        "best evidence must have no remaining promotion blocker",
    )
    add_check(
        "walk_forward_positive",
        "fail" if positive_fold_rate < 100.0 else "pass",
        positive_fold_rate,
        "fixed-rule walk-forward must have no negative fold under the current contract",
    )
    add_check(
        "holdout_as_evidence_not_selection",
        "pass",
        "preserved in priority layer; branch layer remains diagnostic",
        "holdout/walk-forward may reject promotion but must not be treated as proof of finality",
    )

    failures = [check["check"] for check in checks if check["status"] == "fail"]
    warnings = [check["check"] for check in checks if check["status"] == "warn"]
    return {
        "policy_id": NO_OVERLIFT_POLICY_ID,
        "promotion_decision": "STOP_NO_PROMOTION_UNDER_NO_OVERLIFT_POLICY" if failures else "ELIGIBLE_FOR_FORMAL_PROMOTION_REVIEW",
        "failures": failures,
        "warnings": warnings,
        "checks": checks,
    }


def run_audit(*, out_dir: Path = DEFAULT_OUT_DIR, patterns: Sequence[str] = DEFAULT_PATTERNS) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    best_rows: list[dict[str, Any]] = []
    for pattern_id in patterns:
        evidence = [
            _load_evidence(pattern_id, layer_id, base_dir)
            for layer_id, base_dir in EVIDENCE_LAYERS.items()
        ]
        evidence = [row for row in evidence if row]
        rows.extend(evidence)
        if not evidence:
            continue
        best = max(evidence, key=lambda row: _as_float(row.get("score")))
        guard = _build_no_overlift_guard(best)
        best_rows.append(best | {"no_overlift_guard": guard})

    payload = {
        "audit_id": AUDIT_ID,
        "no_overlift_policy_id": NO_OVERLIFT_POLICY_ID,
        "pattern_count": len(best_rows),
        "best_rows": best_rows,
        "evidence_rows": rows,
    }
    paths = {
        "json": out_dir / "other_candidate_tradable_ceiling_audit.json",
        "csv": out_dir / "other_candidate_tradable_ceiling_audit.csv",
        "md": out_dir / "other_candidate_tradable_ceiling_audit.md",
    }
    _write_json(paths["json"], payload)
    _write_csv(paths["csv"], rows)
    paths["md"].write_text(render_markdown(payload), encoding="utf-8")
    return paths


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Other Candidate Tradable Ceiling Audit",
        "",
        f"Audit: `{AUDIT_ID}`",
        "",
        "This audit reads existing tradable evidence and applies the no-overlift promotion guard. It does not run new branch mining.",
        "",
        "| Pattern | Best evidence | Score | Scope | Decision | Failures |",
        "|---|---|---:|---|---|---|",
    ]
    for row in payload.get("best_rows") or []:
        guard = row.get("no_overlift_guard") if isinstance(row.get("no_overlift_guard"), Mapping) else {}
        score = "" if row.get("score") is None else f"{_as_float(row.get('score')):.2f}"
        lines.append(
            f"| {row.get('pattern_id')} | {row.get('evidence_id')} | {score} | {row.get('scope')} | "
            f"{guard.get('promotion_decision')} | {', '.join(guard.get('failures') or [])} |"
        )
    lines.extend(
        [
            "",
            "## Evidence Rows",
            "",
            "| Pattern | Evidence | Score | Blockers | Trades | Validation | Holdout | WF positive | WF sum |",
            "|---|---|---:|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in payload.get("evidence_rows") or []:
        score = "" if row.get("score") is None else f"{_as_float(row.get('score')):.2f}"
        lines.append(
            f"| {row.get('pattern_id')} | {row.get('evidence_id')} | {score} | {row.get('promotion_blockers') or ''} | "
            f"{row.get('trades') or ''} | {row.get('validation_total_return_pct') or ''} | "
            f"{row.get('holdout_total_return_pct') or ''} | {row.get('walk_forward_positive_fold_rate_pct') or ''} | "
            f"{row.get('walk_forward_sum_return_pct') or ''} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run no-overlift ceiling audit for non-Pennant priority candidates.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--patterns", default=",".join(DEFAULT_PATTERNS))
    args = parser.parse_args()
    patterns = [item.strip() for item in str(args.patterns).split(",") if item.strip()]
    paths = run_audit(out_dir=Path(args.out_dir), patterns=patterns)
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
