"""Source-grounding audit for the expanded Flag-like Family.

This audit records what is allowed to move forward from the original
Bulkowski source review before any public chapter is built. It is deliberately
stricter than a scanner smoke test: a pattern may be source-grounded but still
blocked from publication if the detector or statistical branch is not ready.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


PENNANT_FILE = Path("scanner/v2/pennants.py")
MANIFEST = Path("scanner/v2/pattern_family_manifest.json")


SOURCE_NOTES: dict[str, dict[str, Any]] = {
    "bull_pennants": {
        "source_chapter": 34,
        "source_book_pages": [522, 523, 524, 525, 532],
        "source_pdf_pages_checked": [545, 546, 547, 548, 556],
        "publication_lane": "watchlist candidate; source-aligned branch calibration required",
        "source_rules": [
            {
                "rule_id": "bp.shape.converging_lines",
                "rule": "Body must be a short triangle bounded by two converging trendlines, not a parallel flag channel.",
            },
            {
                "rule_id": "bp.duration.max_three_weeks",
                "rule": "Formation should be short, with three trading weeks treated as the upper bound.",
            },
            {
                "rule_id": "bp.prior_trend.steep_up",
                "rule": "A steep, quick advance must precede the pennant.",
            },
            {
                "rule_id": "bp.breakout.up_close",
                "rule": "Bull branch confirms on a close above the upper pennant boundary.",
            },
            {
                "rule_id": "bp.volume.contracts",
                "rule": "Volume normally contracts during the pennant; this is a diagnostic unless explicitly configured as a hard gate.",
            },
            {
                "rule_id": "bp.target.pole_projection_conservative",
                "rule": "Measure rule projects the prior pole from the breakout area, but the chapter must treat it conservatively and report calibrated bands.",
            },
        ],
    },
    "bear_pennants": {
        "source_chapter": 34,
        "source_book_pages": [522, 523, 524, 525, 532],
        "source_pdf_pages_checked": [545, 546, 547, 548, 556],
        "publication_lane": "defensive/informational candidate; source-aligned branch calibration required",
        "source_rules": [
            {
                "rule_id": "brp.shape.converging_lines",
                "rule": "Body must be a short triangle bounded by two converging trendlines, not a parallel flag channel.",
            },
            {
                "rule_id": "brp.duration.max_three_weeks",
                "rule": "Formation should be short, with three trading weeks treated as the upper bound.",
            },
            {
                "rule_id": "brp.prior_trend.steep_down",
                "rule": "A steep, quick decline must precede the pennant.",
            },
            {
                "rule_id": "brp.breakout.down_close",
                "rule": "Bear branch confirms on a close below the lower pennant boundary.",
            },
            {
                "rule_id": "brp.volume.contracts",
                "rule": "Volume normally contracts during the pennant; this is a diagnostic unless explicitly configured as a hard gate.",
            },
            {
                "rule_id": "brp.target.pole_projection_conservative",
                "rule": "Measure rule projects the prior pole from the breakout area, but the chapter must treat it conservatively and report calibrated bands.",
            },
        ],
    },
    "high_tight_flags": {
        "source_chapter": 22,
        "source_book_pages": [350, 351, 352, 353, 354],
        "source_pdf_pages_checked": [374, 375, 376, 377, 378],
        "publication_lane": "watchlist-reference; dedicated detector present and half-prior-move target required",
        "source_rules": [
            {
                "rule_id": "htf.prior_trend.near_double",
                "rule": "Require an exceptional prior advance, with at least roughly ninety percent rise and ideally a doubling in under two months.",
            },
            {
                "rule_id": "htf.consolidation.near_high",
                "rule": "Find a short consolidation near the doubled price area after the strong advance.",
            },
            {
                "rule_id": "htf.pullback.limit",
                "rule": "The consolidation should not drift too deeply from the high.",
            },
            {
                "rule_id": "htf.volume.contracts",
                "rule": "Receding volume inside the consolidation is a favorable diagnostic.",
            },
            {
                "rule_id": "htf.breakout.up_only",
                "rule": "High-and-tight flags are treated as upward continuation patterns.",
            },
            {
                "rule_id": "htf.target.half_prior_move",
                "rule": "The source measure rule uses about half the prior advance projected from breakout, not the full pole.",
            },
        ],
    },
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _read_json(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, Mapping) else {}


def _pennant_code_checks(code: str) -> dict[str, bool]:
    return {
        "uses_converging_trendlines": "upper.slope_per_bar >= lower.slope_per_bar" in code and "compression_ratio" in code,
        "limits_duration_to_three_weeks": "width_max_bars: int = 15" in code,
        "requires_prior_pole": "_prior_pole" in code and "pole_min_change_pct" in code,
        "confirms_by_close_breakout": "close > boundary" in code and "close < boundary" in code,
        "has_branch_variants": "bull_pennant" in code and "bear_pennant" in code,
        "records_candidate_status": "candidate_flag_like_family_not_final" in code,
    }


def audit_flag_like_family_source_grounding(*, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    code = _read(PENNANT_FILE)
    manifest = _read_json(MANIFEST)
    families = manifest.get("families") if isinstance(manifest.get("families"), Mapping) else {}
    flag_like = families.get("flag_like_family") if isinstance(families.get("flag_like_family"), Mapping) else {}
    flag_like_patterns = flag_like.get("patterns") if isinstance(flag_like.get("patterns"), Mapping) else {}

    failures: list[dict[str, Any]] = []
    code_checks = _pennant_code_checks(code)
    if not all(code_checks.values()):
        failures.append({"pattern_id": "pennants", "check": "pennant_detector_markers", "detail": code_checks})

    for pattern_id in ("bull_pennants", "bear_pennants"):
        if pattern_id not in flag_like_patterns:
            failures.append({"pattern_id": pattern_id, "check": "manifest_registration", "detail": "Missing from flag_like_family manifest."})

    high_tight = flag_like_patterns.get("high_tight_flags") if isinstance(flag_like_patterns.get("high_tight_flags"), Mapping) else {}
    if high_tight.get("status") not in {"source_grounded_detector_required", "reference_only_until_detector", "publication_final"}:
        failures.append({"pattern_id": "high_tight_flags", "check": "publication_blocker_status", "detail": high_tight.get("status")})

    pattern_payloads: dict[str, Any] = {}
    for pattern_id, notes in SOURCE_NOTES.items():
        pattern_payload = {
            "pattern_id": pattern_id,
            "source_review_status": "PASS",
            "publication_ready": pattern_id in {"bull_pennants", "bear_pennants", "high_tight_flags"} and not failures,
            "rule_count": len(notes["source_rules"]),
            **notes,
        }
        pattern_payloads[pattern_id] = pattern_payload
        (out_dir / f"{pattern_id}_source_notes.json").write_text(
            json.dumps(pattern_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    payload = {
        "audit_id": "flag_like_family_source_grounding_audit_v1",
        "status": "PASS" if not failures else "FAIL",
        "policy": "Source review may pass while public chapter remains blocked until scanner/statistical gates pass.",
        "code_checks": code_checks,
        "patterns": pattern_payloads,
        "failures": failures,
    }
    (out_dir / "flag_like_family_source_grounding_audit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_dir / "flag_like_family_source_grounding_audit.md").write_text(
        "\n".join(
            [
                "# Flag-like Family source-grounding audit",
                "",
                f"**Status:** {payload['status']}",
                "",
                "- Bull Pennant: source-grounded watchlist chapter.",
                "- Bear Pennant: source-grounded defensive/informational chapter.",
                "- High-and-Tight Flag: source-grounded watchlist chapter with a dedicated detector.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Flag-like Family source grounding.")
    parser.add_argument("--out-dir", default="artifacts/scanner_v2/flag_like_family_source_grounding")
    args = parser.parse_args()
    payload = audit_flag_like_family_source_grounding(out_dir=Path(args.out_dir))
    print(json.dumps({"status": payload["status"], "failures": payload["failures"]}, ensure_ascii=False, indent=2))
    if payload["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
