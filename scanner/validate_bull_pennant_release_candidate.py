"""Validate the Bull Pennant KPI evidence bundle.

This gate intentionally mirrors the Bull Flag release-candidate contract, but
it does not promote Pennant results when the walk-forward evidence is weaker.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_SCORECARD = Path("artifacts/scanner_v2/bull_pennants_tradable_setup/bull_pennant_tradable_scorecard.json")
DEFAULT_SELECTED_STRATEGY = Path("artifacts/scanner_v2/bull_pennants_tradable_setup/bull_pennant_tradable_selected_strategy.json")
DEFAULT_RULE_CONTRACT = Path("artifacts/scanner_v2/bull_pennants_tradable_setup/bull_pennant_tradable_frozen_rule_contract.json")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bull_pennants_release_candidate")


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _check(check_id: str, passed: bool, detail: str, *, severity: str = "High", evidence: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    return {
        "check_id": check_id,
        "status": "PASS" if passed else "FAIL",
        "severity": severity,
        "detail": detail,
        "evidence": dict(evidence or {}),
    }


def build_release_candidate(
    *,
    scorecard_path: Path = DEFAULT_SCORECARD,
    selected_strategy_path: Path = DEFAULT_SELECTED_STRATEGY,
    rule_contract_path: Path = DEFAULT_RULE_CONTRACT,
    min_score: float = 95.0,
    max_median_adtv_participation_pct: float = 5.0,
) -> Dict[str, Any]:
    artifacts = {
        "scorecard": str(scorecard_path),
        "selected_strategy": str(selected_strategy_path),
        "rule_contract": str(rule_contract_path),
    }
    missing = [str(path) for path in (scorecard_path, selected_strategy_path, rule_contract_path) if not path.exists()]
    if missing:
        checks = [_check("artifact_completeness", False, "Required Bull Pennant KPI artifacts are missing.", severity="Critical", evidence={"missing": missing})]
        return {
            "release_id": "bull_pennant_kpi_gate_v1",
            "release_status": "BLOCK",
            "classification": "blocked",
            "artifacts": artifacts,
            "checks": checks,
            "failures": [check["check_id"] for check in checks if check["status"] == "FAIL"],
        }

    scorecard = _read_json(scorecard_path)
    selected_strategy = _read_json(selected_strategy_path)
    rule_contract = _read_json(rule_contract_path)
    selected_metrics = selected_strategy.get("selected_metrics") if isinstance(selected_strategy.get("selected_metrics"), Mapping) else {}
    walk_forward = selected_strategy.get("walk_forward_summary") if isinstance(selected_strategy.get("walk_forward_summary"), Mapping) else {}
    adaptive_walk_forward = selected_strategy.get("adaptive_walk_forward_summary") if isinstance(selected_strategy.get("adaptive_walk_forward_summary"), Mapping) else {}
    cost_stress = selected_strategy.get("cost_stress_summary") if isinstance(selected_strategy.get("cost_stress_summary"), Mapping) else {}
    source_scope = selected_strategy.get("source_scope") if isinstance(selected_strategy.get("source_scope"), Mapping) else {}

    score = _as_float(scorecard.get("score"))
    blockers = list(scorecard.get("promotion_blockers") or []) if isinstance(scorecard.get("promotion_blockers"), list) else []
    median_adtv = _as_float(selected_metrics.get("median_adtv_participation_pct"), default=999.0)
    checks = [
        _check("artifact_completeness", True, "All Bull Pennant KPI artifacts are present.", severity="Critical", evidence=artifacts),
        _check("score_kpi", score >= float(min_score), "Bull Pennant must meet the Bull Flag-style KPI threshold before promotion.", severity="Critical", evidence={"score": score, "threshold": float(min_score)}),
        _check("no_promotion_blockers", not blockers, "Scorecard must have no promotion blockers.", severity="Critical", evidence={"blockers": blockers}),
        _check(
            "walk_forward_positive",
            _as_float(walk_forward.get("positive_fold_rate_pct")) >= 100.0,
            "Fixed-rule walk-forward must have no negative fold to match Bull Flag release quality.",
            severity="Critical",
            evidence=walk_forward,
        ),
        _check(
            "adaptive_walk_forward_reported",
            adaptive_walk_forward.get("status") == "walk_forward_complete",
            "Adaptive walk-forward evidence must be generated and reported.",
            severity="High",
            evidence=adaptive_walk_forward,
        ),
        _check(
            "capacity_kpi",
            median_adtv <= float(max_median_adtv_participation_pct),
            "Median ADTV participation must remain under the execution capacity KPI.",
            severity="High",
            evidence={"median_adtv_participation_pct": median_adtv, "threshold": float(max_median_adtv_participation_pct)},
        ),
        _check(
            "cost_stress_positive",
            _as_float(cost_stress.get("positive_scenario_rate_pct")) >= 100.0,
            "All cost-stress scenarios should remain positive before promotion.",
            severity="High",
            evidence=cost_stress,
        ),
        _check(
            "public_grade_scope",
            source_scope.get("variant") == "bull_pennant" and _as_float(source_scope.get("public_grade_events")) >= 250.0,
            "Release scope must be Bull Pennant public-grade events with enough sample depth.",
            severity="High",
            evidence=source_scope,
        ),
        _check(
            "target_contract",
            "Bull Pennant" in str(rule_contract.get("target_rule") or ""),
            "Frozen contract must name the Bull Pennant target rule.",
            severity="High",
            evidence={"target_rule": rule_contract.get("target_rule")},
        ),
    ]
    failures = [check["check_id"] for check in checks if check["status"] == "FAIL"]
    release_status = "PASS" if not failures else "BLOCK"
    return {
        "release_id": "bull_pennant_kpi_gate_v1",
        "release_status": release_status,
        "classification": "bull_pennant_tradable_research_candidate_95" if release_status == "PASS" else "blocked",
        "score": score,
        "claim_level": "tradable-research-candidate under available-series scope" if release_status == "PASS" else "watchlist-reference; not promoted to tradable KPI final",
        "artifacts": artifacts,
        "selected_strategy_id": selected_strategy.get("selected_strategy_id"),
        "selected_metrics": {
            "trades": selected_metrics.get("trades"),
            "total_return_pct": selected_metrics.get("total_return_pct"),
            "validation_total_return_pct": selected_metrics.get("validation_total_return_pct"),
            "holdout_total_return_pct": selected_metrics.get("holdout_total_return_pct"),
            "median_adtv_participation_pct": selected_metrics.get("median_adtv_participation_pct"),
        },
        "walk_forward": walk_forward,
        "adaptive_walk_forward": adaptive_walk_forward,
        "cost_stress": cost_stress,
        "scorecard": scorecard,
        "checks": checks,
        "failures": failures,
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Bull Pennant KPI Gate",
        "",
        f"- Status: `{payload.get('release_status')}`",
        f"- Classification: `{payload.get('classification')}`",
        f"- Score: `{payload.get('score')}`",
        f"- Selected strategy: `{payload.get('selected_strategy_id')}`",
        f"- Claim level: {payload.get('claim_level')}",
        "",
        "## Checks",
        "",
        "| Check | Status | Severity | Detail |",
        "|---|---|---|---|",
    ]
    for check in payload.get("checks", []):
        if isinstance(check, Mapping):
            lines.append(f"| {check.get('check_id')} | {check.get('status')} | {check.get('severity')} | {str(check.get('detail') or '').replace('|', '/')} |")
    lines.extend(["", "## Main Metrics", "", "```json", json.dumps(payload.get("selected_metrics"), ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(lines)


def write_release_candidate(payload: Mapping[str, Any], out_dir: Path = DEFAULT_OUT_DIR) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": out_dir / "bull_pennant_release_candidate.json",
        "md": out_dir / "bull_pennant_release_candidate.md",
    }
    paths["json"].write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    paths["md"].write_text(render_markdown(payload), encoding="utf-8")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Bull Pennant KPI release gate.")
    parser.add_argument("--scorecard", default=str(DEFAULT_SCORECARD))
    parser.add_argument("--selected-strategy", default=str(DEFAULT_SELECTED_STRATEGY))
    parser.add_argument("--rule-contract", default=str(DEFAULT_RULE_CONTRACT))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--min-score", type=float, default=95.0)
    args = parser.parse_args()
    payload = build_release_candidate(
        scorecard_path=Path(args.scorecard),
        selected_strategy_path=Path(args.selected_strategy),
        rule_contract_path=Path(args.rule_contract),
        min_score=args.min_score,
    )
    paths = write_release_candidate(payload, Path(args.out_dir))
    for key, path in paths.items():
        print(f"{key}: {path}")
    print(f"status: {payload['release_status']}")
    if payload["release_status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
