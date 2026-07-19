"""Audit final chapters against the canonical publication factory contract."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.canonical_publication_chapter_factory import (  # noqa: E402
    CANONICAL_PUBLICATION_FACTORY_ID,
    CANONICAL_PUBLICATION_FLOW,
    CANONICAL_PUBLICATION_STYLE_VERSION,
    CANONICAL_READER_EXPERIENCE_GATE_ID,
    REQUIRED_READER_SECTIONS,
)
from scanner.canonical_chapter_content import CANONICAL_CONTENT_GENERATOR_ID  # noqa: E402
from scanner.canonical_editorial_layer import (  # noqa: E402
    CANONICAL_AI_EDITORIAL_GATE_ID,
    CANONICAL_EDITORIAL_WORKFLOW_ID,
    validate_canonical_editorial_sections,
)
from scanner.publication_flow_contract import PUBLICATION_CORE_ID  # noqa: E402


DEFAULT_MANIFEST = Path("artifacts/final_chapters/final_chapters_manifest.json")
DEFAULT_OUT_DIR = Path("artifacts/final_chapters/governance")
AUDIT_ID = "canonical_publication_flow_audit_v1"


def _read_json(path: Path | None) -> Mapping[str, Any]:
    if not path or not path.exists() or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, Mapping) else {}


def _pdf_text(path: Path | None) -> str:
    if not path or not path.exists() or not path.is_file():
        return ""
    return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


def _artifact_path(chapter: Mapping[str, Any], key: str) -> Path | None:
    value = str(chapter.get(key) or "").strip()
    return Path(value) if value else None


def _has_marker(text: str, marker: str) -> bool:
    return marker in text


def audit_chapter(chapter: Mapping[str, Any]) -> dict[str, Any]:
    pattern_id = str(chapter.get("pattern_id") or "")
    payload_path = _artifact_path(chapter, "payload")
    pdf_path = _artifact_path(chapter, "pdf")
    manuscript_path = _artifact_path(chapter, "manuscript")
    notes_path = _artifact_path(chapter, "notes")

    payload = _read_json(payload_path)
    pdf_text = _pdf_text(pdf_path)
    manuscript_text = manuscript_path.read_text(encoding="utf-8", errors="replace") if manuscript_path and manuscript_path.exists() else ""
    notes_text = notes_path.read_text(encoding="utf-8", errors="replace") if notes_path and notes_path.exists() else ""

    failures: list[str] = []

    if str(chapter.get("publication_flow") or "") != CANONICAL_PUBLICATION_FLOW:
        failures.append("manifest_publication_flow_not_canonical")
    if str(chapter.get("factory_id") or "") != CANONICAL_PUBLICATION_FACTORY_ID:
        failures.append("manifest_factory_not_canonical")
    if str(chapter.get("canonical_publication_factory_id") or "") != CANONICAL_PUBLICATION_FACTORY_ID:
        failures.append("manifest_missing_canonical_factory_id")
    if str(chapter.get("canonical_reader_experience_gate_id") or "") != CANONICAL_READER_EXPERIENCE_GATE_ID:
        failures.append("manifest_missing_reader_experience_gate")
    if str(chapter.get("canonical_publication_style_version") or "") != CANONICAL_PUBLICATION_STYLE_VERSION:
        failures.append("manifest_missing_publication_style_v3")
    if str(chapter.get("canonical_ai_editorial_gate_id") or "") != CANONICAL_AI_EDITORIAL_GATE_ID:
        failures.append("manifest_missing_ai_editorial_gate")
    if str(chapter.get("canonical_editorial_workflow_id") or "") != CANONICAL_EDITORIAL_WORKFLOW_ID:
        failures.append("manifest_missing_editorial_workflow")
    if str(chapter.get("canonical_content_generator_id") or "") != CANONICAL_CONTENT_GENERATOR_ID:
        failures.append("manifest_missing_content_generator")

    if not payload:
        failures.append("payload_missing_or_unreadable")
    else:
        if payload.get("publication_core_id") != PUBLICATION_CORE_ID:
            failures.append("payload_publication_core_not_current")
        if payload.get("factory_id") != CANONICAL_PUBLICATION_FACTORY_ID:
            failures.append("payload_factory_not_canonical")
        if payload.get("canonical_publication_factory_id") != CANONICAL_PUBLICATION_FACTORY_ID:
            failures.append("payload_missing_canonical_factory_id")
        if payload.get("canonical_reader_experience_gate_id") != CANONICAL_READER_EXPERIENCE_GATE_ID:
            failures.append("payload_missing_reader_experience_gate")
        if payload.get("canonical_publication_style_version") != CANONICAL_PUBLICATION_STYLE_VERSION:
            failures.append("payload_missing_publication_style_v3")
        if payload.get("canonical_ai_editorial_gate_id") != CANONICAL_AI_EDITORIAL_GATE_ID:
            failures.append("payload_missing_ai_editorial_gate")
        if payload.get("canonical_editorial_workflow_id") != CANONICAL_EDITORIAL_WORKFLOW_ID:
            failures.append("payload_missing_editorial_workflow")
        if payload.get("canonical_content_generator_id") != CANONICAL_CONTENT_GENERATOR_ID:
            failures.append("payload_missing_content_generator")
        editorial_report = validate_canonical_editorial_sections(payload)
        if editorial_report["status"] != "PASS":
            failures.append("payload_editorial_depth_gate_failed")

    missing_sections = [section for section in REQUIRED_READER_SECTIONS if section not in pdf_text]
    if missing_sections:
        failures.append("pdf_missing_reader_sections:" + ",".join(missing_sections))

    marker = f"`{CANONICAL_PUBLICATION_FACTORY_ID}`"
    if not _has_marker(manuscript_text, marker):
        failures.append("manuscript_missing_canonical_marker")
    if not _has_marker(notes_text, marker):
        failures.append("notes_missing_canonical_marker")

    if "public_chapter_manuscript.md" in str(manuscript_path or "") and "ai_editorial" not in str(manuscript_path or ""):
        failures.append("manuscript_looks_mechanical_not_editorial")

    return {
        "pattern_id": pattern_id,
        "family": chapter.get("family"),
        "title": chapter.get("title"),
        "status": "PASS" if not failures else "FAIL",
        "failure_count": len(failures),
        "failures": failures,
        "pdf": str(pdf_path) if pdf_path else "",
        "payload": str(payload_path) if payload_path else "",
    }


def audit_manifest(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    chapters = manifest.get("chapters") if isinstance(manifest.get("chapters"), list) else []
    rows = [audit_chapter(chapter) for chapter in chapters if isinstance(chapter, Mapping)]
    pass_count = sum(1 for row in rows if row["status"] == "PASS")
    return {
        "audit_id": AUDIT_ID,
        "status": "PASS" if pass_count == len(rows) and rows else "FAIL",
        "manifest": str(manifest_path),
        "canonical_publication_factory_id": CANONICAL_PUBLICATION_FACTORY_ID,
        "canonical_publication_style_version": CANONICAL_PUBLICATION_STYLE_VERSION,
        "canonical_reader_experience_gate_id": CANONICAL_READER_EXPERIENCE_GATE_ID,
        "canonical_editorial_workflow_id": CANONICAL_EDITORIAL_WORKFLOW_ID,
        "canonical_ai_editorial_gate_id": CANONICAL_AI_EDITORIAL_GATE_ID,
        "canonical_content_generator_id": CANONICAL_CONTENT_GENERATOR_ID,
        "counts": {
            "chapters": len(rows),
            "canonical_pass": pass_count,
            "canonical_fail": len(rows) - pass_count,
        },
        "chapters": rows,
    }


def write_audit(report: Mapping[str, Any], out_dir: Path = DEFAULT_OUT_DIR) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "canonical_publication_flow_audit.json"
    csv_path = out_dir / "canonical_publication_flow_audit.csv"
    md_path = out_dir / "canonical_publication_flow_audit.md"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")

    rows = report.get("chapters") if isinstance(report.get("chapters"), list) else []
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["family", "pattern_id", "title", "status", "failure_count", "failures", "pdf"])
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "family": row.get("family"),
                    "pattern_id": row.get("pattern_id"),
                    "title": row.get("title"),
                    "status": row.get("status"),
                    "failure_count": row.get("failure_count"),
                    "failures": ";".join(row.get("failures") or []),
                    "pdf": row.get("pdf"),
                }
            )

    lines = [
        "# Canonical Publication Flow Audit",
        "",
        f"Audit ID: `{report.get('audit_id')}`",
        f"Factory bắt buộc: `{CANONICAL_PUBLICATION_FACTORY_ID}`",
        f"Reader gate bắt buộc: `{CANONICAL_READER_EXPERIENCE_GATE_ID}`",
        f"Content generator bắt buộc: `{CANONICAL_CONTENT_GENERATOR_ID}`",
        "",
        "| Family | Pattern | Title | Status | Failures |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        failures = "; ".join(row.get("failures") or [])
        lines.append(f"| {row.get('family')} | {row.get('pattern_id')} | {row.get('title')} | {row.get('status')} | {failures} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {"json": json_path, "csv": csv_path, "md": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit final chapters against canonical publication flow.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    report = audit_manifest(Path(args.manifest))
    paths = write_audit(report, Path(args.out_dir))
    print(json.dumps({"report": report, "paths": {key: str(value) for key, value in paths.items()}}, ensure_ascii=False, indent=2))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
