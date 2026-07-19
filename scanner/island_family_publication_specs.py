"""Publication-semantic specs for Island Family chapters."""

from __future__ import annotations

from typing import Any, Mapping

try:
    from scanner.publication_semantic_contract import PUBLICATION_SEMANTIC_GATE_ID
except ModuleNotFoundError:  # pragma: no cover - local builder can run before PDF deps are installed.
    PUBLICATION_SEMANTIC_GATE_ID = "publication_semantic_gate_v1"


ISLAND_FAMILY_PUBLICATION_SPEC_VERSION = "island_family_publication_spec_v1"

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
    "scanner",
    "pipeline",
)

PATTERN_REQUIRED_PHRASES = {
    "island_reversals": (
        "Island Reversal",
        "hai khoảng trống giá",
        "vùng giá bị cô lập",
        "đảo chiều",
    ),
    "islands_long": (
        "Island dài",
        "hai khoảng trống giá",
        "vùng giá bị cô lập",
        "thời gian cô lập dài hơn",
    ),
}


def build_island_publication_spec(*, pattern_id: str, title: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    publication_spec = dict(spec)
    publication_spec.update(
        {
            "status": "PASS",
            "semantic_gate_id": PUBLICATION_SEMANTIC_GATE_ID,
            "publication_spec_id": f"{pattern_id}_{ISLAND_FAMILY_PUBLICATION_SPEC_VERSION}",
            "pattern_id": pattern_id,
            "family": "island_family",
            "spec_scope": "pattern_chapter",
            "variant_specific": True,
            "public_required_phrases": list(PATTERN_REQUIRED_PHRASES.get(pattern_id, (title, "khoảng trống giá"))),
            "public_forbidden_terms": list(PUBLIC_FORBIDDEN_TERMS),
            "public_rule_rows": list(spec.get("public_rule_rows") or []),
            "title": title,
            "source_chapter": spec.get("local_source_chapter"),
            "public_story_contract": {
                "must_read_like": "public investor-facing chart-pattern chapter",
                "must_not_read_like": "internal audit, scanner QA, or release-gate report",
                "allowed_data_scope": "available OHLCV DB scope with explicit caveats",
            },
        }
    )
    return publication_spec
