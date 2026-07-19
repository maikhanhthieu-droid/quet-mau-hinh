from __future__ import annotations

import json

import pandas as pd

from scanner.analyze_falling_wedge_branch_candidates import build_branch_candidates


def test_falling_wedge_branch_candidates_require_visual_gate_and_select_premium(tmp_path) -> None:
    audit_dir = tmp_path / "audit"
    out_dir = tmp_path / "out"
    audit_dir.mkdir()
    (audit_dir / "triangle_publication_quality_audit.json").write_text(
        json.dumps(
            {
                "audit_id": "falling_wedge_publication_quality_audit_v1",
                "premium_visual_validation_summary": {"premium_visual_gate": "PASS"},
            }
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {
                "tier": "premium",
                "row_id": "premium",
                "target_multiple": 0.5,
                "n": 141,
                "target_hit_rate_pct": 74.0,
                "target_first_before_adverse_5pct_rate_pct": 48.0,
                "failure_5pct_rate_pct": 16.0,
                "mfe_mae_median_ratio": 2.0,
            },
            {
                "tier": "premium+standard",
                "row_id": "premium+standard",
                "target_multiple": 0.5,
                "n": 793,
                "target_hit_rate_pct": 68.0,
                "target_first_before_adverse_5pct_rate_pct": 35.0,
                "failure_5pct_rate_pct": 18.0,
                "mfe_mae_median_ratio": 1.13,
            },
        ]
    ).to_csv(audit_dir / "target_family_by_publication_tier.csv", index=False)

    payload = build_branch_candidates(audit_dir=audit_dir, out_dir=out_dir)

    assert payload["decision"] == "USE_BRANCH_HEADLINE"
    assert payload["recommended_headline_scope"]["branch_label"] == "tier:premium"
    assert (out_dir / "falling_wedge_branch_candidates.json").exists()
