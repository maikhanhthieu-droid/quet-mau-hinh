"""Audit Double Pattern variants against the source-grounded publication gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.publication_flow_contract import (  # noqa: E402
    SOURCE_GROUNDED_MIN_RULES,
    SOURCE_GROUNDED_PUBLICATION_GATE_ID,
)


CORE_PATTERNS = ROOT / "scanner/v2/core_patterns.json"
DEFAULT_VARIANT_ROOT = ROOT / "artifacts/scanner_v2/double_pattern_variant_public_chapters"
DEFAULT_OUT_DIR = ROOT / "artifacts/scanner_v2/double_pattern_source_grounding"

REQUIRED_DOUBLE_BOTTOM_RULES = {
    "db.prior_trend.downward",
    "db.shape.two_bottoms",
    "db.rise_between_bottoms.min_10pct",
    "db.bottom_similarity.close_prices",
    "db.confirmation.close_above_highest_high",
    "db.measure_rule.height_to_confirmation",
    "db.variant.adam_shape",
    "db.variant.eve_shape",
}

REQUIRED_DOUBLE_TOP_RULES = {
    "dt.prior_trend.upward",
    "dt.shape.two_near_peaks",
    "dt.valley_depth.meaningful",
    "dt.top_similarity.close_prices",
    "dt.top_separation.few_weeks",
    "dt.confirmation.close_below_lowest_low",
    "dt.breakout.down",
    "dt.variant.adam_shape",
    "dt.variant.eve_shape",
}

VARIANT_REQUIRED_RULES = {
    ("double_bottoms", "AE"): {"db.variant.adam_eve_order"},
}

BOTTOM_VARIANT_SOURCE_CHAPTER = {
    "AA": 13,
    "AE": 14,
    "EA": 15,
    "EE": 16,
}
TOP_VARIANT_SOURCE_CHAPTER = {
    "AA": 17,
    "AE": 18,
    "EA": 19,
    "EE": 20,
}


def _read_json(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, Mapping) else {}


def _variant_pattern_id(base_pattern: str, variant: str) -> str:
    suffix = {"AA": "adam_adam", "AE": "adam_eve", "EA": "eve_adam", "EE": "eve_eve"}[variant]
    return f"{base_pattern}_{suffix}"


def audit_variant(*, base_pattern: str, variant: str, variant_root: Path = DEFAULT_VARIANT_ROOT) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []

    def fail(check: str, severity: str, detail: str) -> None:
        failures.append({"check": check, "severity": severity, "detail": detail})

    registry = _read_json(CORE_PATTERNS)
    rules = ((registry.get("patterns") or {}).get(base_pattern) or {}).get("rules") or []
    rule_ids = {str(rule.get("rule_id")) for rule in rules if isinstance(rule, Mapping)}
    required_rules = REQUIRED_DOUBLE_BOTTOM_RULES if base_pattern == "double_bottoms" else REQUIRED_DOUBLE_TOP_RULES
    missing = sorted(required_rules - rule_ids)
    if missing:
        fail("core_source_rules", "high", "missing: " + ", ".join(missing))

    variant_required = VARIANT_REQUIRED_RULES.get((base_pattern, variant), set())
    missing_variant = sorted(variant_required - rule_ids)
    if missing_variant:
        fail("variant_source_rules", "high", "missing: " + ", ".join(missing_variant))

    variant_id = _variant_pattern_id(base_pattern, variant)
    chapter_dir = variant_root / variant_id
    source_notes = _read_json(chapter_dir / f"{variant_id}_source_notes.json")
    payload = _read_json(chapter_dir / f"{variant_id}_public_chapter_payload.json")
    manifest = _read_json(chapter_dir / f"{variant_id}_candidate_manifest.json")

    if source_notes:
        notes_rules = source_notes.get("source_rules") if isinstance(source_notes.get("source_rules"), list) else []
        if str(source_notes.get("status") or "").upper() != "PASS":
            fail("source_notes_status", "high", str(source_notes.get("status")))
        if source_notes.get("source_grounding_policy_id") != SOURCE_GROUNDED_PUBLICATION_GATE_ID:
            fail("source_grounding_policy", "high", str(source_notes.get("source_grounding_policy_id")))
        if len(notes_rules) < SOURCE_GROUNDED_MIN_RULES:
            fail("source_notes_rule_count", "high", f"got {len(notes_rules)}")
        chapter_map = BOTTOM_VARIANT_SOURCE_CHAPTER if base_pattern == "double_bottoms" else TOP_VARIANT_SOURCE_CHAPTER
        expected_chapter = chapter_map.get(variant)
        local_source = source_notes.get("local_source") if isinstance(source_notes.get("local_source"), Mapping) else {}
        if expected_chapter and local_source.get("source_chapter") != expected_chapter:
            fail("variant_source_chapter", "high", f"expected {expected_chapter}, got {local_source.get('source_chapter')}")
    else:
        fail("source_notes_exists", "medium", f"missing {chapter_dir / f'{variant_id}_source_notes.json'}")

    source_alignment = {}
    if payload:
        chapter_ref = payload.get("chapter_reference") if isinstance(payload.get("chapter_reference"), Mapping) else {}
        source_alignment = chapter_ref.get("source_alignment") if isinstance(chapter_ref.get("source_alignment"), Mapping) else {}
    if source_alignment:
        basis = str(source_alignment.get("source_basis") or "")
        if variant == "AE" and "Chapter 13" in basis:
            fail("variant_source_basis", "high", "Adam & Eve candidate still references Chapter 13 as its source basis")
        if base_pattern == "double_tops" and "downward trend" in basis:
            fail("variant_source_basis", "high", "Double Top candidate still references a downward prior trend")
        if source_alignment.get("enabled") is not True:
            fail("source_aligned_sample_depth", "medium", f"source-aligned filter not enabled: {source_alignment.get('reason')}")
    elif manifest:
        fail("source_alignment_exists", "medium", "candidate manifest/payload does not expose source_alignment")

    high = sum(1 for item in failures if item["severity"] == "high")
    medium = sum(1 for item in failures if item["severity"] == "medium")
    level = "publication_aligned" if high == 0 and medium == 0 else ("implementation_aligned" if high == 0 else "partial")
    return {
        "audit_id": "double_pattern_source_grounding_audit_v1",
        "base_pattern": base_pattern,
        "variant": variant,
        "variant_pattern_id": variant_id,
        "source_grounding_policy_id": SOURCE_GROUNDED_PUBLICATION_GATE_ID,
        "source_grounding_level": level,
        "failure_counts": {"high": high, "medium": medium},
        "failures": failures,
        "source_alignment": source_alignment,
    }


def write_report(report: Mapping[str, Any], out_dir: Path = DEFAULT_OUT_DIR) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    variant_id = str(report["variant_pattern_id"])
    json_path = out_dir / f"{variant_id}_source_grounding_audit.json"
    md_path = out_dir / f"{variant_id}_source_grounding_audit.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    lines = [
        f"# Double Pattern Source Grounding Audit: {variant_id}",
        "",
        f"- Level: `{report['source_grounding_level']}`",
        f"- High issues: `{report['failure_counts']['high']}`",
        f"- Medium issues: `{report['failure_counts']['medium']}`",
        "",
    ]
    if report.get("failures"):
        lines.append("## Issues")
        for item in report["failures"]:
            lines.append(f"- `{item['severity']}` `{item['check']}`: {item['detail']}")
    else:
        lines.append("No high/medium source-grounding issues found.")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "md": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit one Double Pattern variant against the source-grounded gate.")
    parser.add_argument("--base-pattern", choices=["double_bottoms", "double_tops"], default="double_bottoms")
    parser.add_argument("--variant", choices=["AA", "AE", "EA", "EE"], default="AE")
    parser.add_argument("--variant-root", default=str(DEFAULT_VARIANT_ROOT))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    report = audit_variant(base_pattern=args.base_pattern, variant=args.variant, variant_root=Path(args.variant_root))
    paths = write_report(report, Path(args.out_dir))
    print(json.dumps({key: str(value) for key, value in paths.items()}, ensure_ascii=False, indent=2))
    if report["failure_counts"]["high"] > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
