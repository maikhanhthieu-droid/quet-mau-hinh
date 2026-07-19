from __future__ import annotations

from scanner.broadening_family_publication_specs import build_broadening_publication_spec
from scanner.build_broadening_family_public_chapters import PATTERNS, _source_notes
from scanner.v2.broadening_patterns import BROADENING_PATTERNS, PATTERN_META


def test_broadening_family_covers_first_six_source_chapters() -> None:
    assert set(BROADENING_PATTERNS) == {
        "broadening_bottoms",
        "broadening_formations_right_angled_ascending",
        "broadening_formations_right_angled_descending",
        "broadening_tops",
        "broadening_wedges_ascending",
        "broadening_wedges_descending",
    }
    assert {PATTERNS[key]["source_chapter"] for key in BROADENING_PATTERNS} == {1, 2, 3, 4, 5, 6}


def test_broadening_geometry_is_variant_specific() -> None:
    assert PATTERN_META["broadening_bottoms"]["geometry"] == "megaphone"
    assert PATTERN_META["broadening_formations_right_angled_ascending"]["geometry"] == "right_angled_ascending"
    assert PATTERN_META["broadening_formations_right_angled_descending"]["geometry"] == "right_angled_descending"
    assert PATTERN_META["broadening_wedges_ascending"]["geometry"] == "ascending_wedge"
    assert PATTERN_META["broadening_wedges_descending"]["geometry"] == "descending_wedge"
    assert PATTERN_META["broadening_wedges_ascending"]["min_touches"] == 3
    assert PATTERN_META["broadening_bottoms"]["min_touches"] == 2


def test_broadening_source_notes_are_direct_pdf_reviewed_and_vietnamese() -> None:
    notes = _source_notes("broadening_wedges_ascending", PATTERNS["broadening_wedges_ascending"])
    assert notes["status"] == "PASS"
    assert notes["source_grounding_level"] == "direct_pdf_reviewed"
    assert notes["source_chapter"] == 5
    assert len(notes["source_rules"]) >= 6
    joined = " ".join(f"{rule['short_excerpt']} {rule['implementation_mapping']}" for rule in notes["source_rules"])
    assert "pivot high/low" not in joined
    assert "Event date" not in joined
    assert "Tops/Bottoms" not in joined
    assert "nêm mở rộng" in joined


def test_broadening_publication_spec_uses_family_flow_contract() -> None:
    spec = build_broadening_publication_spec(
        pattern_id="broadening_formations_right_angled_ascending",
        title=PATTERNS["broadening_formations_right_angled_ascending"]["title"],
        spec={"local_source_chapter": 2},
    )
    assert spec["status"] == "PASS"
    assert spec["family"] == "broadening_family"
    assert spec["variant_specific"] is True
    assert "đáy ngang" in spec["public_required_phrases"]
