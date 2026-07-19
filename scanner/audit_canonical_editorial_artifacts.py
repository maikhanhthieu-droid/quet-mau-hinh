"""Audit final chapters against their approved editorial artifacts.

The final payload can already contain rendered ``editorial_sections``. That is
not strong enough evidence that the chapter can be rebuilt cleanly. This gate
loads each chapter's ``editorial_source_path`` and validates the approved
AI/refinement artifact directly through ``prepare_canonical_chapter_content``.
If the source artifact is missing or thin, the chapter must be rewritten through
the canonical editorial workflow before it can be rerendered as final.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from scanner.canonical_chapter_content import prepare_canonical_chapter_content
from scanner.validate_final_chapters_manifest import DEFAULT_MANIFEST


AUDIT_ID = "canonical_editorial_artifact_gate_v1"


def _read_json(path: Path) -> Mapping[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, Mapping) else {}


def _resolve_path(path_value: Any, *, root: Path) -> Path | None:
    text = str(path_value or "").strip()
    if not text:
        return None
    path = Path(text)
    if path.is_absolute():
        return path
    return root / path


def audit_manifest(manifest_path: Path = DEFAULT_MANIFEST, *, root: Path | None = None) -> dict[str, Any]:
    project_root = root or Path(__file__).resolve().parents[1]
    manifest = _read_json(manifest_path)
    chapters = [row for row in manifest.get("chapters", []) if isinstance(row, Mapping)]
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for entry in chapters:
        pattern_id = str(entry.get("pattern_id") or "")
        payload_path = _resolve_path(entry.get("payload"), root=project_root)
        row: dict[str, Any] = {
            "pattern_id": pattern_id,
            "family": entry.get("family"),
            "payload": str(payload_path) if payload_path else "",
            "editorial_source_path": "",
            "status": "UNKNOWN",
            "failure": "",
        }
        if not payload_path or not payload_path.exists():
            row["status"] = "FAIL"
            row["failure"] = "payload_missing"
            failures.append(dict(row))
            rows.append(row)
            continue

        payload = _read_json(payload_path)
        editorial_source = _resolve_path(payload.get("editorial_source_path"), root=project_root)
        row["editorial_source_path"] = str(editorial_source) if editorial_source else ""
        if not editorial_source or not editorial_source.exists():
            row["status"] = "FAIL"
            row["failure"] = "editorial_source_missing"
            failures.append(dict(row))
            rows.append(row)
            continue

        try:
            prepared = prepare_canonical_chapter_content(payload, approved_sections_path=editorial_source)
        except Exception as exc:  # noqa: BLE001 - audit should record all gate failures
            row["status"] = "FAIL"
            row["failure"] = str(exc)
            failures.append(dict(row))
            rows.append(row)
            continue

        report = prepared.get("canonical_content_generation_report", {}).get("editorial_gate_report", {})
        row["status"] = "PASS" if report.get("status") == "PASS" else "FAIL"
        row["section_count"] = prepared.get("canonical_content_generation_report", {}).get("section_count")
        if row["status"] != "PASS":
            row["failure"] = json.dumps(report.get("failures", []), ensure_ascii=False)
            failures.append(dict(row))
        rows.append(row)

    return {
        "audit_id": AUDIT_ID,
        "status": "PASS" if not failures else "FAIL",
        "chapter_count": len(chapters),
        "pass_count": sum(1 for row in rows if row["status"] == "PASS"),
        "failure_count": len(failures),
        "rows": rows,
        "failures": failures,
    }


def write_report(report: Mapping[str, Any], out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "canonical_editorial_artifact_gate.json"
    md_path = out_dir / "canonical_editorial_artifact_gate.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    lines = [
        "# Canonical Editorial Artifact Gate",
        "",
        f"Audit ID: `{report.get('audit_id')}`",
        f"Status: `{report.get('status')}`",
        f"Chapters: `{report.get('chapter_count')}`",
        f"Pass: `{report.get('pass_count')}`",
        f"Fail: `{report.get('failure_count')}`",
        "",
        "| Pattern | Status | Failure |",
        "|---|---|---|",
    ]
    for row in report.get("rows", []):
        lines.append(f"| {row.get('pattern_id')} | {row.get('status')} | {str(row.get('failure') or '')[:180]} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit approved editorial artifacts for all final chapters.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--out-dir", default="artifacts/final_chapters/governance")
    args = parser.parse_args()
    report = audit_manifest(Path(args.manifest))
    paths = write_report(report, Path(args.out_dir))
    print(json.dumps({"report": report, "paths": paths}, ensure_ascii=False, indent=2, default=str))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
