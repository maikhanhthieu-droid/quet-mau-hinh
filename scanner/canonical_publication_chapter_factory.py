"""Canonical public-chapter factory and reader-experience contract.

This is the only factory allowed to produce *final* investor-facing PDF
chapters. Pattern/family modules may own scanners, morphology, target logic,
statistics, source grounding, and examples. They must hand those ingredients to
this factory instead of rendering a final PDF directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping

import pandas as pd

from scanner.canonical_chapter_content import (
    CANONICAL_CONTENT_CONTRACT,
    CANONICAL_CONTENT_GENERATOR_ID,
    prepare_canonical_chapter_content,
)
from scanner.canonical_editorial_layer import (
    CANONICAL_AI_EDITORIAL_GATE_ID,
    CANONICAL_EDITORIAL_WORKFLOW_ID,
    CANONICAL_EDITORIAL_CONTRACT,
    validate_canonical_editorial_sections,
)
from scanner.pattern_publication_core import PUBLICATION_CORE_ID, build_pattern_public_chapter


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_PUBLICATION_FACTORY_ID = "canonical_publication_chapter_factory_v1"
CANONICAL_READER_EXPERIENCE_GATE_ID = "canonical_reader_experience_gate_v1"
CANONICAL_PUBLICATION_STYLE_VERSION = "canonical_publication_style_v3"
CANONICAL_PUBLICATION_FLOW = f"{CANONICAL_PUBLICATION_FACTORY_ID} + {PUBLICATION_CORE_ID}"

REQUIRED_READER_SECTIONS = (
    "Kết quả quan trọng",
    "Mẫu hình hoạt động ra sao",
    "Cách nhận diện",
    "Ví dụ minh họa",
    "Tập trung vào thất bại",
    "Cách đọc kết quả quan trọng",
    "Khi mẫu đáng chú ý hơn",
    "Cách sử dụng thực tế",
    "Phụ lục kỹ thuật",
)

CANONICAL_STORY_CONTRACT = {
    "must_read_like": "investor-facing Vietnamese chart-pattern chapter",
    "must_not_read_like": "internal audit, scanner QA, release-gate report, or source-comparison memo",
    "canonical_model": "canonical public chart-pattern chapter reader flow",
    "required_sections": list(REQUIRED_READER_SECTIONS),
    "editorial_workflow_id": CANONICAL_EDITORIAL_WORKFLOW_ID,
    "editorial_gate_id": CANONICAL_AI_EDITORIAL_GATE_ID,
    "content_generator_id": CANONICAL_CONTENT_GENERATOR_ID,
    "publication_style_version": CANONICAL_PUBLICATION_STYLE_VERSION,
    "style_v3_requirements": [
        "statistics must be translated into reader-facing interpretation",
        "tables must be bridged by prose before and after the table",
        "example charts must read as mini case studies",
        "appendix material must close with a practical reading guide",
    ],
}


def canonicalize_publication_payload(payload: Mapping[str, Any], *, family_factory_id: str | None = None) -> Dict[str, Any]:
    """Attach canonical publication metadata to a chapter payload."""

    out: Dict[str, Any] = dict(payload)
    if out.get("canonical_content_generator_id") != CANONICAL_CONTENT_GENERATOR_ID:
        raise ValueError(f"canonical content generator missing: expected {CANONICAL_CONTENT_GENERATOR_ID}")
    editorial_report = validate_canonical_editorial_sections(out)
    if editorial_report["status"] != "PASS":
        raise ValueError(f"canonical editorial gate failed: {editorial_report['failures']}")
    out["status"] = out.get("status") or "PASS"
    out["publication_core_id"] = PUBLICATION_CORE_ID
    out["canonical_publication_factory_id"] = CANONICAL_PUBLICATION_FACTORY_ID
    out["canonical_reader_experience_gate_id"] = CANONICAL_READER_EXPERIENCE_GATE_ID
    out["canonical_publication_style_version"] = CANONICAL_PUBLICATION_STYLE_VERSION
    out["canonical_editorial_workflow_id"] = CANONICAL_EDITORIAL_WORKFLOW_ID
    out["canonical_ai_editorial_gate_id"] = CANONICAL_AI_EDITORIAL_GATE_ID
    out["canonical_ai_editorial_gate_report"] = editorial_report
    out["canonical_editorial_contract"] = CANONICAL_EDITORIAL_CONTRACT
    out["canonical_content_contract"] = out.get("canonical_content_contract") or CANONICAL_CONTENT_CONTRACT
    out["canonical_story_contract"] = CANONICAL_STORY_CONTRACT
    if family_factory_id:
        out["source_family_factory_id"] = family_factory_id
    out["factory_id"] = CANONICAL_PUBLICATION_FACTORY_ID
    return out


def canonicalize_publication_spec(spec: Mapping[str, Any], *, family_id: str | None = None) -> Dict[str, Any]:
    """Attach canonical rendering metadata to a family/pattern spec."""

    out: Dict[str, Any] = dict(spec)
    out["canonical_publication_factory_id"] = CANONICAL_PUBLICATION_FACTORY_ID
    out["canonical_reader_experience_gate_id"] = CANONICAL_READER_EXPERIENCE_GATE_ID
    out["canonical_publication_style_version"] = CANONICAL_PUBLICATION_STYLE_VERSION
    out["canonical_story_contract"] = CANONICAL_STORY_CONTRACT
    if family_id:
        out["family_id"] = family_id
    return out


def _resolve_editorial_source_path(payload: Mapping[str, Any]) -> Path | None:
    value = payload.get("editorial_source_path")
    if not value:
        return None
    path = Path(str(value))
    if not path.is_absolute():
        path = ROOT / path
    return path if path.exists() and path.is_file() else None


def build_canonical_publication_chapter(
    *,
    payload: Mapping[str, Any],
    source_notes: Mapping[str, Any],
    events: pd.DataFrame,
    path_df: pd.DataFrame,
    charts: Mapping[str, Path],
    spec: Mapping[str, Any],
    out_dir: Path,
    pdf_filename: str,
    payload_filename: str,
    manuscript_filename: str,
    notes_filename: str,
    family_id: str,
    source_family_factory_id: str | None = None,
    approved_sections_path: Path | None = None,
    editorial_sections: Mapping[str, Any] | None = None,
) -> Dict[str, Path]:
    """Render one final public chapter through the canonical PDF authority."""

    if approved_sections_path is not None or editorial_sections is not None:
        prepared_payload = prepare_canonical_chapter_content(
            payload,
            approved_sections_path=approved_sections_path,
            editorial_sections=editorial_sections,
        )
    elif (resolved_editorial_source_path := _resolve_editorial_source_path(payload)) is not None:
        prepared_payload = prepare_canonical_chapter_content(
            payload,
            approved_sections_path=resolved_editorial_source_path,
        )
    elif payload.get("canonical_content_generator_id") == CANONICAL_CONTENT_GENERATOR_ID:
        prepared_payload = payload
    else:
        prepared_payload = payload
    canonical_payload = canonicalize_publication_payload(prepared_payload, family_factory_id=source_family_factory_id)
    canonical_spec = canonicalize_publication_spec(spec, family_id=family_id)
    return build_pattern_public_chapter(
        payload=canonical_payload,
        source_notes=source_notes,
        events=events,
        path_df=path_df,
        charts=charts,
        spec=canonical_spec,
        out_dir=out_dir,
        pdf_filename=pdf_filename,
        payload_filename=payload_filename,
        manuscript_filename=manuscript_filename,
        notes_filename=notes_filename,
        family_factory_id=CANONICAL_PUBLICATION_FACTORY_ID,
    )
