"""Validate the Bull Flag release-candidate evidence bundle.

This gate is deliberately stricter than the descriptive chapter data gate. It
does not optimize or rerun the scanner; it only reads frozen artifacts and
fails if the Bull Flag tradable-research candidate falls below the current KPI
contract.
"""

from __future__ import annotations

import argparse
import json
import textwrap
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_MAIN_SCORECARD = Path("artifacts/scanner_v2/bull_flags_tradable_setup/bull_flag_tradable_scorecard.json")
DEFAULT_SELECTED_STRATEGY = Path("artifacts/scanner_v2/bull_flags_tradable_setup/bull_flag_tradable_selected_strategy.json")
DEFAULT_RULE_CONTRACT = Path("artifacts/scanner_v2/bull_flags_tradable_setup/bull_flag_tradable_frozen_rule_contract.json")
DEFAULT_FRESH_GATE = Path("artifacts/scanner_v2/bull_flags_fresh_discovery/gate/bull_flag_wider_oos_gate.json")
DEFAULT_DATA_GATE = Path("artifacts/scanner_v2/bull_flags_adaptive_grid/scans/bull_flag_v2_split_stable_recovery/data_gate_audit.json")
DEFAULT_SUPPORTING_ROBUSTNESS = Path("artifacts/scanner_v2/bull_flags_supporting_robustness/bull_flag_supporting_robustness.json")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bull_flags_release_candidate")
BULKOWSKI_FLAGS_URL = "https://thepatternsite.com/flags.html"
BULKOWSKI_MEASURE_URL = "https://thepatternsite.com/measure.html"


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def _nested(mapping: Mapping[str, Any], *keys: str) -> Any:
    value: Any = mapping
    for key in keys:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


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
    main_scorecard_path: Path = DEFAULT_MAIN_SCORECARD,
    selected_strategy_path: Path = DEFAULT_SELECTED_STRATEGY,
    rule_contract_path: Path = DEFAULT_RULE_CONTRACT,
    fresh_gate_path: Path = DEFAULT_FRESH_GATE,
    data_gate_path: Path = DEFAULT_DATA_GATE,
    supporting_robustness_path: Path = DEFAULT_SUPPORTING_ROBUSTNESS,
    min_main_score: float = 95.0,
    min_fresh_score: float = 95.0,
    max_median_adtv_participation_pct: float = 5.0,
) -> Dict[str, Any]:
    artifacts = {
        "main_scorecard": str(main_scorecard_path),
        "selected_strategy": str(selected_strategy_path),
        "rule_contract": str(rule_contract_path),
        "fresh_gate": str(fresh_gate_path),
        "data_gate": str(data_gate_path),
        "supporting_robustness": str(supporting_robustness_path),
    }
    artifact_paths = [main_scorecard_path, selected_strategy_path, rule_contract_path, fresh_gate_path, data_gate_path, supporting_robustness_path]
    missing = [str(path) for path in artifact_paths if not path.exists()]
    if missing:
        checks = [_check("artifact_completeness", False, "Required Bull Flag release artifacts are missing.", severity="Critical", evidence={"missing": missing})]
        return {
            "release_id": "bull_flag_tradable_rc_v1",
            "release_status": "BLOCK",
            "classification": "blocked",
            "artifacts": artifacts,
            "checks": checks,
            "failures": [check["check_id"] for check in checks if check["status"] == "FAIL"],
        }

    main_scorecard = _read_json(main_scorecard_path)
    selected_strategy = _read_json(selected_strategy_path)
    rule_contract = _read_json(rule_contract_path)
    fresh_gate = _read_json(fresh_gate_path)
    data_gate = _read_json(data_gate_path)
    supporting_robustness = _read_json(supporting_robustness_path)

    selected_metrics = selected_strategy.get("selected_metrics") if isinstance(selected_strategy.get("selected_metrics"), Mapping) else {}
    fresh_eval = fresh_gate.get("full_profile_evaluation") if isinstance(fresh_gate.get("full_profile_evaluation"), Mapping) else {}
    fresh_scorecard = fresh_eval.get("scorecard") if isinstance(fresh_eval.get("scorecard"), Mapping) else {}
    fresh_summary = fresh_eval.get("summary") if isinstance(fresh_eval.get("summary"), Mapping) else {}
    fresh_walk_forward = fresh_eval.get("walk_forward_summary") if isinstance(fresh_eval.get("walk_forward_summary"), Mapping) else {}
    scope = fresh_gate.get("scope") if isinstance(fresh_gate.get("scope"), Mapping) else {}
    main_walk_forward = selected_strategy.get("walk_forward_summary") if isinstance(selected_strategy.get("walk_forward_summary"), Mapping) else {}

    main_score = _as_float(main_scorecard.get("score"))
    fresh_score = _as_float(fresh_scorecard.get("score"))
    selected_score = _as_float(_nested(selected_strategy, "tradable_scorecard", "score"))
    main_blockers = _as_list(main_scorecard.get("promotion_blockers"))
    fresh_blockers = _as_list(fresh_scorecard.get("promotion_blockers"))
    support_failures = _as_list(supporting_robustness.get("failures"))
    main_median_adtv = _as_float(selected_metrics.get("median_adtv_participation_pct"), default=999.0)
    fresh_median_adtv = _as_float(fresh_summary.get("median_adtv_participation_pct"), default=999.0)
    contract_sizing = rule_contract.get("sizing") if isinstance(rule_contract.get("sizing"), Mapping) else {}
    contract_filters = rule_contract.get("execution_filters") if isinstance(rule_contract.get("execution_filters"), Mapping) else {}
    selected_regimes = selected_metrics.get("allowed_market_regimes")
    contract_regimes = contract_filters.get("allowed_market_regimes")
    expected_regimes = ["bull", "bear"]

    checks = [
        _check("artifact_completeness", True, "All required Bull Flag release artifacts are present.", severity="Critical", evidence=artifacts),
        _check(
            "main_score_kpi",
            main_score >= float(min_main_score),
            "Main Bull Flag tradable artifact must stay at or above the KPI threshold.",
            severity="Critical",
            evidence={"score": main_score, "threshold": float(min_main_score)},
        ),
        _check(
            "main_selected_score_consistency",
            abs(main_score - selected_score) < 1e-9,
            "Selected strategy embedded scorecard must match the standalone scorecard artifact.",
            severity="High",
            evidence={"standalone_score": main_score, "selected_strategy_score": selected_score},
        ),
        _check(
            "main_no_promotion_blockers",
            not main_blockers,
            "Main scorecard must have no promotion blockers.",
            severity="Critical",
            evidence={"blockers": main_blockers},
        ),
        _check(
            "main_walk_forward_positive",
            _as_float(main_walk_forward.get("positive_fold_rate_pct")) >= 100.0,
            "Main fixed-rule walk-forward must have no negative fold.",
            severity="Critical",
            evidence=main_walk_forward,
        ),
        _check(
            "main_capacity_kpi",
            main_median_adtv <= float(max_median_adtv_participation_pct),
            "Main median ADTV participation must remain under the execution capacity KPI.",
            severity="High",
            evidence={"median_adtv_participation_pct": main_median_adtv, "threshold": float(max_median_adtv_participation_pct)},
        ),
        _check(
            "frozen_scope_contract",
            selected_metrics.get("min_breakout_date") == "2019-01-01"
            and selected_regimes == expected_regimes
            and contract_filters.get("min_breakout_date") == "2019-01-01"
            and contract_regimes == expected_regimes,
            "Frozen rule must keep the known-regime post-2019 research scope.",
            severity="Critical",
            evidence={
                "selected_min_breakout_date": selected_metrics.get("min_breakout_date"),
                "selected_allowed_market_regimes": selected_regimes,
                "contract_min_breakout_date": contract_filters.get("min_breakout_date"),
                "contract_allowed_market_regimes": contract_regimes,
            },
        ),
        _check(
            "frozen_sizing_contract",
            _as_float(contract_sizing.get("target_adtv_participation_pct")) <= 10.0
            and _as_float(contract_sizing.get("max_adtv_participation_pct")) <= 30.0,
            "Frozen rule must keep capacity-aware sizing caps.",
            severity="High",
            evidence={
                "target_adtv_participation_pct": contract_sizing.get("target_adtv_participation_pct"),
                "max_adtv_participation_pct": contract_sizing.get("max_adtv_participation_pct"),
            },
        ),
        _check(
            "fresh_score_kpi",
            fresh_score >= float(min_fresh_score),
            "Fresh-source candidate gate must stay at or above the KPI threshold.",
            severity="Critical",
            evidence={"score": fresh_score, "threshold": float(min_fresh_score)},
        ),
        _check(
            "fresh_no_promotion_blockers",
            not fresh_blockers,
            "Fresh-source gate must have no promotion blockers.",
            severity="Critical",
            evidence={"blockers": fresh_blockers},
        ),
        _check(
            "fresh_scope",
            scope.get("is_fresh_oos") is True and not _as_list(scope.get("failures")),
            "Fresh-source gate must be a fresh OOS candidate with no scope failures.",
            severity="Critical",
            evidence=scope,
        ),
        _check(
            "fresh_walk_forward_positive",
            _as_float(fresh_walk_forward.get("positive_fold_rate_pct")) >= 100.0,
            "Fresh fixed-rule walk-forward must have no negative fold.",
            severity="Critical",
            evidence=fresh_walk_forward,
        ),
        _check(
            "fresh_capacity_kpi",
            fresh_median_adtv <= float(max_median_adtv_participation_pct),
            "Fresh median ADTV participation must remain under the execution capacity KPI.",
            severity="High",
            evidence={"median_adtv_participation_pct": fresh_median_adtv, "threshold": float(max_median_adtv_participation_pct)},
        ),
        _check(
            "available_series_data_gate",
            data_gate.get("investment_reference_data_gates_pass") is True and data_gate.get("universe_scope") == "available_series_descriptive",
            "Data gate must pass under the explicitly limited available-series scope.",
            severity="High",
            evidence={
                "investment_reference_data_gates_pass": data_gate.get("investment_reference_data_gates_pass"),
                "blocked_by": data_gate.get("blocked_by"),
                "universe_scope": data_gate.get("universe_scope"),
                "summary": data_gate.get("summary"),
            },
        ),
        _check(
            "supporting_robustness_closed",
            supporting_robustness.get("status") == "PASS" and not support_failures,
            "Overlap sensitivity, liquidity bucket robustness, and OHLCV price-limit proxy checks must pass.",
            severity="High",
            evidence={
                "status": supporting_robustness.get("status"),
                "failures": support_failures,
                "closed_data_gate_partials": supporting_robustness.get("closed_data_gate_partials"),
            },
        ),
    ]
    failures = [check["check_id"] for check in checks if check["status"] == "FAIL"]
    warnings = list(scope.get("warnings") or []) if isinstance(scope.get("warnings"), list) else []
    data_partials = [
        gate.get("gate_id")
        for gate in data_gate.get("gates", [])
        if isinstance(gate, Mapping) and gate.get("status") == "PARTIAL"
    ]
    closed_partials = set(supporting_robustness.get("closed_data_gate_partials") or [])
    remaining_partials = [gate_id for gate_id in data_partials if gate_id not in closed_partials]
    release_status = "PASS" if not failures else "BLOCK"
    conservative_score = round(min(main_score, fresh_score), 2)
    return {
        "release_id": "bull_flag_tradable_rc_v1",
        "release_status": release_status,
        "classification": "bull_flag_tradable_research_candidate_95" if release_status == "PASS" else "blocked",
        "conservative_score": conservative_score,
        "claim_level": "tradable-research-candidate under available-series descriptive scope",
        "forbidden_claims": [
            "production trading system",
            "personalized buy/sell recommendation",
            "full historical point-in-time universe coverage",
            "historical VN30/VN100 membership conclusion",
            "official corporate-action factor audit",
        ],
        "remaining_caveats": sorted(set(warnings + remaining_partials)),
        "closed_supporting_caveats": sorted(closed_partials),
        "artifacts": artifacts,
        "main": {
            "score": main_score,
            "classification": main_scorecard.get("classification"),
            "blockers": main_blockers,
            "selected_strategy_id": selected_strategy.get("selected_strategy_id"),
            "trades": selected_metrics.get("trades"),
            "total_return_pct": selected_metrics.get("total_return_pct"),
            "validation_total_return_pct": selected_metrics.get("validation_total_return_pct"),
            "holdout_total_return_pct": selected_metrics.get("holdout_total_return_pct"),
            "median_adtv_participation_pct": main_median_adtv,
            "walk_forward": main_walk_forward,
        },
        "fresh": {
            "score": fresh_score,
            "classification": fresh_scorecard.get("classification"),
            "blockers": fresh_blockers,
            "scope": scope,
            "events": fresh_eval.get("events_n"),
            "trades": fresh_summary.get("trades"),
            "total_return_pct": fresh_summary.get("total_return_pct"),
            "validation_total_return_pct": fresh_summary.get("validation_total_return_pct"),
            "holdout_total_return_pct": fresh_summary.get("holdout_total_return_pct"),
            "median_adtv_participation_pct": fresh_median_adtv,
            "walk_forward": fresh_walk_forward,
        },
        "data_gate": {
            "pass": data_gate.get("investment_reference_data_gates_pass"),
            "universe_scope": data_gate.get("universe_scope"),
            "blocked_by": data_gate.get("blocked_by"),
            "summary": data_gate.get("summary"),
            "partial_gates": data_partials,
        },
        "supporting_robustness": {
            "status": supporting_robustness.get("status"),
            "failures": support_failures,
            "closed_data_gate_partials": supporting_robustness.get("closed_data_gate_partials"),
            "profiles": [
                {
                    "profile_id": profile.get("profile_id"),
                    "status": profile.get("status"),
                    "scoped_events": profile.get("scoped_events"),
                    "checks": profile.get("checks"),
                }
                for profile in supporting_robustness.get("profiles", [])
                if isinstance(profile, Mapping)
            ],
        },
        "checks": checks,
        "failures": failures,
    }


