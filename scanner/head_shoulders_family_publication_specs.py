"""Publication-semantic specs for Head-and-Shoulders Family chapters."""

from __future__ import annotations

from typing import Any, Mapping

from scanner.publication_semantic_contract import PUBLICATION_SEMANTIC_GATE_ID


HEAD_SHOULDERS_PUBLICATION_SPEC_VERSION = "head_shoulders_family_publication_spec_v1"

PUBLIC_FORBIDDEN_TERMS = (
    "Temporal robustness",
    "Manual visual",
    "Publication core",
    "release gate",
    "source grounding",
    "publication_quality_tier",
    "data_limited",
    "candidate",
    "aggregate",
    "audit",
)


PATTERN_REQUIRED_PHRASES = {
    "head_and_shoulders_bottoms": ("Vai đầu vai đáy", "vai trái", "đầu thấp hơn", "vai phải", "đường cổ", "giá đóng cửa phá lên"),
    "head_and_shoulders_bottoms_complex": ("Vai đầu vai đáy phức hợp", "nhiều vai", "đầu thấp hơn", "đường cổ", "giá đóng cửa phá lên"),
    "head_and_shoulders_tops": ("Vai đầu vai đỉnh", "vai trái", "đầu cao hơn", "vai phải", "đường cổ", "giá đóng cửa phá xuống"),
    "head_and_shoulders_tops_complex": ("Vai đầu vai đỉnh phức hợp", "nhiều vai", "đầu cao hơn", "đường cổ", "giá đóng cửa phá xuống"),
}


def build_head_shoulders_publication_spec(*, pattern_id: str, title: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": "PASS",
        "semantic_gate_id": PUBLICATION_SEMANTIC_GATE_ID,
        "publication_spec_id": f"{pattern_id}_{HEAD_SHOULDERS_PUBLICATION_SPEC_VERSION}",
        "pattern_id": pattern_id,
        "family": "head_shoulders_family",
        "spec_scope": "pattern_chapter",
        "variant_specific": True,
        "public_required_phrases": list(PATTERN_REQUIRED_PHRASES.get(pattern_id, (title,))),
        "public_forbidden_terms": list(PUBLIC_FORBIDDEN_TERMS),
        "title": title,
        "source_chapter": spec.get("local_source_chapter"),
        "public_story_contract": {
            "must_read_like": "public investor-facing chart-pattern chapter",
            "must_not_read_like": "internal audit, scanner QA, or release-gate report",
            "allowed_data_scope": "available-series scope with explicit caveats",
        },
    }


def sanitize_head_shoulders_public_text(text: Any) -> str:
    out = str(text)
    replacements = {
        "premium": "nhóm tốt nhất",
        "standard": "nhóm chuẩn",
        "data_limited": "thiếu dữ liệu",
        "loose": "lỏng",
        "audit": "kiểm tra",
        "target-first-before-adverse": "đạt mục tiêu trước kéo ngược",
        "target-first": "đạt trước kéo ngược",
        "target-hit": "tỷ lệ đạt mục tiêu",
        "breakdown": "phá vỡ xuống",
        "aggregate": "toàn mẫu",
    }
    for old, new in replacements.items():
        out = out.replace(old, new)
    return out
