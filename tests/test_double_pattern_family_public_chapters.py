from __future__ import annotations

import json
from pathlib import Path

from scanner.build_double_pattern_variant_public_chapter import build_double_pattern_variant_public_chapter
from scanner.build_double_pattern_variant_public_chapter import _source_notes_for_variant
from scanner.double_pattern_variant_publication_specs import (
    build_double_bottom_variant_publication_spec,
    build_double_top_variant_publication_spec,
)
from scanner.double_pattern_family_public_chapter_factory import FACTORY_ID
from scanner.publication_flow_contract import SOURCE_GROUNDED_PUBLICATION_GATE_ID
from scanner.publication_flow_contract import PUBLICATION_CORE_ID


def test_double_pattern_family_factory_identity() -> None:
    assert FACTORY_ID == "double_pattern_family_public_chapter_factory_v1"
    assert PUBLICATION_CORE_ID == "pattern_publication_core_v1"


def test_double_pattern_editorial_packs_exist() -> None:
    root = Path("artifacts/scanner_v2/double_pattern_family_ai_writing_approved_v1")
    for pattern_id in ("double_bottoms", "double_tops"):
        path = root / pattern_id / "approved_ai_sections.json"
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        for section in ("summary", "tour", "failure", "statistics", "post_breakout", "size_volume", "tactics", "checklist"):
            assert f'"{section}"' in text


def test_double_bottom_core_source_contract_is_deep_enough_for_variants() -> None:
    registry = json.loads(Path("scanner/v2/core_patterns.json").read_text(encoding="utf-8"))
    rules = registry["patterns"]["double_bottoms"]["rules"]
    ids = {rule["rule_id"] for rule in rules}

    assert len(rules) >= 10
    assert {
        "db.prior_trend.downward",
        "db.rise_between_bottoms.min_10pct",
        "db.confirmation.close_above_highest_high",
        "db.measure_rule.height_to_confirmation",
        "db.variant.adam_shape",
        "db.variant.eve_shape",
        "db.variant.adam_eve_order",
    }.issubset(ids)


def test_double_top_core_source_contract_is_deep_enough_before_publication() -> None:
    registry = json.loads(Path("scanner/v2/core_patterns.json").read_text(encoding="utf-8"))
    rules = registry["patterns"]["double_tops"]["rules"]
    ids = {rule["rule_id"] for rule in rules}

    assert len(rules) >= 9
    assert {
        "dt.prior_trend.upward",
        "dt.valley_depth.meaningful",
        "dt.top_similarity.close_prices",
        "dt.confirmation.close_below_lowest_low",
        "dt.breakout.down",
        "dt.variant.adam_shape",
        "dt.variant.eve_shape",
    }.issubset(ids)


def test_adam_eve_variant_source_notes_use_chapter_14_not_adam_adam_default() -> None:
    notes = _source_notes_for_variant("double_bottoms", "double_bottoms_adam_eve", "AE")
    rule_ids = {rule["rule_id"] for rule in notes["source_rules"]}

    assert notes["source_grounding_policy_id"] == SOURCE_GROUNDED_PUBLICATION_GATE_ID
    assert notes["local_source"]["source_chapter"] == 14
    assert notes["local_source"]["source_name"] == "Double Bottoms, Adam & Eve"
    assert len(notes["source_rules"]) >= 6
    assert "db.variant.adam_eve_order" in rule_ids
    assert "bulkowski-rise-to-neckline" not in rule_ids


def test_all_double_bottom_variant_publication_specs_are_variant_specific() -> None:
    expected = {
        "AA": ("double_bottoms_adam_adam", "Hai đáy Adam & Adam"),
        "AE": ("double_bottoms_adam_eve", "Hai đáy Adam & Eve"),
        "EA": ("double_bottoms_eve_adam", "Hai đáy Eve & Adam"),
        "EE": ("double_bottoms_eve_eve", "Hai đáy Eve & Eve"),
    }
    for variant, (pattern_id, phrase) in expected.items():
        spec = build_double_bottom_variant_publication_spec(variant, n_events=42)
        assert spec["status"] == "PASS"
        assert spec["pattern_id"] == pattern_id
        assert spec["variant_specific"] is True
        assert phrase in spec["public_required_phrases"]
        assert spec["story_spec"]["title"] == phrase


