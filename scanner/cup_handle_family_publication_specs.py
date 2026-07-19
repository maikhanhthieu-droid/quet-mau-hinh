"""Publication-semantic specs for Cup-with-Handle Family chapters."""

from __future__ import annotations

from typing import Any, Mapping

from scanner.publication_semantic_contract import PUBLICATION_SEMANTIC_GATE_ID


CUP_HANDLE_PUBLICATION_SPEC_VERSION = "cup_handle_family_publication_spec_v1"

PUBLIC_FORBIDDEN_TERMS = (
    "Temporal robustness",
    "Regime x liquidity interaction",
    "Manual visual",
    "pass rate",
    "Publication core",
    "release gate",
    "source grounding",
    "source_alignment",
    "publication_quality_tier",
    "data_limited",
    "headline",
    "candidate",
    "public-grade",
    "premium",
    "standard",
    "loose",
    "aggregate",
    "audit",
)


PATTERN_REQUIRED_PHRASES = {
    "cup_with_handle": (
        "Cốc tay cầm",
        "đáy tròn",
        "tay cầm bên phải",
        "giá đóng cửa phá lên",
        "0,5x",
    ),
    "cup_with_handle_inverted": (
        "Cốc tay cầm đảo ngược",
        "đỉnh tròn",
        "tay cầm bên phải",
        "giá đóng cửa phá xuống",
        "chiều cao tay cầm",
    ),
}


def build_cup_handle_publication_spec(*, pattern_id: str, title: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": "PASS",
        "semantic_gate_id": PUBLICATION_SEMANTIC_GATE_ID,
        "publication_spec_id": f"{pattern_id}_{CUP_HANDLE_PUBLICATION_SPEC_VERSION}",
        "pattern_id": pattern_id,
        "family": "cup_handle_family",
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


def sanitize_cup_handle_public_text(text: Any) -> str:
    out = str(text)
    replacements = {
        "premium + standard": "nhóm tốt nhất + nhóm chuẩn",
        "premium+standard": "nhóm tốt nhất + nhóm chuẩn",
        "premium": "nhóm tốt nhất",
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
        "breakdown": "phá vỡ xuống",
        "aggregate": "toàn mẫu",
    }
    for old, new in replacements.items():
        out = out.replace(old, new)
    return out