def render_release_candidate_markdown(payload: Mapping[str, Any]) -> str:
    main = payload.get("main") if isinstance(payload.get("main"), Mapping) else {}
    fresh = payload.get("fresh") if isinstance(payload.get("fresh"), Mapping) else {}
    data_gate = payload.get("data_gate") if isinstance(payload.get("data_gate"), Mapping) else {}
    support = payload.get("supporting_robustness") if isinstance(payload.get("supporting_robustness"), Mapping) else {}
    lines = [
        "# Bull Flag Release Candidate Gate",
        "",
        f"- Status: `{payload.get('release_status')}`",
        f"- Classification: `{payload.get('classification')}`",
        f"- Conservative score: `{payload.get('conservative_score')}`",
        f"- Claim level: {payload.get('claim_level')}",
        "",
        "## KPI Snapshot",
        "",
        "| Scope | Score | Blockers | Trades | Total return | Validation | Holdout | Median ADTV participation |",
        "|---|---:|---|---:|---:|---:|---:|---:|",
        "| Main artifact | {score} | {blockers} | {trades} | {total} | {validation} | {holdout} | {adtv} |".format(
            score=main.get("score"),
            blockers=", ".join(main.get("blockers") or []) or "none",
            trades=main.get("trades"),
            total=main.get("total_return_pct"),
            validation=main.get("validation_total_return_pct"),
            holdout=main.get("holdout_total_return_pct"),
            adtv=main.get("median_adtv_participation_pct"),
        ),
        "| Fresh candidate | {score} | {blockers} | {trades} | {total} | {validation} | {holdout} | {adtv} |".format(
            score=fresh.get("score"),
            blockers=", ".join(fresh.get("blockers") or []) or "none",
            trades=fresh.get("trades"),
            total=fresh.get("total_return_pct"),
            validation=fresh.get("validation_total_return_pct"),
            holdout=fresh.get("holdout_total_return_pct"),
            adtv=fresh.get("median_adtv_participation_pct"),
        ),
        "",
        "## Data Gate",
        "",
        f"- Pass: `{data_gate.get('pass')}`",
        f"- Universe scope: `{data_gate.get('universe_scope')}`",
        f"- Blocked by: `{', '.join(data_gate.get('blocked_by') or []) or 'none'}`",
        f"- Partial gates: `{', '.join(data_gate.get('partial_gates') or []) or 'none'}`",
        "",
        "## Supporting Robustness",
        "",
        f"- Status: `{support.get('status')}`",
        f"- Failures: `{', '.join(support.get('failures') or []) or 'none'}`",
        f"- Closed caveats: `{', '.join(payload.get('closed_supporting_caveats') or []) or 'none'}`",
        "",
        "| Profile | Status | Scoped events | Overlap | Liquidity | Price-limit proxy |",
        "|---|---|---:|---|---|---|",
    ]
    for profile in support.get("profiles", []):
        if not isinstance(profile, Mapping):
            continue
        checks = profile.get("checks") if isinstance(profile.get("checks"), Mapping) else {}
        lines.append(
            "| {profile} | {status} | {events} | {overlap} | {liq} | {limit} |".format(
                profile=profile.get("profile_id"),
                status=profile.get("status"),
                events=profile.get("scoped_events"),
                overlap=checks.get("overlap_sensitivity"),
                liq=checks.get("liquidity_bucket_robustness"),
                limit=checks.get("price_limit_proxy_robustness"),
            )
        )
    lines.extend(
        [
            "",
            "## Checks",
            "",
            "| Check | Status | Severity | Detail |",
            "|---|---|---|---|",
        ]
    )
    for check in payload.get("checks", []):
        if not isinstance(check, Mapping):
            continue
        lines.append(
            "| {check} | {status} | {severity} | {detail} |".format(
                check=check.get("check_id"),
                status=check.get("status"),
                severity=check.get("severity"),
                detail=str(check.get("detail") or "").replace("|", "/"),
            )
        )
    lines.extend(
        [
            "",
            "## Claim Boundaries",
            "",
        ]
    )
    for claim in payload.get("forbidden_claims", []):
        lines.append(f"- Không claim: `{claim}`")
    lines.extend(
        [
            "",
            "## Bulkowski Alignment",
            "",
            f"- Flags source: {BULKOWSKI_FLAGS_URL}",
            f"- Measure rule source: {BULKOWSKI_MEASURE_URL}",
            "- Alignment: base target `0.46x pole` follows Bulkowski's adjusted Flags measure-rule logic.",
            "- Difference: this release is a Vietnam available-series tradable-research candidate, not Bulkowski's descriptive perfect-trade table.",
        ]
    )
    return "\n".join(lines) + "\n"


