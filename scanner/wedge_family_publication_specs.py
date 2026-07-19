"""Publication-semantic specs for Wedge Family public chapters."""

from __future__ import annotations

from typing import Any, Mapping

from scanner.publication_semantic_contract import PUBLICATION_SEMANTIC_GATE_ID


WEDGE_PUBLICATION_SPEC_VERSION = "wedge_family_publication_spec_v3"

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
    "branch",
    "branch_id",
    "candidate",
    "defensive",
    "headline",
    "informational",
    "public-grade",
    "reference",
    "scope",
    "premium",
    "standard",
    "watchlist",
    "loose",
    "aggregate",
    "audit",
)


PATTERN_REQUIRED_PHRASES = {
    "wedges_falling": (
        "Nêm giảm",
        "hai biên cùng dốc xuống",
        "biên trên giảm nhanh hơn",
        "giá đóng cửa phá lên",
        "0,5x",
    ),
    "wedges_rising": (
        "Nêm tăng",
        "hai biên cùng dốc lên",
        "biên dưới tăng nhanh hơn",
        "giá đóng cửa phá xuống",
        "0,5x",
    ),
}


def build_wedge_publication_spec(*, pattern_id: str, title: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    required = list(PATTERN_REQUIRED_PHRASES.get(pattern_id, (title, "0,5x")))
    return {
        "status": "PASS",
        "semantic_gate_id": PUBLICATION_SEMANTIC_GATE_ID,
        "publication_spec_id": f"{pattern_id}_{WEDGE_PUBLICATION_SPEC_VERSION}",
        "pattern_id": pattern_id,
        "family": "wedge_family",
        "spec_scope": "pattern_chapter",
        "variant_specific": True,
        "public_required_phrases": required,
        "public_forbidden_terms": list(PUBLIC_FORBIDDEN_TERMS),
        "title": title,
        "source_chapter": spec.get("local_source_chapter"),
        "public_story_contract": {
            "must_read_like": "public investor-facing chart-pattern chapter",
            "must_not_read_like": "internal audit, scanner QA, or release-gate report",
            "allowed_data_scope": "available-series scope with explicit caveats",
        },
    }


def sanitize_wedge_public_text(text: Any) -> str:
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
