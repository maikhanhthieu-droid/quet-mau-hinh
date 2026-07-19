"""Consolidated cross-check for final chapters.

This audit ties together the four release concerns:
- visual/PDF quality;
- canonical factory consistency;
- source grounding and statistical governance;
- realtime scanner/watchlist readiness.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from scanner.audit_canonical_publication_flow import audit_manifest as audit_canonical_manifest
from scanner.audit_final_chapter_deep_pdf_review import build_audit as audit_deep_pdf_review
from scanner.audit_final_chapter_morphology_assets import audit_manifest as audit_morphology_assets
from scanner.audit_final_chapter_pdf_quality import audit_manifest as audit_pdf_quality_manifest
from scanner.audit_publication_entrypoints import audit_publication_entrypoints
from scanner.build_final_chapter_visual_review_pack import build_visual_review_pack
from scanner.run_realtime_scan_watchlist import build_realtime_scan_plan, build_watchlist_from_artifacts, write_realtime_outputs
from scanner.validate_final_chapters_manifest import validate_final_manifest


DEFAULT_MANIFEST = Path("artifacts/final_chapters/final_chapters_manifest.json")
DEFAULT_OUT_DIR = Path("artifacts/final_chapters/governance")
AUDIT_ID = "final_chapter_crosscheck_audit_v1"


def _read_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return payload if isinstance(payload, Mapping) else {}


def _source_grounding_level(source_notes: Mapping[str, Any]) -> str:
    rules = source_notes.get("source_rules") if isinstance(source_notes.get("source_rules"), list) else []
    direct = source_notes.get("direct_pdf_review") if isinstance(source_notes.get("direct_pdf_review"), Mapping) else {}
    if str(direct.get("status") or "").upper() == "PASS" and len(rules) >= 6:
        return "direct_pdf_reviewed"
    if len(rules) >= 6:
        return "rule_grounded"
    if len(rules) >= 2:
        return "basic_source_notes"
    return "thin_or_missing_source_notes"


def _source_rows(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for chapter in manifest.get("chapters", []):
        if not isinstance(chapter, Mapping):
            continue
        source_path = Path(str(chapter.get("source_notes") or ""))
        source_notes = _read_json(source_path)
        rules = source_notes.get("source_rules") if isinstance(source_notes.get("source_rules"), list) else []
        rows.append(
            {
                "pattern_id": chapter.get("pattern_id"),
                "family": chapter.get("family"),
                "source_notes": str(source_path),
                "source_status": source_notes.get("status"),
                "source_rule_count": len(rules),
                "source_grounding_level": _source_grounding_level(source_notes),
                "source_policy_id": source_notes.get("source_grounding_policy_id"),
                "direct_pdf_review_status": (
                    source_notes.get("direct_pdf_review", {}).get("status")
                    if isinstance(source_notes.get("direct_pdf_review"), Mapping)
                    else None
                ),
            }
        )
    return rows


def _governance_summary() -> dict[str, Any]:
    governance = _read_json(Path("artifacts/final_chapters/governance/chapter_governance_matrix.json"))
    preflight = _read_json(Path("artifacts/final_chapters/governance/chapter_tradable_preflight_matrix.json"))
    target = _read_json(Path("artifacts/scanner_v2/final_chapters_target_calibration_audit/chapter_target_calibration_summary.json"))
    blockers = _read_json(Path("artifacts/final_chapters/governance/tradable_blocker_matrix.json"))
    return {
        "governance_matrix_id": governance.get("governance_matrix_id"),
        "governance_counts": governance.get("counts"),
        "preflight_matrix_id": preflight.get("preflight_matrix_id"),
        "preflight_counts": preflight.get("counts"),
        "target_calibration_audit_id": target.get("audit_id") or target.get("summary_id"),
        "target_calibration_counts": target.get("counts"),
        "tradable_blocker_matrix_id": blockers.get("blocker_matrix_id"),
        "tradable_blocker_counts": blockers.get("counts"),
    }


def audit_final_chapter_crosscheck(
    manifest_path: Path = DEFAULT_MANIFEST,
    out_dir: Path = DEFAULT_OUT_DIR,
    *,
    build_visual_pack: bool = True,
    build_realtime_watchlist: bool = True,
) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    manifest_report = validate_final_manifest(manifest_path)
    canonical_report = audit_canonical_manifest(manifest_path)
    pdf_report = audit_pdf_quality_manifest(manifest_path)
    deep_pdf_report = audit_deep_pdf_review(manifest_path)
    morphology_report = audit_morphology_assets(manifest_path)
    entrypoint_report = audit_publication_entrypoints()
    visual_report = (
        build_visual_review_pack(manifest_path, Path("artifacts/final_chapters/visual_review/latest"))
        if build_visual_pack
        else {"status": "SKIPPED"}
    )
    realtime_paths: dict[str, str] = {}
    realtime_counts: dict[str, Any] = {}
    if build_realtime_watchlist:
        plan = build_realtime_scan_plan()
        watchlist = build_watchlist_from_artifacts(plan, lookback_days=14)
        realtime_paths = write_realtime_outputs(plan, watchlist)
        realtime_counts = {"jobs": len(plan.get("jobs", [])), "watchlist": len(watchlist)}

    source_rows = _source_rows(manifest)
    source_failures = [
        row
        for row in source_rows
        if row["source_grounding_level"] == "thin_or_missing_source_notes" or str(row.get("source_status") or "").upper() != "PASS"
    ]
    reports = {
        "manifest": manifest_report.get("status"),
        "canonical_publication_flow": canonical_report.get("status"),
        "pdf_quality": pdf_report.get("status"),
        "deep_pdf_review": deep_pdf_report.get("status"),
        "morphology_assets": morphology_report.get("status"),
        "publication_entrypoints": entrypoint_report.get("status"),
        "visual_review_pack": visual_report.get("status"),
        "source_grounding_coverage": "PASS" if not source_failures else "FAIL",
        "realtime_watchlist": "PASS" if not build_realtime_watchlist or realtime_counts.get("jobs", 0) > 0 else "FAIL",
    }
    status = "PASS" if all(value in {"PASS", "SKIPPED"} for value in reports.values()) else "FAIL"
    return {
        "audit_id": AUDIT_ID,
        "status": status,
        "reports": reports,
        "manifest_counts": {
            "final_count": manifest_report.get("final_count"),
            "quarantine_count": manifest_report.get("quarantine_count"),
            "pdf_quality": pdf_report.get("counts"),
            "deep_pdf_review": deep_pdf_report.get("counts"),
            "morphology_assets": morphology_report.get("counts"),
            "canonical": canonical_report.get("counts"),
        },
        "source_grounding_counts": {
            "chapters": len(source_rows),
            "direct_pdf_reviewed": sum(1 for row in source_rows if row["source_grounding_level"] == "direct_pdf_reviewed"),
            "rule_grounded": sum(1 for row in source_rows if row["source_grounding_level"] == "rule_grounded"),
            "basic_source_notes": sum(1 for row in source_rows if row["source_grounding_level"] == "basic_source_notes"),
            "thin_or_missing_source_notes": sum(1 for row in source_rows if row["source_grounding_level"] == "thin_or_missing_source_notes"),
        },
        "source_grounding_rows": source_rows,
        "source_grounding_failures": source_failures,
        "statistical_governance": _governance_summary(),
        "realtime": {"counts": realtime_counts, "paths": realtime_paths},
        "visual_review": {"sheets": visual_report.get("sheets"), "counts": visual_report.get("counts")},
    }


def write_report(report: Mapping[str, Any], out_dir: Path = DEFAULT_OUT_DIR) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "final_chapter_crosscheck_audit.json"
    md_path = out_dir / "final_chapter_crosscheck_audit.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    lines = [
        "# Final Chapter Crosscheck Audit",
        "",
        f"Audit ID: `{report.get('audit_id')}`",
        f"Status: `{report.get('status')}`",
        "",
        "## Gates",
        "",
        "| Gate | Status |",
        "|---|---|",
    ]
    for key, value in (report.get("reports") or {}).items():
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "## Source Grounding", "", "| Family | Pattern | Level | Rules |", "|---|---|---|---|"])
    for row in report.get("source_grounding_rows", []):
        lines.append(f"| {row.get('family')} | {row.get('pattern_id')} | {row.get('source_grounding_level')} | {row.get('source_rule_count')} |")
    realtime = report.get("realtime") if isinstance(report.get("realtime"), Mapping) else {}
    lines.extend(["", "## Realtime", "", f"- Jobs: `{(realtime.get('counts') or {}).get('jobs')}`", f"- Watchlist rows: `{(realtime.get('counts') or {}).get('watchlist')}`"])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run final chapter crosscheck audit.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--skip-visual-pack", action="store_true")
    parser.add_argument("--skip-realtime-watchlist", action="store_true")
    args = parser.parse_args()
    report = audit_final_chapter_crosscheck(
        Path(args.manifest),
        Path(args.out_dir),
        build_visual_pack=not args.skip_visual_pack,
        build_realtime_watchlist=not args.skip_realtime_watchlist,
    )
    paths = write_report(report, Path(args.out_dir))
    print(json.dumps({"report": report, "paths": paths}, ensure_ascii=False, indent=2, default=str))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
