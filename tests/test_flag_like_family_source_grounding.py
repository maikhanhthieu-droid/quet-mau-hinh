from __future__ import annotations

from pathlib import Path

from scanner.audit_flag_like_family_source_grounding import audit_flag_like_family_source_grounding


def test_flag_like_family_source_grounding_records_pennant_and_high_tight_scope(tmp_path: Path) -> None:
    payload = audit_flag_like_family_source_grounding(out_dir=tmp_path)

    assert payload["status"] == "PASS"
    assert payload["patterns"]["bull_pennants"]["rule_count"] >= 6
    assert payload["patterns"]["bear_pennants"]["rule_count"] >= 6
    assert payload["patterns"]["high_tight_flags"]["source_review_status"] == "PASS"
    assert payload["patterns"]["high_tight_flags"]["publication_ready"] is True
    assert "dedicated detector" in payload["patterns"]["high_tight_flags"]["publication_lane"]
    assert (tmp_path / "flag_like_family_source_grounding_audit.json").exists()
