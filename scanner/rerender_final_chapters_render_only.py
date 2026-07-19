"""Render final chapters from locked payloads without invoking AI.

This command is intentionally narrower than ``rebuild_source_guided_final_chapters``.
Use it when the publication core/layout changes but the approved AI editorial
sections, scanner outputs, examples, and source notes must remain unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.audit_publication_style_v3 import audit_publication_style_v3  # noqa: E402
from scanner.canonical_publication_chapter_factory import (  # noqa: E402
    CANONICAL_PUBLICATION_FACTORY_ID,
    CANONICAL_PUBLICATION_FLOW,
    CANONICAL_PUBLICATION_STYLE_VERSION,
    CANONICAL_READER_EXPERIENCE_GATE_ID,
    build_canonical_publication_chapter,
)
from scanner.canonical_chapter_content import CANONICAL_CONTENT_GENERATOR_ID  # noqa: E402
from scanner.canonical_editorial_layer import CANONICAL_AI_EDITORIAL_GATE_ID, CANONICAL_EDITORIAL_WORKFLOW_ID  # noqa: E402
from scanner.pattern_publication_core import PUBLICATION_CORE_ID  # noqa: E402
from scanner.promote_final_chapter import promote_final_chapters  # noqa: E402
from scanner.publication_flow_contract import CANONICAL_SOURCE_GUIDED_REFINEMENT_ID  # noqa: E402
from scanner.rebuild_source_guided_final_chapters import (  # noqa: E402
    _load_charts,
    _load_events,
    _load_publication_spec,
    _read_json,
    _slug_from_entry,
    _write_json,
)
from scanner.validate_final_chapters_manifest import DEFAULT_MANIFEST  # noqa: E402


def _select_entries(manifest: Mapping[str, Any], patterns: list[str]) -> list[Mapping[str, Any]]:
    chapters = [chapter for chapter in manifest.get("chapters", []) if isinstance(chapter, Mapping)]
    if not patterns:
        return chapters
    wanted = set(patterns)
    return [chapter for chapter in chapters if chapter.get("pattern_id") in wanted]


def rerender_one(entry: Mapping[str, Any]) -> Path:
    pattern_id = str(entry.get("pattern_id"))
    family = str(entry.get("family") or "uncategorized")
    slug = _slug_from_entry(entry)
    payload_path = Path(str(entry.get("payload")))
    source_notes_path = Path(str(entry.get("source_notes")))
    source_pdf = Path(str(entry.get("source_pdf") or entry.get("pdf")))
    render_dir = source_pdf.parent
    payload = dict(_read_json(payload_path))
    source_notes = dict(_read_json(source_notes_path))
    spec = _load_publication_spec(entry, payload)
    events = _load_events(pattern_id)
    charts = _load_charts(source_pdf, payload_path, slug)
    result = build_canonical_publication_chapter(
        payload=payload,
        source_notes=source_notes,
        events=events,
        path_df=pd.DataFrame(),
        charts=charts,
        spec=spec,
        out_dir=render_dir,
        pdf_filename=source_pdf.name,
        payload_filename=payload_path.name,
        manuscript_filename=Path(str(entry.get("manuscript") or f"{slug}_ai_editorial_manuscript.md")).name,
        notes_filename=Path(str(entry.get("notes") or f"{slug}_public_chapter_notes.md")).name,
        family_id=family,
        source_family_factory_id=payload.get("source_family_factory_id"),
    )
    audit_path = render_dir / "style_v3_audit.json"
    audit = audit_publication_style_v3(Path(result["pdf"]), Path(result["payload"]))
    _write_json(audit_path, audit)
    if audit["status"] != "PASS":
        raise RuntimeError(f"style-v3 audit failed for {pattern_id}: {audit['failures']}")

    manifest_entry = dict(entry)
    manifest_entry.update(
        {
            "status": "final",
            "source_pdf": str(result["pdf"]),
            "payload": str(result["payload"]),
            "manuscript": str(result["manuscript"]),
            "notes": str(result["notes"]),
            "factory_id": CANONICAL_PUBLICATION_FACTORY_ID,
            "publication_core_id": PUBLICATION_CORE_ID,
            "publication_flow": CANONICAL_PUBLICATION_FLOW,
            "canonical_publication_factory_id": CANONICAL_PUBLICATION_FACTORY_ID,
            "canonical_reader_experience_gate_id": CANONICAL_READER_EXPERIENCE_GATE_ID,
            "canonical_publication_style_version": CANONICAL_PUBLICATION_STYLE_VERSION,
            "canonical_editorial_workflow_id": CANONICAL_EDITORIAL_WORKFLOW_ID,
            "canonical_ai_editorial_gate_id": CANONICAL_AI_EDITORIAL_GATE_ID,
            "canonical_content_generator_id": CANONICAL_CONTENT_GENERATOR_ID,
            "style_v3_audit": str(audit_path),
            "chapter_writing_policy_id": CANONICAL_SOURCE_GUIDED_REFINEMENT_ID,
        }
    )
    entry_path = render_dir.parent / f"{pattern_id}_final_manifest_entry.json"
    _write_json(entry_path, manifest_entry)
    return entry_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Render final chapters from locked payloads without AI calls.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--pattern", action="append", default=[])
    parser.add_argument("--promote", action="store_true")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    manifest = _read_json(manifest_path)
    entries = _select_entries(manifest, list(args.pattern))
    if not entries:
        raise SystemExit("No chapters selected.")

    entry_paths: list[Path] = []
    for index, entry in enumerate(entries, start=1):
        print(f"[{index}/{len(entries)}] render-only {entry.get('pattern_id')}", flush=True)
        entry_paths.append(rerender_one(entry))
    report: dict[str, Any] = {"status": "PASS", "rendered": [str(path) for path in entry_paths], "promoted": None}
    if args.promote:
        report["promoted"] = promote_final_chapters(entry_paths=entry_paths, manifest_path=manifest_path)
        if report["promoted"]["status"] != "PASS":
            report["status"] = "FAIL"
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