def _fmt(value: Any, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        text = f"{value:.2f}".rstrip("0").rstrip(".")
    else:
        text = str(value)
    return f"{text}{suffix}"


def _text_lines(text: str, *, width: int = 92) -> List[str]:
    return textwrap.wrap(str(text), width=width) or [""]


def _draw_wrapped_lines(fig: Any, lines: Sequence[str], *, x: float, y: float, width: int = 96, fontsize: float = 8.4, line_step: float = 0.020) -> float:
    for line in lines:
        for wrapped in _text_lines(line, width=width):
            fig.text(x, y, wrapped, fontsize=fontsize, ha="left", va="top")
            y -= line_step
        y -= line_step * 0.35
    return y


def _draw_table(
    fig: Any,
    rows: Sequence[Sequence[Any]],
    *,
    x: float,
    y: float,
    col_x: Sequence[float],
    fontsize: float = 7.8,
    row_step: float = 0.027,
) -> float:
    for row_index, row in enumerate(rows):
        weight = "bold" if row_index == 0 else None
        for col_index, value in enumerate(row):
            fig.text(x + col_x[col_index], y, str(value), fontsize=fontsize, ha="left", va="top", weight=weight)
        y -= row_step
    return y


def render_release_candidate_pdf(payload: Mapping[str, Any], pdf_path: Path) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    main = payload.get("main") if isinstance(payload.get("main"), Mapping) else {}
    fresh = payload.get("fresh") if isinstance(payload.get("fresh"), Mapping) else {}
    data_gate = payload.get("data_gate") if isinstance(payload.get("data_gate"), Mapping) else {}
    support = payload.get("supporting_robustness") if isinstance(payload.get("supporting_robustness"), Mapping) else {}

    page_bg = "#fffdf8"
    ink = "#171717"
    muted = "#555555"

    with PdfPages(pdf_path) as pdf:
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.patch.set_facecolor(page_bg)
        fig.text(0.5, 0.93, "Bull Flag Release Candidate", ha="center", va="top", fontsize=22, weight="bold", color=ink)
        fig.text(0.5, 0.895, "Tradable research candidate 95+ under available-series scope", ha="center", va="top", fontsize=10.5, color=muted)
        rows = [
            ("Release status", payload.get("release_status")),
            ("Classification", payload.get("classification")),
            ("Conservative score", payload.get("conservative_score")),
            ("Main score", main.get("score")),
            ("Fresh candidate score", fresh.get("score")),
            ("Main trades", main.get("trades")),
            ("Fresh trades", fresh.get("trades")),
            ("Main total return", _fmt(main.get("total_return_pct"), "%")),
            ("Fresh total return", _fmt(fresh.get("total_return_pct"), "%")),
            ("Main validation / holdout", f"{_fmt(main.get('validation_total_return_pct'), '%')} / {_fmt(main.get('holdout_total_return_pct'), '%')}"),
            ("Fresh validation / holdout", f"{_fmt(fresh.get('validation_total_return_pct'), '%')} / {_fmt(fresh.get('holdout_total_return_pct'), '%')}"),
            ("Main median ADTV participation", _fmt(main.get("median_adtv_participation_pct"), "%")),
            ("Fresh median ADTV participation", _fmt(fresh.get("median_adtv_participation_pct"), "%")),
        ]
        y = 0.82
        for label, value in rows:
            fig.text(0.12, y, label, fontsize=9.6, weight="bold", ha="left", va="top", color=ink)
            fig.text(0.52, y, str(value), fontsize=9.6, ha="left", va="top", color=ink)
            y -= 0.035
        y -= 0.015
        _draw_wrapped_lines(
            fig,
            [
                "Decision: PASS as a Bull Flag tradable-research candidate under available-series descriptive scope.",
                "This is not a production trading system and not a personalized buy/sell recommendation.",
            ],
            x=0.12,
            y=y,
            width=96,
            fontsize=9.0,
        )
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        fig = plt.figure(figsize=(8.27, 11.69))
        fig.patch.set_facecolor(page_bg)
        fig.text(0.08, 0.93, "1. Gates And Robustness", fontsize=16, weight="bold", ha="left", va="top", color=ink)
        gate_rows = [
            ("Gate", "Value"),
            ("Data gate pass", data_gate.get("pass")),
            ("Universe scope", data_gate.get("universe_scope")),
            ("Blocked by", ", ".join(data_gate.get("blocked_by") or []) or "none"),
            ("Partial gates", ", ".join(data_gate.get("partial_gates") or []) or "none"),
            ("Supporting robustness", support.get("status")),
            ("Supporting failures", ", ".join(support.get("failures") or []) or "none"),
            ("Closed caveats", ", ".join(payload.get("closed_supporting_caveats") or []) or "none"),
            ("Remaining caveats", ", ".join(payload.get("remaining_caveats") or []) or "none"),
        ]
        y = _draw_table(fig, gate_rows, x=0.08, y=0.875, col_x=[0.0, 0.32], fontsize=8.2, row_step=0.031)
        y -= 0.02
        profile_rows = [("Profile", "Status", "Events", "Overlap", "Liquidity", "Limit proxy")]
        for profile in support.get("profiles", []):
            if not isinstance(profile, Mapping):
                continue
            checks = profile.get("checks") if isinstance(profile.get("checks"), Mapping) else {}
            profile_rows.append(
                (
                    profile.get("profile_id"),
                    profile.get("status"),
                    profile.get("scoped_events"),
                    checks.get("overlap_sensitivity"),
                    checks.get("liquidity_bucket_robustness"),
                    checks.get("price_limit_proxy_robustness"),
                )
            )
        _draw_table(fig, profile_rows, x=0.08, y=y, col_x=[0.0, 0.23, 0.34, 0.46, 0.59, 0.73], fontsize=7.2, row_step=0.027)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        fig = plt.figure(figsize=(8.27, 11.69))
        fig.patch.set_facecolor(page_bg)
        fig.text(0.08, 0.93, "2. Bulkowski Alignment", fontsize=16, weight="bold", ha="left", va="top", color=ink)
        y = 0.87
        alignment_rows = [
            ("Bulkowski Flags concept", "Vietnam Bull Flag release"),
            ("Short continuation pattern", "Scanner requires flagpole, short flag, slope/parallel controls"),
            ("Adjusted measure rule", "Base target is 0.46x pole"),
            ("Full pole target", "Kept only as legacy/stretch benchmark"),
            ("Perfect-trade reference", "Separated from executable tradable setup"),
            ("Up/down flags", "Bull Flag is release candidate; Bear Flag remains defensive/informational"),
        ]
        y = _draw_table(fig, alignment_rows, x=0.08, y=y, col_x=[0.0, 0.38], fontsize=7.8, row_step=0.036)
        y -= 0.025
        _draw_wrapped_lines(
            fig,
            [
                f"Source: {BULKOWSKI_FLAGS_URL}",
                f"Source: {BULKOWSKI_MEASURE_URL}",
                "Interpretation: the release follows Bulkowski most closely where it matters for Flags: the empirical 0.46x pole target. Differences in hit/failure rates should be read as Vietnam data/scope/filter effects, not as a contradiction in the rule logic.",
            ],
            x=0.08,
            y=y,
            width=105,
            fontsize=8.8,
        )
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        fig = plt.figure(figsize=(8.27, 11.69))
        fig.patch.set_facecolor(page_bg)
        fig.text(0.08, 0.93, "3. Checks And Claim Boundaries", fontsize=16, weight="bold", ha="left", va="top", color=ink)
        check_rows = [("Check", "Status", "Severity")]
        for check in payload.get("checks", []):
            if isinstance(check, Mapping):
                check_rows.append((check.get("check_id"), check.get("status"), check.get("severity")))
        y = _draw_table(fig, check_rows[:18], x=0.08, y=0.875, col_x=[0.0, 0.50, 0.65], fontsize=7.25, row_step=0.026)
        y -= 0.02
        boundary_lines = ["Forbidden claims:"]
        boundary_lines.extend(f"- {claim}" for claim in payload.get("forbidden_claims", []))
        _draw_wrapped_lines(fig, boundary_lines, x=0.08, y=y, width=105, fontsize=8.4)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)


