"""Canonical editorial contract for public chart-pattern chapters.

This module does not call an AI model. It validates the *result* of an AI or
human editorial pass before the canonical PDF factory is allowed to render a
final chapter. The goal is to prevent thin statistical summaries from passing
as investor-facing publication chapters.
"""

from __future__ import annotations

from typing import Any, Mapping

CANONICAL_EDITORIAL_WORKFLOW_ID = "canonical_editorial_workflow_v1"
CANONICAL_AI_EDITORIAL_GATE_ID = "canonical_ai_editorial_gate_v1"

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

MIN_SECTION_PARAGRAPHS = {
    "summary": 3,
    "tour": 2,
    "failure": 2,
    "statistics": 2,
    "post_breakout": 2,
    "size_volume": 2,
    "tactics": 2,
    "checklist": 5,
}

MIN_SECTION_CHARS = {
    "summary": 700,
    "tour": 380,
    "failure": 420,
    "statistics": 440,
    "post_breakout": 360,
    "size_volume": 340,
    "tactics": 380,
    "checklist": 160,
}

INTERPRETIVE_CUES = (
    "người đọc",
    "nên hiểu",
    "cách đọc",
    "vì vậy",
    "điều này",
    "cho thấy",
    "không nên",
    "cần",
    "khi",
    "nếu",
    "thận trọng",
    "đáng chú ý",
    "nghĩa là",
    "hàm ý",
)

STAT_ONLY_CUES = (
    "tỷ lệ",
    "trung vị",
    "mẫu",
    "%",
    "khoảng tin cậy",
    "điểm",
)

FORBIDDEN_PUBLIC_TERMS = (
    "MFE",
    "MAE",
    "breakout",
    "target-hit",
    "target-first",
    "scanner",
    "pipeline",
    "proxy",
    "available-series",
    "research-only",
    "setup",
    "payload",
    "factory",
    "publication_quality_tier",
    "Flag Family",
    "Corporate actions",
    "delisted/halted",
    "status tape",
    "historical VN30/VN100 membership",
    "point-in-time universe",
    "vào lệnh",
    "dừng lỗ",
    "stop-loss",
    "low-liquidity",
    "data_limited",
    "branch_id",
    "regime",
    "bucket",
)

CANONICAL_EDITORIAL_CONTRACT = {
    "workflow_id": CANONICAL_EDITORIAL_WORKFLOW_ID,
    "gate_id": CANONICAL_AI_EDITORIAL_GATE_ID,
    "purpose": "validate AI/human editorial sections before canonical PDF rendering",
    "required_sections": list(REQUIRED_EDITORIAL_SECTIONS),
    "must_do": [
        "turn statistics into chart-reading implications",
        "explain failure and usage, not only headline metrics",
        "use Vietnamese public-facing terminology",
        "keep trading-advice language out of the chapter",
    ],
    "must_not_do": [
        "pass thin one-line section placeholders",
        "let internal audit vocabulary leak into the public chapter",
        "let numbers stand without interpretation",
    ],
}


def _section_items(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    return [text] if text else []


def _cue_count(text: str, cues: tuple[str, ...]) -> int:
    lower = text.lower()
    return sum(lower.count(cue.lower()) for cue in cues)


def _digit_ratio(text: str) -> float:
    visible = [char for char in text if not char.isspace()]
    if not visible:
        return 0.0
    digits = sum(char.isdigit() for char in visible)
    return digits / len(visible)


def validate_canonical_editorial_sections(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate public editorial depth and terminology.

    The validator is intentionally stricter than the old manifest contract. A
    section must have enough prose and enough interpretive language to read like
    a chapter, not like a statistics dump.
    """

    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    sections = payload.get("editorial_sections") if isinstance(payload.get("editorial_sections"), Mapping) else {}

    def fail(check: str, section: str, detail: str) -> None:
        failures.append({"check": check, "section": section, "detail": detail})

    def warn(check: str, section: str, detail: str) -> None:
        warnings.append({"check": check, "section": section, "detail": detail})

    for section in REQUIRED_EDITORIAL_SECTIONS:
        items = _section_items(sections.get(section))
        text = "\n".join(items)
        if not items:
            fail("editorial_section_missing", section, "missing or empty")
            continue
        min_items = MIN_SECTION_PARAGRAPHS[section]
        min_chars = MIN_SECTION_CHARS[section]
        if len(items) < min_items:
            fail("editorial_section_too_few_paragraphs", section, f"expected at least {min_items}, got {len(items)}")
        if len(text) < min_chars:
            fail("editorial_section_too_short", section, f"expected at least {min_chars} chars, got {len(text)}")
        cue_count = _cue_count(text, INTERPRETIVE_CUES)
        if section != "checklist" and cue_count < 2:
            fail("editorial_section_lacks_reader_implication", section, f"expected at least 2 interpretive cues, got {cue_count}")
        stat_count = _cue_count(text, STAT_ONLY_CUES)
        if section != "checklist" and stat_count > 0 and cue_count == 0:
            fail("editorial_section_stat_dump", section, "statistics are present without reader-facing interpretation")
        digit_ratio = _digit_ratio(text)
        if digit_ratio > 0.09 and cue_count < 3:
            fail("editorial_section_number_heavy", section, f"digit ratio {digit_ratio:.3f} without enough interpretation")
        leaked = [term for term in FORBIDDEN_PUBLIC_TERMS if term.lower() in text.lower()]
        if leaked:
            fail("editorial_section_forbidden_terms", section, ", ".join(sorted(set(leaked))))
        if section in {"summary", "statistics", "tactics"} and cue_count < 4:
            warn("editorial_section_could_be_richer", section, f"only {cue_count} interpretive cues")

    return {
        "status": "PASS" if not failures else "FAIL",
        "gate_id": CANONICAL_AI_EDITORIAL_GATE_ID,
        "failures": failures,
        "warnings": warnings,
    }
