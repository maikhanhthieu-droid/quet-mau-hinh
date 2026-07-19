"""Machine-checkable publication contract for final chart-pattern chapters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from scanner.canonical_publication_chapter_factory import (
    CANONICAL_PUBLICATION_FACTORY_ID,
    CANONICAL_PUBLICATION_FLOW,
    CANONICAL_PUBLICATION_STYLE_VERSION,
    CANONICAL_READER_EXPERIENCE_GATE_ID,
)
from scanner.canonical_chapter_content import CANONICAL_CONTENT_GENERATOR_ID
from scanner.canonical_editorial_layer import (
    CANONICAL_AI_EDITORIAL_GATE_ID,
    CANONICAL_EDITORIAL_WORKFLOW_ID,
    validate_canonical_editorial_sections,
)


PUBLICATION_CORE_ID = "pattern_publication_core_v1"
SOURCE_GROUNDED_PUBLICATION_GATE_ID = "source_grounded_publication_gate_v1"
CANONICAL_SOURCE_GUIDED_REFINEMENT_ID = "canonical_source_guided_refinement_v1"
SOURCE_GROUNDED_MIN_RULES = 6
REQUIRED_EDITORIAL_SECTIONS = (
    "summary",
    "tour",
    "failure",
    "statistics",
    "post_breakout",
    "size_volume",
    "tactics",
    "checklist",
)

SOURCE_GUIDED_REFINEMENT_REQUIRED_STAGES = (
    "source_style_dossier",
    "source_guided_ai_sections",
    "refined_ai_sections",
    "canonical_pdf",
    "style_v3_audit",
)


def _read_json(path: Path) -> Mapping[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, Mapping) else {}


def _artifact_path(chapter: Mapping[str, Any], key: str) -> Path | None:
    value = str(chapter.get(key) or "").strip()
    return Path(value) if value else None


def _nonempty_section(value: Any) -> bool:
    if isinstance(value, list):
        return any(str(item).strip() for item in value)
    return bool(str(value or "").strip())


def validate_publication_contract(chapter: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one final chapter entry.

    The contract is intentionally artifact-based. A chapter cannot pass because
    a script name looks right; it must provide the payload, manuscript, notes,
    and source-grounding artifacts that define the public publication flow.
    """

    failures: list[dict[str, Any]] = []
    pattern_id = chapter.get("pattern_id")
    family = str(chapter.get("family") or "").strip()
    expected_factory = str(chapter.get("factory_id") or "").strip()
    expected_flow = str(chapter.get("publication_flow") or "").strip()
    expected_core = str(chapter.get("publication_core_id") or PUBLICATION_CORE_ID).strip()
    canonical_required = True

    def fail(check: str, detail: str) -> None:
        failures.append({"check": check, "pattern_id": pattern_id, "detail": detail})

    paths = {
        "pdf": _artifact_path(chapter, "pdf"),
        "payload": _artifact_path(chapter, "payload"),
        "manuscript": _artifact_path(chapter, "manuscript"),
        "notes": _artifact_path(chapter, "notes"),
        "source_notes": _artifact_path(chapter, "source_notes"),
    }
    for key, path in paths.items():
        if path is None:
            fail(f"{key}_exists", "missing manifest field")
        elif not path.exists() or not path.is_file():
            fail(f"{key}_exists", str(path))

    payload_path = paths["payload"]
    payload = _read_json(payload_path) if payload_path else {}
    if canonical_required:
        if expected_factory != CANONICAL_PUBLICATION_FACTORY_ID:
            fail("canonical_manifest_factory_id", f"expected {CANONICAL_PUBLICATION_FACTORY_ID}, got {expected_factory}")
        if expected_flow != CANONICAL_PUBLICATION_FLOW:
            fail("canonical_publication_flow", f"expected {CANONICAL_PUBLICATION_FLOW}, got {expected_flow}")
        if str(chapter.get("canonical_publication_factory_id") or "").strip() != CANONICAL_PUBLICATION_FACTORY_ID:
            fail("canonical_manifest_factory_marker", "missing canonical_publication_factory_id")
        if str(chapter.get("canonical_reader_experience_gate_id") or "").strip() != CANONICAL_READER_EXPERIENCE_GATE_ID:
            fail("canonical_reader_experience_gate", "missing canonical_reader_experience_gate_id")
        if str(chapter.get("canonical_publication_style_version") or "").strip() != CANONICAL_PUBLICATION_STYLE_VERSION:
            fail("canonical_publication_style_version", f"expected {CANONICAL_PUBLICATION_STYLE_VERSION}")
        if str(chapter.get("canonical_ai_editorial_gate_id") or "").strip() != CANONICAL_AI_EDITORIAL_GATE_ID:
            fail("canonical_ai_editorial_gate", f"expected {CANONICAL_AI_EDITORIAL_GATE_ID}")
        if str(chapter.get("canonical_editorial_workflow_id") or "").strip() != CANONICAL_EDITORIAL_WORKFLOW_ID:
            fail("canonical_editorial_workflow", f"expected {CANONICAL_EDITORIAL_WORKFLOW_ID}")
        if str(chapter.get("canonical_content_generator_id") or "").strip() != CANONICAL_CONTENT_GENERATOR_ID:
            fail("canonical_content_generator", f"expected {CANONICAL_CONTENT_GENERATOR_ID}")
    if payload:
        if expected_factory and payload.get("factory_id") != expected_factory:
            fail("payload_factory_id", f"expected {expected_factory}, got {payload.get('factory_id')}")
        if payload.get("publication_core_id") != expected_core:
            fail("payload_publication_core_id", f"expected {expected_core}, got {payload.get('publication_core_id')}")
        if str(payload.get("status") or "").upper() != "PASS":
            fail("payload_status", f"expected PASS, got {payload.get('status')}")
        if canonical_required:
            if payload.get("canonical_publication_factory_id") != CANONICAL_PUBLICATION_FACTORY_ID:
                fail("payload_canonical_factory_id", f"expected {CANONICAL_PUBLICATION_FACTORY_ID}, got {payload.get('canonical_publication_factory_id')}")
            if payload.get("canonical_reader_experience_gate_id") != CANONICAL_READER_EXPERIENCE_GATE_ID:
                fail(
                    "payload_canonical_reader_experience_gate",
                    f"expected {CANONICAL_READER_EXPERIENCE_GATE_ID}, got {payload.get('canonical_reader_experience_gate_id')}",
                )
            if payload.get("canonical_publication_style_version") != CANONICAL_PUBLICATION_STYLE_VERSION:
                fail(
                    "payload_canonical_publication_style_version",
                    f"expected {CANONICAL_PUBLICATION_STYLE_VERSION}, got {payload.get('canonical_publication_style_version')}",
                )
            if payload.get("canonical_ai_editorial_gate_id") != CANONICAL_AI_EDITORIAL_GATE_ID:
                fail(
                    "payload_canonical_ai_editorial_gate",
                    f"expected {CANONICAL_AI_EDITORIAL_GATE_ID}, got {payload.get('canonical_ai_editorial_gate_id')}",
                )
            if payload.get("canonical_editorial_workflow_id") != CANONICAL_EDITORIAL_WORKFLOW_ID:
                fail(
                    "payload_canonical_editorial_workflow",
                    f"expected {CANONICAL_EDITORIAL_WORKFLOW_ID}, got {payload.get('canonical_editorial_workflow_id')}",
                )
            if payload.get("canonical_content_generator_id") != CANONICAL_CONTENT_GENERATOR_ID:
                fail(
                    "payload_canonical_content_generator",
                    f"expected {CANONICAL_CONTENT_GENERATOR_ID}, got {payload.get('canonical_content_generator_id')}",
                )
            editorial_report = validate_canonical_editorial_sections(payload)
            if editorial_report["status"] != "PASS":
                fail("payload_canonical_editorial_depth", str(editorial_report["failures"][:5]))
        editorial = payload.get("editorial_sections") if isinstance(payload.get("editorial_sections"), Mapping) else {}
        missing = [section for section in REQUIRED_EDITORIAL_SECTIONS if not _nonempty_section(editorial.get(section))]
        if missing:
            fail("editorial_sections", "missing or empty: " + ", ".join(missing))
        if family in {"triangle_family", "cup_handle_family", "rectangle_family"}:
            editorial_source = str(payload.get("editorial_source_path") or "").strip()
            if not editorial_source:
                fail(f"{family}_editorial_source", "missing approved editorial source path")
            elif not Path(editorial_source).exists():
                fail(f"{family}_editorial_source_exists", editorial_source)
            elif family in {"cup_handle_family", "rectangle_family"} and Path(editorial_source).suffix == ".py":
                check = "cup_handle_editorial_source_artifact" if family == "cup_handle_family" else "rectangle_family_editorial_source_artifact"
                fail(check, f"expected approved editorial artifact, got code file: {editorial_source}")
    elif payload_path and payload_path.exists() and payload_path.is_file():
        fail("payload_parse", str(payload_path))

    source_notes_path = paths["source_notes"]
    source_notes = _read_json(source_notes_path) if source_notes_path else {}
    source_grounding_required = (
        bool(chapter.get("source_grounding_required"))
        or str(chapter.get("source_grounding_policy_id") or "").strip() == SOURCE_GROUNDED_PUBLICATION_GATE_ID
    )
    direct_source_review_required = bool(chapter.get("direct_source_review_required"))
    if source_notes:
        if str(source_notes.get("status") or "").upper() != "PASS":
            fail("source_notes_status", f"expected PASS, got {source_notes.get('status')}")
        rules = source_notes.get("source_rules") if isinstance(source_notes.get("source_rules"), list) else []
        if len(rules) < 2:
            fail("source_rules", f"expected at least 2, got {len(rules)}")
        notes_policy_id = str(source_notes.get("source_grounding_policy_id") or "").strip()
        if notes_policy_id == SOURCE_GROUNDED_PUBLICATION_GATE_ID:
            source_grounding_required = True
        if source_grounding_required:
            if notes_policy_id != SOURCE_GROUNDED_PUBLICATION_GATE_ID:
                fail("source_grounding_policy_id", f"expected {SOURCE_GROUNDED_PUBLICATION_GATE_ID}, got {notes_policy_id}")
            if len(rules) < SOURCE_GROUNDED_MIN_RULES:
                fail("source_grounded_source_rules", f"expected at least {SOURCE_GROUNDED_MIN_RULES}, got {len(rules)}")
            grounding_level = str(source_notes.get("source_grounding_level") or "").strip().lower()
            if grounding_level in {"partial", "implementation_aligned"}:
                fail("source_grounding_level", f"publication gate cannot pass with {grounding_level}")
        if direct_source_review_required:
            review = source_notes.get("direct_pdf_review") if isinstance(source_notes.get("direct_pdf_review"), Mapping) else {}
            if str(review.get("status") or "").upper() != "PASS":
                fail("direct_source_review_status", f"expected PASS, got {review.get('status')}")
            if not str(review.get("pdf_path") or "").strip():
                fail("direct_source_review_pdf_path", "missing pdf_path")
            if not review.get("pdf_pages_checked"):
                fail("direct_source_review_pdf_pages", "missing pdf_pages_checked")
            if not review.get("book_pages_checked"):
                fail("direct_source_review_book_pages", "missing book_pages_checked")
    elif source_notes_path and source_notes_path.exists() and source_notes_path.is_file():
        fail("source_notes_parse", str(source_notes_path))
    elif direct_source_review_required:
        fail("direct_source_review_status", "missing source notes")

    for key in ("manuscript", "notes"):
        path = paths[key]
        if path and path.exists() and path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            if expected_factory and f"`{expected_factory}`" not in text:
                fail(f"{key}_factory_marker", expected_factory)
            if f"`{expected_core}`" not in text:
                fail(f"{key}_core_marker", expected_core)
            if canonical_required and f"`{CANONICAL_PUBLICATION_FACTORY_ID}`" not in text:
                fail(f"{key}_canonical_factory_marker", CANONICAL_PUBLICATION_FACTORY_ID)
            if key == "manuscript":
                missing = [section for section in REQUIRED_EDITORIAL_SECTIONS if f"## {section}" not in text]
                if missing:
                    fail("manuscript_sections", "missing: " + ", ".join(missing))

    if expected_flow and expected_factory and expected_core and expected_flow != f"{expected_factory} + {expected_core}":
        fail("publication_flow_string", f"expected {expected_factory} + {expected_core}, got {expected_flow}")
    if canonical_required and expected_flow != CANONICAL_PUBLICATION_FLOW:
        fail("canonical_publication_flow_string", f"expected {CANONICAL_PUBLICATION_FLOW}, got {expected_flow}")
    if str(chapter.get("chapter_writing_policy_id") or "").strip():
        writing_report = validate_source_guided_refinement_contract(chapter)
        if writing_report["status"] != "PASS":
            failures.extend(writing_report["failures"])

    return {
        "status": "PASS" if not failures else "FAIL",
        "pattern_id": pattern_id,
        "factory_id": expected_factory,
        "publication_core_id": expected_core,
        "failures": failures,
    }


