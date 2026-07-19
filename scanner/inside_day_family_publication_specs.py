"""Publication-semantic specs for Inside Day Family chapters."""

from __future__ import annotations

from typing import Any, Mapping

from scanner.publication_semantic_contract import PUBLICATION_SEMANTIC_GATE_ID


INSIDE_DAY_FAMILY_PUBLICATION_SPEC_VERSION = "inside_day_family_publication_spec_v1"

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
    "inside_day": (
        "Inside Day",
        "nến nằm hoàn toàn trong biên độ nến trước",
        "đóng cửa vượt đỉnh hoặc thủng đáy của nến trong",
        "mẫu rất ngắn nên phải đọc cùng xác nhận",
    ),
}


def build_inside_day_publication_spec(*, pattern_id: str, title: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    publication_spec = dict(spec)
    publication_spec.update(
        {
            "status": "PASS",
            "semantic_gate_id": PUBLICATION_SEMANTIC_GATE_ID,
            "publication_spec_id": f"{pattern_id}_{INSIDE_DAY_FAMILY_PUBLICATION_SPEC_VERSION}",
            "pattern_id": pattern_id,
            "family": "inside_day_family",
            "spec_scope": "pattern_chapter",
            "variant_specific": True,
            "public_required_phrases": list(PATTERN_REQUIRED_PHRASES.get(pattern_id, (title,))),
            "public_forbidden_terms": list(PUBLIC_FORBIDDEN_TERMS),
            "public_rule_rows": list(spec.get("public_rule_rows") or []),
            "title": title,
            "source_chapter": spec.get("local_source_chapter"),
            "public_story_contract": {
                "must_read_like": "public investor-facing short-term chart-pattern chapter",
                "must_not_read_like": "internal audit, scanner QA, or release-gate report",
                "allowed_data_scope": "available-series scope with explicit caveats",
            },
        }
    )
    return publication_spec
