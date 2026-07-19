"""Publication-semantic specs for Diamond Family chapters."""

from __future__ import annotations

from typing import Any, Mapping

from scanner.publication_semantic_contract import PUBLICATION_SEMANTIC_GATE_ID


DIAMOND_FAMILY_PUBLICATION_SPEC_VERSION = "diamond_family_publication_spec_v1"

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
    "diamond_bottoms": (
        "Diamond Bottoms",
        "xu hướng giảm trước mẫu",
        "mở rộng rồi thu hẹp",
        "chờ đóng cửa phá vỡ",
    ),
    "diamond_tops": (
        "Diamond Tops",
        "xu hướng tăng trước mẫu",
        "mở rộng rồi thu hẹp",
        "chờ đóng cửa phá vỡ",
    ),
}


def build_diamond_publication_spec(*, pattern_id: str, title: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    publication_spec = dict(spec)
    publication_spec.update(
        {
            "status": "PASS",
            "semantic_gate_id": PUBLICATION_SEMANTIC_GATE_ID,
            "publication_spec_id": f"{pattern_id}_{DIAMOND_FAMILY_PUBLICATION_SPEC_VERSION}",
            "pattern_id": pattern_id,
            "family": "diamond_family",
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
    )
    return publication_spec
