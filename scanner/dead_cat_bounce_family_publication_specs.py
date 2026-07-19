"""Publication-semantic specs for Dead-Cat Bounce Family chapters."""

from __future__ import annotations

from typing import Any, Mapping

from scanner.publication_semantic_contract import PUBLICATION_SEMANTIC_GATE_ID


DEAD_CAT_BOUNCE_PUBLICATION_SPEC_VERSION = "dead_cat_bounce_family_publication_spec_v1"

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
    "dead_cat_bounce": (
        "Dead-Cat Bounce",
        "cú rơi mạnh",
        "nhịp hồi",
        "giảm sau hồi",
    ),
    "dead_cat_bounce_inverted": (
        "Inverted Dead-Cat Bounce",
        "cú tăng mạnh",
        "ngày thứ hai",
        "trả lại thành quả",
    ),
}


def build_dead_cat_publication_spec(*, pattern_id: str, title: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    publication_spec = dict(spec)
    publication_spec.update(
        {
            "status": "PASS",
            "semantic_gate_id": PUBLICATION_SEMANTIC_GATE_ID,
            "publication_spec_id": f"{pattern_id}_{DEAD_CAT_BOUNCE_PUBLICATION_SPEC_VERSION}",
            "pattern_id": pattern_id,
            "family": "dead_cat_bounce_family",
            "spec_scope": "event_pattern_chapter",
            "variant_specific": True,
            "public_required_phrases": list(PATTERN_REQUIRED_PHRASES.get(pattern_id, (title,))),
            "public_forbidden_terms": list(PUBLIC_FORBIDDEN_TERMS),
            "public_rule_rows": list(spec.get("public_rule_rows") or []),
            "title": title,
            "source_chapter": spec.get("local_source_chapter"),
            "public_story_contract": {
                "must_read_like": "public investor-facing event-pattern chapter",
                "must_not_read_like": "internal detector report, scanner QA, or release-gate report",
                "allowed_data_scope": "available-series scope with explicit caveats",
            },
        }
    )
    return publication_spec