def write_release_candidate(payload: Mapping[str, Any], out_dir: Path = DEFAULT_OUT_DIR) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "bull_flag_release_candidate.json"
    md_path = out_dir / "bull_flag_release_candidate.md"
    pdf_path = out_dir / "bull_flag_release_candidate.pdf"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_release_candidate_markdown(payload), encoding="utf-8")
    render_release_candidate_pdf(payload, pdf_path)
    return {"json": json_path, "report": md_path, "pdf": pdf_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Bull Flag release-candidate artifacts.")
    parser.add_argument("--main-scorecard", default=str(DEFAULT_MAIN_SCORECARD))
    parser.add_argument("--selected-strategy", default=str(DEFAULT_SELECTED_STRATEGY))
    parser.add_argument("--rule-contract", default=str(DEFAULT_RULE_CONTRACT))
    parser.add_argument("--fresh-gate", default=str(DEFAULT_FRESH_GATE))
    parser.add_argument("--data-gate", default=str(DEFAULT_DATA_GATE))
    parser.add_argument("--supporting-robustness", default=str(DEFAULT_SUPPORTING_ROBUSTNESS))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--min-main-score", type=float, default=95.0)
    parser.add_argument("--min-fresh-score", type=float, default=95.0)
    args = parser.parse_args()
    payload = build_release_candidate(
        main_scorecard_path=Path(args.main_scorecard),
        selected_strategy_path=Path(args.selected_strategy),
        rule_contract_path=Path(args.rule_contract),
        fresh_gate_path=Path(args.fresh_gate),
        data_gate_path=Path(args.data_gate),
        supporting_robustness_path=Path(args.supporting_robustness),
        min_main_score=float(args.min_main_score),
        min_fresh_score=float(args.min_fresh_score),
    )
    paths = write_release_candidate(payload, Path(args.out_dir))
    for key, path in paths.items():
        print(f"{key}: {path}")
    if payload.get("release_status") != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
