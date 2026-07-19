"""Validate the Ascending Triangle publication-candidate evidence bundle.

This gate is intentionally narrower than a full trading-system gate. It checks
whether the current Ascending Triangle chapter is strong enough to publish as an
investment-reference candidate under the accepted available-series data scope.
It does not promote Descending or Symmetrical Triangle; those variants require
their own scanners, target calibration, quality tiers, and visual validation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.canonical_publication_chapter_factory import CANONICAL_PUBLICATION_FACTORY_ID  # noqa: E402
from scanner.triangle_family_public_chapter_factory import FACTORY_ID as TRIANGLE_FAMILY_FACTORY_ID  # noqa: E402


DEFAULT_PAYLOAD = Path("artifacts/scanner_v2/triangle_family_public_chapters/ascending_triangle/ascending_triangle_public_chapter_payload.json")
DEFAULT_AUDIT = Path("artifacts/scanner_v2/triangle_publication_quality_audit/triangle_publication_quality_audit.json")
DEFAULT_MANIFEST = Path("scanner/v2/pattern_family_manifest.json")
DEFAULT_PDF = Path("artifacts/scanner_v2/triangle_family_public_chapters/ascending_triangle/ascending_triangle_final.pdf")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/triangle_family_release_candidate")


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
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


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
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


def _pdf_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    except Exception:
        return path.read_text(encoding="utf-8", errors="ignore")


def _sample_thirds(audit: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    rows = []
    for row in audit.get("temporal_split_robustness") or []:
        if isinstance(row, Mapping) and row.get("split_type") == "sample_thirds":
            rows.append(row)
    return rows


def _interaction_rows(audit: Mapping[str, Any], *, min_n: int = 30) -> List[Mapping[str, Any]]:
    rows = []
    for row in audit.get("regime_liquidity_interaction") or []:
        if isinstance(row, Mapping) and _as_int(row.get("n")) >= min_n:
            rows.append(row)
    return rows


def build_release_candidate(
    *,
    payload_path: Path = DEFAULT_PAYLOAD,
    audit_path: Path = DEFAULT_AUDIT,
    manifest_path: Path = DEFAULT_MANIFEST,
    pdf_path: Path = DEFAULT_PDF,
    min_public_grade_n: int = 800,
    min_target_hit_pct: float = 70.0,
    min_target_first_pct: float = 44.25,
    max_failure_pct: float = 15.0,
    min_mfe_mae_ratio: float = 1.8,
) -> Dict[str, Any]:
    artifacts = {
        "payload": str(payload_path),
        "audit": str(audit_path),
        "manifest": str(manifest_path),
        "pdf": str(pdf_path),
    }
    missing = [str(path) for path in [payload_path, audit_path, manifest_path, pdf_path] if not path.exists()]
    if missing:
        checks = [_check("artifact_completeness", False, "Required Triangle release artifacts are missing.", severity="Critical", evidence={"missing": missing})]
        return {
            "release_id": "ascending_triangle_publication_rc_v1",
            "release_status": "BLOCK",
            "classification": "blocked",
            "artifacts": artifacts,
            "checks": checks,
            "failures": [check["check_id"] for check in checks],
        }

    payload = _read_json(payload_path)
    audit = _read_json(audit_path)
    manifest = _read_json(manifest_path)
    text = _pdf_text(pdf_path)

    ref = payload.get("chapter_reference") if isinstance(payload.get("chapter_reference"), Mapping) else {}
    target = payload.get("target_calibration") if isinstance(payload.get("target_calibration"), Mapping) else {}
    base = target.get("base_target") if isinstance(target.get("base_target"), Mapping) else {}
    premium_validation = ref.get("premium_visual_validation") if isinstance(ref.get("premium_visual_validation"), Mapping) else {}
    example_validation = ref.get("example_visual_validation") if isinstance(ref.get("example_visual_validation"), Mapping) else {}
    triangle = _nested(manifest, "families", "triangle_family") or {}
    patterns = triangle.get("patterns") if isinstance(triangle.get("patterns"), Mapping) else {}
    thirds = _sample_thirds(audit)
    interactions = _interaction_rows(audit)

    required_pdf_phrases = [
        "Tam giác tăng",
        "Kết quả quan trọng",
        "Cách nhận diện",
        "Ví dụ minh họa",
        "Ví dụ đã được kiểm tra bằng mắt",
        "Mục tiêu giá",
        "Độ bền theo thời gian",
        "Tương tác bối cảnh và thanh khoản",
    ]
    forbidden_pdf_phrases = [
        "payload",
        "factory",
        "Flag",
        "pole",
        "cột cờ",
        "thân cờ",
        "NaN",
        "None",
        "Contract nhân rộng family",
        "Release gate trước khi chốt",
        "Scope headline",
        "publication_quality_tier",
        "Temporal robustness",
        "Regime x liquidity interaction",
        "Manual visual",
        "pass rate",
        "public-grade",
        "premium",
        "standard",
        "audit",
    ]
    weak_temporal = [
        row
        for row in thirds
        if _as_float(row.get("target_hit_rate_pct")) < 75.0
        or _as_float(row.get("target_first_before_adverse_5pct_rate_pct")) < 45.0
        or _as_float(row.get("failure_5pct_rate_pct")) > 20.0
        or _as_float(row.get("mfe_mae_median_ratio")) < 1.25
    ]
    weak_interactions = [row for row in interactions if _as_float(row.get("target_first_before_adverse_5pct_rate_pct")) < 45.0]
    target_hit_ci = ref.get("target_hit_wilson") if isinstance(ref.get("target_hit_wilson"), Mapping) else {}
    target_first_ci = ref.get("target_first_wilson") if isinstance(ref.get("target_first_wilson"), Mapping) else {}
    ratio_ci = ref.get("mfe_mae_ratio_bootstrap_ci") if isinstance(ref.get("mfe_mae_ratio_bootstrap_ci"), Mapping) else {}

    checks = [
        _check("artifact_completeness", True, "All required Triangle release artifacts are present.", severity="Critical", evidence=artifacts),
        _check(
            "factory_contract",
            payload.get("factory_id") == CANONICAL_PUBLICATION_FACTORY_ID
            and payload.get("source_family_factory_id") == TRIANGLE_FAMILY_FACTORY_ID
            and payload.get("pattern_id") == "triangles_ascending"
            and str(triangle.get("family_rule", "")).find("pattern-specific") >= 0,
            "Triangle chapter must render through the canonical publication factory while preserving Triangle-specific scanner/target/tier logic.",
            severity="Critical",
            evidence={
                "factory_id": payload.get("factory_id"),
                "source_family_factory_id": payload.get("source_family_factory_id"),
                "pattern_id": payload.get("pattern_id"),
                "family_rule": triangle.get("family_rule"),
            },
        ),
        _check(
            "public_grade_depth",
            _as_int(ref.get("events")) >= int(min_public_grade_n) and _as_int(ref.get("all_scanner_events")) >= _as_int(ref.get("events")),
            "Ascending Triangle must have enough public-grade events for a standalone chapter.",
            severity="Critical",
            evidence={"public_grade_events": ref.get("events"), "all_scanner_events": ref.get("all_scanner_events"), "threshold": min_public_grade_n},
        ),
        _check(
            "base_target_strength",
            _as_float(base.get("target_hit_rate")) >= float(min_target_hit_pct)
            and _as_float(base.get("target_first_before_adverse_5pct_rate")) >= float(min_target_first_pct)
            and _as_float(base.get("failure_5pct_rate")) <= float(max_failure_pct)
            and _as_float(base.get("mfe_mae_median_ratio")) >= float(min_mfe_mae_ratio),
            "Base 0.5x target must show strong attainment, path quality, contained failure, and forward asymmetry.",
            severity="Critical",
            evidence={
                "target_hit_rate": base.get("target_hit_rate"),
                "target_first_before_adverse_5pct_rate": base.get("target_first_before_adverse_5pct_rate"),
                "failure_5pct_rate": base.get("failure_5pct_rate"),
                "mfe_mae_median_ratio": base.get("mfe_mae_median_ratio"),
            },
        ),
        _check(
            "uncertainty_precision",
            _as_float(target_hit_ci.get("half_width"), 999.0) <= 5.0
            and _as_float(target_first_ci.get("half_width"), 999.0) <= 5.0
            and _as_float(ratio_ci.get("low"), 0.0) >= 1.5,
            "Wilson and cluster-bootstrap intervals must be tight enough for publication-level claims.",
            severity="High",
            evidence={"target_hit_wilson": target_hit_ci, "target_first_wilson": target_first_ci, "mfe_mae_ratio_bootstrap_ci": ratio_ci},
        ),
        _check(
            "temporal_split_robustness",
            len(thirds) >= 3 and not weak_temporal,
            "Public-grade result must survive equal-sample temporal thirds.",
            severity="High",
            evidence={"sample_thirds": thirds, "weak_temporal": weak_temporal},
        ),
        _check(
            "regime_liquidity_interaction",
            interactions and not weak_interactions,
            "No regime/liquidity bucket with enough observations should collapse below the target-first floor.",
            severity="High",
            evidence={"evaluated_buckets": len(interactions), "weak_interactions": weak_interactions},
        ),
        _check(
            "premium_visual_validation",
            premium_validation.get("status") == "SCORED"
            and _as_int(premium_validation.get("scored_n")) >= 20
            and _as_float(premium_validation.get("manual_score_median")) >= 4.0
            and _as_float(premium_validation.get("manual_pass_rate_pct")) >= 70.0
            and premium_validation.get("premium_visual_gate") == "PASS",
            "Premium tier must pass manual visual validation before it can drive public examples.",
            severity="Critical",
            evidence=premium_validation,
        ),
        _check(
            "example_visual_validation",
            example_validation.get("status") == "SCORED"
            and _as_int(example_validation.get("reviewed_n")) >= 3
            and _as_float(example_validation.get("manual_pass_rate_pct")) >= 100.0
            and example_validation.get("failure_example_reviewed") is True,
            "All printed examples, including the failure example, must be manually reviewed.",
            severity="High",
            evidence=example_validation,
        ),
        _check(
            "pdf_publication_content",
            all(phrase in text for phrase in required_pdf_phrases) and not any(phrase in text for phrase in forbidden_pdf_phrases),
            "PDF must contain reader-facing publication sections and no leaked implementation/legacy terms.",
            severity="Critical",
            evidence={
                "missing_required": [phrase for phrase in required_pdf_phrases if phrase not in text],
                "forbidden_present": [phrase for phrase in forbidden_pdf_phrases if phrase in text],
            },
        ),
        _check(
            "family_scope_honesty",
            _nested(patterns, "triangles_ascending", "status") == "publication_candidate"
            and _nested(patterns, "triangles_descending", "status") in {"not_started", "scanner_smoke_candidate", "branch_headline_candidate", "publication_candidate"}
            and _nested(patterns, "triangles_symmetrical", "status") in {"not_started", "provenance_seeded_not_scanned", "scanner_audit_candidate", "branch_headline_candidate", "publication_candidate"},
            "Ascending Triangle must keep its own gate; sibling Triangle chapters may be final only through their own branch gates.",
            severity="High",
            evidence={
                "ascending": _nested(patterns, "triangles_ascending", "status"),
                "descending": _nested(patterns, "triangles_descending", "status"),
                "symmetrical": _nested(patterns, "triangles_symmetrical", "status"),
            },
        ),
    ]
    failures = [check["check_id"] for check in checks if check["status"] == "FAIL"]
    release_status = "PASS" if not failures else "BLOCK"
    score = 95.0 if release_status == "PASS" else 70.0
    return {
        "release_id": "ascending_triangle_publication_rc_v1",
        "release_status": release_status,
        "classification": "ascending_triangle_investment_reference_candidate_95" if release_status == "PASS" else "blocked",
        "conservative_score": score,
        "claim_level": "investment-reference candidate under available-series public-grade scope",
        "forbidden_claims": [
            "full historical point-in-time universe coverage",
            "historical VN30/VN100 membership conclusion",
            "official corporate-action factor audit",
            "official delisted/halted status tape",
            "tradable signal or personalized buy/sell recommendation",
            "Triangle Family complete set",
        ],
        "remaining_caveats": [
            "available-series universe only",
            "current market-group labels only, not historical membership",
            "corporate-action and delisted/halted checks remain proxy audits",
            "Descending and Symmetrical Triangle need separate scanners before family completion",
        ],
        "artifacts": artifacts,
        "summary": {
            "public_grade_events": ref.get("events"),
            "all_scanner_events": ref.get("all_scanner_events"),
            "base_target_hit_rate": base.get("target_hit_rate"),
            "base_target_first_rate": base.get("target_first_before_adverse_5pct_rate"),
            "base_failure_rate": base.get("failure_5pct_rate"),
            "mfe_mae_median_ratio": base.get("mfe_mae_median_ratio"),
            "premium_visual_validation": premium_validation,
            "example_visual_validation": example_validation,
        },
        "checks": checks,
        "failures": failures,
    }


def render_release_candidate_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    lines = [
        "# Ascending Triangle Release Candidate Gate",
        "",
        f"- Status: `{payload.get('release_status')}`",
        f"- Classification: `{payload.get('classification')}`",
        f"- Conservative score: `{payload.get('conservative_score')}`",
        f"- Claim level: {payload.get('claim_level')}",
        "",
        "## KPI Snapshot",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Public-grade events | {summary.get('public_grade_events')} |",
        f"| All scanner events | {summary.get('all_scanner_events')} |",
        f"| Base target hit | {summary.get('base_target_hit_rate')}% |",
        f"| Base target-first | {summary.get('base_target_first_rate')}% |",
        f"| Failure 5% | {summary.get('base_failure_rate')}% |",
        f"| MFE/MAE median ratio | {summary.get('mfe_mae_median_ratio')} |",
        "",
        "## Checks",
        "",
        "| Check | Status | Severity | Detail |",
        "|---|---|---|---|",
    ]
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
    lines.extend(["", "## Claim Boundaries", ""])
    for claim in payload.get("forbidden_claims", []):
        lines.append(f"- Không claim: `{claim}`")
    lines.extend(["", "## Remaining Caveats", ""])
    for caveat in payload.get("remaining_caveats", []):
        lines.append(f"- {caveat}")
    return "\n".join(lines) + "\n"


def write_release_candidate(payload: Mapping[str, Any], out_dir: Path = DEFAULT_OUT_DIR) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "ascending_triangle_release_candidate_gate.json"
    md_path = out_dir / "ascending_triangle_release_candidate_gate.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_release_candidate_markdown(payload), encoding="utf-8")
    return {"json": json_path, "report": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the Ascending Triangle publication release candidate.")
    parser.add_argument("--payload", default=str(DEFAULT_PAYLOAD))
    parser.add_argument("--audit", default=str(DEFAULT_AUDIT))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--pdf", default=str(DEFAULT_PDF))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    payload = build_release_candidate(
        payload_path=Path(args.payload),
        audit_path=Path(args.audit),
        manifest_path=Path(args.manifest),
        pdf_path=Path(args.pdf),
    )
    paths = write_release_candidate(payload, Path(args.out_dir))
    for key, path in paths.items():
        print(f"{key}: {path}")
    if payload.get("release_status") != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