def validate_source_guided_refinement_contract(chapter: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the preferred writing workflow for new or refreshed chapters.

    This is the chapter-experience contract, separate from the statistical
    scanner and from the PDF factory. It records the rule we learned from Bull
    Flag: use the original book chapter as a style/structure reference, generate
    a source-guided candidate, then run a smaller refinement pass before the
    canonical PDF factory renders the final artifact.
    """

    failures: list[dict[str, Any]] = []
    pattern_id = chapter.get("pattern_id")

    def fail(check: str, detail: str) -> None:
        failures.append({"check": check, "pattern_id": pattern_id, "detail": detail})

    policy_id = str(chapter.get("chapter_writing_policy_id") or "").strip()
    if policy_id != CANONICAL_SOURCE_GUIDED_REFINEMENT_ID:
        fail("chapter_writing_policy_id", f"expected {CANONICAL_SOURCE_GUIDED_REFINEMENT_ID}, got {policy_id}")

    stages = chapter.get("chapter_writing_stages") if isinstance(chapter.get("chapter_writing_stages"), Mapping) else {}
    for stage in SOURCE_GUIDED_REFINEMENT_REQUIRED_STAGES:
        path_value = str(stages.get(stage) or "").strip()
        if not path_value:
            fail(f"{stage}_exists", "missing stage artifact path")
            continue
        path = Path(path_value)
        if not path.exists() or not path.is_file():
            fail(f"{stage}_exists", str(path))

    notes = str(chapter.get("chapter_writing_notes") or "").lower()
    if "không sao chép" not in notes and "do not copy" not in notes:
        fail("chapter_writing_notes_copy_policy", "missing explicit no-copy/no-translation note")
    if "factory" not in notes and "canonical" not in notes:
        fail("chapter_writing_notes_factory_policy", "missing canonical factory note")

    return {
        "status": "PASS" if not failures else "FAIL",
        "pattern_id": pattern_id,
        "chapter_writing_policy_id": policy_id,
        "required_stages": list(SOURCE_GUIDED_REFINEMENT_REQUIRED_STAGES),
        "failures": failures,
    }
