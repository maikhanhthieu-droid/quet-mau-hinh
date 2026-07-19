"""Promote rebuilt canonical style-v3 chapters into the final folder."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.canonical_chapter_content import CANONICAL_CONTENT_GENERATOR_ID  # noqa: E402
from scanner.canonical_editorial_layer import CANONICAL_AI_EDITORIAL_GATE_ID, CANONICAL_EDITORIAL_WORKFLOW_ID  # noqa: E402
from scanner.canonical_publication_chapter_factory import (  # noqa: E402
    CANONICAL_PUBLICATION_FACTORY_ID,
    CANONICAL_PUBLICATION_FLOW,
    CANONICAL_PUBLICATION_STYLE_VERSION,
    CANONICAL_READER_EXPERIENCE_GATE_ID,
)
from scanner.pattern_publication_core import PUBLICATION_CORE_ID  # noqa: E402


DEFAULT_MANIFEST = Path("artifacts/final_chapters/final_chapters_manifest.json")


def _read_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, Mapping) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _style_audit_path(entry: Mapping[str, Any]) -> Path:
    payload_path = Path(str(entry.get("payload") or ""))
    return payload_path.with_name("style_v3_audit.json")


def _single_artifact(parent: Path, pattern: str) -> str | None:
    matches = sorted(parent.glob(pattern))
    return str(matches[0]) if matches else None


def promote_patterns(pattern_ids: list[str], *, manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest = dict(_read_json(manifest_path))
    chapters = manifest.get("chapters") if isinstance(manifest.get("chapters"), list) else []
    requested = set(pattern_ids)
    promoted: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for entry in chapters:
        if not isinstance(entry, dict) or entry.get("pattern_id") not in requested:
            continue
        pattern_id = str(entry.get("pattern_id"))
        source_pdf = Path(str(entry.get("source_pdf") or ""))
        final_pdf = Path(str(entry.get("pdf") or ""))
        payload_path = Path(str(entry.get("payload") or ""))
        style_audit = _style_audit_path(entry)
        if not source_pdf.exists():
            failures.append({"pattern_id": pattern_id, "check": "source_pdf_exists", "detail": str(source_pdf)})
            continue
        if not payload_path.exists():
            failures.append({"pattern_id": pattern_id, "check": "payload_exists", "detail": str(payload_path)})
            continue
        if not style_audit.exists():
            failures.append({"pattern_id": pattern_id, "check": "style_audit_exists", "detail": str(style_audit)})
            continue
        audit = _read_json(style_audit)
        if audit.get("status") != "PASS":
            failures.append({"pattern_id": pattern_id, "check": "style_audit_pass", "detail": str(style_audit)})
            continue

        final_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_pdf, final_pdf)
        entry["factory_id"] = CANONICAL_PUBLICATION_FACTORY_ID
        entry["publication_core_id"] = PUBLICATION_CORE_ID
        entry["publication_flow"] = CANONICAL_PUBLICATION_FLOW
        entry["canonical_publication_factory_id"] = CANONICAL_PUBLICATION_FACTORY_ID
        entry["canonical_reader_experience_gate_id"] = CANONICAL_READER_EXPERIENCE_GATE_ID
        entry["canonical_publication_style_version"] = CANONICAL_PUBLICATION_STYLE_VERSION
        entry["canonical_editorial_workflow_id"] = CANONICAL_EDITORIAL_WORKFLOW_ID
        entry["canonical_ai_editorial_gate_id"] = CANONICAL_AI_EDITORIAL_GATE_ID
        entry["canonical_content_generator_id"] = CANONICAL_CONTENT_GENERATOR_ID
        entry["style_v3_audit"] = str(style_audit)
        artifact_dir = payload_path.parent
        manuscript = _single_artifact(artifact_dir, "*_ai_editorial_manuscript.md")
        notes = _single_artifact(artifact_dir, "*_public_chapter_notes.md")
        source_notes = _single_artifact(artifact_dir, "*_source_notes.json")
        publication_spec = _single_artifact(artifact_dir, "*_publication_spec.json")
        if manuscript:
            entry["manuscript"] = manuscript
        if notes:
            entry["notes"] = notes
        if source_notes:
            entry["source_notes"] = source_notes
        if publication_spec:
            entry["publication_spec"] = publication_spec
        promoted.append({"pattern_id": pattern_id, "final_pdf": str(final_pdf), "source_pdf": str(source_pdf)})

    missing = sorted(requested - {row["pattern_id"] for row in promoted} - {row["pattern_id"] for row in failures})
    for pattern_id in missing:
        failures.append({"pattern_id": pattern_id, "check": "manifest_entry_exists", "detail": "not found"})

    if not failures:
        _write_json(manifest_path, manifest)

    return {
        "status": "PASS" if not failures else "FAIL",
        "manifest": str(manifest_path),
        "promoted": promoted,
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote rebuilt canonical style-v3 chapters.")
    parser.add_argument("pattern_ids", nargs="+")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    args = parser.parse_args()
    report = promote_patterns(args.pattern_ids, manifest_path=Path(args.manifest))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