def test_all_double_top_variant_publication_specs_are_variant_specific() -> None:
    expected = {
        "AA": ("double_tops_adam_adam", "Hai đỉnh Adam & Adam"),
        "AE": ("double_tops_adam_eve", "Hai đỉnh Adam & Eve"),
        "EA": ("double_tops_eve_adam", "Hai đỉnh Eve & Adam"),
        "EE": ("double_tops_eve_eve", "Hai đỉnh Eve & Eve"),
    }
    for variant, (pattern_id, phrase) in expected.items():
        spec = build_double_top_variant_publication_spec(variant, n_events=42)
        assert spec["status"] == "PASS"
        assert spec["pattern_id"] == pattern_id
        assert spec["variant_specific"] is True
        assert phrase in spec["public_required_phrases"]
        assert spec["story_spec"]["title"] == phrase
        assert "đóng cửa dưới neckline" in spec["public_required_phrases"]


def test_eve_eve_variant_can_emit_final_with_source_compatible_exception(tmp_path: Path) -> None:
    paths = build_double_pattern_variant_public_chapter(
        base_pattern="double_bottoms",
        variant="EE",
        out_dir=tmp_path / "double_variants",
        final=True,
    )
    manifest = json.loads(paths["candidate_manifest"].read_text(encoding="utf-8"))

    assert paths["pdf"].name.endswith("_final.pdf")
    assert "final_manifest_entry" in paths
    assert manifest["requested_final"] is True
    assert manifest["status"] == "FINAL_READY"
    assert manifest["source_alignment"]["enabled"] is True
    assert manifest["source_alignment"]["alignment_level"] == "source_compatible_exception"
    assert manifest["source_alignment"]["strict_aligned_n"] < 30
    assert manifest["source_alignment"]["expanded_aligned_n"] >= 30
    assert manifest["public_variant_events"] >= 30


def test_double_top_adam_adam_can_emit_final_with_strict_source_alignment(tmp_path: Path) -> None:
    paths = build_double_pattern_variant_public_chapter(
        base_pattern="double_tops",
        variant="AA",
        out_dir=tmp_path / "double_variants",
        final=True,
    )
    manifest = json.loads(paths["candidate_manifest"].read_text(encoding="utf-8"))

    assert paths["pdf"].name.endswith("_final.pdf")
    assert "final_manifest_entry" in paths
    assert manifest["status"] == "FINAL_READY"
    assert manifest["source_alignment"]["enabled"] is True
    assert manifest["source_alignment"]["alignment_level"] == "strict_source_aligned"
    assert manifest["source_alignment"]["strict_aligned_n"] >= 30


def test_sparse_double_top_eve_eve_can_publish_as_technical_ceiling_final(tmp_path: Path) -> None:
    paths = build_double_pattern_variant_public_chapter(
        base_pattern="double_tops",
        variant="EE",
        out_dir=tmp_path / "double_variants",
        final=True,
    )
    manifest = json.loads(paths["candidate_manifest"].read_text(encoding="utf-8"))

    assert paths["pdf"].name.endswith("_final.pdf")
    assert "final_manifest_entry" in paths
    assert manifest["requested_final"] is True
    assert manifest["status"] == "FINAL_READY"
    assert manifest["final_basis"] == "technical_ceiling"
    assert manifest["source_alignment"]["enabled"] is False
    assert manifest["source_alignment"]["technical_ceiling_final"] is True
    assert manifest["source_alignment"]["sample_depth_aligned_n"] < 30
