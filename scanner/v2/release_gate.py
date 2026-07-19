"""P1-P5 chapter gate for Scanner V2 monographs.

This module intentionally evaluates the chapter payload, not the rendered PDF.
The PDF is allowed to be prettier than the payload, but it must not be more
ambitious than the payload.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence


STANDARD_VERSION = "bulkowski_vietnam_p1_p5_v1"

CLASSIFICATION_ORDER = [
    "not-usable",
    "research-only",
    "watchlist-reference",
    "investment-reference",
    "tradable-setup",
]


@dataclass(frozen=True)
class GateCheck:
    check_id: str
    label: str
    severity: str
    passed: bool
    action: str
    detail: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_id": self.check_id,
            "label": self.label,
            "severity": self.severity,
            "passed": self.passed,
            "action": self.action,
            "detail": self.detail,
        }


def _has_path(mapping: Mapping[str, Any], path: Sequence[str]) -> bool:
    cur: Any = mapping
    for key in path:
        if not isinstance(cur, Mapping) or key not in cur:
            return False
        cur = cur[key]
    if cur is None:
        return False
    if isinstance(cur, (str, list, dict, tuple, set)) and not cur:
        return False
    return True


def _all_rules_have_provenance(rules: Iterable[Mapping[str, Any]]) -> bool:
    required = {
        "rule_id",
        "book_chapter",
        "source_page",
        "source_section",
        "evidence_excerpt",
        "interpreted_rule",
        "numeric_threshold",
        "confidence",
        "notes_when_ambiguous",
    }
    for rule in rules:
        if not required.issubset(rule):
            return False
    return True


def _scanner_coverage_ok(contract: Mapping[str, Any]) -> bool:
    coverage = contract.get("coverage")
    if not isinstance(coverage, list) or not coverage:
        return False
    return all(isinstance(row, Mapping) and row.get("status") == "implemented" for row in coverage)


def _required_p0_missing(payload: Mapping[str, Any]) -> List[str]:
    stats = payload.get("statistics") if isinstance(payload.get("statistics"), Mapping) else {}
    market_data = payload.get("market_data") if isinstance(payload.get("market_data"), Mapping) else {}
    release = payload.get("release_gate_status") if isinstance(payload.get("release_gate_status"), Mapping) else {}

    checks = {
        "event_level_ohlcv_path": _has_path(payload, ["event_artifacts", "post_breakout_path"]),
        "event_level_json_csv": _has_path(payload, ["event_artifacts", "event_json"])
        and _has_path(payload, ["event_artifacts", "event_csv"]),
        "b_ref_and_b_exec": _has_path(payload, ["statistics", "anchor_mode"])
        and "B_exec" in str(stats.get("anchor_mode") or ""),
        "point_in_time_universe": _has_path(market_data, ["data_integrity", "point_in_time_universe"]),
        "delisted_halted_coverage": _has_path(market_data, ["data_integrity", "delisted_halted_coverage"]),
        "corporate_action_audit": _has_path(market_data, ["data_integrity", "corporate_action_audit"]),
        "market_group_table": _has_path(stats, ["market_group_table"]),
        "direction_table": _has_path(stats, ["breakout_groups"]),
        "regime_table": _has_path(stats, ["regime_groups"]),
        "failure_ladder": _has_path(stats, ["failure_ladder"]),
        "target_first_before_adverse": _has_path(stats, ["target_first_before_adverse_5pct"]),
        "throwback_pullback_30": _has_path(stats, ["tbpb_30_rate"]),
        "time_to_target": _has_path(stats, ["time_to_target"]),
        "quantiles_p1_p99": _has_path(stats, ["quantile_metrics"]),
        "wilson_ci": _has_path(stats, ["ci", "wilson"]),
        "bootstrap_ci": _has_path(stats, ["ci", "bootstrap"]),
        "concentration_metrics": _has_path(stats, ["symbol_concentration"]),
        "overlap_policy": _has_path(payload, ["sample_policy", "overlap_policy"]),
        "censoring_policy": _has_path(payload, ["sample_policy", "censoring_policy"]),
        "seeded_stratified_examples": _has_path(payload, ["example_scope", "selection_mode"])
        and str(payload.get("example_scope", {}).get("selection_mode")) == "seeded_stratified_random",
        "release_reviewer_signoff": _has_path(release, ["reviewer_id"]),
    }
    return [key for key, passed in checks.items() if not passed]


def _score_payload(payload: Mapping[str, Any], checks: Sequence[GateCheck], p0_missing: Sequence[str]) -> Dict[str, Any]:
    rules = payload.get("rules") if isinstance(payload.get("rules"), list) else []
    stats = payload.get("statistics") if isinstance(payload.get("statistics"), Mapping) else {}
    contract = payload.get("scanner_contract") if isinstance(payload.get("scanner_contract"), Mapping) else {}
    source_alignment = payload.get("source_alignment") if isinstance(payload.get("source_alignment"), Mapping) else {}

    scores = {
        "data": 4 if _has_path(payload, ["market_data", "source"]) else 0,
        "provenance": 12 if _all_rules_have_provenance(rules) and source_alignment.get("aligned") is True else 0,
        "scanner_coverage": 10 if _scanner_coverage_ok(contract) else 0,
        "core_statistics": 8
        + (4 if _has_path(stats, ["breakout_groups"]) else 0)
        + (4 if _has_path(stats, ["regime_groups"]) else 0),
        "distribution_uncertainty": 0,
        "bias_controls": max(0, 18 - min(18, len([c for c in checks if not c.passed and c.severity in {"High", "Critical"}]) * 2)),
        "examples": 2 if payload.get("example_detections") else 0,
        "ai_interpretation": 3 if _has_path(payload, ["investment_reference_status", "tradable_setup"]) else 0,
        "governance_reproducibility": 2 if _has_path(contract, ["spec_hash"]) else 0,
    }
    score = min(100, int(sum(scores.values())))
    if any(c.check_id == "rule_provenance" and not c.passed for c in checks):
        score = min(score, 49)
    elif p0_missing:
        score = min(score, 74)
    return {"score": score, "components": scores}


def _classification(score: int, checks: Sequence[GateCheck], p0_missing: Sequence[str]) -> str:
    if any(c.check_id == "rule_provenance" and not c.passed for c in checks):
        return "not-usable"
    if not p0_missing and score >= 85:
        return "investment-reference"
    if score >= 70:
        return "watchlist-reference"
    return "research-only"


def evaluate_release_gate(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Evaluate a Scanner V2 monograph payload against the P1-P5 standard."""

    rules = payload.get("rules") if isinstance(payload.get("rules"), list) else []
    stats = payload.get("statistics") if isinstance(payload.get("statistics"), Mapping) else {}
    contract = payload.get("scanner_contract") if isinstance(payload.get("scanner_contract"), Mapping) else {}
    source_alignment = payload.get("source_alignment") if isinstance(payload.get("source_alignment"), Mapping) else {}
    market_data = payload.get("market_data") if isinstance(payload.get("market_data"), Mapping) else {}

    checks = [
        GateCheck(
            "rule_provenance",
            "Rule provenance and source alignment",
            "Critical",
            _all_rules_have_provenance(rules) and source_alignment.get("aligned") is True,
            "Block PDF",
            "Every official rule must have source fields and aligned evidence.",
        ),
        GateCheck(
            "scanner_coverage",
            "Scanner coverage",
            "High",
            _scanner_coverage_ok(contract),
            "Block if missing",
            "Every sourced rule must map to an implemented Scanner V2 module.",
        ),
        GateCheck(
            "point_in_time_universe",
            "Point-in-time universe including delisted/halted symbols",
            "Critical",
            _has_path(market_data, ["data_integrity", "point_in_time_universe"])
            and _has_path(market_data, ["data_integrity", "delisted_halted_coverage"]),
            "Block PDF",
            "Market Stats V1 is useful, but the chapter must disclose or prove PTI delisted/halted coverage.",
        ),
        GateCheck(
            "corporate_actions",
            "Corporate-action adjustment audit",
            "Critical",
            _has_path(market_data, ["data_integrity", "corporate_action_audit"]),
            "Block PDF",
            "Chapter must prove point-in-time adjusted data or explicitly stay below investment-reference.",
        ),
        GateCheck(
            "event_path",
            "Post-breakout OHLC path",
            "Critical",
            _has_path(payload, ["event_artifacts", "post_breakout_path"]),
            "Block investment-reference",
            "Path data is required for throwback/pullback, time-to-target, retrace, and censoring.",
        ),
        GateCheck(
            "statistics_pack",
            "P0 statistics pack",
            "Critical",
            not _required_p0_missing(payload),
            "Block investment-reference",
            "P0 requires event paths, anchors, direction/regime/market groups, CI, quantiles, and concentration.",
        ),
        GateCheck(
            "direction_regime_counts",
            "Direction and regime split with sample counts",
            "High",
            _has_path(stats, ["breakout_groups"]) and _has_path(stats, ["regime_groups"]),
            "Cap at watchlist-reference if missing",
            "Bulkowski-style chapters must not hide up/down or bull/bear behavior.",
        ),
        GateCheck(
            "overlap_censoring",
            "Overlap and censoring policy",
            "High",
            _has_path(payload, ["sample_policy", "overlap_policy"])
            and _has_path(payload, ["sample_policy", "censoring_policy"]),
            "Block investment-reference",
            "Event overlap and incomplete future paths must be governed before publication.",
        ),
        GateCheck(
            "inference_uncertainty",
            "CI/bootstrap/KM uncertainty layer",
            "High",
            _has_path(stats, ["ci", "wilson"]) and _has_path(stats, ["ci", "bootstrap"]),
            "Downgrade or block comparisons",
            "Point estimates are not enough for investment-reference claims.",
        ),
        GateCheck(
            "example_selection",
            "Seeded stratified chart examples",
            "Medium",
            _has_path(payload, ["example_scope", "selection_mode"])
            and str(payload.get("example_scope", {}).get("selection_mode")) == "seeded_stratified_random",
            "Require note or rerun examples",
            "Examples must include median, strong-tail, failure, and borderline cases by rule.",
        ),
        GateCheck(
            "ai_claims",
            "AI narrative constrained by payload",
            "Medium",
            _has_path(payload, ["investment_reference_status", "tradable_setup"])
            and payload.get("investment_reference_status", {}).get("tradable_setup") is False,
            "Block if AI overclaims",
            "AI may edit prose only and must not turn reference statistics into trade advice.",
        ),
    ]
    p0_missing = _required_p0_missing(payload)
    score_info = _score_payload(payload, checks, p0_missing)
    classification = _classification(int(score_info["score"]), checks, p0_missing)
    high_failures = [c for c in checks if c.severity in {"High", "Critical"} and not c.passed]
    publish_status = "Hold" if high_failures else ("Publish with caveats" if int(score_info["score"]) < 90 else "Strong chapter")
    return {
        "standard_version": STANDARD_VERSION,
        "classification": classification,
        "publish_status": publish_status,
        "chapter_score": score_info["score"],
        "score_components": score_info["components"],
        "p0_missing": p0_missing,
        "high_severity_failures": [c.check_id for c in high_failures],
        "checks": [c.to_dict() for c in checks],
        "allowed_claim": _allowed_claim(classification),
    }


