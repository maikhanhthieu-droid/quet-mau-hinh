from __future__ import annotations

import json
from pathlib import Path

from scanner.build_triangle_family_public_chapters import build_triangle_family_public_chapters
from scanner.validate_triangle_family_release_candidate import build_release_candidate, render_release_candidate_markdown, write_release_candidate


def test_triangle_family_release_candidate_passes_current_contract(tmp_path: Path) -> None:
    paths = build_triangle_family_public_chapters(out_dir=tmp_path / "triangle_family")

    payload = build_release_candidate(pdf_path=paths["pdf"], payload_path=paths["payload"])
    report = render_release_candidate_markdown(payload)

    assert payload["release_status"] == "PASS"
    assert payload["classification"] == "ascending_triangle_investment_reference_candidate_95"
    assert payload["conservative_score"] == 95.0
    assert payload["failures"] == []
    assert payload["summary"]["public_grade_events"] == 877
    assert payload["summary"]["base_target_hit_rate"] == 74.23
    assert "Triangle Family complete set" in payload["forbidden_claims"]
    assert "Ascending Triangle Release Candidate Gate" in report


def test_triangle_family_release_candidate_writer_outputs_artifacts(tmp_path: Path) -> None:
    paths = build_triangle_family_public_chapters(out_dir=tmp_path / "triangle_family")
    payload = build_release_candidate(pdf_path=paths["pdf"], payload_path=paths["payload"])

    out_paths = write_release_candidate(payload, tmp_path / "release")

    assert out_paths["json"].exists()
    assert out_paths["report"].exists()
    written = json.loads(out_paths["json"].read_text(encoding="utf-8"))
    assert written["release_status"] == "PASS"


def test_triangle_family_release_candidate_blocks_when_pdf_has_forbidden_legacy_term(tmp_path: Path) -> None:
    paths = build_triangle_family_public_chapters(out_dir=tmp_path / "triangle_family")
    bad_pdf = tmp_path / "bad.pdf"
    bad_pdf.write_text("Flag", encoding="utf-8")

    payload = build_release_candidate(pdf_path=bad_pdf, payload_path=paths["payload"])

    assert payload["release_status"] == "BLOCK"
    assert "pdf_publication_content" in payload["failures"]


def test_triangle_family_release_candidate_blocks_when_target_first_is_weak(tmp_path: Path) -> None:
    paths = build_triangle_family_public_chapters(out_dir=tmp_path / "triangle_family")
    payload_file = paths["payload"]
    payload = json.loads(payload_file.read_text(encoding="utf-8"))
    payload["target_calibration"]["base_target"]["target_first_before_adverse_5pct_rate"] = 44.0
    payload_file.write_text(json.dumps(payload), encoding="utf-8")

    gate = build_release_candidate(pdf_path=paths["pdf"], payload_path=payload_file)

    assert gate["release_status"] == "BLOCK"
    assert "base_target_strength" in gate["failures"]
