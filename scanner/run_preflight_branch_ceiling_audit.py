"""Audit whether weak-preflight patterns still have material branch lift.

This is a bounded ceiling audit for the preflight/reference axis. It does not
run a new scanner pass and it does not promote tradable status. Its job is to
make the latest preflight branch selection auditable: if the best remaining
candidate is not materially better than the selected branch, we stop pushing
this layer and move the blocker to data/scope/tradable execution.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


DEFAULT_PREFLIGHT_MATRIX = Path("artifacts/final_chapters/governance/chapter_tradable_preflight_matrix.json")
DEFAULT_OUT_DIR = Path("artifacts/final_chapters/governance")
AUDIT_ID = "preflight_branch_ceiling_audit_v1"
BRANCH_SELECTION_THRESHOLD_PP = 3.0
MATERIAL_RESIDUAL_LIFT_PP = 3.0
DEFAULT_PATTERNS = (
    "bear_flags",
    "bull_pennants",
    "triangles_symmetrical",
    "wedges_rising",
)


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


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fieldnames = [
        "pattern_id",
        "selected_branch_id",
        "selected_score",
        "selected_status",
        "aggregate_score",
        "selected_lift_vs_aggregate_pp",
        "best_unselected_branch_id",
        "best_unselected_score",
        "best_unselected_lift_vs_selected_pp",
        "branch_candidate_count",
        "n_events",
        "technical_ceiling_decision",
        "remaining_ceiling_reason",
        "warnings",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            out = {key: row.get(key) for key in fieldnames}
            out["warnings"] = ",".join(row.get("warnings") or [])
            writer.writerow(out)


def _candidate_score(candidate: Mapping[str, Any]) -> float:
    return _as_float(candidate.get("preflight_score"), -1.0)


def _ceiling_reason(row: Mapping[str, Any], residual_lift: float) -> str:
    warnings = set(row.get("warnings") or [])
    status = str(row.get("preflight_status") or "")
    if residual_lift >= MATERIAL_RESIDUAL_LIFT_PP:
        return "best_unselected_branch_can_still_lift_materially"
    if status == "preflight_strong":
        return "preflight_is_already_strong_and_remaining_branch_lift_is_not_material"
    if "thin_sample" in warnings and "cash_equity_downside_not_direct_tradable" in warnings:
        return "best_branch_is_selected_but_thin_sample_and_defensive_scope_cap_the_preflight_layer"
    if "thin_sample" in warnings:
        return "best_branch_is_selected_but_sample_depth_caps_the_preflight_layer"
    if "cash_equity_downside_not_direct_tradable" in warnings:
        return "best_branch_is_selected_but_downside_scope_caps_the_preflight_layer"
    return "best_branch_is_selected_and_remaining_branch_lift_is_not_material"


def _audit_row(row: Mapping[str, Any]) -> dict[str, Any]:
    selected_branch = str(row.get("preflight_branch_id") or "aggregate")
    selected_score = _as_float(row.get("preflight_score"))
    aggregate_score = _as_float(row.get("aggregate_preflight_score"), selected_score)
    candidates = [
        item
        for item in (row.get("preflight_branch_candidates") or [])
        if isinstance(item, Mapping) and item.get("branch_id") != selected_branch
    ]
    best_unselected = max(candidates, key=_candidate_score, default={})
    best_unselected_score = _candidate_score(best_unselected)
    residual_lift = 0.0 if best_unselected_score < 0 else round(best_unselected_score - selected_score, 2)
    selected_lift = round(selected_score - aggregate_score, 2)
    decision = (
        "ADDITIONAL_BRANCH_LIFT_AVAILABLE"
        if residual_lift >= MATERIAL_RESIDUAL_LIFT_PP
        else "STOP_PREFLIGHT_CEILING_REACHED"
    )
    return {
        "pattern_id": row.get("pattern_id"),
        "selected_branch_id": selected_branch,
        "selected_branch_description": row.get("preflight_branch_description"),
        "selected_score": round(selected_score, 2),
        "selected_status": row.get("preflight_status"),
        "selected_target_multiple": row.get("preflight_target_multiple"),
        "aggregate_score": round(aggregate_score, 2),
        "aggregate_status": row.get("aggregate_preflight_status") or ("same_as_selected" if selected_branch == "aggregate" else None),
        "selected_lift_vs_aggregate_pp": selected_lift,
        "branch_candidate_count": _as_int(row.get("branch_candidate_count")),
        "best_unselected_branch_id": best_unselected.get("branch_id"),
        "best_unselected_score": None if best_unselected_score < 0 else round(best_unselected_score, 2),
        "best_unselected_lift_vs_selected_pp": residual_lift,
        "technical_ceiling_decision": decision,
        "remaining_ceiling_reason": _ceiling_reason(row, residual_lift),
        "n_events": row.get("n_events"),
        "n_symbols": row.get("n_symbols"),
        "mfe_mae_ratio": row.get("mfe_mae_ratio"),
        "target_first_before_adverse_5pct_rate": row.get("target_first_before_adverse_5pct_rate"),
        "failure_5pct_rate": row.get("failure_5pct_rate"),
        "warnings": row.get("warnings") or [],
        "candidate_scores": row.get("preflight_branch_candidates") or [],
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Preflight Branch Ceiling Audit",
        "",
        f"Audit: `{AUDIT_ID}`.",
        "",
        "This audit checks whether the current preflight matrix still has an unselected branch with material score lift. It is a reference/preflight audit, not a tradable-final promotion.",
        "",
        f"Material lift threshold: `{MATERIAL_RESIDUAL_LIFT_PP:.1f}` points.",
        "",
        "| Pattern | Selected branch | Status | Score | Aggregate | Lift vs aggregate | Best remaining | Remaining lift | Decision | Reason |",
        "|---|---|---|---:|---:|---:|---|---:|---|---|",
    ]
    for row in payload.get("rows") or []:
        best_score = "" if row.get("best_unselected_score") is None else f"{_as_float(row.get('best_unselected_score')):.2f}"
        lines.append(
            f"| {row.get('pattern_id')} | {row.get('selected_branch_id')} | {row.get('selected_status')} | "
            f"{_as_float(row.get('selected_score')):.2f} | {_as_float(row.get('aggregate_score')):.2f} | "
            f"{_as_float(row.get('selected_lift_vs_aggregate_pp')):.2f} | {row.get('best_unselected_branch_id') or ''} {best_score} | "
            f"{_as_float(row.get('best_unselected_lift_vs_selected_pp')):.2f} | {row.get('technical_ceiling_decision')} | "
            f"{row.get('remaining_ceiling_reason')} |"
        )
    lines.extend(
        [
            "",
            "## Candidate Detail",
            "",
        ]
    )
    for row in payload.get("rows") or []:
        lines.extend(
            [
                f"### {row.get('pattern_id')}",
                "",
                "| Branch | Score | Status | N | MFE/MAE | Target-first | Failure |",
                "|---|---:|---|---:|---:|---:|---:|",
            ]
        )
        candidates = list(row.get("candidate_scores") or [])
        if row.get("selected_branch_id") == "aggregate":
            candidates = [
                {
                    "branch_id": "aggregate",
                    "preflight_score": row.get("selected_score"),
                    "preflight_status": row.get("selected_status"),
                    "n_events": row.get("n_events"),
                    "mfe_mae_ratio": row.get("mfe_mae_ratio"),
                    "target_first_before_adverse_5pct_rate": row.get("target_first_before_adverse_5pct_rate"),
                    "failure_5pct_rate": row.get("failure_5pct_rate"),
                }
            ] + candidates
        for candidate in candidates:
            score = "" if candidate.get("preflight_score") is None else f"{_as_float(candidate.get('preflight_score')):.2f}"
            ratio = "" if candidate.get("mfe_mae_ratio") is None else f"{_as_float(candidate.get('mfe_mae_ratio')):.2f}"
            target_first = (
                ""
                if candidate.get("target_first_before_adverse_5pct_rate") is None
                else f"{_as_float(candidate.get('target_first_before_adverse_5pct_rate')) * 100:.1f}%"
            )
            failure = (
                ""
                if candidate.get("failure_5pct_rate") is None
                else f"{_as_float(candidate.get('failure_5pct_rate')) * 100:.1f}%"
            )
            lines.append(
                f"| {candidate.get('branch_id')} | {score} | {candidate.get('preflight_status') or ''} | "
                f"{candidate.get('n_events') or ''} | {ratio} | {target_first} | {failure} |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def run_audit(
    *,
    preflight_matrix_path: Path = DEFAULT_PREFLIGHT_MATRIX,
    out_dir: Path = DEFAULT_OUT_DIR,
    patterns: Sequence[str] = DEFAULT_PATTERNS,
) -> dict[str, Path]:
    matrix = _read_json(preflight_matrix_path)
    rows_by_pattern = {
        str(row.get("pattern_id")): row
        for row in matrix.get("chapters", [])
        if isinstance(row, Mapping)
    }
    rows = [_audit_row(rows_by_pattern[pattern_id]) for pattern_id in patterns if pattern_id in rows_by_pattern]
    counts = {
        "patterns": len(rows),
        "ceiling_reached": sum(1 for row in rows if row.get("technical_ceiling_decision") == "STOP_PREFLIGHT_CEILING_REACHED"),
        "additional_branch_lift_available": sum(
            1 for row in rows if row.get("technical_ceiling_decision") == "ADDITIONAL_BRANCH_LIFT_AVAILABLE"
        ),
        "preflight_strong": sum(1 for row in rows if row.get("selected_status") == "preflight_strong"),
        "preflight_candidate": sum(1 for row in rows if row.get("selected_status") == "preflight_candidate"),
    }
    payload = {
        "audit_id": AUDIT_ID,
        "preflight_matrix": str(preflight_matrix_path),
        "branch_selection_threshold_pp": BRANCH_SELECTION_THRESHOLD_PP,
        "material_residual_lift_pp": MATERIAL_RESIDUAL_LIFT_PP,
        "counts": counts,
        "rows": rows,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": out_dir / "preflight_branch_ceiling_audit.json",
        "csv": out_dir / "preflight_branch_ceiling_audit.csv",
        "md": out_dir / "preflight_branch_ceiling_audit.md",
    }
    _write_json(paths["json"], payload)
    _write_csv(paths["csv"], rows)
    paths["md"].write_text(render_markdown(payload), encoding="utf-8")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Run preflight branch ceiling audit.")
    parser.add_argument("--preflight-matrix", default=str(DEFAULT_PREFLIGHT_MATRIX))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--patterns", default=",".join(DEFAULT_PATTERNS))
    args = parser.parse_args()
    patterns = tuple(item.strip() for item in str(args.patterns).split(",") if item.strip())
    paths = run_audit(
        preflight_matrix_path=Path(args.preflight_matrix),
        out_dir=Path(args.out_dir),
        patterns=patterns,
    )
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
