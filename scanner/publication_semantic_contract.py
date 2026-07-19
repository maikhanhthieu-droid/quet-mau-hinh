"""Editorial-semantic gate for final public chart-pattern chapters."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from pypdf import PdfReader


PUBLICATION_SEMANTIC_GATE_ID = "publication_semantic_gate_v1"

DEFAULT_INTERNAL_FORBIDDEN_TERMS = (
    "payload",
    "factory",
    "source_alignment",
    "publication_quality_tier",
    "data_limited",
    "branch_id",
    "chapter_lane",
    "candidate",
    "headline",
)

ENGLISH_WORD_RE = re.compile(r"[A-Za-z]{3,}(?:[-'][A-Za-z]+)?")


def _read_json(path: Path | None) -> Mapping[str, Any]:
    if not path or not path.exists() or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, Mapping) else {}


def _artifact_path(chapter: Mapping[str, Any], key: str) -> Path | None:
    value = str(chapter.get(key) or "").strip()
    return Path(value) if value else None


def _pdf_text(path: Path | None) -> str:
    if not path or not path.exists() or not path.is_file():
        return ""
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _is_raw_english_fragment(value: Any) -> bool:
    text = str(value or "").strip()
    if len(text) < 28:
        return False
    words = ENGLISH_WORD_RE.findall(text)
    if len(words) < 5:
        return False
    ascii_letters = sum(ch.isascii() and ch.isalpha() for ch in text)
    letters = sum(ch.isalpha() for ch in text)
    return letters > 0 and ascii_letters / max(letters, 1) > 0.85


def _contains_fragment(pdf_text: str, fragment: str) -> bool:
    needle = " ".join(str(fragment).split())
    haystack = " ".join(pdf_text.split())
    return bool(needle) and needle in haystack


def _raw_source_fragments(source_notes: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for rule in source_notes.get("source_rules") or []:
        if not isinstance(rule, Mapping):
            continue
        for key in ("short_excerpt", "implementation_mapping", "evidence_excerpt", "interpreted_rule"):
            value = rule.get(key)
            if _is_raw_english_fragment(value):
                out.append(str(value).strip())
    return out


def _looks_like_variant(pattern_id: str) -> bool:
    return any(token in pattern_id for token in ("adam_adam", "adam_eve", "eve_adam", "eve_eve"))


def semantic_required(chapter: Mapping[str, Any]) -> bool:
    return (
        bool(chapter.get("publication_semantic_required"))
        or bool(chapter.get("source_grounding_required"))
        or str(chapter.get("publication_semantic_gate_id") or "").strip() == PUBLICATION_SEMANTIC_GATE_ID
    )


def validate_publication_semantic_contract(chapter: Mapping[str, Any]) -> dict[str, Any]:
    """Validate whether a final chapter reads like a public chapter, not an internal report."""

    failures: list[dict[str, Any]] = []
    pattern_id = str(chapter.get("pattern_id") or "")

    def fail(check: str, detail: str) -> None:
        failures.append({"check": check, "pattern_id": pattern_id, "detail": detail})

    pdf_path = _artifact_path(chapter, "pdf")
    spec_path = _artifact_path(chapter, "publication_spec")
    source_notes_path = _artifact_path(chapter, "source_notes")
    payload_path = _artifact_path(chapter, "payload")

    spec = _read_json(spec_path)
    source_notes = _read_json(source_notes_path)
    payload = _read_json(payload_path)
    pdf_text = _pdf_text(pdf_path)

    if not spec_path:
        fail("semantic_publication_spec_exists", "missing manifest field publication_spec")
    elif not spec:
        fail("semantic_publication_spec_parse", str(spec_path))
    else:
        if str(spec.get("status") or "").upper() != "PASS":
            fail("semantic_publication_spec_status", f"expected PASS, got {spec.get('status')}")
        if spec.get("semantic_gate_id") != PUBLICATION_SEMANTIC_GATE_ID:
            fail("semantic_gate_id", f"expected {PUBLICATION_SEMANTIC_GATE_ID}, got {spec.get('semantic_gate_id')}")
        if spec.get("pattern_id") and str(spec.get("pattern_id")) != pattern_id:
            fail("semantic_spec_pattern_id", f"expected {pattern_id}, got {spec.get('pattern_id')}")
        if str(spec.get("spec_scope") or "").strip() == "generic_family":
            fail("semantic_spec_scope", "generic_family spec cannot be used for a final pattern/variant")
        if _looks_like_variant(pattern_id) and spec.get("variant_specific") is not True:
            fail("semantic_variant_specific", "Adam/Eve variant final requires variant_specific=true")

    if not pdf_text:
        fail("semantic_pdf_text", f"unable to extract text from {pdf_path}")

    forbidden_terms = list(DEFAULT_INTERNAL_FORBIDDEN_TERMS)
    if spec:
        forbidden_terms.extend(str(item) for item in spec.get("public_forbidden_terms") or [])
    lower_text = pdf_text.lower()
    for term in sorted(set(item.lower() for item in forbidden_terms if str(item).strip())):
        if term and term in lower_text:
            fail("semantic_forbidden_public_term", term)

    if spec:
        for phrase in spec.get("public_required_phrases") or []:
            phrase_text = str(phrase).strip()
            if phrase_text and not _contains_fragment(pdf_text, phrase_text):
                fail("semantic_required_phrase", phrase_text)

    for fragment in _raw_source_fragments(source_notes):
        if _contains_fragment(pdf_text, fragment):
            fail("semantic_raw_source_text", fragment[:140])

    if payload:
        spec_id = str(spec.get("publication_spec_id") or "").strip() if spec else ""
        payload_spec_id = str(payload.get("publication_spec_id") or "").strip()
        if spec_id and payload_spec_id and payload_spec_id != spec_id:
            fail("semantic_payload_spec_id", f"expected {spec_id}, got {payload_spec_id}")

    return {
        "status": "PASS" if not failures else "FAIL",
        "pattern_id": pattern_id,
        "semantic_gate_id": PUBLICATION_SEMANTIC_GATE_ID,
        "failures": failures,
    }