def _allowed_claim(classification: str) -> str:
    if classification == "investment-reference":
        return "Có thể dùng như tài liệu tham khảo đầu tư có điều kiện và caveat rõ."
    if classification == "watchlist-reference":
        return "Có thể dùng để theo dõi có điều kiện, nhưng không được gọi là tín hiệu giao dịch."
    if classification == "research-only":
        return "Chỉ dùng cho nhận diện và mô tả phân phối lịch sử cấp research draft."
    if classification == "tradable-setup":
        return "Cần tài liệu chiến lược riêng với execution/OOS/cost model."
    return "Chưa đủ điều kiện công bố."


def build_methodology_status(payload: Mapping[str, Any], release_gate: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "standard_version": STANDARD_VERSION,
        "target": "Bulkowski cho Việt Nam 85-90%",
        "chapter_lane": "investment_reference_candidate",
        "classification": release_gate.get("classification"),
        "publish_status": release_gate.get("publish_status"),
        "tradable_setup": False,
        "non_advice_boundary": "Thống kê lịch sử là tham khảo mô tả, không phải khuyến nghị mua/bán.",
    }


def build_statistics_status(payload: Mapping[str, Any], release_gate: Mapping[str, Any]) -> Dict[str, Any]:
    stats = payload.get("statistics") if isinstance(payload.get("statistics"), Mapping) else {}
    return {
        "standard_version": STANDARD_VERSION,
        "p0_complete": not bool(release_gate.get("p0_missing")),
        "p0_missing": list(release_gate.get("p0_missing") or []),
        "current_tables": {
            "summary": bool(stats),
            "direction": _has_path(stats, ["breakout_groups"]),
            "regime": _has_path(stats, ["regime_groups"]),
            "market_group": _has_path(stats, ["market_group_table"]),
            "failure_target": _has_path(stats, ["failure_target_table"]),
            "post_breakout_behavior": _has_path(stats, ["post_breakout_table"]),
        },
        "anchor_mode": stats.get("anchor_mode", "B_ref_only"),
        "required_quantiles": ["P1", "P5", "P10", "P25", "P50", "P75", "P90", "P95", "P99"],
    }


def build_framework_status(release_gate: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "standard_version": STANDARD_VERSION,
        "score": release_gate.get("chapter_score"),
        "classification": release_gate.get("classification"),
        "hard_gate_caps": release_gate.get("high_severity_failures") or [],
        "required_figures": ["ECDF", "forest_plot", "Kaplan_Meier_or_CIF", "heatmap", "TD_vs_HitT_or_RTR"],
        "current_required_figures_coverage": "not_implemented",
    }


def enrich_payload_with_p1_p5_status(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a copy of payload with methodology/statistics/framework/release statuses."""

    enriched = deepcopy(dict(payload))
    release_gate = evaluate_release_gate(enriched)
    enriched["release_gate_status"] = release_gate
    enriched["methodology_status"] = build_methodology_status(enriched, release_gate)
    enriched["statistics_contract_status"] = build_statistics_status(enriched, release_gate)
    enriched["chapter_framework_status"] = build_framework_status(release_gate)
    return enriched
