"""Publication-semantic specs for Measured Move Family chapters."""

from __future__ import annotations

from typing import Any, Mapping

from scanner.publication_semantic_contract import PUBLICATION_SEMANTIC_GATE_ID


MEASURED_MOVE_PUBLICATION_SPEC_VERSION = "measured_move_family_publication_spec_v1"

PUBLIC_FORBIDDEN_TERMS = (
    "payload",
    "factory",
    "source_alignment",
    "publication_quality_tier",
    "data_limited",
    "branch_id",
    "chapter_lane",
    "candidate",
    "headline",
    "audit",
    "premium",
    "standard",
    "loose",
    "aggregate",
)


PATTERN_REQUIRED_PHRASES = {
    "measured_move_up": (
        "Measured Move Up",
        "nhịp tăng đầu tiên",
        "pha điều chỉnh",
        "nhịp tăng thứ hai",
        "Mục tiêu theo nhịp đầu",
    ),
    "measured_move_down": (
        "Measured Move Down",
        "nhịp giảm đầu tiên",
        "pha điều chỉnh",
        "nhịp giảm thứ hai",
        "Mục tiêu theo nhịp đầu",
    ),
}


def build_measured_move_publication_spec(*, pattern_id: str, title: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": "PASS",
        "semantic_gate_id": PUBLICATION_SEMANTIC_GATE_ID,
        "publication_spec_id": f"{pattern_id}_{MEASURED_MOVE_PUBLICATION_SPEC_VERSION}",
        "pattern_id": pattern_id,
        "family": "measured_move_family",
        "spec_scope": "pattern_chapter",
        "variant_specific": True,
        "public_required_phrases": list(PATTERN_REQUIRED_PHRASES.get(pattern_id, (title,))),
        "public_forbidden_terms": list(PUBLIC_FORBIDDEN_TERMS),
        "public_rule_rows": list(spec.get("public_rule_rows") or []),
        "title": title,
        "source_chapter": spec.get("local_source_chapter"),
        "public_story_contract": {
            "must_read_like": "public investor-facing chart-pattern chapter",
            "must_not_read_like": "internal audit, scanner QA, or release-gate report",
            "allowed_data_scope": "available-series scope with explicit caveats",
        },
    }


def sanitize_measured_move_public_text(text: Any) -> str:
    out = str(text)
    replacements = {
        "premium + standard": "nhóm hình thái tốt + nhóm chuẩn",
        "premium+standard": "nhóm hình thái tốt + nhóm chuẩn",
        "premium": "nhóm hình thái tốt",
        "standard": "nhóm chuẩn",
        "public-grade": "đủ điều kiện công bố",
        "data_limited": "thiếu dữ liệu",
        "loose": "lỏng",
        "audit": "kiểm tra",
        "headline": "kết luận chính",
        "candidate": "ứng viên",
        "target-first-before-adverse": "đạt mục tiêu trước kéo ngược",
        "target-first": "đạt trước kéo ngược",
        "target-hit": "tỷ lệ đạt mục tiêu",
        "breakout": "xác nhận",
        "aggregate": "toàn mẫu",
    }
    for old, new in replacements.items():
        out = out.replace(old, new)
    return out
