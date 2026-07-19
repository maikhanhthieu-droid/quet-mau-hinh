"""Publication-semantic specs for Broadening Family chapters."""

from __future__ import annotations

from typing import Any, Mapping

from scanner.publication_semantic_contract import PUBLICATION_SEMANTIC_GATE_ID


BROADENING_PUBLICATION_SPEC_VERSION = "broadening_family_publication_spec_v1"

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
    "payload",
    "factory",
    "Mốc nguồn Bulkowski",
    "mốc Việt Nam",
    "nếu có, nếu không",
    "đối chiếu nguồn",
    "theo tài liệu gốc",
    "source_measure_rule",
    "watchlist",
)

PATTERN_REQUIRED_PHRASES = {
    "broadening_bottoms": ("Đáy mở rộng", "loa phóng thanh", "đỉnh cao hơn", "đáy thấp hơn", "giá đóng cửa phá ra ngoài"),
    "broadening_tops": ("Đỉnh mở rộng", "loa phóng thanh", "đỉnh cao hơn", "đáy thấp hơn", "giá đóng cửa phá ra ngoài"),
    "broadening_formations_right_angled_ascending": ("Mở rộng vuông góc tăng", "đáy ngang", "đỉnh cao dần", "giá đóng cửa phá ra ngoài"),
    "broadening_formations_right_angled_descending": ("Mở rộng vuông góc giảm", "đỉnh ngang", "đáy thấp dần", "giá đóng cửa phá ra ngoài"),
    "broadening_wedges_ascending": ("Nêm mở rộng tăng", "hai đường biên cùng dốc lên", "mở rộng", "giá đóng cửa phá ra ngoài"),
    "broadening_wedges_descending": ("Nêm mở rộng giảm", "hai đường biên cùng dốc xuống", "mở rộng", "giá đóng cửa phá ra ngoài"),
}


def build_broadening_publication_spec(*, pattern_id: str, title: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": "PASS",
        "semantic_gate_id": PUBLICATION_SEMANTIC_GATE_ID,
        "publication_spec_id": f"{pattern_id}_{BROADENING_PUBLICATION_SPEC_VERSION}",
        "pattern_id": pattern_id,
        "family": "broadening_family",
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


def sanitize_broadening_public_text(text: Any) -> str:
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
